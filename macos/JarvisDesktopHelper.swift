import AppKit
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

let args = CommandLine.arguments
guard args.count >= 3 else { fail("Missing desktop action arguments") }
let action = args[1]

if action != "screenshot" {
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    guard AXIsProcessTrustedWithOptions(options) else {
        fail("Accessibility permission is required for Jarvis Desktop Helper")
    }
}

switch action {
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
