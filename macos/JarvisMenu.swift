import AppKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let service = "gui/\(getuid())/com.jarvis.voice"
    private let appDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Jarvis")
    private let voicePlist = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents/com.jarvis.voice.plist")
    private lazy var controlFlag = appDirectory.appendingPathComponent(".runtime/desktop-control-enabled")
    private var statusItem: NSStatusItem!
    private var statusMenuItem: NSMenuItem!
    private var desktopControlItem: NSMenuItem!
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        // Desktop control is session-scoped and starts disabled after login.
        try? FileManager.default.removeItem(at: controlFlag)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.toolTip = "Jarvis voice assistant"

        let menu = NSMenu()
        statusMenuItem = NSMenuItem(title: "Checking status…", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = true
        menu.addItem(statusMenuItem)
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
        timer = Timer.scheduledTimer(timeInterval: 2.0, target: self, selector: #selector(refreshStatus), userInfo: nil, repeats: true)
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
        }
        let desktopEnabled = running && FileManager.default.fileExists(atPath: controlFlag.path)
        let menuColor: NSColor = running ? .systemGreen : .systemRed
        let barColor: NSColor = running ? .systemCyan : .systemRed
        statusMenuItem.attributedTitle = NSAttributedString(
            string: running ? "● Status: Listening" : "● Status: Stopped",
            attributes: [
                .foregroundColor: menuColor,
                .font: NSFont.boldSystemFont(ofSize: NSFont.systemFontSize),
            ]
        )
        statusItem.button?.attributedTitle = NSAttributedString(
            string: "● Jarvis",
            attributes: [
                .foregroundColor: barColor,
                .font: NSFont.boldSystemFont(ofSize: NSFont.systemFontSize),
            ]
        )
        statusItem.button?.toolTip = running ? "Jarvis is listening" : "Jarvis is stopped"
        desktopControlItem.title = desktopEnabled
            ? "Disable Desktop Control (Emergency Stop)"
            : "Enable Desktop Control"
    }

    @objc private func startJarvis() {
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
        } else {
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
