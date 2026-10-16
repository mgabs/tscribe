import XCTest
import AVFoundation
@testable import TscribeMac

final class AudioTests: XCTestCase {
    func testConverterInputIsConsumedOnlyOnce() throws {
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 160))
        let source = ConverterInput(buffer)
        XCTAssertTrue(source.take() === buffer)
        XCTAssertNil(source.take())
        XCTAssertNil(source.take())
    }

    func testConvertsNativeStereoToConfiguredMonoWAV() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("recording.wav")
        let writer = try PCMWriter(url: url, sampleRate: 16000, channels: 1)
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 2, interleaved: false))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4800))
        buffer.frameLength = 4800
        let samples = try XCTUnwrap(buffer.floatChannelData)
        for channel in 0..<2 {
            for frame in 0..<4800 { samples[channel][frame] = 0.25 * sin(Float(frame) * 0.04) }
        }
        try writer.queue.sync { try writer.appendPCM(buffer) }
        try writer.finish()
        let audio = try AVAudioFile(forReading: url)
        XCTAssertEqual(audio.fileFormat.sampleRate, 16000)
        XCTAssertEqual(audio.fileFormat.channelCount, 1)
        XCTAssertEqual(audio.fileFormat.commonFormat, .pcmFormatInt16)
        XCTAssertGreaterThan(audio.length, 1500)
        XCTAssertLessThanOrEqual(audio.length, 1600)
    }

    func testEmptyRecordingHasActionableError() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        let writer = try PCMWriter(url: url, sampleRate: 16000, channels: 1)
        XCTAssertThrowsError(try writer.finish()) { error in
            XCTAssertTrue(error.localizedDescription.contains("No audio was captured"))
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }
}

final class WorkerTests: XCTestCase {
    @MainActor
    func testCaptionSettingsSaveAndReloadThroughAppModel() async throws {
        guard ProcessInfo.processInfo.environment["TSCRIBE_PYTHON_EXECUTABLE"] != nil else {
            throw XCTSkip("Set TSCRIBE_PYTHON_EXECUTABLE to run the worker integration test")
        }
        let model = AppModel()
        defer { model.worker.stop() }
        await model.bootstrap()
        XCTAssertNil(model.error)
        model.captionAudioSource = "both"
        model.captionOutputMode = "speakers"
        model.captionFontSize = 36
        model.captionsAlwaysOnTop = false
        await model.saveSettings()
        XCTAssertNil(model.error)
        let reopened = AppModel()
        defer { reopened.worker.stop() }
        await reopened.bootstrap()
        XCTAssertNil(reopened.error)
        XCTAssertEqual(reopened.captionAudioSource, "both")
        XCTAssertEqual(reopened.captionOutputMode, "speakers")
        XCTAssertEqual(reopened.captionFontSize, 36)
        XCTAssertFalse(reopened.captionsAlwaysOnTop)
    }

    @MainActor
    func testNativeClientTalksToRealPythonWorker() async throws {
        guard ProcessInfo.processInfo.environment["TSCRIBE_PYTHON_EXECUTABLE"] != nil else {
            throw XCTSkip("Set TSCRIBE_PYTHON_EXECUTABLE to run the worker integration test")
        }
        let client = WorkerClient()
        defer { client.stop() }
        let snapshot = try await client.request("bootstrap")
        XCTAssertNotNil(snapshot["config"] as? [String: Any])
        XCTAssertNotNil(snapshot["recordings_dir"] as? String)
        do {
            _ = try await client.request("not-a-command")
            XCTFail("Invalid worker commands must surface as errors")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("Unknown worker command"))
        }
        let retried = try await client.request("bootstrap")
        XCTAssertNotNil(retried["config"])
        _ = try await client.request("save-config", values: ["changes": ["recording.auto_transcribe": false]])
        let prepared = try await client.request("prepare-recording")
        let stem = try XCTUnwrap(prepared["stem"] as? String)
        let path = try XCTUnwrap(prepared["wav_path"] as? String)
        let writer = try PCMWriter(url: URL(fileURLWithPath: path), sampleRate: 16000, channels: 1)
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 1600))
        buffer.frameLength = 1600
        try XCTUnwrap(buffer.int16ChannelData).pointee.initialize(repeating: 0, count: 1600)
        try writer.queue.sync { try writer.appendPCM(buffer) }
        try writer.finish()
        let saved = try await client.request("finish-recording", values: ["stem": stem])
        let rows = try XCTUnwrap(saved["sessions"] as? [[String: Any]])
        let session = try XCTUnwrap(rows.compactMap(RecordingSession.init).first { $0.id == stem })
        XCTAssertEqual(session.duration, 0.1, accuracy: 0.0001)
        XCTAssertFalse(session.transcribed)
    }
}
