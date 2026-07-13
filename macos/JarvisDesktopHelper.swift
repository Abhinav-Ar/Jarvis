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
case "screenshot":
    guard args.count == 3 else { fail("screenshot requires an output path") }
    Task {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
            guard let display = content.displays.first else { fail("No display is available") }
            let filter = SCContentFilter(display: display, excludingWindows: [])
            let configuration = SCStreamConfiguration()
            configuration.width = display.width
            configuration.height = display.height
            configuration.showsCursor = true
            let image = try await SCScreenshotManager.captureImage(
                contentFilter: filter,
                configuration: configuration
            )
            let url = URL(fileURLWithPath: args[2]) as CFURL
            guard let destination = CGImageDestinationCreateWithURL(
                url,
                UTType.png.identifier as CFString,
                1,
                nil
            ) else { fail("Unable to create screenshot destination") }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else { fail("Unable to save screenshot") }
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
