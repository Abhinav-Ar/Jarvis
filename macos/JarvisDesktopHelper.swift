import AppKit
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

func axString(_ element: AXUIElement, _ attribute: String) -> String {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return "" }
    return value as? String ?? ""
}

func axBool(_ element: AXUIElement, _ attribute: String) -> Bool {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return false }
    return (value as? Bool) ?? false
}

func axArray(_ element: AXUIElement, _ attribute: String) -> [AXUIElement] {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return [] }
    return value as? [AXUIElement] ?? []
}

func axPoint(_ element: AXUIElement, _ attribute: String) -> CGPoint? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success,
          let axValue = value as! AXValue?, AXValueGetType(axValue) == .cgPoint else { return nil }
    var point = CGPoint.zero
    return AXValueGetValue(axValue, .cgPoint, &point) ? point : nil
}

func axSize(_ element: AXUIElement, _ attribute: String) -> CGSize? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success,
          let axValue = value as! AXValue?, AXValueGetType(axValue) == .cgSize else { return nil }
    var size = CGSize.zero
    return AXValueGetValue(axValue, .cgSize, &size) ? size : nil
}

func setWindowFrame(_ window: AXUIElement, frame: CGRect) -> Bool {
    var point = frame.origin
    var size = frame.size
    guard let position = AXValueCreate(.cgPoint, &point), let dimensions = AXValueCreate(.cgSize, &size) else { return false }
    let sized = AXUIElementSetAttributeValue(window, kAXSizeAttribute as CFString, dimensions) == .success
    let positioned = AXUIElementSetAttributeValue(window, kAXPositionAttribute as CFString, position) == .success
    // Several Chromium/Electron windows recalculate their origin after a resize.
    // Re-apply both values once, then verify the actual frame instead of trusting
    // the Accessibility return code.
    _ = AXUIElementSetAttributeValue(window, kAXSizeAttribute as CFString, dimensions)
    _ = AXUIElementSetAttributeValue(window, kAXPositionAttribute as CFString, position)
    usleep(180_000)
    guard sized && positioned, let observedPoint = axPoint(window, kAXPositionAttribute as String),
          let observedSize = axSize(window, kAXSizeAttribute as String) else { return false }
    return abs(observedPoint.x - frame.minX) <= 16 && abs(observedPoint.y - frame.minY) <= 16
        && observedSize.width >= 240 && observedSize.height >= 180
}

func displayRecords() -> [(CGDirectDisplayID, CGRect)] {
    NSScreen.screens.compactMap { screen in
        guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else { return nil }
        let identifier = CGDirectDisplayID(number.uint32Value)
        return (identifier, CGDisplayBounds(identifier))
    }
}

func frameRecord(_ frame: CGRect) -> [String: CGFloat] {
    ["x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height]
}

func primaryWindow(_ application: AXUIElement) -> AXUIElement? {
    var focused: CFTypeRef?
    if AXUIElementCopyAttributeValue(application, kAXFocusedWindowAttribute as CFString, &focused) == .success,
       let window = focused as! AXUIElement? { return window }
    return axArray(application, kAXWindowsAttribute as String).first
}

func axChildren(_ element: AXUIElement) -> [AXUIElement] {
    // Electron applications commonly expose their real content through AXWindows
    // while AXChildren contains only the native menu bar. Visit windows first so
    // labelled fields are not crowded out by hundreds of menu descendants.
    return axArray(element, kAXWindowsAttribute as String) + axArray(element, kAXChildrenAttribute as String)
}

func applicationAliases(_ requested: String) -> ([String], [String]) {
    let normalized = requested.lowercased()
    let aliases: [String: ([String], [String])] = [
        "visual studio code": (["visual studio code", "code"], ["com.microsoft.VSCode"]),
        "vs code": (["visual studio code", "code"], ["com.microsoft.VSCode"]),
        "github desktop": (["github desktop"], ["com.github.GitHubClient"]),
        "google chrome": (["google chrome", "chrome"], ["com.google.Chrome"]),
        "codex": (["codex", "chatgpt"], ["com.openai.codex", "com.openai.chat"]),
    ]
    return aliases[normalized] ?? ([normalized], [])
}

func applicationElement(_ requested: String) -> AXUIElement {
    let (names, bundleIdentifiers) = applicationAliases(requested)
    var application = NSWorkspace.shared.runningApplications.first(where: {
        let name = ($0.localizedName ?? "").lowercased()
        return names.contains(where: { name == $0 || name.contains($0) })
            || bundleIdentifiers.contains($0.bundleIdentifier ?? "")
    })
    // Prefer the process that owns the largest visible window. Multi-process
    // Electron applications can publish several similarly named processes, but
    // only the window owner exposes the renderer's accessibility tree.
    if let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]],
       let owner = windows.filter({ window in
           let name = (window[kCGWindowOwnerName as String] as? String ?? "").lowercased()
            let layer = (window[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 1
            return names.contains(where: { name == $0 || name.contains($0) }) && layer == 0
       }).max(by: { first, second in
           let firstDictionary = first[kCGWindowBounds as String] as? NSDictionary ?? [:]
           let secondDictionary = second[kCGWindowBounds as String] as? NSDictionary ?? [:]
           let firstBounds = CGRect(dictionaryRepresentation: firstDictionary) ?? .zero
           let secondBounds = CGRect(dictionaryRepresentation: secondDictionary) ?? .zero
           return firstBounds.width * firstBounds.height < secondBounds.width * secondBounds.height
       }), let pid = (owner[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value,
       let windowApplication = NSRunningApplication(processIdentifier: pid) {
        application = windowApplication
    }
    guard let application else { fail("Application is not running: \(requested)") }
    application.activate(options: [.activateAllWindows])
    usleep(300_000)
    let element = AXUIElementCreateApplication(application.processIdentifier)
    // Electron enables its renderer accessibility tree when a trusted assistive
    // client requests manual accessibility.
    AXUIElementSetAttributeValue(element, "AXManualAccessibility" as CFString, true as CFTypeRef)
    usleep(120_000)
    return element
}

func processID(_ application: AXUIElement) -> pid_t {
    var pid: pid_t = 0
    AXUIElementGetPid(application, &pid)
    return pid
}

func largestWindowFrame(pid: pid_t) -> CGRect? {
    guard let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return nil }
    return windows.compactMap { window -> CGRect? in
        guard (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid,
              (window[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
              let dictionary = window[kCGWindowBounds as String] as? NSDictionary else { return nil }
        return CGRect(dictionaryRepresentation: dictionary)
    }.max(by: { $0.width * $0.height < $1.width * $1.height })
}

func looksFullscreen(_ frame: CGRect) -> Bool {
    displayRecords().contains { _, display in
        abs(frame.minX - display.minX) <= 4 && abs(frame.minY - display.minY) <= 4
            && abs(frame.width - display.width) <= 8 && abs(frame.height - display.height) <= 8
    }
}

func fullscreenShortcut() {
    let source = CGEventSource(stateID: .hidSystemState)
    let down = CGEvent(keyboardEventSource: source, virtualKey: 3, keyDown: true)
    down?.flags = [.maskCommand, .maskControl]
    down?.post(tap: .cghidEventTap)
    let up = CGEvent(keyboardEventSource: source, virtualKey: 3, keyDown: false)
    up?.flags = [.maskCommand, .maskControl]
    up?.post(tap: .cghidEventTap)
}

func normalizedWindow(_ application: AXUIElement) -> (AXUIElement?, Bool) {
    var window = primaryWindow(application)
    var exitedFullscreen = false
    if let window, axBool(window, "AXFullScreen") {
        if AXUIElementSetAttributeValue(window, "AXFullScreen" as CFString, false as CFTypeRef) == .success {
            exitedFullscreen = true
            usleep(900_000)
        }
    } else if let frame = largestWindowFrame(pid: processID(application)), looksFullscreen(frame) {
        fullscreenShortcut()
        exitedFullscreen = true
        usleep(1_100_000)
    }
    window = primaryWindow(application)
    if window == nil {
        // Native menus expose this even when a fullscreen Space temporarily hides
        // the ordinary AXWindows collection.
        if let exitItem = matchingElements(application, selector: "Exit Full Screen").first,
           AXUIElementPerformAction(exitItem, kAXPressAction as CFString) == .success {
            exitedFullscreen = true
            usleep(1_100_000)
            window = primaryWindow(application)
        }
    }
    return (window, exitedFullscreen)
}

func collectElements(_ root: AXUIElement, maximum: Int = 500) -> [AXUIElement] {
    var result: [AXUIElement] = []
    var queue: [(AXUIElement, Int)] = [(root, 0)]
    while !queue.isEmpty && result.count < maximum {
        let (element, depth) = queue.removeFirst()
        result.append(element)
        if depth < 14 {
            queue.append(contentsOf: axChildren(element).prefix(100).map { ($0, depth + 1) })
        }
    }
    return result
}

func isSensitive(_ element: AXUIElement, fields: [String]) -> Bool {
    if axString(element, kAXRoleAttribute as String) == "AXSecureTextField" { return true }
    let combined = fields.joined(separator: " ").lowercased()
    return ["password", "passcode", "authentication code", "credit card", "security code", "token", "secret"].contains {
        combined.contains($0)
    }
}

func selectorParts(_ selector: String) -> (String, String) {
    let parts = selector.split(separator: "|", maxSplits: 1).map(String.init)
    return parts.count == 2 ? (parts[0].lowercased(), parts[1].lowercased()) : ("", selector.lowercased())
}

func matchingElements(_ root: AXUIElement, selector: String) -> [AXUIElement] {
    let (roleQuery, textQuery) = selectorParts(selector)
    return collectElements(root).filter { element in
        let role = axString(element, kAXRoleAttribute as String)
        let fields = [
            axString(element, kAXTitleAttribute as String),
            axString(element, kAXDescriptionAttribute as String),
            axString(element, "AXPlaceholderValue"),
            axString(element, kAXIdentifierAttribute as String),
            axString(element, kAXValueAttribute as String),
        ]
        let roleMatches = roleQuery.isEmpty || role.lowercased().contains(roleQuery)
        let textMatches = textQuery.isEmpty || fields.contains { $0.lowercased().contains(textQuery) }
        return roleMatches && textMatches
    }.sorted { first, second in
        let firstEnabled = axBool(first, kAXEnabledAttribute as String)
        let secondEnabled = axBool(second, kAXEnabledAttribute as String)
        if firstEnabled != secondEnabled { return firstEnabled }
        let preferred = ["AXButton", "AXTextField", "AXTextArea"]
        return (preferred.firstIndex(of: axString(first, kAXRoleAttribute as String)) ?? 99) <
            (preferred.firstIndex(of: axString(second, kAXRoleAttribute as String)) ?? 99)
    }
}

let args = CommandLine.arguments
guard args.count >= 3 else { fail("Missing desktop action arguments") }
let action = args[1]

if !["screenshot", "screenshot-app", "ocr-app", "list-windows"].contains(action) {
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    guard AXIsProcessTrustedWithOptions(options) else {
        fail("Accessibility permission is required for Jarvis Desktop Helper")
    }
}

switch action {
case "list-displays":
    let records = displayRecords().map { displayID, frame in
        ["id": displayID, "frame": frameRecord(frame)] as [String: Any]
    }
    let data = try! JSONSerialization.data(withJSONObject: ["ok": true, "displays": records])
    print(String(data: data, encoding: .utf8)!)
case "window-state":
    let application = applicationElement(args[2])
    let window = primaryWindow(application)
    let point = window.flatMap { axPoint($0, kAXPositionAttribute as String) }
    let size = window.flatMap { axSize($0, kAXSizeAttribute as String) }
    let fallback = largestWindowFrame(pid: processID(application))
    guard let frame = (point != nil && size != nil ? CGRect(origin: point!, size: size!) : fallback) else {
        fail("Application has no observable window")
    }
    let fullscreen = window.map { axBool($0, "AXFullScreen") } ?? looksFullscreen(frame)
    let output: [String: Any] = [
        "ok": true, "application": args[2], "fullscreen": fullscreen,
        "frame": ["x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height],
    ]
    let data = try! JSONSerialization.data(withJSONObject: output)
    print(String(data: data, encoding: .utf8)!)
case "window-layout":
    guard args.count >= 5, let requestedReserve = Double(args[4]) else {
        fail("window-layout requires application, layout, and reserved width")
    }
    let application = applicationElement(args[2])
    let normalized = normalizedWindow(application)
    guard let window = normalized.0 else { fail("Application has no movable window after fullscreen recovery") }
    guard let oldPoint = axPoint(window, kAXPositionAttribute as String),
          let oldSize = axSize(window, kAXSizeAttribute as String) else { fail("Unable to read the application window frame") }
    let oldFrame = CGRect(origin: oldPoint, size: oldSize)
    let requestedDisplay = args.count >= 6 ? UInt32(args[5]) : nil
    let displays = displayRecords()
    let selected = displays.first(where: { requestedDisplay != nil && $0.0 == requestedDisplay! })
        ?? displays.max(by: { $0.1.intersection(oldFrame).width * $0.1.intersection(oldFrame).height < $1.1.intersection(oldFrame).width * $1.1.intersection(oldFrame).height })
    guard let (displayID, display) = selected else { fail("No display is available for the application window") }
    let reserved = requestedReserve > 0 ? CGFloat(requestedReserve) : 0
    let margin: CGFloat = 12
    let topInset: CGFloat = 34
    let workWidth = max(520, display.width - reserved - margin * 3)
    let workHeight = max(420, display.height - topInset - margin * 2)
    let layout = args[3].lowercased()
    var target = CGRect(x: display.minX + margin, y: display.minY + topInset, width: workWidth, height: workHeight)
    if layout == "tile-left" || layout == "tile-right" {
        let gutter: CGFloat = 10
        let half = (workWidth - gutter) / 2
        target.size.width = half
        if layout == "tile-right" { target.origin.x += half + gutter }
    }
    guard setWindowFrame(window, frame: target) else { fail("The application does not allow its window to be moved or resized") }
    let actualPoint = axPoint(window, kAXPositionAttribute as String) ?? target.origin
    let actualSize = axSize(window, kAXSizeAttribute as String) ?? target.size
    let actual = CGRect(origin: actualPoint, size: actualSize)
    let output: [String: Any] = [
        "ok": true, "application": args[2], "layout": layout, "display_id": displayID,
        "exited_fullscreen": normalized.1, "verified": true,
        "display_frame": frameRecord(display), "original": frameRecord(oldFrame),
        "requested_frame": frameRecord(target), "frame": frameRecord(actual),
    ]
    let data = try! JSONSerialization.data(withJSONObject: output)
    print(String(data: data, encoding: .utf8)!)
case "window-place":
    guard args.count == 7, let x = Double(args[3]), let y = Double(args[4]),
          let width = Double(args[5]), let height = Double(args[6]), width >= 240, height >= 180 else {
        fail("window-place requires application, x, y, width, and height")
    }
    let application = applicationElement(args[2])
    let normalized = normalizedWindow(application)
    guard let window = normalized.0 else { fail("Application has no movable window after fullscreen recovery") }
    let target = CGRect(x: x, y: y, width: width, height: height)
    guard setWindowFrame(window, frame: target) else { fail("The application window could not be placed") }
    let actual = CGRect(
        origin: axPoint(window, kAXPositionAttribute as String) ?? target.origin,
        size: axSize(window, kAXSizeAttribute as String) ?? target.size
    )
    let output: [String: Any] = [
        "ok": true, "application": args[2], "exited_fullscreen": normalized.1,
        "verified": true, "requested_frame": frameRecord(target), "frame": frameRecord(actual),
    ]
    let data = try! JSONSerialization.data(withJSONObject: output)
    print(String(data: data, encoding: .utf8)!)
case "window-frame":
    guard args.count == 7, let x = Double(args[3]), let y = Double(args[4]),
          let width = Double(args[5]), let height = Double(args[6]), width >= 240, height >= 180 else {
        fail("window-frame requires application, x, y, width, and height")
    }
    let application = applicationElement(args[2])
    let normalized = normalizedWindow(application)
    guard let window = normalized.0,
          setWindowFrame(window, frame: CGRect(x: x, y: y, width: width, height: height)) else {
        fail("The application window could not be restored")
    }
    print("{\"ok\":true}")
case "window-fullscreen":
    guard args.count == 4 else { fail("window-fullscreen requires application and state") }
    let application = applicationElement(args[2])
    guard let window = primaryWindow(application) else { fail("Application has no window for fullscreen restoration") }
    let enabled = ["1", "true", "yes"].contains(args[3].lowercased())
    guard AXUIElementSetAttributeValue(window, "AXFullScreen" as CFString, enabled as CFTypeRef) == .success else {
        fail("The application fullscreen state could not be changed")
    }
    usleep(700_000)
    print("{\"ok\":true}")
case "list-windows":
    Task {
        do {
            let requested = args[2].lowercased()
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            let records: [[String: Any]] = content.windows.compactMap { window in
                guard let owner = window.owningApplication else { return nil }
                if !requested.isEmpty && !owner.applicationName.lowercased().contains(requested) { return nil }
                return [
                    "application": owner.applicationName,
                    "pid": owner.processID,
                    "title": window.title ?? "",
                    "on_screen": window.isOnScreen,
                    "x": window.frame.minX,
                    "y": window.frame.minY,
                    "width": window.frame.width,
                    "height": window.frame.height,
                ]
            }
            guard let data = try? JSONSerialization.data(withJSONObject: ["ok": true, "windows": records]),
                  let line = String(data: data, encoding: .utf8) else { fail("Unable to encode window list") }
            print(line)
            exit(0)
        } catch {
            fail("Window listing failed: \(error.localizedDescription)")
        }
    }
    dispatchMain()
case "ocr-app":
    let backgroundApplication = NSApplication.shared
    backgroundApplication.setActivationPolicy(.prohibited)
    Task {
        do {
            let requested = args[2]
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            let windows = content.windows.filter { window in
                guard let owner = window.owningApplication else { return false }
                return owner.applicationName.localizedCaseInsensitiveContains(requested)
            }
            guard let window = windows.max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) else {
                fail("No visible window found for \(requested)")
            }
            let filter = SCContentFilter(desktopIndependentWindow: window)
            let configuration = SCStreamConfiguration()
            configuration.width = max(1, Int(window.frame.width * 2))
            configuration.height = max(1, Int(window.frame.height * 2))
            configuration.showsCursor = false
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .fast
            request.usesLanguageCorrection = false
            let handler = VNImageRequestHandler(cgImage: image)
            try handler.perform([request])
            let observations: [[String: Any]] = (request.results ?? []).compactMap { observation in
                guard let candidate = observation.topCandidates(1).first else { return nil }
                let box = observation.boundingBox
                return [
                    "text": candidate.string,
                    "confidence": candidate.confidence,
                    "x": window.frame.minX + box.minX * window.frame.width,
                    "y": window.frame.minY + (1 - box.maxY) * window.frame.height,
                    "width": box.width * window.frame.width,
                    "height": box.height * window.frame.height,
                ]
            }
            let output: [String: Any] = ["ok": true, "application": requested, "text": observations]
            guard let data = try? JSONSerialization.data(withJSONObject: output),
                  let line = String(data: data, encoding: .utf8) else { fail("Unable to encode local OCR") }
            print(line)
            exit(0)
        } catch {
            fail("Local OCR failed: \(error.localizedDescription)")
        }
    }
    dispatchMain()
case "screenshot", "screenshot-app":
    guard args.count == 3 || (action == "screenshot-app" && args.count == 4) else { fail("screenshot requires an output path") }
    Task {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
            guard !content.displays.isEmpty else { fail("No display is available") }
            let overlayWindows = content.windows.filter { window in
                guard let owner = window.owningApplication else { return false }
                return owner.bundleIdentifier == "com.jarvis.menu" || owner.applicationName == "JarvisMenu"
            }
            var selectedDisplays = content.displays
            if action == "screenshot-app" {
                let requested = args[3]
                let windows = content.windows.filter { window in
                    guard let owner = window.owningApplication else { return false }
                    return owner.applicationName.localizedCaseInsensitiveContains(requested) && window.isOnScreen
                }
                if let targetWindow = windows.max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }),
                   let targetDisplay = content.displays.max(by: { first, second in
                       first.frame.intersection(targetWindow.frame).width * first.frame.intersection(targetWindow.frame).height <
                       second.frame.intersection(targetWindow.frame).width * second.frame.intersection(targetWindow.frame).height
                   }) {
                    selectedDisplays = [targetDisplay]
                } else {
                    fail("No visible window found for \(requested)")
                }
            }
            var captures: [(SCDisplay, CGImage)] = []
            for display in selectedDisplays {
                let filter = SCContentFilter(display: display, excludingWindows: overlayWindows)
                let configuration = SCStreamConfiguration()
                configuration.width = display.width
                configuration.height = display.height
                configuration.showsCursor = true
                let image = try await SCScreenshotManager.captureImage(
                    contentFilter: filter,
                    configuration: configuration
                )
                captures.append((display, image))
            }
            let gutter = 12
            let totalWidth = captures.reduce(0) { $0 + $1.1.width } + gutter * max(0, captures.count - 1)
            let totalHeight = captures.map { $0.1.height }.max() ?? 1
            let colorSpace = CGColorSpaceCreateDeviceRGB()
            guard let context = CGContext(
                data: nil, width: totalWidth, height: totalHeight,
                bitsPerComponent: 8, bytesPerRow: totalWidth * 4,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else { fail("Unable to create multi-display canvas") }
            context.setFillColor(CGColor(gray: 0.02, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: totalWidth, height: totalHeight))
            var offsetX = 0
            var metadata: [[String: Any]] = []
            for (index, capture) in captures.enumerated() {
                let display = capture.0
                let image = capture.1
                context.draw(image, in: CGRect(x: offsetX, y: totalHeight - image.height, width: image.width, height: image.height))
                let global = CGDisplayBounds(display.displayID)
                metadata.append([
                    "screen": index + 1,
                    "display_id": display.displayID,
                    "montage_x": offsetX,
                    "montage_y": totalHeight - image.height,
                    "pixel_width": image.width,
                    "pixel_height": image.height,
                    "global_x": global.origin.x,
                    "global_y": global.origin.y,
                    "global_width": global.width,
                    "global_height": global.height,
                ])
                offsetX += image.width + gutter
            }
            guard let image = context.makeImage() else { fail("Unable to render multi-display canvas") }
            let url = URL(fileURLWithPath: args[2]) as CFURL
            guard let destination = CGImageDestinationCreateWithURL(
                url,
                UTType.png.identifier as CFString,
                1,
                nil
            ) else { fail("Unable to create screenshot destination") }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else { fail("Unable to save screenshot") }
            let mapping: [String: Any] = [
                "montage_width": totalWidth,
                "montage_height": totalHeight,
                "displays": metadata,
                "coordinate_rule": "For a point (mx,my) inside a display: gx=global_x+(mx-montage_x)*global_width/pixel_width; gy=global_y+(my-montage_y)*global_height/pixel_height",
            ]
            if let data = try? JSONSerialization.data(withJSONObject: mapping),
               let line = String(data: data, encoding: .utf8) {
                print(line)
            }
            exit(0)
        } catch {
            fail("Screen capture failed: \(error.localizedDescription)")
        }
    }
    dispatchMain()
case "inspect-ui":
    let root = applicationElement(args[2])
    let selector = args.count >= 4 ? args[3] : ""
    let elements = selector.isEmpty ? collectElements(root, maximum: 300) : matchingElements(root, selector: selector)
    let records: [[String: Any]] = elements.compactMap { element in
        let fields = [
            axString(element, kAXTitleAttribute as String),
            axString(element, kAXDescriptionAttribute as String),
            axString(element, "AXPlaceholderValue"),
            axString(element, kAXIdentifierAttribute as String),
        ]
        let role = axString(element, kAXRoleAttribute as String)
        if role.isEmpty || (fields.allSatisfy { $0.isEmpty } && !["AXButton", "AXTextField", "AXTextArea"].contains(role)) {
            return nil
        }
        return [
            "role": role,
            "title": fields[0],
            "description": fields[1],
            "placeholder": fields[2],
            "identifier": fields[3],
            "value": isSensitive(element, fields: fields) ? "[REDACTED]" : String(axString(element, kAXValueAttribute as String).prefix(500)),
            "enabled": axBool(element, kAXEnabledAttribute as String),
        ]
    }
    guard let data = try? JSONSerialization.data(withJSONObject: ["ok": true, "application": args[2], "elements": records]),
          let output = String(data: data, encoding: .utf8) else { fail("Unable to encode accessibility elements") }
    print(output)
case "press-ui":
    guard args.count == 4 else { fail("press-ui requires application and selector") }
    let root = applicationElement(args[2])
    guard let element = matchingElements(root, selector: args[3]).first else { fail("No accessible control matched: \(args[3])") }
    guard axBool(element, kAXEnabledAttribute as String) else { fail("Matched control is disabled: \(args[3])") }
    guard AXUIElementPerformAction(element, kAXPressAction as CFString) == .success else { fail("Unable to press accessible control: \(args[3])") }
    print("{\"ok\":true}")
case "set-ui":
    guard args.count == 5, let data = Data(base64Encoded: args[4]), let value = String(data: data, encoding: .utf8) else {
        fail("set-ui requires application, selector, and encoded value")
    }
    let root = applicationElement(args[2])
    guard let element = matchingElements(root, selector: args[3]).first else { fail("No accessible field matched: \(args[3])") }
    let fields = [args[3], axString(element, kAXTitleAttribute as String), axString(element, kAXDescriptionAttribute as String)]
    guard !isSensitive(element, fields: fields) else { fail("Jarvis will not fill a sensitive field") }
    guard AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString, value as CFTypeRef) == .success else {
        fail("Unable to set accessible field: \(args[3])")
    }
    print("{\"ok\":true}")
case "click":
    guard args.count == 4, let x = Double(args[2]), let y = Double(args[3]) else {
        fail("click requires x and y")
    }
    let point = CGPoint(x: x, y: y)
    CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(80_000)
    CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
    CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
case "type":
    guard let data = Data(base64Encoded: args[2]), let value = String(data: data, encoding: .utf8) else {
        fail("Invalid text encoding")
    }
    let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true)
    event?.keyboardSetUnicodeString(stringLength: value.utf16.count, unicodeString: Array(value.utf16))
    event?.post(tap: .cghidEventTap)
    CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)?.post(tap: .cghidEventTap)
case "key":
    let codes: [String: CGKeyCode] = ["return": 36, "enter": 36, "tab": 48, "escape": 53, "space": 49, "delete": 51]
    guard let code = codes[args[2]] else { fail("Unsupported key") }
    CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
    CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
case "scroll":
    guard let amount = Int32(args[2]) else { fail("Invalid scroll amount") }
    CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: amount, wheel2: 0, wheel3: 0)?.post(tap: .cghidEventTap)
default:
    fail("Unsupported desktop action")
}
