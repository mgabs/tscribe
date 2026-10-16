import AppKit
import Combine
import SwiftUI

struct StatusItemPlacement {
    static func isReachable(frame: NSRect, visibleAreas: [NSRect]) -> Bool {
        frame.width > 0 && frame.height > 0 && visibleAreas.contains { $0.contains(frame) }
    }
}

/// Actions are shared by the real status menu and its AppKit regression tests.
@MainActor
struct StatusMenuActions {
    let open: () -> Void
    let recordMicrophone: () -> Void
    let recordSystemAudio: () -> Void
    let stop: () -> Void
    let openRecordings: () -> Void
    let quit: () -> Void
}

@MainActor
final class StatusMenuController: NSObject, NSMenuDelegate {
    let menu = NSMenu(title: "tscribe")
    private(set) var openCount = 0
    private let model: AppModel
    private let actions: StatusMenuActions
    private var observation: AnyCancellable?
    private var microphoneItem: NSMenuItem!
    private var systemAudioItem: NSMenuItem!
    private var stopItem: NSMenuItem!
    private var messageItem: NSMenuItem!
    private var recordingsItem: NSMenuItem!

    init(model: AppModel, actions: StatusMenuActions) {
        self.model = model
        self.actions = actions
        super.init()
        menu.autoenablesItems = false
        menu.delegate = self
        add("Open tscribe", #selector(openWindow))
        menu.addItem(.separator())
        microphoneItem = add("Record Microphone", #selector(recordMicrophone))
        systemAudioItem = add("Record System Audio", #selector(recordSystemAudio))
        stopItem = add("Stop Recording", #selector(stopRecording))
        menu.addItem(.separator())
        messageItem = add(model.message, nil)
        recordingsItem = add("Open Recordings", #selector(openRecordings))
        add("Quit tscribe", #selector(quit))
        refresh()
        observation = model.objectWillChange.sink { [weak self] _ in
            // Published values change after objectWillChange is emitted.
            Task { @MainActor in self?.refresh() }
        }
    }

    func menuNeedsUpdate(_ menu: NSMenu) { refresh() }
    func menuWillOpen(_ menu: NSMenu) { openCount += 1 }

    private func refresh() {
        // Keep the same menu items while AppKit is tracking the open menu.
        microphoneItem.isEnabled = !model.busy
        systemAudioItem.isEnabled = !model.busy
        stopItem.isEnabled = model.phase == "recording"
        messageItem.title = model.message
        messageItem.isEnabled = false
        recordingsItem.isEnabled = !model.recordingsPath.isEmpty
    }

    @discardableResult
    private func add(_ title: String, _ action: Selector?) -> NSMenuItem {
        let entry = NSMenuItem(title: title, action: action, keyEquivalent: "")
        entry.target = self
        menu.addItem(entry)
        return entry
    }
    @objc private func openWindow() { actions.open() }
    @objc private func recordMicrophone() { if !model.busy { actions.recordMicrophone() } }
    @objc private func recordSystemAudio() { if !model.busy { actions.recordSystemAudio() } }
    @objc private func stopRecording() { if model.phase == "recording" { actions.stop() } }
    @objc private func openRecordings() { if !model.recordingsPath.isEmpty { actions.openRecordings() } }
    @objc private func quit() { actions.quit() }
}

/// Own the AppKit item for the entire app lifetime, independently of its windows.
@MainActor
final class StatusBarController: NSObject {
    private let item: NSStatusItem
    let menuController: StatusMenuController
    private let model: AppModel
    private var observation: AnyCancellable?

    var isVisible: Bool { item.isVisible && item.button?.window != nil }

    private var buttonFrame: NSRect {
        guard let button = item.button, let window = button.window else { return .zero }
        return window.convertToScreen(button.convert(button.bounds, to: nil))
    }

    var isReachable: Bool {
        guard isVisible, item.button?.window?.isVisible == true else { return false }
        let areas = NSScreen.screens.flatMap { screen -> [NSRect] in
            if let left = screen.auxiliaryTopLeftArea, let right = screen.auxiliaryTopRightArea { return [left, right] }
            return [screen.frame]
        }
        return StatusItemPlacement.isReachable(frame: buttonFrame, visibleAreas: areas)
    }

    var diagnostics: [String: Any] {
        ["requested_visible": item.isVisible, "window_visible": item.button?.window?.isVisible == true,
         "frame": NSStringFromRect(buttonFrame), "reachable": isReachable,
         "menu_items": menuController.menu.numberOfItems,
         "screens": NSScreen.screens.map { NSStringFromRect($0.frame) },
         "window_number": item.button?.window?.windowNumber ?? -1]
    }

    func checkMenuOpens() -> Bool {
        let before = menuController.openCount
        let timer = Timer(timeInterval: 0.3, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.menuController.menu.cancelTracking() }
        }
        RunLoop.main.add(timer, forMode: .common)
        item.button?.performClick(nil)
        timer.invalidate()
        return menuController.openCount > before
    }

    func dispose() {
        observation?.cancel()
        NSStatusBar.system.removeStatusItem(item)
    }

    init(model: AppModel, delegate: AppDelegate) {
        self.model = model
        menuController = StatusMenuController(model: model, actions: StatusMenuActions(
            open: { [weak delegate] in delegate?.showMainWindow() },
            recordMicrophone: { Task { await model.startRecording(system: false) } },
            recordSystemAudio: { Task { await model.startRecording(system: true) } },
            stop: { Task { await model.stopRecording() } },
            openRecordings: { model.openRecordings() },
            quit: { model.quit() }
        ))
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        item.autosaveName = NSStatusItem.AutosaveName("tscribe.main")
        item.behavior = []
        item.isVisible = true
        // Assign a populated menu: an empty status menu may not start tracking,
        // so relying on menuNeedsUpdate alone can leave the icon unresponsive.
        item.menu = menuController.menu
        updateIcon()
        observation = model.objectWillChange.sink { [weak self] _ in
            Task { @MainActor in self?.updateIcon() }
        }
    }

    private func updateIcon() {
        guard let button = item.button else { return }
        let image = NSImage(systemSymbolName: model.phase == "recording" ? "record.circle.fill" : "mic.fill", accessibilityDescription: "tscribe")
        image?.size = NSSize(width: 18, height: 18)
        image?.isTemplate = true
        button.image = image
        button.title = image == nil ? "T" : ""
        button.setAccessibilityLabel("tscribe")
        button.toolTip = "tscribe — \(model.menuTitle(at: model.menuDate)) · \(model.message)"
    }
}

/// Find the SwiftUI window without replacing SwiftUI's own NSWindowDelegate.
struct WindowAccessor: NSViewRepresentable {
    let onWindow: (NSWindow) -> Void
    func makeNSView(context: Context) -> NSView { WindowView(onWindow: onWindow) }
    func updateNSView(_ nsView: NSView, context: Context) {
        if let window = nsView.window { onWindow(window) }
    }
    private final class WindowView: NSView {
        let onWindow: (NSWindow) -> Void
        init(onWindow: @escaping (NSWindow) -> Void) {
            self.onWindow = onWindow
            super.init(frame: .zero)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let window { onWindow(window) }
        }
    }
}
