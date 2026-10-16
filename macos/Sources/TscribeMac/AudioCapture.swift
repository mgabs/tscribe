@preconcurrency import AVFoundation
import CoreMedia
import ScreenCaptureKit

/// Serial sample processing keeps capture callbacks off the main/UI thread.
final class PCMWriter {
    let queue = DispatchQueue(label: "tscribe.audio.samples")
    private let url: URL
    private let target: AVAudioFormat
    private var file: AVAudioFile?
    private var converter: AVAudioConverter?
    private var frames: AVAudioFramePosition = 0
    private var inputDuration: Double = 0
    private var failure: Error?

    init(url: URL, sampleRate: Double, channels: Int) throws {
        guard sampleRate > 0, channels > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: AVAudioChannelCount(channels), interleaved: true) else {
            throw AppFailure(message: "Invalid audio sample rate or channel count.")
        }
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
        var supplied = false
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, state in
            if supplied { state.pointee = .noDataNow; return nil }
            supplied = true
            state.pointee = .haveData
            return input
        }
        if status == .error { throw error ?? AppFailure(message: "Audio conversion failed.") as NSError }
        if output.frameLength > 0 {
            if file == nil { file = try AVAudioFile(forWriting: url, settings: target.settings, commonFormat: .pcmFormatInt16, interleaved: true) }
            try file?.write(from: output)
            frames += AVAudioFramePosition(output.frameLength)
        }
    }

    func finish() throws {
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
                        try file?.write(from: output)
                        frames += AVAudioFramePosition(output.frameLength)
                    }
                    if status == .endOfStream || output.frameLength == 0 { break }
                }
            }
            file = nil // Close and finalize the WAV header before the worker reads it.
            if let failure { throw failure }
            guard frames > 0 else { throw AppFailure(message: "No audio was captured. Check permissions and the selected input device.") }
        }
    }
}

final class NativeAudioCapture: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate, SCStreamOutput, SCStreamDelegate {
    private var microphone: AVCaptureSession?
    private var system: SCStream?
    private var writer: PCMWriter?
    var onFailure: ((Error) -> Void)?

    func start(url: URL, systemAudio: Bool, sampleRate: Double, channels: Int, deviceName: String) async throws {
        let writer = try PCMWriter(url: url, sampleRate: sampleRate, channels: channels)
        self.writer = writer
        if systemAudio {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else { throw AppFailure(message: "No display is available for system-audio capture.") }
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let settings = SCStreamConfiguration()
            settings.width = 16
            settings.height = 16
            settings.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            settings.capturesAudio = true
            settings.excludesCurrentProcessAudio = true
            // ScreenCaptureKit accepts native system rates; PCMWriter converts to config.
            settings.sampleRate = 48000
            settings.channelCount = 2
            let stream = SCStream(filter: filter, configuration: settings, delegate: self)
            try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: writer.queue)
            do { try await stream.startCapture() }
            catch { self.writer = nil; throw error }
            system = stream
        } else {
            guard await AVCaptureDevice.requestAccess(for: .audio) else {
                self.writer = nil
                throw AppFailure(message: "Microphone access is off. Enable tscribe in System Settings → Privacy & Security → Microphone, then try again.")
            }
            let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
            let device: AVCaptureDevice?
            if deviceName.isEmpty { device = AVCaptureDevice.default(for: .audio) }
            else { device = discovery.devices.first { $0.uniqueID == deviceName || $0.localizedName == deviceName } }
            guard let device else { throw AppFailure(message: "Microphone '\(deviceName)' was not found. Set recording.default_device to a device name or leave it empty for the system default.") }
            let session = AVCaptureSession()
            let input = try AVCaptureDeviceInput(device: device)
            let output = AVCaptureAudioDataOutput()
            output.setSampleBufferDelegate(self, queue: writer.queue)
            guard session.canAddInput(input), session.canAddOutput(output) else { throw AppFailure(message: "The selected microphone cannot be captured.") }
            session.beginConfiguration()
            session.addInput(input)
            session.addOutput(output)
            session.commitConfiguration()
            await withCheckedContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async { session.startRunning(); continuation.resume() }
            }
            guard session.isRunning else { throw AppFailure(message: "The microphone did not start. Check macOS permissions and reconnect the device.") }
            microphone = session
        }
    }

    func stop() async throws {
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
        guard let writer else { throw AppFailure(message: "No recording is active.") }
        defer { self.writer = nil }
        try writer.finish()
        if let stoppingError { throw stoppingError }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        writer?.append(sampleBuffer)
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        if type == .audio { writer?.append(sampleBuffer) }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { onFailure?(error) }
}
