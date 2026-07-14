import AppKit
import CoreGraphics
import Foundation
import ScreenCaptureKit
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, @unchecked Sendable {
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
    private lazy var uiPlanFile = appDirectory.appendingPathComponent(".runtime/ui-plan.json")
    private lazy var contrastFile = appDirectory.appendingPathComponent(".runtime/contrast-state.json")
    private lazy var platformFile = appDirectory.appendingPathComponent(".runtime/platform-status.json")
    private var statusItem: NSStatusItem!
    private var statusMenuItem: NSMenuItem!
    private var detailMenuItem: NSMenuItem!
    private var desktopControlItem: NSMenuItem!
    private var platformMenuItem: NSMenuItem!
    private var timer: Timer?
    private var interactionTimer: Timer?
    private var hud: NSWindow?
    private var hudView: JarvisHUDView?
    private var previousState = ""
    private var lastLuminanceCheck = Date.distantPast
    private var sampledLuminance: CGFloat = 0.25
    private var luminanceSampling = false
    private var recordedMissingScreenPermission = false

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
        platformMenuItem = NSMenuItem(title: "Agent platform: starting…", action: nil, keyEquivalent: "")
        platformMenuItem.isEnabled = false
        menu.addItem(platformMenuItem)
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
        interactionTimer = Timer.scheduledTimer(timeInterval: 0.10, target: self, selector: #selector(updateHUDInteraction), userInfo: nil, repeats: true)
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

    private func requestLuminanceSample() {
        // ScreenCaptureKit can display a privacy prompt when queried without a
        // recognized TCC grant. The HUD must never create a repeating prompt in
        // the background; use the safest high-contrast appearance instead.
        guard CGPreflightScreenCaptureAccess() else {
            sampledLuminance = 1.0
            hudView?.backgroundLuminance = sampledLuminance
            if !recordedMissingScreenPermission,
               let data = try? JSONSerialization.data(withJSONObject: [
                   "luminance": sampledLuminance,
                   "bright_ratio": 1.0,
                   "bright_mode": true,
                   "capture_permission": "not_granted",
                   "timestamp": Date().timeIntervalSince1970,
               ]) {
                recordedMissingScreenPermission = true
                try? data.write(to: contrastFile, options: .atomic)
            }
            return
        }
        recordedMissingScreenPermission = false
        guard !luminanceSampling, Date().timeIntervalSince(lastLuminanceCheck) > 1.5,
              let application = NSWorkspace.shared.frontmostApplication else { return }
        lastLuminanceCheck = Date()
        luminanceSampling = true
        let pid = application.processIdentifier
        Task { [weak self] in
            var luminance: CGFloat?
            var brightRatio: CGFloat = 0
            do {
                let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                let candidates = content.windows.filter { $0.owningApplication?.processID == pid && $0.isOnScreen }
                if let window = candidates.max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) {
                    let filter = SCContentFilter(desktopIndependentWindow: window)
                    let configuration = SCStreamConfiguration()
                    configuration.width = 24
                    configuration.height = 24
                    configuration.showsCursor = false
                    let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
                    let side = 24
                    var pixels = [UInt8](repeating: 0, count: side * side * 4)
                    let colorSpace = CGColorSpaceCreateDeviceRGB()
                    pixels.withUnsafeMutableBytes { buffer in
                        if let context = CGContext(data: buffer.baseAddress, width: side, height: side, bitsPerComponent: 8, bytesPerRow: side * 4, space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) {
                            context.draw(image, in: CGRect(x: 0, y: 0, width: side, height: side))
                        }
                    }
                    var total: CGFloat = 0
                    var brightPixels = 0
                    for index in stride(from: 0, to: pixels.count, by: 4) {
                        let pixelLuminance = (0.2126 * CGFloat(pixels[index]) + 0.7152 * CGFloat(pixels[index + 1]) + 0.0722 * CGFloat(pixels[index + 2])) / 255.0
                        total += pixelLuminance
                        if pixelLuminance > 0.72 { brightPixels += 1 }
                    }
                    let average = total / CGFloat(side * side)
                    brightRatio = CGFloat(brightPixels) / CGFloat(side * side)
                    // A browser can have dark chrome surrounding a bright page. Weight the
                    // amount of bright content so the HUD still switches to high contrast.
                    luminance = max(average, min(1.0, brightRatio * 2.5))
                }
            } catch {}
            DispatchQueue.main.async {
                if let luminance { self?.sampledLuminance = luminance }
                self?.luminanceSampling = false
                self?.hudView?.backgroundLuminance = self?.sampledLuminance ?? 0.25
                self?.hudView?.needsDisplay = true
                if let self,
                   let data = try? JSONSerialization.data(withJSONObject: [
                       "luminance": self.sampledLuminance,
                       "bright_ratio": brightRatio,
                       "bright_mode": self.sampledLuminance > 0.58,
                       "timestamp": Date().timeIntervalSince1970,
                   ]) {
                    try? data.write(to: self.contrastFile, options: .atomic)
                }
            }
        }
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
            "listening": .systemCyan, "session": .systemYellow, "transcribing": .systemYellow,
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
        if let data = try? Data(contentsOf: platformFile),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            let memories = value["memories"] as? Int ?? 0
            let documents = value["documents"] as? Int ?? 0
            let calls = value["cloud_calls_24h"] as? Int ?? 0
            let tasks = value["task_history"] as? Int ?? 0
            let project = value["active_project"] as? String ?? ""
            let projectLabel = project.isEmpty ? "no active project" : "project: \(project)"
            platformMenuItem.title = "Local agent: \(projectLabel) • \(tasks) tasks • \(memories) memories • \(documents) files • \(calls) cloud calls"
        }
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
        if !visible {
            hudView?.setAnimating(false)
            hud?.orderOut(nil)
            return
        }
        if hud == nil {
            let frame = targetScreen().visibleFrame
            let panel = NSPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            panel.level = .floating
            panel.isOpaque = false
            panel.backgroundColor = .clear
            panel.hasShadow = false
            panel.ignoresMouseEvents = true
            panel.hidesOnDeactivate = false
            panel.isReleasedWhenClosed = false
            panel.becomesKeyOnlyIfNeeded = true
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
        var planUpdated: Double = 0
        let taskFile = appDirectory.appendingPathComponent(".runtime/active-task.json")
        if let data = try? Data(contentsOf: taskFile),
           let task = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let plan = task["plan"] as? [String: Any] {
                goal = plan["goal"] as? String ?? ""
                steps = plan["steps"] as? [String] ?? []
            }
            events = (task["events"] as? [[String: Any]])?.count ?? 0
            planUpdated = task["updated_at"] as? Double ?? 0
        }
        if let data = try? Data(contentsOf: uiPlanFile),
           let plan = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let localSteps = plan["steps"] as? [String], !localSteps.isEmpty,
           (plan["updated"] as? Double ?? 0) >= planUpdated {
            goal = plan["goal"] as? String ?? goal
            steps = localSteps
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
        hudView?.setAnimating(true)
        hudView?.label = label
        hudView?.detail = detail
        hudView?.goal = goal
        hudView?.steps = steps
        hudView?.eventCount = max(events, actions.count)
        hudView?.messages = messages
        hudView?.actions = actions
        hudView?.backgroundLuminance = sampledLuminance
        requestLuminanceSample()
        hudView?.needsDisplay = true
        let frame = targetScreen().visibleFrame
        hud?.setFrame(frame, display: true)
        hudView?.frame = NSRect(origin: .zero, size: frame.size)
        hud?.orderFrontRegardless()
        updateHUDInteraction()
    }

    @objc private func updateHUDInteraction() {
        guard let panel = hud, panel.isVisible, let view = hudView else {
            hud?.ignoresMouseEvents = true
            return
        }
        let local = panel.convertPoint(fromScreen: NSEvent.mouseLocation)
        panel.ignoresMouseEvents = !view.containsInteractivePoint(local)
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
