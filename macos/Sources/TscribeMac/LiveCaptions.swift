import AppKit
import Combine
import SwiftUI

/// Exactly one bounded window can be in flight. Slow inference never queues audio.
@MainActor
final class LiveCaptions: ObservableObject {
    @Published private(set) var confirmed = ""
    @Published private(set) var provisional = ""
    @Published private(set) var status = "Live captions are off"
    @Published private(set) var running = false
    @Published private(set) var finalized = false
    private var sessionStem: String?
    private let worker: WorkerClient
    private let interval: UInt64
    init(worker: WorkerClient? = nil, interval: UInt64 = 3_000_000_000) {
        self.worker = worker ?? WorkerClient()
        self.interval = interval
    }
    private var task: Task<Void, Never>?

    func start(stem: String, directory: URL, capture: NativeAudioCapture) {
        start(stem: stem, directory: directory) { directory, sequence in
            try await capture.snapshot(directory: directory, stem: stem, sequence: sequence)
        }
    }

    func start(stem: String, directory: URL, snapshot: @escaping (URL, Int) async throws -> [String: Double]) {
        stop()
        sessionStem = stem
        confirmed = ""; provisional = ""; running = true; finalized = false
        status = "Preparing captions… First use may download the caption model."
        let directory = directory.appendingPathComponent(".live").appendingPathComponent(stem)
        task = Task { [weak self] in
            guard let self else { return }
            var sequence = 0
            var delay = interval
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: delay) }
                catch { break }
                do {
                    let began = Date()
                    defer {
                        let remaining = Double(interval) / 1_000_000_000 - Date().timeIntervalSince(began)
                        delay = UInt64(max(0.25, remaining) * 1_000_000_000)
                    }
                    let windowSequence = sequence
                    let tracks = try await snapshot(directory, windowSequence)
                    defer {
                        for source in ["microphone", "system"] {
                            try? FileManager.default.removeItem(at: directory.appendingPathComponent("\(windowSequence)-\(source).wav"))
                        }
                    }
                    guard !Task.isCancelled else { break }
                    if tracks.isEmpty { continue }
                    let result = try await worker.request("live-caption", values: ["stem": stem, "sequence": windowSequence, "tracks": tracks])
                    guard !Task.isCancelled else { break }
                    confirmed = result["text"] as? String ?? ""
                    provisional = result["provisional_text"] as? String ?? ""
                    let gaps = result["gaps"] as? [[String: Any]] ?? []
                    if !gaps.isEmpty { status = "Some captions were missed. Full audio is still being recorded." }
                    else if Date().timeIntervalSince(began) > 3 { status = "Captions catching up · audio recording continues" }
                    else { status = "Live draft · the latest phrase may change" }
                    if result["echo_active"] as? Bool == true { status += " · echo reduction active" }
                    if let warning = result["warning"] as? String, !warning.isEmpty { status += " · " + warning }
                    sequence += 1
                } catch {
                    if !Task.isCancelled { status = "Captions unavailable: \(error.localizedDescription) Recording continues." }
                    break
                }
            }
            if !Task.isCancelled { worker.stop() }
            try? FileManager.default.removeItem(at: directory)
        }
    }

    func finish(text: String, stem: String) {
        guard stem == sessionStem else { return }
        confirmed = text; provisional = ""; finalized = true
        status = "Final transcript · saved with the recording"
    }

    func stop() {
        task?.cancel()
        task = nil
        worker.stop()
        if running {
            status = confirmed.isEmpty && provisional.isEmpty
                ? "No caption draft was produced. The full recording remains available."
                : "Caption draft saved · final transcription follows your recording settings"
        }
        running = false
    }
}

struct CaptionText: View {
    @ObservedObject var captions: LiveCaptions
    let fontSize: Int
    var body: some View {
        ScrollViewReader { reader in
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    Text(captions.confirmed).textSelection(.enabled)
                    Text(captions.provisional).foregroundStyle(.secondary).textSelection(.enabled)
                    Color.clear.frame(height: 1).id("latest")
                }.font(.system(size: CGFloat(fontSize))).frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: captions.provisional) { _, _ in reader.scrollTo("latest", anchor: .bottom) }
        }
    }
}

struct CaptionsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var captions: LiveCaptions
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label(captions.running ? "Live captions" : (captions.finalized ? "Final transcript" : "Caption draft"), systemImage: "captions.bubble")
                Spacer()
                if model.phase == "recording" { Button("Stop Recording") { Task { await model.stopRecording() } } }
            }
            Text(captions.status).font(.caption).foregroundStyle(.secondary)
            CaptionText(captions: captions, fontSize: model.captionFontSize)
        }.padding(18).frame(minWidth: 400, minHeight: 180)
            .background(WindowAccessor { $0.level = model.captionsAlwaysOnTop ? .floating : .normal })
    }
}
