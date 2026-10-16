import AppKit
import Combine
import SwiftUI

/// Own the AppKit item for the entire app lifetime, independently of its windows.
@MainActor
final class StatusBarController: NSObject, NSMenuDelegate {
    private let item: NSStatusItem
    private let model: AppModel
    private weak var delegate: AppDelegate?
    private var observation: AnyCancellable?

    var isVisible: Bool {
        item.isVisible && item.button?.window != nil
    }

    init(model: AppModel, delegate: AppDelegate) {
        self.model = model
        self.delegate = delegate
        // An icon-only, fixed-width item fits crowded/notched menu bars better
        // than the former SwiftUI icon plus application-name label.
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        item.behavior = []
        item.isVisible = true
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        updateIcon()
        observation = model.objectWillChange.sink { [weak self] _ in
            Task { @MainActor in self?.updateIcon() }
        }
    }

    private func updateIcon() {
        guard let button = item.button else { return }
        let recording = model.phase == "recording"
        let image = NSImage(systemSymbolName: recording ? "record.circle.fill" : "mic.fill", accessibilityDescription: "tscribe")
        image?.size = NSSize(width: 18, height: 18)
        image?.isTemplate = true
        button.image = image
        button.title = image == nil ? "T" : ""
        button.setAccessibilityLabel("tscribe")
        button.toolTip = "tscribe — \(model.menuTitle(at: model.menuDate)) · \(model.message)"
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        add("Open tscribe", #selector(openWindow), to: menu)
        menu.addItem(.separator())
        add("Record Microphone", #selector(recordMicrophone), enabled: !model.busy, to: menu)
        add("Record System Audio", #selector(recordSystemAudio), enabled: !model.busy, to: menu)
        add("Stop Recording", #selector(stopRecording), enabled: model.phase == "recording", to: menu)
        menu.addItem(.separator())
        add(model.message, nil, enabled: false, to: menu)
        add("Open Recordings", #selector(openRecordings), to: menu)
        add("Quit tscribe", #selector(quit), to: menu)
    }

    private func add(_ title: String, _ action: Selector?, enabled: Bool = true, to menu: NSMenu) {
        let entry = NSMenuItem(title: title, action: action, keyEquivalent: "")
        entry.target = self
        entry.isEnabled = enabled
        menu.addItem(entry)
    }
    @objc private func openWindow() { delegate?.showMainWindow() }
    @objc private func recordMicrophone() { Task { await model.startRecording(system: false) } }
    @objc private func recordSystemAudio() { Task { await model.startRecording(system: true) } }
    @objc private func stopRecording() { Task { await model.stopRecording() } }
    @objc private func openRecordings() { model.openRecordings() }
    @objc private func quit() { model.quit() }
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
