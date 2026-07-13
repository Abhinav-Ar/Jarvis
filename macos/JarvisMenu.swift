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
    private lazy var previewFlag = appDirectory.appendingPathComponent(".runtime/hud-preview")
    private lazy var chatFile = appDirectory.appendingPathComponent(".runtime/chat.json")
    private lazy var actionsFile = appDirectory.appendingPathComponent(".runtime/actions.json")
    private var statusItem: NSStatusItem!
    private var statusMenuItem: NSMenuItem!
    private var detailMenuItem: NSMenuItem!
    private var desktopControlItem: NSMenuItem!
    private var timer: Timer?
    private var hud: NSWindow?
    private var hudView: JarvisHUDView?
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
        menu.addItem(NSMenuItem(title: "Open Diagnostic Events", action: #selector(openDiagnostics), keyEquivalent: "e"))
        menu.addItem(NSMenuItem(title: "Open Runtime Folder", action: #selector(openRuntime), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Preview Full-Screen HUD", action: #selector(previewHUD), keyEquivalent: "h"))
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

    private func targetScreen() -> NSScreen {
        guard let application = NSWorkspace.shared.frontmostApplication else {
            return NSScreen.main ?? NSScreen.screens.first!
        }
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        if let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] {
            for window in windows {
                let owner = (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value
                let layer = (window[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 1
                guard owner == application.processIdentifier, layer == 0,
                      let dictionary = window[kCGWindowBounds as String] as? NSDictionary,
                      let bounds = CGRect(dictionaryRepresentation: dictionary) else { continue }
                let center = CGPoint(x: bounds.midX, y: bounds.midY)
                for screen in NSScreen.screens {
                    guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { continue }
                    if CGDisplayBounds(CGDirectDisplayID(number.uint32Value)).contains(center) {
                        return screen
                    }
                }
            }
        }
        let mouse = NSEvent.mouseLocation
        return NSScreen.screens.first(where: { $0.frame.contains(mouse) }) ?? NSScreen.main ?? NSScreen.screens.first!
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
        if let attributes = try? FileManager.default.attributesOfItem(atPath: previewFlag.path),
           let modified = attributes[.modificationDate] as? Date,
           Date().timeIntervalSince(modified) < 10 {
            state = "working"
            label = "Working…"
            detail = "Previewing the Jarvis command interface"
        }
        let colors: [String: NSColor] = [
            "listening": .systemCyan, "session": .systemCyan, "transcribing": .systemYellow,
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
        let visible = ["session", "transcribing", "planning", "working", "verifying", "speaking", "needs_input", "error"].contains(state)
        if !visible { hud?.orderOut(nil); return }
        if hud == nil {
            let frame = targetScreen().visibleFrame
            let panel = NSWindow(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
            panel.level = .screenSaver
            panel.isOpaque = false
            panel.backgroundColor = .clear
            panel.hasShadow = false
            panel.ignoresMouseEvents = true
            panel.hidesOnDeactivate = false
            panel.isReleasedWhenClosed = false
            panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            let view = JarvisHUDView(frame: NSRect(origin: .zero, size: frame.size))
            view.autoresizingMask = [.width, .height]
            panel.contentView = view
            hud = panel
            hudView = view
        }
        var goal = ""
        var steps: [String] = []
        var events = 0
        var messages: [[String: String]] = []
        var actions: [[String: String]] = []
        let taskFile = appDirectory.appendingPathComponent(".runtime/active-task.json")
        if let data = try? Data(contentsOf: taskFile),
           let task = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let plan = task["plan"] as? [String: Any] {
                goal = plan["goal"] as? String ?? ""
                steps = plan["steps"] as? [String] ?? []
            }
            events = (task["events"] as? [[String: Any]])?.count ?? 0
        }
        if let data = try? Data(contentsOf: chatFile),
           let chat = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
            messages = chat.compactMap { item in
                guard let role = item["role"] as? String, let text = item["text"] as? String else { return nil }
                return ["role": role, "text": text]
            }
        }
        if let data = try? Data(contentsOf: actionsFile),
           let values = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
            actions = values.compactMap { item in
                guard let label = item["label"] as? String, let status = item["status"] as? String else { return nil }
                return [
                    "label": label,
                    "target": item["target"] as? String ?? "",
                    "status": status,
                    "result": item["result"] as? String ?? "",
                ]
            }
        }
        hudView?.state = state
        hudView?.label = label
        hudView?.detail = detail
        hudView?.goal = goal
        hudView?.steps = steps
        hudView?.eventCount = max(events, actions.count)
        hudView?.messages = messages
        hudView?.actions = actions
        hudView?.needsDisplay = true
        let frame = targetScreen().visibleFrame
        hud?.setFrame(frame, display: true)
        hudView?.frame = NSRect(origin: .zero, size: frame.size)
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

    @objc private func openDiagnostics() {
        let log = appDirectory.appendingPathComponent(".runtime/events.jsonl")
        NSWorkspace.shared.open(log)
    }

    @objc private func openRuntime() {
        NSWorkspace.shared.open(appDirectory)
    }

    @objc private func previewHUD() {
        FileManager.default.createFile(atPath: previewFlag.path, contents: Data())
        refreshStatus()
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

@main
struct JarvisMenuApplication {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
