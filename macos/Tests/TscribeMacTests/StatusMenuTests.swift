import AppKit
import XCTest
@testable import TscribeMac

final class StatusMenuTests: XCTestCase {
    @MainActor
    private func fixture() -> (AppModel, StatusMenuController, Calls) {
        _ = NSApplication.shared
        let model = AppModel()
        let calls = Calls()
        let controller = StatusMenuController(model: model, actions: StatusMenuActions(
            open: { calls.open += 1 },
            settings: { calls.settings += 1 },
            recordMeeting: { calls.meeting += 1 },
            recordMicrophone: { calls.microphone += 1 },
            recordSystemAudio: { calls.systemAudio += 1 },
            stop: { calls.stop += 1 },
            openRecordings: { calls.recordings += 1 },
            quit: { calls.quit += 1 }
        ))
        return (model, controller, calls)
    }

    @MainActor
    func testMenuIsPopulatedBeforeFirstClickEvenWhileWorkerLoads() throws {
        let (_, controller, _) = fixture()
        XCTAssertNotNil(controller.menu.item(withTitle: "Open tscribe"))
        XCTAssertNotNil(controller.menu.item(withTitle: "Quit tscribe"))
        XCTAssertFalse(try XCTUnwrap(controller.menu.item(withTitle: "Record Microphone")).isEnabled)
        XCTAssertFalse(try XCTUnwrap(controller.menu.item(withTitle: "Open Recordings")).isEnabled)
    }

    @MainActor
    func testIdleRecordingAndTranscriptionStatesUpdateWithoutReplacingItems() async throws {
        let (model, controller, _) = fixture()
        let microphone = try XCTUnwrap(controller.menu.item(withTitle: "Record Microphone"))
        let stop = try XCTUnwrap(controller.menu.item(withTitle: "Stop Recording"))
        for (phase, canRecord, canStop) in [("idle", true, false), ("recording", false, true), ("saving", false, false), ("transcribing", false, false), ("idle", true, false)] {
            model.phase = phase
            model.message = "State: \(phase)"
            // Flush the async publisher observer; do not reopen the menu.
            await Task { @MainActor in }.value
            XCTAssertEqual(microphone.isEnabled, canRecord, phase)
            XCTAssertEqual(stop.isEnabled, canStop, phase)
            XCTAssertTrue(controller.menu.item(withTitle: "Record Microphone") === microphone)
            XCTAssertNotNil(controller.menu.item(withTitle: "State: \(phase)"))
        }
    }

    @MainActor
    func testAppKitActionsReachEachCommandAndGuardBusyRecording() throws {
        let (model, controller, calls) = fixture()
        func click(_ title: String) throws {
            let item = try XCTUnwrap(controller.menu.item(withTitle: title))
            controller.menu.performActionForItem(at: controller.menu.index(of: item))
        }
        try click("Open tscribe")
        try click("Quit tscribe")
        try click("Settings…")
        XCTAssertEqual(calls.settings, 0)
        try click("Record Microphone")
        try click("Stop Recording")
        XCTAssertEqual(calls.open, 1)
        XCTAssertEqual(calls.quit, 1)
        XCTAssertEqual(calls.microphone, 0)
        XCTAssertEqual(calls.stop, 0)
        model.phase = "idle"
        model.recordingsPath = "/test/recordings"
        controller.menuNeedsUpdate(controller.menu)
        try click("Settings…")
        XCTAssertEqual(calls.settings, 1)
        try click("Record Meeting")
        XCTAssertEqual(calls.meeting, 1)
        try click("Record Microphone")
        try click("Record System Audio")
        try click("Open Recordings")
        XCTAssertEqual(calls.microphone, 1)
        XCTAssertEqual(calls.systemAudio, 1)
        XCTAssertEqual(calls.recordings, 1)
        model.phase = "recording"
        controller.menuNeedsUpdate(controller.menu)
        try click("Stop Recording")
        XCTAssertEqual(calls.stop, 1)
        try click("Record System Audio")
        XCTAssertEqual(calls.systemAudio, 1)
    }
}

@MainActor
private final class Calls {
    var open = 0
    var settings = 0
    var meeting = 0
    var microphone = 0
    var systemAudio = 0
    var stop = 0
    var recordings = 0
    var quit = 0
}

final class StatusItemLifecycleTests: XCTestCase {
    func testAnOffscreenOrZeroSizedStatusItemDoesNotPassVisibilityCheck() {
        let screen = NSRect(x: 0, y: 0, width: 1440, height: 900)
        XCTAssertTrue(StatusItemPlacement.isReachable(frame: NSRect(x: 1200, y: 876, width: 24, height: 24), visibleAreas: [screen]))
        XCTAssertFalse(StatusItemPlacement.isReachable(frame: .zero, visibleAreas: [screen]))
        XCTAssertFalse(StatusItemPlacement.isReachable(frame: NSRect(x: -24, y: 876, width: 24, height: 24), visibleAreas: [screen]))
        XCTAssertFalse(StatusItemPlacement.isReachable(frame: NSRect(x: 1430, y: 876, width: 24, height: 24), visibleAreas: [screen]))
    }

    func testCameraHousingIsExcludedAndSecondaryDisplaysUseGlobalCoordinates() {
        let left = NSRect(x: 0, y: 868, width: 650, height: 32)
        let right = NSRect(x: 790, y: 868, width: 650, height: 32)
        XCTAssertFalse(StatusItemPlacement.isReachable(frame: NSRect(x: 700, y: 876, width: 24, height: 24), visibleAreas: [left, right]))
        let secondary = NSRect(x: -1920, y: 0, width: 1920, height: 1080)
        XCTAssertTrue(StatusItemPlacement.isReachable(frame: NSRect(x: -100, y: 1056, width: 24, height: 24), visibleAreas: [secondary]))
    }
}
