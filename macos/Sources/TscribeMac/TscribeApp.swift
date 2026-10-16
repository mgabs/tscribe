import SwiftUI
import AppKit

@main
struct TscribeNativeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("tscribe", id: "main") {
            MainView(model: model, delegate: delegate)
                .onAppear { delegate.model = model }
                .task { if model.phase == "loading" { await model.bootstrap() } }
        }
        .defaultSize(width: 900, height: 620)
        .commands {
            CommandGroup(replacing: .windowSize) {
                Button("Minimize to Menu Bar") { delegate.hideToMenuBar() }.keyboardShortcut("m")
                Button("Zoom") { NSApp.keyWindow?.performZoom(nil) }
            }
            CommandGroup(replacing: .appTermination) {
                Button("Quit tscribe") { model.quit() }.keyboardShortcut("q")
            }
        }

    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel? {
        didSet {
            guard let model, statusController == nil else { return }
            statusController = StatusBarController(model: model, delegate: self)
        }
    }
    private(set) var statusController: StatusBarController?
    private var windowObservers: [NSObjectProtocol] = []
    private var mainWindows: [NSWindow] = []
    private var hidingWindow = false
    var openMainWindow: (() -> Void)?
    private var exitingDuplicate = false
    private var smokeTimer: Timer?
    private let launched = Date()

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let identifier = Bundle.main.bundleIdentifier,
           let existing = NSRunningApplication.runningApplications(withBundleIdentifier: identifier).first(where: {
               $0.processIdentifier != ProcessInfo.processInfo.processIdentifier && $0.executableURL?.lastPathComponent == "tscribe-native"
           }) {
            DistributedNotificationCenter.default().postNotificationName(Notification.Name("com.tscribe.show-main"), object: nil)
            existing.activate(options: [])
            exitingDuplicate = true
            NSApp.terminate(nil)
            return
        }
        NSApp.setActivationPolicy(.regular)
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(showMainWindow), name: Notification.Name("com.tscribe.show-main"), object: nil)
        DispatchQueue.main.async { self.showMainWindow() }
        if let index = CommandLine.arguments.firstIndex(of: "--smoke-report"), CommandLine.arguments.count > index + 1 {
            let report = CommandLine.arguments[index + 1]
            smokeTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.checkLaunch(report: report) }
            }
        }
    }
    func attachWindow(_ window: NSWindow) {
        guard !mainWindows.contains(where: { $0 === window }) else { return }
        mainWindows.append(window)
        // Keep the primary window available when its close button is used.
        window.isReleasedWhenClosed = false
        if let minimize = window.standardWindowButton(.miniaturizeButton) {
            minimize.target = self
            minimize.action = #selector(hideToMenuBar)
        }
        for name in [NSWindow.willCloseNotification, NSWindow.didMiniaturizeNotification] {
            windowObservers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.hideToMenuBar() }
            })
        }
    }
    @objc func hideToMenuBar() {
        guard !hidingWindow, statusController?.isVisible == true else { return }
        hidingWindow = true
        for window in mainWindows {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.orderOut(nil)
        }
        NSApp.setActivationPolicy(.accessory)
        hidingWindow = false
    }
    @objc func showMainWindow() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        for window in NSApp.windows where window.canBecomeKey {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
        }
        // A closed primary window can still be restored from the Dock/Finder.
        if !NSApp.windows.contains(where: { $0.isVisible && $0.canBecomeKey }) {
            openMainWindow?()
        }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if exitingDuplicate { return .terminateNow }
        if model?.busy == true { model?.quit(); return .terminateCancel }
        model?.worker.stop()
        return .terminateNow
    }
    private func checkLaunch(report: String) {
        let visible = NSApp.windows.contains { $0.isVisible && $0.canBecomeKey }
        let ready = model?.phase == "idle" && model?.error == nil
        guard (visible && ready && Date().timeIntervalSince(launched) > 2) || Date().timeIntervalSince(launched) > 30 else { return }
        smokeTimer?.invalidate()
        var result: [String: Any] = ["window_visible": visible, "worker_ready": ready, "native_ui": true, "error": model?.error ?? "", "status_item_visible": statusController?.isVisible == true]
        Task { @MainActor in
            if CommandLine.arguments.contains("--smoke-menu-bar"), let window = mainWindows.first {
                // Exercise the actual traffic-light actions as well as Cmd-M's
                // native miniaturization path. Let AppKit notifications settle.
                window.standardWindowButton(.miniaturizeButton)?.performClick(nil)
                try? await Task.sleep(nanoseconds: 300_000_000)
                result["hidden_to_menu_bar"] = self.isHiddenToMenuBar
                self.showMainWindow()
                try? await Task.sleep(nanoseconds: 300_000_000)
                result["window_restored"] = window.isVisible && NSApp.activationPolicy() == .regular
                if let (menu, index) = self.minimizeCommand(in: NSApp.mainMenu) {
                    result["minimize_shortcut_registered"] = menu.items[index].keyEquivalent == "m"
                    menu.performActionForItem(at: index)
                }
                try? await Task.sleep(nanoseconds: 300_000_000)
                result["keyboard_minimize_to_menu_bar"] = self.isHiddenToMenuBar
                self.showMainWindow()
                try? await Task.sleep(nanoseconds: 300_000_000)
                window.performClose(nil)
                try? await Task.sleep(nanoseconds: 300_000_000)
                result["close_to_menu_bar"] = self.isHiddenToMenuBar
                self.showMainWindow()
                try? await Task.sleep(nanoseconds: 300_000_000)
                result["closed_window_restored"] = NSApp.windows.contains { $0.isVisible && $0.canBecomeKey } && NSApp.activationPolicy() == .regular
            }
            if let data = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted]) { try? data.write(to: URL(fileURLWithPath: report)) }
            self.model?.quit()
        }
    }
    private func minimizeCommand(in menu: NSMenu?) -> (NSMenu, Int)? {
        guard let menu else { return nil }
        for (index, item) in menu.items.enumerated() {
            if item.title == "Minimize to Menu Bar" { return (menu, index) }
            if let found = minimizeCommand(in: item.submenu) { return found }
        }
        return nil
    }
    private var isHiddenToMenuBar: Bool {
        !NSApp.windows.contains { $0.isVisible && $0.canBecomeKey } && NSApp.activationPolicy() == .accessory && statusController?.isVisible == true
    }
}

struct MainView: View {
    @ObservedObject var model: AppModel
    let delegate: AppDelegate
    @State private var settings = false
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selected) {
                Section("Recordings") {
                    ForEach(model.sessions) { session in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(session.id).font(.system(.caption, design: .monospaced))
                            Text("\(Int(session.duration))s · \(session.source) · \(session.transcribed ? "Transcribed" : "Audio saved")")
                                .font(.caption2).foregroundStyle(.secondary)
                        }.padding(.vertical, 4).tag(session.id)
                    }
                }
            }
            .disabled(model.busy)
            .navigationSplitViewColumnWidth(min: 230, ideal: 260)
        } detail: {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Label("tscribe", systemImage: "mic.circle.fill").font(.largeTitle.bold())
                    Spacer()
                    Button("Hide to Menu Bar") { delegate.hideToMenuBar() }
                    Button { settings = true } label: { Label("Settings", systemImage: "gearshape") }.disabled(model.busy)
                }
                Text(model.message).foregroundStyle(.secondary).textSelection(.enabled)
                if model.phase == "recording", model.showElapsed, let started = model.started {
                    Text(started, style: .timer).font(.system(size: 36, weight: .medium, design: .monospaced)).foregroundStyle(.red)
                }
                if let error = model.error {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Action needed", systemImage: "exclamationmark.triangle.fill").font(.headline)
                        Text(error).textSelection(.enabled)
                        Button("Dismiss") { model.error = nil }
                    }.padding().frame(maxWidth: .infinity, alignment: .leading).background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
                }
                HStack {
                    Button { Task { await model.startRecording(system: false) } } label: { Label("Record Microphone", systemImage: "mic.fill") }.disabled(model.busy)
                    Button { Task { await model.startRecording(system: true) } } label: { Label("Record System Audio", systemImage: "speaker.wave.2.fill") }.disabled(model.busy)
                    if model.phase == "recording" {
                        Button("Stop", role: .destructive) { Task { await model.stopRecording() } }
                    }
                }.buttonStyle(.borderedProminent)
                if model.phase == "transcribing" {
                    ProgressView(value: model.progress)
                    Text("Audio stays on this Mac. Model download may be needed on first use.").font(.caption).foregroundStyle(.secondary)
                } else if model.busy && model.phase != "recording" { ProgressView().controlSize(.small) }
                Divider()
                HStack {
                    Text("Transcript").font(.headline)
                    Spacer()
                    Button("Transcribe") { Task { await model.transcribeSelected() } }.disabled(model.busy || model.selected == nil)
                    Button("Copy") { model.copyTranscript() }.disabled(model.transcript.isEmpty)
                }
                ScrollView { Text(model.transcript).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled) }
                HStack {
                    Button("Open Recordings Folder") { model.openRecordings() }.disabled(model.recordingsPath.isEmpty)
                    Spacer()
                    if model.phase == "loading" || model.error != nil { Button("Retry Connection") { Task { await model.bootstrap() } }.disabled(model.phase == "recording") }
                }
            }.padding(24).frame(minWidth: 560, minHeight: 500)
        }
        .background(WindowAccessor { delegate.attachWindow($0) })
        .onAppear { delegate.openMainWindow = { openWindow(id: "main") } }
        .onChange(of: model.selected) { _, _ in Task { await model.loadTranscript() } }
        .sheet(isPresented: $settings) { SettingsView(model: model) }

    }
}

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Settings").font(.title2.bold())
            Form {
                Picker("Whisper model", selection: $model.model) {
                    ForEach(["tiny", "base", "small", "medium", "large"], id: \.self) { Text($0).tag($0) }
                }
                TextField("Language (auto or a language code)", text: $model.language)
                Toggle("Transcribe after recording", isOn: $model.autoTranscribe)
                Toggle("Experimental speaker grouping", isOn: $model.diarize)
                Toggle("Completion notifications", isOn: $model.notifications)
                Stepper("Recent recordings: \(model.recentLimit)", value: $model.recentLimit, in: 1...100)
                Text("Shared with the Python CLI. Advanced audio and output settings are in config.toml.").font(.caption).foregroundStyle(.secondary)
            }.formStyle(.grouped)
            HStack {
                Button("Open config.toml") { Task { await model.openConfig() } }
                Spacer()
                Button("Cancel") { dismiss(); Task { await model.bootstrap() } }
                Button("Save") { Task { await model.saveSettings(); if model.error == nil { dismiss() } } }.keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 480)
    }
}
