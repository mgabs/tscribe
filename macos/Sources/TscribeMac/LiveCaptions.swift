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
    @Published private(set) var finishing = false
    private var sessionStem: String?
    private var directory: URL?
    private var sessionID = UUID()
    private var nextSequence = 0
    private var publishedSequence = -1
    private let worker: WorkerClient
    private let interval: UInt64
    private var task: Task<Void, Never>?

    init(worker: WorkerClient? = nil, interval: UInt64 = 3_000_000_000) {
        self.worker = worker ?? WorkerClient()
        self.interval = interval
    }

    func start(stem: String, directory: URL, capture: NativeAudioCapture) {
        start(stem: stem, directory: directory) { directory, sequence in
            try await capture.snapshot(directory: directory, stem: stem, sequence: sequence)
        }
    }

    func start(stem: String, directory: URL, snapshot: @escaping (URL, Int) async throws -> [String: Double]) {
        stop()
        sessionStem = stem
        confirmed = ""; provisional = ""; running = true; finalized = false
        nextSequence = 0; publishedSequence = -1
        status = "Preparing captions… First use may download the caption model."
        let directory = directory.appendingPathComponent(".live").appendingPathComponent(stem)
        self.directory = directory
        let generation = sessionID
        task = Task { [weak self] in
            guard let self else { return }
            var delay = interval
            while !Task.isCancelled, sessionID == generation {
                do { try await Task.sleep(nanoseconds: delay) }
                catch { break }
                do {
                    let began = Date()
                    defer {
                        let remaining = Double(interval) / 1_000_000_000 - Date().timeIntervalSince(began)
                        delay = UInt64(max(0.25, remaining) * 1_000_000_000)
                    }
                    let sequence = reserveSequence()
                    let tracks = try await snapshot(directory, sequence)
                    defer { removeWindow(directory: directory, sequence: sequence) }
                    guard !Task.isCancelled, sessionID == generation else { break }
                    if tracks.isEmpty { continue }
                    let result = try await worker.request("live-caption", values: ["stem": stem, "sequence": sequence, "tracks": tracks])
                    guard sessionID == generation, !Task.isCancelled || finishing else { break }
                    guard sequence >= publishedSequence else { break }
                    apply(result, sequence: sequence)
                    if !finishing {
                        let gaps = result["gaps"] as? [[String: Any]] ?? []
                        if !gaps.isEmpty { status = "Some captions were missed. Full audio is still being recorded." }
                        else if Date().timeIntervalSince(began) > 3 { status = "Captions catching up · audio recording continues" }
                        else { status = "Live draft · the latest phrase may change" }
                        if result["echo_active"] as? Bool == true { status += " · echo reduction active" }
                        if let warning = result["warning"] as? String, !warning.isEmpty { status += " · " + warning }
                    }
                } catch {
                    if !Task.isCancelled, sessionID == generation { status = "Captions unavailable: \(error.localizedDescription) Recording continues." }
                    break
                }
            }
            if sessionID == generation, !finishing {
                if !Task.isCancelled { worker.stop() }
                try? FileManager.default.removeItem(at: directory)
            }
        }
    }

    private func reserveSequence() -> Int {
        let sequence = nextSequence
        nextSequence += 1
        return sequence
    }

    private func apply(_ result: [String: Any], sequence: Int) {
        guard sequence >= publishedSequence else { return }
        publishedSequence = sequence
        confirmed = result["text"] as? String ?? ""
        provisional = result["provisional_text"] as? String ?? ""
    }

    private func removeWindow(directory: URL, sequence: Int) {
        for source in ["microphone", "system"] {
            try? FileManager.default.removeItem(at: directory.appendingPathComponent("\(sequence)-\(source).wav"))
        }
    }

    /// Stop scheduling windows, retaining the model and any already queued pass.
    func prepareStop() -> CaptionSnapshot? {
        guard running, let directory else { return nil }
        finishing = true; running = false
        status = "Finishing captions… Audio capture is stopping."
        task?.cancel()
        return CaptionSnapshot(directory: directory, sequence: reserveSequence(), sessionID: sessionID)
    }

    /// Called after capture closes and exports its final, converter-drained window.
    func flushFinal(_ snapshot: CaptionSnapshot, tracks: [String: Double], timeout: UInt64 = 15_000_000_000) async -> String? {
        guard snapshot.sessionID == sessionID, finishing, let stem = sessionStem else {
            return "Caption finishing was skipped. The latest saved draft is retained."
        }
        let generation = sessionID
        var timedOut = false
        let deadline = Task { @MainActor [weak self] in
            do { try await Task.sleep(nanoseconds: timeout) } catch { return }
            guard let self, self.sessionID == generation, self.finishing else { return }
            timedOut = true
            self.worker.stop()
        }
        defer {
            deadline.cancel()
            if sessionID == generation {
                worker.stop()
                finishing = false
                try? FileManager.default.removeItem(at: snapshot.directory)
            }
        }
        if tracks.isEmpty {
            status = "No caption audio was available. The full recording remains saved."
            return nil
        }
        do {
            let result = try await worker.request("live-caption", values: ["stem": stem, "sequence": snapshot.sequence, "tracks": tracks, "final": true])
            guard sessionID == generation else { return "Caption finishing was skipped. The latest saved draft is retained." }
            apply(result, sequence: snapshot.sequence)
            let gaps = result["gaps"] as? [[String: Any]] ?? []
            if confirmed.isEmpty && provisional.isEmpty { status = "No speech was recognized. The full recording remains saved." }
            else if !gaps.isEmpty { status = "Caption draft saved, including the end. Earlier gaps remain; full audio is saved." }
            else { status = "Caption draft saved through the end of the recording" }
            if let warning = result["warning"] as? String, !warning.isEmpty { status += " · " + warning; return warning }
            return nil
        } catch {
            guard sessionID == generation else { return "Caption finishing was skipped. The latest saved draft is retained." }
            let warning = timedOut
                ? "Caption finishing timed out. The latest saved draft and full recording are retained."
                : "Caption finishing failed: \(error.localizedDescription). The latest saved draft and full recording are retained."
            status = warning
            return warning
        }
    }

    func finish(text: String, stem: String) {
        guard stem == sessionStem else { return }
        confirmed = text; provisional = ""; finalized = true
        status = "Final transcript · saved with the recording"
    }

    /// Abort captions, including a final flush; does not stop audio recording.
    func stop() {
        let oldTask = task, oldDirectory = directory, oldGeneration = sessionID
        task?.cancel()
        task = nil
        sessionID = UUID()
        worker.stop()
        if finishing { status = "Caption finishing skipped. The latest saved draft is retained." }
        else if running {
            status = confirmed.isEmpty && provisional.isEmpty
                ? "No caption draft was produced. The full recording remains available."
                : "Caption draft saved · final transcription follows your recording settings"
        }
        finishing = false; running = false
        if let oldDirectory {
            Task { [weak self] in
                await oldTask?.value
                if self?.directory != oldDirectory || self?.sessionID == oldGeneration || (self?.running == false && self?.finishing == false) {
                    try? FileManager.default.removeItem(at: oldDirectory)
                }
            }
        }
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
            HStack {
                if captions.finishing { ProgressView().controlSize(.small) }
                Text(captions.status).font(.caption).foregroundStyle(.secondary)
                if captions.finishing { Button("Skip Captions") { captions.stop() } }
            }
            CaptionText(captions: captions, fontSize: model.captionFontSize)
        }.padding(18).frame(minWidth: 400, minHeight: 180)
            .background(WindowAccessor { $0.level = model.captionsAlwaysOnTop ? .floating : .normal })
    }
}
