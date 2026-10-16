import AppKit
import Combine
import Foundation
import UserNotifications

struct RecordingSession: Identifiable {
    let id: String
    let duration: Double
    let transcribed: Bool
    let source: String
    init?(_ data: [String: Any]) {
        guard let stem = data["stem"] as? String else { return nil }
        id = stem
        duration = data["duration"] as? Double ?? 0
        transcribed = data["transcribed"] as? Bool ?? false
        source = data["source"] as? String ?? "audio"
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var phase = "loading"
    @Published var message = "Loading settings…"
    @Published var error: String?
    @Published var progress = 0.0
    @Published var sessions: [RecordingSession] = []
    @Published var selected: String?
    @Published var transcript = "Select a recording to read its transcript."
    @Published var model = "small"
    @Published var language = "auto"
    @Published var autoTranscribe = true
    @Published var diarize = false
    @Published var notifications = true
    @Published var recentLimit = 5
    @Published var showElapsed = true
    @Published var liveEnabled = false
    @Published var captionModel = "base"
    let liveCaptions = LiveCaptions()
    @Published var captionAudioSource = "both"
    @Published var captionOutputMode = "headphones"
    @Published var captionFontSize = 24
    @Published var captionsAlwaysOnTop = true
    @Published var configPath = ""
    @Published var recordingsPath = ""
    @Published var started: Date?
    @Published var menuDate = Date()
    let worker = WorkerClient()
    private let capture = NativeAudioCapture()
    private var activeStem: String?
    private var recordingSource = "microphone"
    private var quitting = false
    private var menuTimer: Timer?
    private let diarizeOverride: Bool? = ProcessInfo.processInfo.arguments.contains("--diarize") ? true : (ProcessInfo.processInfo.arguments.contains("--no-diarize") ? false : nil)
    private var transcriptCache: [String: String] = [:]
    var busy: Bool { phase != "idle" }

    init() {
        // Publish elapsed-time updates only during capture.
        menuTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.phase == "recording" else { return }
                self.menuDate = Date()
            }
        }
        worker.onEvent = { [weak self] event, data in
            guard let self else { return }
            if event == "phase" { self.phase = "transcribing"; self.message = "Transcribing with \(data["model"] as? String ?? self.model)… First use may download the model." }
            if event == "progress", let current = data["current"] as? Double, let total = data["total"] as? Double, total > 0 { self.progress = min(current / total, 1) }
            if event == "worker-stopped" { self.error = data["message"] as? String }
        }
        capture.onFailure = { [weak self] error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.error = error.localizedDescription
                if self.phase == "recording" { await self.stopRecording() }
            }
        }
    }

    func bootstrap() async {
        do { apply(try await worker.request("bootstrap")); phase = "idle"; message = "Ready to record" }
        catch { fail(error) }
    }

    private func apply(_ snapshot: [String: Any]) {
        configPath = snapshot["config_path"] as? String ?? configPath
        recordingsPath = snapshot["recordings_dir"] as? String ?? recordingsPath
        if let list = snapshot["sessions"] as? [[String: Any]] { sessions = list.compactMap(RecordingSession.init) }
        guard let config = snapshot["config"] as? [String: [String: Any]] else { return }
        model = config["transcription"]?["model"] as? String ?? "small"
        language = config["transcription"]?["language"] as? String ?? "auto"
        diarize = diarizeOverride ?? (config["transcription"]?["diarize"] as? Bool ?? false)
        autoTranscribe = config["recording"]?["auto_transcribe"] as? Bool ?? true
        notifications = config["app"]?["notifications"] as? Bool ?? true
        recentLimit = config["app"]?["recent_limit"] as? Int ?? 5
        showElapsed = config["app"]?["show_elapsed_time"] as? Bool ?? true
        liveEnabled = config["captions"]?["enabled"] as? Bool ?? false
        captionModel = config["captions"]?["model"] as? String ?? "base"
        captionAudioSource = config["captions"]?["audio_source"] as? String ?? "both"
        captionOutputMode = config["captions"]?["output_mode"] as? String ?? "headphones"
        captionFontSize = config["captions"]?["font_size"] as? Int ?? 24
        captionsAlwaysOnTop = config["captions"]?["always_on_top"] as? Bool ?? true
    }

    func startRecording(system: Bool) async {
        await startRecording(source: system ? "system" : "microphone")
    }

    func startMeeting() async { await startRecording(source: captionAudioSource) }

    func startRecording(source: String) async {
        guard !busy else { return }
        phase = "preparing"; error = nil; progress = 0
        message = "Preparing audio. macOS may request microphone or system-audio capture permission…"
        do {
            let prepared = try await worker.request("prepare-recording")
            guard let stem = prepared["stem"] as? String, let path = prepared["wav_path"] as? String,
                  let config = prepared["config"] as? [String: [String: Any]] else { throw AppFailure(message: "Invalid recording details from the worker.") }
            let recording = config["recording"] ?? [:]
            try await capture.start(url: URL(fileURLWithPath: path), source: source,
                                    sampleRate: recording["sample_rate"] as? Double ?? 16000,
                                    channels: recording["channels"] as? Int ?? 1,
                                    deviceName: recording["default_device"] as? String ?? "", live: liveEnabled)
            activeStem = stem; recordingSource = source; started = Date(); menuDate = Date()
            phase = "recording"; message = source == "both" ? "Recording microphone + system audio" : "Recording \(source)"
            if liveEnabled { liveCaptions.start(stem: stem, directory: URL(fileURLWithPath: path).deletingLastPathComponent(), capture: capture) }
            if quitting { await stopRecording() }
        } catch { fail(error) }
    }

    func stopRecording() async {
        guard phase == "recording", let stem = activeStem else { return }
        phase = "saving"; message = "Saving recording…"
        liveCaptions.stop()
        do {
            let summary = try await capture.stop()
            let source = recordingSource == "both" ? "meeting" : (recordingSource == "system" ? "loopback" : "microphone")
            let result = try await worker.request("finish-recording", values: ["stem": stem, "source": source, "device": "macOS native audio", "diarize": diarize, "track_offsets": summary.offsets])
            complete(result, stem: stem)
        } catch { fail(error) }
    }

    func transcribeSelected() async {
        guard !busy, let selected else { return }
        phase = "transcribing"; progress = 0; error = nil; message = "Preparing transcription…"
        do { complete(try await worker.request("transcribe", values: ["stem": selected, "diarize": diarize]), stem: selected) }
        catch { fail(error) }
    }

    private func complete(_ result: [String: Any], stem: String) {
        apply(result); selected = stem
        transcript = result["text"] as? String ?? ""
        transcriptCache[stem] = transcript
        if result["message"] as? String == "Transcription complete" { liveCaptions.finish(text: transcript, stem: stem) }
        message = result["message"] as? String ?? "Complete"
        phase = "idle"; started = nil; activeStem = nil
        if notifications {
            let completionMessage = result["message"] as? String ?? "Recording saved"
            Task { @MainActor in
                let center = UNUserNotificationCenter.current()
                if (try? await center.requestAuthorization(options: [.alert, .sound])) == true {
                    let content = UNMutableNotificationContent()
                    content.title = "tscribe"
                    content.body = completionMessage
                    try? await center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
                }
            }
        }
        if quitting { quit() }
    }

    func loadTranscript() async {
        guard !busy, let stem = selected else { return }
        if let cached = transcriptCache[stem] { transcript = cached; return }
        do {
            let result = try await worker.request("read-transcript", values: ["stem": stem])
            if selected == stem { transcript = result["text"] as? String ?? "" }
        } catch { self.error = error.localizedDescription }
    }

    func saveSettings() async {
        guard !busy else { return }
        phase = "saving"
        do {
            apply(try await worker.request("save-config", values: ["changes": [
                "transcription.model": model, "transcription.language": language,
                "transcription.diarize": diarize, "recording.auto_transcribe": autoTranscribe,
                "app.notifications": notifications, "app.recent_limit": recentLimit,
                "app.show_elapsed_time": showElapsed,
                "captions.enabled": liveEnabled, "captions.model": captionModel,
                "captions.audio_source": captionAudioSource, "captions.output_mode": captionOutputMode,
                "captions.font_size": captionFontSize, "captions.always_on_top": captionsAlwaysOnTop,
            ]]))
            phase = "idle"; message = "Settings saved"
        } catch { fail(error) }
    }

    func openConfig() async {
        guard !busy else { return }
        do {
            let data = try await worker.request("save-config", values: ["changes": [:]])
            apply(data)
            NSWorkspace.shared.open(URL(fileURLWithPath: configPath))
        } catch { fail(error) }
    }

    func menuTitle(at date: Date) -> String {
        guard phase == "recording" else { return "tscribe" }
        guard showElapsed, let started else { return "Recording" }
        let seconds = max(0, Int(date.timeIntervalSince(started)))
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }

    func copyTranscript() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(transcript, forType: .string)
    }
    func openRecordings() { if !recordingsPath.isEmpty { NSWorkspace.shared.open(URL(fileURLWithPath: recordingsPath)) } }
    func quit() {
        if !busy { liveCaptions.stop() }
        if phase == "loading" { phase = "idle"; worker.stop(); NSApp.terminate(nil); return }
        if phase == "recording" { quitting = true; Task { await stopRecording() }; return }
        if busy { quitting = true; message += " tscribe will quit when this finishes."; return }
        worker.stop(); NSApp.terminate(nil)
    }
    private func fail(_ failure: Error) {
        error = failure.localizedDescription
        phase = "idle"; started = nil; activeStem = nil
        message = "Could not complete the action. Any saved audio remains in Recordings."
        if quitting { quit() }
    }
}
