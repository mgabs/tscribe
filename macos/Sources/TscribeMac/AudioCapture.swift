@preconcurrency import AVFoundation
import CoreMedia
import ScreenCaptureKit

/// The converter may request input more than once; hand off this buffer only once.
/// The lock protects the single mutable reference used by its sendable callback.
final class ConverterInput: @unchecked Sendable {
    private let lock = NSLock()
    private var buffer: AVAudioPCMBuffer?

    init(_ buffer: AVAudioPCMBuffer) { self.buffer = buffer }

    func take() -> AVAudioPCMBuffer? {
        lock.lock()
        defer { lock.unlock() }
        let result = buffer
        buffer = nil
        return result
    }
}

/// Serial sample processing keeps capture callbacks off the main/UI thread.
final class PCMWriter {
    let queue: DispatchQueue
    private let url: URL
    private let target: AVAudioFormat
    private var file: AVAudioFile?
    private var converter: AVAudioConverter?
    private var frames: AVAudioFramePosition = 0
    private var inputDuration: Double = 0
    private var failure: Error?
    private let live: Bool
    private let epoch: Double
    private var startOffset: Double?
    private var recent: [Data] = []
    private var recentFrames = 0

    var offset: Double { startOffset ?? 0 }
    var hasAudio: Bool { frames > 0 }


    init(url: URL, sampleRate: Double, channels: Int, live: Bool = false, epoch: Double = 0, queue: DispatchQueue = DispatchQueue(label: "tscribe.audio.samples")) throws {
        guard sampleRate > 0, channels > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: AVAudioChannelCount(channels), interleaved: true) else {
            throw AppFailure(message: "Invalid audio sample rate or channel count.")
        }
        self.queue = queue
        self.live = live
        self.epoch = epoch
        self.url = url
        self.target = target
    }

    func append(_ sample: CMSampleBuffer) {
        do {
            guard CMSampleBufferDataIsReady(sample),
                  let description = CMSampleBufferGetFormatDescription(sample),
                  let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description),
                  let format = AVAudioFormat(streamDescription: asbd),
                  let input = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(CMSampleBufferGetNumSamples(sample))) else { return }
            input.frameLength = input.frameCapacity
            let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(sample, at: 0, frameCount: Int32(input.frameLength), into: input.mutableAudioBufferList)
            guard status == noErr else { throw AppFailure(message: "Could not read captured audio (\(status)).") }
            if startOffset == nil {
                let timestamp = CMSampleBufferGetPresentationTimeStamp(sample).seconds
                startOffset = timestamp.isFinite ? max(0, timestamp - epoch) : 0
            }
            try appendPCM(input)
        } catch { if failure == nil { failure = error } }
    }

    // Also used by tests to verify real WAV conversion without recording anyone.
    func appendPCM(_ input: AVAudioPCMBuffer) throws {
        inputDuration += Double(input.frameLength) / input.format.sampleRate
        if converter == nil || converter?.inputFormat != input.format {
            converter = AVAudioConverter(from: input.format, to: target)
            converter?.primeMethod = .none
        }
        guard let converter else { throw AppFailure(message: "This audio device's format cannot be converted to WAV.") }
        let capacity = AVAudioFrameCount(ceil(Double(input.frameLength) * target.sampleRate / input.format.sampleRate)) + 64
        guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { throw AppFailure(message: "Could not allocate an audio buffer.") }
        let source = ConverterInput(input)
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, state in
            guard let input = source.take() else { state.pointee = .noDataNow; return nil }
            state.pointee = .haveData
            return input
        }
        if status == .error { throw error ?? AppFailure(message: "Audio conversion failed.") as NSError }
        try write(output)
    }

    private func write(_ output: AVAudioPCMBuffer) throws {
        if output.frameLength > 0 {
            if file == nil { file = try AVAudioFile(forWriting: url, settings: target.settings, commonFormat: .pcmFormatInt16, interleaved: true) }
            try file?.write(from: output)
            frames += AVAudioFramePosition(output.frameLength)
            if live, let samples = output.int16ChannelData {
                let bytesPerFrame = Int(target.channelCount) * 2
                let maxFrames = Int(target.sampleRate * 30)
                let keptFrames = min(Int(output.frameLength), maxFrames)
                let data = Data(bytes: samples.pointee.advanced(by: (Int(output.frameLength) - keptFrames) * Int(target.channelCount)), count: keptFrames * bytesPerFrame)
                recent.append(data)
                recentFrames += keptFrames
                while recentFrames > maxFrames, let first = recent.first {
                    let excess = min(recentFrames - maxFrames, first.count / bytesPerFrame)
                    if excess * bytesPerFrame == first.count { recent.removeFirst() }
                    else { recent[0] = first.dropFirst(excess * bytesPerFrame) }
                    recentFrames -= excess
                }
            }
        }
    }

    /// Called on the sample queue: closed snapshot WAVs are independent of capture.
    func snapshot(to url: URL) throws -> Double? {
        if let failure { throw failure }
        guard live, recentFrames > 0 else { return nil }
        let bytes = recent.reduce(into: Data()) { $0.append($1) }
        guard let buffer = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: AVAudioFrameCount(recentFrames)),
              let destination = buffer.int16ChannelData else { return nil }
        buffer.frameLength = buffer.frameCapacity
        bytes.withUnsafeBytes { source in
            if let address = source.baseAddress { memcpy(destination.pointee, address, bytes.count) }
        }
        let snapshot = try AVAudioFile(forWriting: url, settings: target.settings, commonFormat: .pcmFormatInt16, interleaved: true)
        try snapshot.write(from: buffer)
        return offset + Double(frames - AVAudioFramePosition(recentFrames)) / target.sampleRate
    }

    func finish(allowEmpty: Bool = false) throws {
        try queue.sync {
            // The rate converter retains a filter tail between buffers. Drain it
            // at EOF so short recordings do not lose their final syllables.
            if let converter, file != nil {
                while true {
                    guard let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: 4096) else { break }
                    var conversionError: NSError?
                    let status = converter.convert(to: output, error: &conversionError) { _, state in
                        state.pointee = .endOfStream
                        return nil
                    }
                    if status == .error { throw conversionError ?? AppFailure(message: "Could not finalize the audio conversion.") as NSError }
                    let remaining = max(0, AVAudioFramePosition((inputDuration * target.sampleRate).rounded()) - frames)
                    output.frameLength = min(output.frameLength, AVAudioFrameCount(remaining))
                    if output.frameLength > 0 {
                        try write(output)
                    }
                    if status == .endOfStream || output.frameLength == 0 { break }
                }
            }
            if frames == 0, allowEmpty, failure == nil {
                file = try AVAudioFile(forWriting: url, settings: target.settings, commonFormat: .pcmFormatInt16, interleaved: true)
            }
            file = nil // Close and finalize the WAV header before the worker reads it.
            if let failure { throw failure }
            guard frames > 0 || allowEmpty else { throw AppFailure(message: "No audio was captured. Check permissions and the selected input device.") }
        }
    }
}

struct CaptionSnapshot {
    let directory: URL
    let sequence: Int
    let sessionID: UUID
}

struct CaptureSummary {
    let offsets: [String: Double]
    let captionTracks: [String: Double]
    let captionWarning: String?
}

// Capture lifecycle is serialized by AppModel; sample callbacks, snapshots, and
// writer disposal all use sampleQueue. Inference never runs on that queue.
final class NativeAudioCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let sampleQueue = DispatchQueue(label: "tscribe.capture.samples")
    private var microphone: AVCaptureSession?
    private var system: SCStream?
    private var microphoneWriter: PCMWriter?
    private var systemWriter: PCMWriter?
    var onFailure: ((Error) -> Void)?

    func start(url: URL, source: String, sampleRate: Double, channels: Int, deviceName: String, live: Bool) async throws {
        guard ["both", "microphone", "system"].contains(source) else { throw AppFailure(message: "Unknown audio source.") }
        let useMicrophone = source != "system", useSystem = source != "microphone"
        if useMicrophone {
            guard await AVCaptureDevice.requestAccess(for: .audio) else {
                throw AppFailure(message: "Microphone access is off. Enable tscribe in System Settings → Privacy & Security → Microphone, then try again.")
            }
        }
        // Resolve permissions before starting the common recording clock.
        let content = useSystem ? try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true) : nil
        let epoch = CMClockGetTime(CMClockGetHostTimeClock()).seconds
        do {
            if useMicrophone {
                microphoneWriter = try PCMWriter(url: url, sampleRate: sampleRate, channels: channels, live: live, epoch: epoch, queue: sampleQueue)
                try await startMicrophone(deviceName: deviceName)
            }
            if useSystem, let content {
                let trackDirectory = url.deletingLastPathComponent().appendingPathComponent(".tracks").appendingPathComponent(url.deletingPathExtension().lastPathComponent)
                if source == "both" { try FileManager.default.createDirectory(at: trackDirectory, withIntermediateDirectories: true) }
                systemWriter = try PCMWriter(url: source == "both" ? trackDirectory.appendingPathComponent("system.wav") : url,
                                             sampleRate: sampleRate, channels: channels, live: live, epoch: epoch, queue: sampleQueue)
                try await startSystem(content: content)
            }
        } catch {
            // A failure in either half must stop the other half too.
            _ = try? await stop()
            throw error
        }
    }

    private func startMicrophone(deviceName: String) async throws {
        let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
        let device = deviceName.isEmpty ? AVCaptureDevice.default(for: .audio) : discovery.devices.first { $0.uniqueID == deviceName || $0.localizedName == deviceName }
        guard let device else { throw AppFailure(message: "Microphone '\(deviceName)' was not found. Set recording.default_device to a device name or leave it empty for the system default.") }
        let session = AVCaptureSession()
        let input = try AVCaptureDeviceInput(device: device)
        let output = AVCaptureAudioDataOutput()
        output.setSampleBufferDelegate(self, queue: sampleQueue)
        guard session.canAddInput(input), session.canAddOutput(output) else { throw AppFailure(message: "The selected microphone cannot be captured.") }
        session.beginConfiguration()
        session.addInput(input)
        session.addOutput(output)
        session.commitConfiguration()
        microphone = session
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async { session.startRunning(); continuation.resume() }
        }
        guard session.isRunning else { throw AppFailure(message: "The microphone did not start. Check macOS permissions and reconnect the device.") }
    }

    private func startSystem(content: SCShareableContent) async throws {
        guard let display = content.displays.first else { throw AppFailure(message: "No display is available for system-audio capture.") }
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let settings = SCStreamConfiguration()
        settings.width = 16
        settings.height = 16
        settings.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        settings.capturesAudio = true
        settings.excludesCurrentProcessAudio = true
        settings.sampleRate = 48000
        settings.channelCount = 2
        let stream = SCStream(filter: filter, configuration: settings, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: sampleQueue)
        system = stream
        try await stream.startCapture()
    }

    func snapshot(directory: URL, stem: String, sequence: Int) async throws -> [String: Double] {
        try await withCheckedThrowingContinuation { continuation in
            sampleQueue.async {
                do {
                    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                    var offsets: [String: Double] = [:]
                    for (source, writer) in [("microphone", self.microphoneWriter), ("system", self.systemWriter)] {
                        if let offset = try writer?.snapshot(to: directory.appendingPathComponent("\(sequence)-\(source).wav")) {
                            offsets[source] = offset
                        }
                    }
                    continuation.resume(returning: offsets)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    func stop(finalSnapshot: CaptionSnapshot? = nil) async throws -> CaptureSummary {
        var stoppingError: Error?
        if let system {
            do { try await system.stopCapture() } catch { stoppingError = error }
            self.system = nil
        }
        if let microphone {
            await withCheckedContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async { microphone.stopRunning(); continuation.resume() }
            }
            self.microphone = nil
        }
        // Flush callbacks before accessing/releasing their writers.
        let writers = sampleQueue.sync { [("microphone", microphoneWriter), ("system", systemWriter)] }
        guard writers.contains(where: { $0.1 != nil }) else { throw AppFailure(message: "No recording is active.") }
        var offsets: [String: Double] = [:]
        let both = writers.allSatisfy { $0.1 != nil }
        for (source, writer) in writers {
            guard let writer else { continue }
            do { try writer.finish(allowEmpty: both); offsets[source] = writer.offset }
            catch { if stoppingError == nil { stoppingError = error } }
        }
        if !writers.contains(where: { $0.1?.hasAudio == true }), stoppingError == nil {
            stoppingError = AppFailure(message: "No audio was captured. Check permissions and selected devices.")
        }
        var captionTracks: [String: Double] = [:]
        var captionWarning: String?
        if let finalSnapshot, stoppingError == nil {
            do {
                captionTracks = try sampleQueue.sync {
                    try FileManager.default.createDirectory(at: finalSnapshot.directory, withIntermediateDirectories: true)
                    var tracks: [String: Double] = [:]
                    for (source, writer) in writers {
                        let url = finalSnapshot.directory.appendingPathComponent("\(finalSnapshot.sequence)-\(source).wav")
                        if let offset = try writer?.snapshot(to: url) { tracks[source] = offset }
                    }
                    return tracks
                }
            } catch { captionWarning = "The final caption snapshot could not be saved: \(error.localizedDescription). Audio is preserved." }
        }
        sampleQueue.sync { microphoneWriter = nil; systemWriter = nil }
        if let stoppingError { throw stoppingError }
        return CaptureSummary(offsets: offsets, captionTracks: captionTracks, captionWarning: captionWarning)
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        microphoneWriter?.append(sampleBuffer)
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        if type == .audio { systemWriter?.append(sampleBuffer) }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { onFailure?(error) }
}
