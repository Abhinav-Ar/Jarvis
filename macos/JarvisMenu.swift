import AppKit
import Foundation
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let service = "gui/\(getuid())/com.jarvis.voice"
    private let appDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Jarvis")
    private let voicePlist = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents/com.jarvis.voice.plist")
    private lazy var controlFlag = appDirectory.appendingPathComponent(".runtime/desktop-control-enabled")
    private lazy var disabledFlag = appDirectory.appendingPathComponent(".runtime/desktop-control-disabled")
    private lazy var activityFile = appDirectory.appendingPathComponent(".runtime/activity.json")
    private var statusItem: NSStatusItem!
    private var statusMenuItem: NSMenuItem!
    private var detailMenuItem: NSMenuItem!
    private var desktopControlItem: NSMenuItem!
    private var timer: Timer?
    private var hud: NSPanel?
    private var hudLabel: NSTextField?
    private var previousState = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        try? FileManager.default.removeItem(at: disabledFlag)
        try? FileManager.default.createDirectory(at: controlFlag.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: controlFlag.path, contents: Data())
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.toolTip = "Jarvis voice assistant"

        let menu = NSMenu()
        statusMenuItem = NSMenuItem(title: "Checking status…", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = true
        menu.addItem(statusMenuItem)
        detailMenuItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        detailMenuItem.isEnabled = false
        menu.addItem(detailMenuItem)
        desktopControlItem = NSMenuItem(title: "Enable Desktop Control", action: #selector(toggleDesktopControl), keyEquivalent: "d")
        menu.addItem(desktopControlItem)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Start Jarvis", action: #selector(startJarvis), keyEquivalent: "s"))
        menu.addItem(NSMenuItem(title: "Stop Jarvis", action: #selector(stopJarvis), keyEquivalent: "x"))
        menu.addItem(NSMenuItem(title: "Restart Jarvis", action: #selector(restartJarvis), keyEquivalent: "r"))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Open Recent Log", action: #selector(openLog), keyEquivalent: "l"))
        menu.addItem(NSMenuItem(title: "Open Runtime Folder", action: #selector(openRuntime), keyEquivalent: ""))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Screen Recording Permission…", action: #selector(openScreenPermission), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Accessibility Permission…", action: #selector(openAccessibilityPermission), keyEquivalent: ""))
        for item in menu.items { item.target = self }
        statusItem.menu = menu

        refreshStatus()
        timer = Timer.scheduledTimer(timeInterval: 0.5, target: self, selector: #selector(refreshStatus), userInfo: nil, repeats: true)
    }

    @discardableResult
    private func launchctl(_ arguments: [String]) -> (Int32, String) {
        let task = Process()
        let pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        task.arguments = arguments
        task.standardOutput = pipe
        task.standardError = pipe
        do {
            try task.run()
            task.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return (task.terminationStatus, String(data: data, encoding: .utf8) ?? "")
        } catch {
            return (1, error.localizedDescription)
        }
    }

    private func isRunning() -> Bool {
        let result = launchctl(["print", service])
        return result.0 == 0 && result.1.contains("state = running")
    }

    @objc private func refreshStatus() {
        let running = isRunning()
        if !running {
            try? FileManager.default.removeItem(at: controlFlag)
        } else if !FileManager.default.fileExists(atPath: disabledFlag.path) && !FileManager.default.fileExists(atPath: controlFlag.path) {
            FileManager.default.createFile(atPath: controlFlag.path, contents: Data())
        }
        let desktopEnabled = running && FileManager.default.fileExists(atPath: controlFlag.path)
        var state = running ? "listening" : "stopped"
        var label = running ? "Listening" : "Stopped"
        var detail = ""
        if running, let data = try? Data(contentsOf: activityFile),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            state = value["state"] as? String ?? state
            label = value["label"] as? String ?? label
            detail = value["detail"] as? String ?? ""
        }
        let colors: [String: NSColor] = [
            "listening": .systemCyan, "transcribing": .systemYellow,
            "planning": .systemBlue, "working": .systemPurple,
            "verifying": .systemIndigo, "speaking": .systemGreen,
            "needs_input": .systemOrange, "error": .systemRed, "stopped": .systemRed,
        ]
        let color = colors[state] ?? .systemCyan
        statusMenuItem.attributedTitle = NSAttributedString(
            string: "● Status: \(label)",
            attributes: [
                .foregroundColor: color,
                .font: NSFont.boldSystemFont(ofSize: NSFont.systemFontSize),
            ]
        )
        detailMenuItem.title = detail.isEmpty ? "Desktop control: \(desktopEnabled ? "On" : "Off")" : detail
        statusItem.button?.attributedTitle = NSAttributedString(
            string: state == "listening" || state == "stopped" ? "● Jarvis" : "● \(label)",
            attributes: [
                .foregroundColor: color,
                .font: NSFont.boldSystemFont(ofSize: NSFont.systemFontSize),
            ]
        )
        statusItem.button?.toolTip = detail.isEmpty ? "Jarvis is \(label.lowercased())" : detail
        desktopControlItem.title = desktopEnabled
            ? "Disable Desktop Control (Emergency Stop)"
            : "Enable Desktop Control"
        updateHUD(state: state, label: label, detail: detail)
        if state == "listening" && ["working", "verifying", "speaking"].contains(previousState) {
            let content = UNMutableNotificationContent()
            content.title = "Jarvis finished"
            content.body = detail.isEmpty ? "The task is complete." : detail
            content.sound = .default
            UNUserNotificationCenter.current().add(
                UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            )
        }
        previousState = state
    }

    private func updateHUD(state: String, label: String, detail: String) {
        let visible = ["transcribing", "planning", "working", "verifying", "needs_input", "error"].contains(state)
        if !visible { hud?.orderOut(nil); return }
        if hud == nil {
            let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 86), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.level = .floating
            panel.isOpaque = false
            panel.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(0.94)
            panel.hasShadow = true
            panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            let field = NSTextField(labelWithString: "")
            field.frame = NSRect(x: 20, y: 14, width: 320, height: 58)
            field.font = NSFont.systemFont(ofSize: 15, weight: .semibold)
            field.maximumNumberOfLines = 3
            panel.contentView?.addSubview(field)
            hud = panel
            hudLabel = field
        }
        hudLabel?.stringValue = detail.isEmpty ? "Jarvis\n\(label)" : "Jarvis — \(label)\n\(detail)"
        if let screen = NSScreen.main {
            let frame = screen.visibleFrame
            hud?.setFrameOrigin(NSPoint(x: frame.maxX - 380, y: frame.maxY - 110))
        }
        hud?.orderFrontRegardless()
    }

    @objc private func startJarvis() {
        try? FileManager.default.removeItem(at: disabledFlag)
        FileManager.default.createFile(atPath: controlFlag.path, contents: Data())
        _ = launchctl(["enable", service])
        if launchctl(["print", service]).0 == 0 {
            _ = launchctl(["kickstart", service])
        } else {
            _ = launchctl(["bootstrap", "gui/\(getuid())", voicePlist.path])
        }
        refreshStatus()
    }

    @objc private func stopJarvis() {
        try? FileManager.default.removeItem(at: controlFlag)
        _ = launchctl(["bootout", service])
        refreshStatus()
    }

    @objc private func restartJarvis() {
        if launchctl(["print", service]).0 == 0 {
            _ = launchctl(["kickstart", "-k", service])
        } else {
            _ = launchctl(["enable", service])
            _ = launchctl(["bootstrap", "gui/\(getuid())", voicePlist.path])
        }
        refreshStatus()
    }

    @objc private func toggleDesktopControl() {
        if FileManager.default.fileExists(atPath: controlFlag.path) {
            try? FileManager.default.removeItem(at: controlFlag)
            FileManager.default.createFile(atPath: disabledFlag.path, contents: Data())
        } else {
            try? FileManager.default.removeItem(at: disabledFlag)
            try? FileManager.default.createDirectory(
                at: controlFlag.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            FileManager.default.createFile(atPath: controlFlag.path, contents: Data())
        }
        refreshStatus()
    }

    @objc private func openLog() {
        let log = appDirectory.appendingPathComponent(".runtime/jarvis.log")
        NSWorkspace.shared.open(log)
    }

    @objc private func openRuntime() {
        NSWorkspace.shared.open(appDirectory)
    }

    @objc private func openScreenPermission() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func openAccessibilityPermission() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
