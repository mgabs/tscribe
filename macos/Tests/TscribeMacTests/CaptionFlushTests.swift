import AVFoundation
import XCTest
@testable import TscribeMac

final class CaptionFlushTests: XCTestCase {
    private func directory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    @MainActor
    private func captions(in directory: URL, script: String, interval: UInt64 = 60_000_000_000) throws -> LiveCaptions {
        let path = directory.appendingPathComponent("worker.py")
        try script.write(to: path, atomically: true, encoding: .utf8)
        let worker = WorkerClient(executable: URL(fileURLWithPath: "/usr/bin/python3"), arguments: [path.path])
        return LiveCaptions(worker: worker, interval: interval)
    }

    func testConverterDrainIsIncludedInFinalCaptionSnapshot() throws {
        let directory = try directory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let full = directory.appendingPathComponent("full.wav"), last = directory.appendingPathComponent("last.wav")
        let writer = try PCMWriter(url: full, sampleRate: 16000, channels: 1, live: true)
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4800))
        buffer.frameLength = 4800
        for frame in 0..<4800 { buffer.floatChannelData!.pointee[frame] = 0.2 * sin(Float(frame) * 0.07) }
        try writer.queue.sync { try writer.appendPCM(buffer) }
        try writer.finish()
        _ = try writer.queue.sync { try writer.snapshot(to: last) }
        let recording = try AVAudioFile(forReading: full), snapshot = try AVAudioFile(forReading: last)
        XCTAssertEqual(recording.length, 1600)
        XCTAssertEqual(snapshot.length, recording.length)
        let a = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: recording.processingFormat, frameCapacity: 1600))
        let b = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: snapshot.processingFormat, frameCapacity: 1600))
        try recording.read(into: a); try snapshot.read(into: b)
        XCTAssertEqual(Array(UnsafeBufferPointer(start: a.floatChannelData!.pointee, count: 1600)), Array(UnsafeBufferPointer(start: b.floatChannelData!.pointee, count: 1600)))
    }

    @MainActor
    func testStopBeforeFirstTickSendsFinalWindowAndCleansIt() async throws {
        let directory = try directory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let captions = try captions(in: directory, script: """
        import json, sys
        for line in sys.stdin:
            request = json.loads(line)
            assert request['final'] is True and request['sequence'] == 0
            print(json.dumps({'id': request['id'], 'event': 'result', 'data': {'text': '', 'provisional_text': 'Last words', 'finished': True}}), flush=True)
        """)
        defer { captions.stop() }
        captions.start(stem: "short", directory: directory) { _, _ in XCTFail("No periodic tick expected"); return [:] }
        let snapshot = try XCTUnwrap(captions.prepareStop())
        try FileManager.default.createDirectory(at: snapshot.directory, withIntermediateDirectories: true)
        try Data([0]).write(to: snapshot.directory.appendingPathComponent("0-microphone.wav"))
        XCTAssertTrue(captions.finishing)
        let warning = await captions.flushFinal(snapshot, tracks: ["microphone": 0])
        XCTAssertNil(warning)
        XCTAssertEqual(captions.provisional, "Last words")
        XCTAssertFalse(captions.finishing)
        XCTAssertFalse(captions.finalized) // Still a draft, not a polished transcript.
        XCTAssertFalse(FileManager.default.fileExists(atPath: snapshot.directory.path))
    }

    @MainActor
    func testFinalWindowWaitsBehindInflightPassAndCannotBeOverwrittenByIt() async throws {
        let directory = try directory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let marker = directory.appendingPathComponent("started")
        let captions = try captions(in: directory, script: """
        import json, sys, time
        from pathlib import Path
        for line in sys.stdin:
            request = json.loads(line)
            if not request.get('final'):
                Path(\(String(reflecting: marker.path))).write_text('started')
                time.sleep(.3)
                text = 'Old words'
            else:
                assert request['sequence'] == 1
                text = 'Final words'
            print(json.dumps({'id': request['id'], 'event': 'result', 'data': {'text': text}}), flush=True)
        """, interval: 10_000_000)
        defer { captions.stop() }
        captions.start(stem: "ongoing", directory: directory) { _, _ in ["microphone": 0] }
        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: marker.path) { break }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: marker.path))
        let snapshot = try XCTUnwrap(captions.prepareStop())
        XCTAssertEqual(snapshot.sequence, 1)
        let warning = await captions.flushFinal(snapshot, tracks: ["microphone": 0])
        XCTAssertNil(warning)
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(captions.confirmed, "Final words")
        XCTAssertTrue(captions.status.contains("end of the recording"))
    }

    @MainActor
    func testHungFinalPassTimesOutWithoutDiscardingShownDraft() async throws {
        let directory = try directory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let captions = try captions(in: directory, script: """
        import sys, time
        for line in sys.stdin: time.sleep(5)
        """)
        defer { captions.stop() }
        captions.start(stem: "slow", directory: directory) { _, _ in [:] }
        let snapshot = try XCTUnwrap(captions.prepareStop())
        let warning = await captions.flushFinal(snapshot, tracks: ["microphone": 0], timeout: 50_000_000)
        XCTAssertTrue(warning?.contains("timed out") == true)
        XCTAssertFalse(captions.finishing)
        XCTAssertTrue(captions.status.contains("full recording"))
    }

    @MainActor
    func testSkipAndNewSessionIgnoreOldFlushAndItsTimeout() async throws {
        let directory = try directory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let marker = directory.appendingPathComponent("started")
        let captions = try captions(in: directory, script: """
        import json, sys, time
        from pathlib import Path
        for line in sys.stdin:
            request = json.loads(line)
            if request['stem'] == 'first':
                Path(\(String(reflecting: marker.path))).write_text('started')
                time.sleep(5)
            print(json.dumps({'id': request['id'], 'event': 'result', 'data': {'text': 'New session'}}), flush=True)
        """)
        defer { captions.stop() }
        captions.start(stem: "first", directory: directory) { _, _ in [:] }
        let first = try XCTUnwrap(captions.prepareStop())
        let old = Task { await captions.flushFinal(first, tracks: ["microphone": 0], timeout: 200_000_000) }
        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: marker.path) { break }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        captions.stop()
        captions.start(stem: "second", directory: directory) { _, _ in [:] }
        let second = try XCTUnwrap(captions.prepareStop())
        let warning = await captions.flushFinal(second, tracks: ["microphone": 0])
        XCTAssertNil(warning)
        let skipped = await old.value
        XCTAssertTrue(skipped?.contains("skipped") == true)
        try await Task.sleep(nanoseconds: 250_000_000)
        XCTAssertEqual(captions.confirmed, "New session")
        XCTAssertFalse(captions.finishing)
    }
}
