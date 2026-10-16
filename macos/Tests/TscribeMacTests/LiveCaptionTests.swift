import AVFoundation
import XCTest
@testable import TscribeMac

final class LiveCaptionTests: XCTestCase {
    func testRollingSnapshotIsBoundedAndDoesNotTruncateRecording() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let full = directory.appendingPathComponent("full.wav")
        let snapshot = directory.appendingPathComponent("window.wav")
        let writer = try PCMWriter(url: full, sampleRate: 16000, channels: 1, live: true)
        XCTAssertNil(try writer.queue.sync { try writer.snapshot(to: snapshot) })
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 1600))
        buffer.frameLength = 1600
        try XCTUnwrap(buffer.int16ChannelData).pointee.initialize(repeating: 1000, count: 1600)
        for _ in 0..<400 { try writer.queue.sync { try writer.appendPCM(buffer) } }
        let offset = try XCTUnwrap(writer.queue.sync { try writer.snapshot(to: snapshot) })
        XCTAssertEqual(offset, 10, accuracy: 0.01)
        let window = try AVAudioFile(forReading: snapshot)
        XCTAssertEqual(window.length, 480000)
        // Capture can continue after a snapshot, and final audio still has all samples.
        try writer.queue.sync { try writer.appendPCM(buffer) }
        try writer.finish()
        let recording = try AVAudioFile(forReading: full)
        XCTAssertEqual(recording.length, 641600)
    }

    func testEmptyTrackCanBeRetainedAsSilenceForMeetingMix() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let writer = try PCMWriter(url: url, sampleRate: 16000, channels: 1)
        try writer.finish(allowEmpty: true)
        let file = try AVAudioFile(forReading: url)
        XCTAssertEqual(file.length, 0)
        XCTAssertFalse(writer.hasAudio)
    }

    @MainActor
    func testCompletedCaptionSnapshotIsRemovedBeforeNextWindow() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let script = directory.appendingPathComponent("fast.py")
        try """
        import json, sys
        for line in sys.stdin:
            request = json.loads(line)
            print(json.dumps({'id': request['id'], 'event': 'result', 'data': {'text': 'Hello', 'provisional_text': 'meeting'}}), flush=True)
        """.write(to: script, atomically: true, encoding: .utf8)
        let worker = WorkerClient(executable: URL(fileURLWithPath: "/usr/bin/python3"), arguments: [script.path])
        let captions = LiveCaptions(worker: worker, interval: 20_000_000)
        defer { captions.stop() }
        let liveDirectory = directory.appendingPathComponent(".live/session")
        captions.start(stem: "session", directory: directory) { directory, sequence in
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try Data([1, 2]).write(to: directory.appendingPathComponent("\(sequence)-microphone.wav"))
            return ["microphone": 0]
        }
        for _ in 0..<100 {
            if captions.confirmed == "Hello" { break }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertEqual(captions.confirmed, "Hello")
        XCTAssertFalse(FileManager.default.fileExists(atPath: liveDirectory.appendingPathComponent("0-microphone.wav").path))
        captions.stop()
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertFalse(FileManager.default.fileExists(atPath: liveDirectory.path))
        captions.finish(text: "Final meeting text", stem: "session")
        XCTAssertTrue(captions.finalized)
        XCTAssertEqual(captions.confirmed, "Final meeting text")
        XCTAssertTrue(captions.provisional.isEmpty)
        captions.finish(text: "Other recording", stem: "unrelated")
        XCTAssertEqual(captions.confirmed, "Final meeting text")
    }

    @MainActor
    func testSlowCaptionInferenceKeepsOnlyOneWindowInFlightAndStopCancelsIt() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let script = directory.appendingPathComponent("slow.py")
        try """
        import json, sys, time
        for line in sys.stdin:
            request = json.loads(line)
            time.sleep(5)
            print(json.dumps({'id': request['id'], 'event': 'result', 'data': {'text': 'stale'}}), flush=True)
        """.write(to: script, atomically: true, encoding: .utf8)
        let worker = WorkerClient(executable: URL(fileURLWithPath: "/usr/bin/python3"), arguments: [script.path])
        let captions = LiveCaptions(worker: worker, interval: 10_000_000)
        var snapshots = 0
        captions.start(stem: "session", directory: directory) { _, _ in
            snapshots += 1
            return ["microphone": 0]
        }
        try await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(snapshots, 1)
        XCTAssertTrue(captions.running)
        captions.stop()
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertFalse(captions.running)
        XCTAssertTrue(captions.confirmed.isEmpty)
        XCTAssertEqual(snapshots, 1)
    }

    @MainActor
    func testStoppingPendingWorkerRequestAndRestartingIgnoresOldProcessExit() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let script = directory.appendingPathComponent("worker.py")
        try """
        import json, sys, time
        for line in sys.stdin:
            request = json.loads(line)
            if request['command'] == 'wait': time.sleep(10)
            print(json.dumps({'id': request['id'], 'event': 'result', 'data': {'ready': True}}), flush=True)
        """.write(to: script, atomically: true, encoding: .utf8)
        let client = WorkerClient(executable: URL(fileURLWithPath: "/usr/bin/python3"), arguments: [script.path])
        defer { client.stop() }
        let waiting = Task { try await client.request("wait") }
        try await Task.sleep(nanoseconds: 100_000_000)
        client.stop()
        do { _ = try await waiting.value; XCTFail("Pending work must be cancelled") }
        catch { XCTAssertTrue(error.localizedDescription.contains("cancelled")) }
        let result = try await client.request("ready")
        XCTAssertEqual(result["ready"] as? Bool, true)
        try await Task.sleep(nanoseconds: 100_000_000)
        let again = try await client.request("ready")
        XCTAssertEqual(again["ready"] as? Bool, true)
    }
}
