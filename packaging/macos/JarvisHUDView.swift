import AppKit

final class OrionHUDPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class OrionPromptTextView: NSTextView {
    var submitHandler: (() -> Void)?
    var cancelHandler: (() -> Void)?
    var placeholder = "Type a command…"

    override func keyDown(with event: NSEvent) {
        if event.modifierFlags.intersection(.deviceIndependentFlagsMask).contains(.command),
           let key = event.charactersIgnoringModifiers?.lowercased() {
            switch key {
            case "c": copy(nil); return
            case "v": paste(nil); needsDisplay = true; return
            case "x": cut(nil); needsDisplay = true; return
            case "a": selectAll(nil); return
            default: break
            }
        }
        if event.keyCode == 36 && !event.modifierFlags.contains(.shift) {
            submitHandler?()
            return
        }
        if event.keyCode == 53 {
            cancelHandler?()
            return
        }
        super.keyDown(with: event)
        needsDisplay = true
    }

    override func didChangeText() {
        super.didChangeText()
        needsDisplay = true
    }

    override func mouseDown(with event: NSEvent) {
        // The full-screen HUD normally passes clicks through. Once the pointer
        // reaches the composer, explicitly reclaim key focus so the field works
        // after every submission—not only after the menu command opened it.
        window?.makeKey()
        window?.makeFirstResponder(self)
        super.mouseDown(with: event)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        if string.isEmpty && window?.firstResponder !== self {
            NSString(string: placeholder).draw(
                at: NSPoint(x: 6, y: 5),
                withAttributes: [
                    .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
                    .foregroundColor: NSColor.white.withAlphaComponent(0.38),
                ]
            )
        }
    }
}

final class JarvisHUDView: NSView {
    var state = "planning"
    var label = "Planning…"
    var detail = ""
    var goal = ""
    var steps: [String] = []
    var messages: [[String: String]] = [] { didSet { if messages.count != oldValue.count { chatOffset = 0 } } }
    var actions: [[String: String]] = [] { didSet { if actions.count != oldValue.count { intelligenceOffset = 0 } } }
    var eventCount = 0
    var currentStep = 0
    var backgroundLuminance: CGFloat = 0.25
    private var phase: CGFloat = 0
    private var chatOffset: CGFloat = 0
    private var intelligenceOffset: CGFloat = 0
    private var chatMaximum: CGFloat = 0
    private var intelligenceMaximum: CGFloat = 0
    private var animationTimer: Timer?
    var onSubmitCommand: ((String) -> Void)?
    var onCancelCommand: (() -> Void)?
    var onCancelTask: (() -> Void)?
    private let promptScroll = NSScrollView()
    private let promptView = OrionPromptTextView()
    private let sendButton = NSButton(title: "SEND  ↵", target: nil, action: nil)
    private let cancelButton = NSButton(title: "STOP", target: nil, action: nil)

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        promptScroll.drawsBackground = true
        promptScroll.backgroundColor = NSColor.black.withAlphaComponent(0.82)
        promptScroll.borderType = .noBorder
        promptScroll.hasVerticalScroller = true
        promptScroll.autohidesScrollers = true
        promptScroll.wantsLayer = true
        promptScroll.layer?.cornerRadius = 8
        promptScroll.layer?.borderWidth = 1
        promptView.drawsBackground = false
        promptView.textColor = .white
        promptView.insertionPointColor = .systemCyan
        promptView.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        promptView.isRichText = false
        promptView.isAutomaticQuoteSubstitutionEnabled = false
        promptView.isAutomaticDashSubstitutionEnabled = false
        promptView.textContainerInset = NSSize(width: 5, height: 4)
        promptView.minSize = NSSize(width: 0, height: 42)
        promptView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        promptView.isVerticallyResizable = true
        promptView.isHorizontallyResizable = false
        promptView.textContainer?.widthTracksTextView = true
        promptView.submitHandler = { [weak self] in self?.submitCommand() }
        promptView.cancelHandler = { [weak self] in self?.onCancelCommand?() }
        promptScroll.documentView = promptView
        addSubview(promptScroll)
        sendButton.target = self
        sendButton.action = #selector(submitCommand)
        sendButton.isBordered = false
        sendButton.font = NSFont.monospacedSystemFont(ofSize: 10, weight: .bold)
        sendButton.contentTintColor = .white
        sendButton.wantsLayer = true
        sendButton.layer?.cornerRadius = 8
        addSubview(sendButton)
        cancelButton.target = self
        cancelButton.action = #selector(cancelTask)
        cancelButton.isBordered = false
        cancelButton.font = NSFont.monospacedSystemFont(ofSize: 10, weight: .bold)
        cancelButton.contentTintColor = .systemRed
        cancelButton.wantsLayer = true
        cancelButton.layer?.cornerRadius = 8
        cancelButton.layer?.borderWidth = 1
        cancelButton.layer?.borderColor = NSColor.systemRed.withAlphaComponent(0.65).cgColor
        addSubview(cancelButton)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override var acceptsFirstResponder: Bool { false }

    var isComposerFocused: Bool {
        guard let responder = window?.firstResponder else { return false }
        return responder === promptView || (responder as? NSView)?.isDescendant(of: promptScroll) == true
    }

    func focusComposer() {
        window?.makeFirstResponder(promptView)
    }

    @objc private func submitCommand() {
        let command = promptView.string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !command.isEmpty else { NSSound.beep(); return }
        promptView.string = ""
        promptView.needsDisplay = true
        onSubmitCommand?(command)
    }

    @objc private func cancelTask() {
        onCancelTask?()
    }

    override func layout() {
        super.layout()
        let rect = composerRect(in: layoutRects().chat)
        sendButton.frame = NSRect(x: rect.maxX - 92, y: rect.minY + 7, width: 82, height: rect.height - 14)
        cancelButton.frame = NSRect(x: rect.maxX - 157, y: rect.minY + 7, width: 57, height: rect.height - 14)
        promptScroll.frame = NSRect(x: rect.minX + 7, y: rect.minY + 7, width: rect.width - 174, height: rect.height - 14)
    }

    @objc private func animate() {
        phase += 0.04
        needsDisplay = true
    }

    func setAnimating(_ enabled: Bool) {
        if enabled, animationTimer == nil {
            animationTimer = Timer.scheduledTimer(timeInterval: 1.0 / 24.0, target: self, selector: #selector(animate), userInfo: nil, repeats: true)
        } else if !enabled {
            animationTimer?.invalidate()
            animationTimer = nil
        }
    }

    override func scrollWheel(with event: NSEvent) {
        let location = convert(event.locationInWindow, from: nil)
        let amount = event.scrollingDeltaY * (event.hasPreciseScrollingDeltas ? 1.0 : 8.0)
        let rects = layoutRects()
        if rects.chat.contains(location) {
            chatOffset = min(chatMaximum, max(0, chatOffset + amount))
        } else if rects.path.contains(location) {
            intelligenceOffset = min(intelligenceMaximum, max(0, intelligenceOffset + amount))
        }
        needsDisplay = true
    }

    private var accent: NSColor {
        [
            "session": .systemYellow, "speaking": .systemGreen,
            "transcribing": .systemYellow, "planning": .systemCyan,
            "working": NSColor(calibratedRed: 0.88, green: 0.18, blue: 1.0, alpha: 1),
            "verifying": NSColor(calibratedRed: 0.10, green: 0.68, blue: 1.0, alpha: 1),
            "needs_input": .systemOrange, "error": .systemRed,
        ][state] ?? .systemCyan
    }

    private let userColor = NSColor(calibratedRed: 0.03, green: 0.64, blue: 1.0, alpha: 1)
    private let jarvisColor = NSColor(calibratedRed: 0.18, green: 1.0, blue: 0.55, alpha: 1)

    private func font(_ size: CGFloat, _ weight: NSFont.Weight = .regular) -> NSFont {
        NSFont.monospacedSystemFont(ofSize: size, weight: weight)
    }

    private func text(_ value: String, at point: NSPoint, size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) {
        NSString(string: value).draw(at: point, withAttributes: [.font: font(size, weight), .foregroundColor: color])
    }

    private func attributes(size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) -> [NSAttributedString.Key: Any] {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byWordWrapping
        paragraph.lineSpacing = 2
        return [.font: font(size, weight), .foregroundColor: color, .paragraphStyle: paragraph]
    }

    private func block(_ value: String, in rect: NSRect, size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) {
        NSString(string: value).draw(in: rect, withAttributes: attributes(size: size, color: color, weight: weight))
    }

    private func measured(_ value: String, width: CGFloat, size: CGFloat, weight: NSFont.Weight = .regular) -> CGFloat {
        ceil(NSString(string: value).boundingRect(
            with: NSSize(width: width, height: 10_000),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: attributes(size: size, color: .white, weight: weight)
        ).height)
    }

    private func cleaned(_ value: String) -> String {
        value.replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "`", with: "")
            .replacingOccurrences(of: "\\n", with: "\n")
    }

    private func rounded(_ rect: NSRect, radius: CGFloat, fill: NSColor, stroke: NSColor, width: CGFloat = 1) {
        let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
        fill.setFill(); path.fill()
        stroke.setStroke(); path.lineWidth = width; path.stroke()
    }

    private func section(_ rect: NSRect, title: String, badge: String = "") {
        rounded(rect, radius: 12, fill: NSColor.black.withAlphaComponent(backgroundLuminance > 0.58 ? 0.88 : 0.66), stroke: accent.withAlphaComponent(0.86), width: 1.4)
        text(title, at: NSPoint(x: rect.minX + 14, y: rect.maxY - 27), size: 10, color: accent, weight: .bold)
        if !badge.isEmpty {
            let width = max(54, CGFloat(badge.count) * 7 + 14)
            let badgeRect = NSRect(x: rect.maxX - width - 12, y: rect.maxY - 31, width: width, height: 20)
            rounded(badgeRect, radius: 10, fill: accent.withAlphaComponent(0.16), stroke: accent.withAlphaComponent(0.55))
            text(badge, at: NSPoint(x: badgeRect.minX + 8, y: badgeRect.minY + 5), size: 8, color: accent, weight: .bold)
        }
    }

    private func drawConversation(_ rect: NSRect) {
        section(rect, title: "LIVE COMMAND CHANNEL", badge: chatMaximum > 0 ? "SCROLL" : "LIVE")
        let composer = composerRect(in: rect)
        rounded(composer, radius: 10, fill: NSColor.black.withAlphaComponent(0.76), stroke: accent.withAlphaComponent(0.72), width: 1.2)
        promptScroll.layer?.borderColor = accent.withAlphaComponent(isComposerFocused ? 0.95 : 0.48).cgColor
        sendButton.layer?.backgroundColor = accent.withAlphaComponent(0.28).cgColor
        let viewport = NSRect(x: rect.minX + 10, y: composer.maxY + 7, width: rect.width - 20, height: rect.maxY - 42 - composer.maxY - 7)
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: viewport).addClip()
        var total: CGFloat = 0
        let prepared = messages.map { message -> (String, Bool, CGFloat) in
            let value = cleaned(message["text"] ?? "")
            let isUser = message["role"] == "user"
            let height = max(50, measured(value, width: viewport.width - 38, size: 11) + 39)
            total += height + 8
            return (value, isUser, height)
        }
        chatMaximum = max(0, total - viewport.height)
        chatOffset = min(chatOffset, chatMaximum)
        var y = viewport.maxY - total + chatOffset
        for (value, isUser, height) in prepared {
            let color = isUser ? userColor : jarvisColor
            let bubble = NSRect(x: viewport.minX + (isUser ? 18 : 0), y: y, width: viewport.width - 18, height: height)
            if bubble.maxY >= viewport.minY && bubble.minY <= viewport.maxY {
                rounded(bubble, radius: 10, fill: color.withAlphaComponent(0.14), stroke: color.withAlphaComponent(0.68))
                text(isUser ? "YOU" : "ORION", at: NSPoint(x: bubble.minX + 11, y: bubble.maxY - 21), size: 8, color: color, weight: .bold)
                block(value, in: NSRect(x: bubble.minX + 11, y: bubble.minY + 9, width: bubble.width - 22, height: bubble.height - 34), size: 11, color: .white)
            }
            y += height + 8
        }
        if messages.isEmpty {
            block(goal.isEmpty ? "Speak or type what you need." : cleaned(goal), in: viewport.insetBy(dx: 10, dy: 24), size: 12, color: NSColor.white.withAlphaComponent(0.78), weight: .medium)
        }
        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawPath(_ rect: NSRect) {
        let focus = steps.isEmpty ? 0 : min(max(0, currentStep), steps.count - 1)
        // An open, angular trace surface reads like part of the HUD rather than
        // another application panel. Information flows down one luminous spine.
        let cut: CGFloat = 15
        let shell = NSBezierPath()
        shell.move(to: NSPoint(x: rect.minX + cut, y: rect.minY))
        shell.line(to: NSPoint(x: rect.maxX - cut * 2, y: rect.minY))
        shell.line(to: NSPoint(x: rect.maxX, y: rect.minY + cut * 1.4))
        shell.line(to: NSPoint(x: rect.maxX, y: rect.maxY - cut))
        shell.line(to: NSPoint(x: rect.maxX - cut, y: rect.maxY))
        shell.line(to: NSPoint(x: rect.minX + cut * 2, y: rect.maxY))
        shell.line(to: NSPoint(x: rect.minX, y: rect.maxY - cut * 1.4))
        shell.line(to: NSPoint(x: rect.minX, y: rect.minY + cut))
        shell.close()
        NSColor.black.withAlphaComponent(backgroundLuminance > 0.58 ? 0.82 : 0.48).setFill(); shell.fill()
        accent.withAlphaComponent(0.72).setStroke(); shell.lineWidth = 1.2; shell.stroke()
        let headerLine = NSBezierPath()
        headerLine.move(to: NSPoint(x: rect.minX + 18, y: rect.maxY - 39))
        headerLine.line(to: NSPoint(x: rect.maxX - 18, y: rect.maxY - 39))
        accent.withAlphaComponent(0.34).setStroke(); headerLine.lineWidth = 1; headerLine.stroke()
        text("EXECUTION TRACE", at: NSPoint(x: rect.minX + 20, y: rect.maxY - 27), size: 10, color: accent, weight: .bold)
        let traceState = steps.isEmpty ? "STANDBY" : "VECTOR \(focus + 1) / \(steps.count)"
        text(intelligenceMaximum > 0 ? "SCROLL  //  \(traceState)" : "LIVE  //  \(traceState)", at: NSPoint(x: rect.maxX - 145, y: rect.maxY - 27), size: 7.5, color: NSColor.white.withAlphaComponent(0.48), weight: .medium)
        let latest = actions.last
        let latestResult = cleaned((latest?["result"]?.isEmpty == false) ? latest!["result"]! : (latest?["target"] ?? ""))
        var entries: [(String, String, NSColor)] = [
            ("ACTIVE VECTOR", (steps.isEmpty ? (label.isEmpty ? "Waiting for a task" : label) : steps[focus]) + (detail.isEmpty ? "" : "\n" + cleaned(detail)), accent),
            ("OBJECTIVE", goal.isEmpty ? "Maintain verified control of the active task." : cleaned(goal), .white.withAlphaComponent(0.70)),
            ("NEXT VECTOR", focus + 1 < steps.count ? steps[focus + 1] : "Deliver the verified result and surface any remaining limitation.", userColor),
        ]
        for (index, action) in actions.suffix(14).enumerated() {
            let status = action["status"] ?? "running"
            let color: NSColor = status == "complete" ? jarvisColor : status == "failed" ? .systemRed : accent
            let signal = status == "complete" ? "✓" : status == "failed" ? "×" : "▶"
            let duration = action["duration"] ?? ""
            let title = "\(signal) SIGNAL \(String(format: "%02d", index + 1))  //  \(action["label"] ?? "ACTION")" + (duration.isEmpty ? "" : "  //  \(duration)")
            let result = cleaned((action["result"]?.isEmpty == false) ? action["result"]! : (action["target"] ?? "Awaiting result"))
            entries.append((title, result, color))
        }
        if actions.isEmpty {
            entries.append(("SIGNAL STREAM", latestResult.isEmpty ? "Awaiting the first verified action." : latestResult, jarvisColor))
        }
        let viewport = NSRect(x: rect.minX + 14, y: rect.minY + 10, width: rect.width - 28, height: rect.height - 55)
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: viewport).addClip()
        var total: CGFloat = 0
        let prepared = entries.map { entry -> (String, String, NSColor, CGFloat) in
            let height = max(43, measured(entry.1, width: viewport.width - 62, size: 8.8) + 24)
            total += height + 9
            return (entry.0, entry.1, entry.2, height)
        }
        intelligenceMaximum = max(0, total - viewport.height)
        intelligenceOffset = min(intelligenceOffset, intelligenceMaximum)
        var y = viewport.maxY - total + intelligenceOffset
        let spineX = viewport.minX + 14
        let spine = NSBezierPath()
        spine.move(to: NSPoint(x: spineX, y: viewport.minY))
        spine.line(to: NSPoint(x: spineX, y: viewport.maxY))
        accent.withAlphaComponent(0.24).setStroke(); spine.lineWidth = 1.4; spine.stroke()
        for (index, entry) in prepared.enumerated() {
            let (title, value, color, height) = entry
            let row = NSRect(x: viewport.minX, y: y, width: viewport.width, height: height)
            if row.maxY >= viewport.minY && row.minY <= viewport.maxY {
                let nodeCenter = NSPoint(x: spineX, y: row.maxY - 15)
                if index == 0 {
                    for radius in [CGFloat(10), CGFloat(6)] {
                        let glow = NSBezierPath(ovalIn: NSRect(x: nodeCenter.x - radius, y: nodeCenter.y - radius, width: radius * 2, height: radius * 2))
                        color.withAlphaComponent(radius == 10 ? 0.10 : 0.20).setFill(); glow.fill()
                    }
                }
                let node = NSBezierPath(ovalIn: NSRect(x: nodeCenter.x - 3.5, y: nodeCenter.y - 3.5, width: 7, height: 7))
                color.setFill(); node.fill()
                let vector = NSBezierPath()
                vector.move(to: NSPoint(x: spineX + 7, y: nodeCenter.y))
                vector.line(to: NSPoint(x: spineX + 27, y: nodeCenter.y))
                color.withAlphaComponent(0.56).setStroke(); vector.lineWidth = 1.1; vector.stroke()
                text(title, at: NSPoint(x: spineX + 34, y: row.maxY - 19), size: 7.5, color: color, weight: .bold)
                block(value, in: NSRect(x: spineX + 34, y: row.minY + 6, width: row.width - 54, height: row.height - 27), size: 8.8, color: .white, weight: index == 0 ? .bold : .regular)
            }
            y += height + 9
        }
        NSGraphicsContext.restoreGraphicsState()
    }

    private func layoutRects() -> (rail: NSRect, chat: NSRect, path: NSRect) {
        let compact = bounds.width < 1800 || bounds.height < 1000
        let margin: CGFloat = compact ? 18 : 32
        let chatWidth = min(compact ? 610 : 900, bounds.width * (compact ? 0.43 : 0.46))
        let rail = NSRect(x: margin, y: bounds.maxY - margin - 78, width: chatWidth, height: 78)
        let chatHeight = min(compact ? 245 : 385, bounds.height * (compact ? 0.29 : 0.34))
        let chat = NSRect(x: margin, y: rail.minY - 10 - chatHeight, width: chatWidth, height: chatHeight)
        let pathWidth = min(compact ? 620 : 900, bounds.width * (compact ? 0.47 : 0.49))
        let pathHeight = min(compact ? 275 : 360, bounds.height * (compact ? 0.31 : 0.30))
        let path = NSRect(x: bounds.maxX - margin - pathWidth, y: margin, width: pathWidth, height: pathHeight)
        return (rail, chat, path)
    }

    private func composerRect(in chat: NSRect) -> NSRect {
        let height: CGFloat = bounds.width < 1800 || bounds.height < 1000 ? 58 : 68
        return NSRect(x: chat.minX + 10, y: chat.minY + 10, width: chat.width - 20, height: height)
    }

    func containsComposerPoint(_ point: NSPoint) -> Bool {
        composerRect(in: layoutRects().chat).contains(point)
    }

    func containsScrollablePoint(_ point: NSPoint) -> Bool {
        let rects = layoutRects()
        let conversationHistory = rects.chat.contains(point) && !composerRect(in: rects.chat).contains(point)
        return conversationHistory || rects.path.contains(point)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let a = accent
        NSColor.clear.setFill(); bounds.fill()

        // Sparse animated grid, corner locks, and scan line restore the original
        // full-display HUD character without placing an opaque window over work.
        let compact = bounds.width < 1800 || bounds.height < 1000
        let grid = NSBezierPath()
        let spacing: CGFloat = compact ? 54 : 72
        var gx = phase.truncatingRemainder(dividingBy: spacing)
        while gx < bounds.width { grid.move(to: NSPoint(x: gx, y: 0)); grid.line(to: NSPoint(x: gx, y: bounds.height)); gx += spacing }
        var gy = phase.truncatingRemainder(dividingBy: spacing)
        while gy < bounds.height { grid.move(to: NSPoint(x: 0, y: gy)); grid.line(to: NSPoint(x: bounds.width, y: gy)); gy += spacing }
        a.withAlphaComponent(0.035).setStroke(); grid.lineWidth = 0.6; grid.stroke()

        let corner = NSBezierPath()
        let m: CGFloat = compact ? 12 : 20, length: CGFloat = compact ? 54 : 86
        for (sx, sy) in [(CGFloat(1), CGFloat(1)), (-1, CGFloat(1)), (CGFloat(1), -1), (-1, -1)] {
            let x = sx > 0 ? m : bounds.maxX - m
            let y = sy > 0 ? m : bounds.maxY - m
            corner.move(to: NSPoint(x: x, y: y + sy * length)); corner.line(to: NSPoint(x: x, y: y)); corner.line(to: NSPoint(x: x + sx * length, y: y))
        }
        a.withAlphaComponent(0.88).setStroke(); corner.lineWidth = 2; corner.stroke()

        let core = NSPoint(x: bounds.width * (compact ? 0.71 : 0.64), y: bounds.height * 0.53)
        for index in 0..<4 {
            let radius = CGFloat((compact ? 35 : 58) + index * (compact ? 13 : 20)) + sin(phase * 2 + CGFloat(index)) * 4
            let ring = NSBezierPath()
            ring.appendArc(withCenter: core, radius: radius, startAngle: phase * 48 + CGFloat(index * 37), endAngle: phase * 48 + CGFloat(220 + index * 24))
            a.withAlphaComponent(0.66 - CGFloat(index) * 0.11).setStroke(); ring.lineWidth = 1.8; ring.stroke()
        }
        let coreDot = NSBezierPath(ovalIn: NSRect(x: core.x - 10, y: core.y - 10, width: 20, height: 20))
        a.withAlphaComponent(0.72 + 0.22 * sin(phase * 3)).setFill(); coreDot.fill()

        // Fast moving state rail and signal trace make transitions instantly visible.
        let rects = layoutRects()
        let rail = rects.rail
        rounded(rail, radius: 11, fill: NSColor.black.withAlphaComponent(backgroundLuminance > 0.58 ? 0.88 : 0.62), stroke: a.withAlphaComponent(0.88), width: 1.5)
        text("ORION // \(state.uppercased())", at: NSPoint(x: rail.minX + 14, y: rail.maxY - 23), size: 11, color: a, weight: .bold)
        block(label.uppercased(), in: NSRect(x: rail.minX + 14, y: rail.maxY - 45, width: rail.width - 48, height: 17), size: 9, color: .white, weight: .bold)
        if !detail.isEmpty {
            block(cleaned(detail), in: NSRect(x: rail.minX + 14, y: rail.minY + 9, width: rail.width - 28, height: 22), size: 8, color: NSColor.white.withAlphaComponent(0.68))
        }
        let pulseX = rail.maxX - 24 - CGFloat(Int(phase * 35) % max(1, Int(rail.width - 48)))
        let pulse = NSBezierPath(ovalIn: NSRect(x: pulseX, y: rail.midY - 3, width: 6, height: 6))
        a.setFill(); pulse.fill()

        drawConversation(rects.chat)
        drawPath(rects.path)

        let scanY = bounds.height * (0.18 + 0.64 * ((sin(phase * 0.42) + 1) / 2))
        let scan = NSBezierPath(); scan.move(to: NSPoint(x: 20, y: scanY)); scan.line(to: NSPoint(x: bounds.maxX - 20, y: scanY))
        a.withAlphaComponent(0.13).setStroke(); scan.lineWidth = 1; scan.stroke()
    }
}

final class JarvisTaskCapsuleView: NSView {
    var title = "BACKGROUND TASK"
    var phaseLabel = "Working"
    var detail = ""
    var status = "running"
    var step = 1
    var totalSteps = 4
    var started = Date().timeIntervalSince1970
    var route = ""
    private var phase: CGFloat = 0
    private var timer: Timer?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private var accent: NSColor {
        if status == "completed" { return NSColor(calibratedRed: 0.15, green: 1.0, blue: 0.55, alpha: 1) }
        if status == "failed" { return .systemRed }
        return NSColor(calibratedRed: 0.10, green: 0.78, blue: 1.0, alpha: 1)
    }

    @objc private func animate() {
        phase += 0.055
        needsDisplay = true
    }

    func setAnimating(_ enabled: Bool) {
        if enabled, timer == nil {
            timer = Timer.scheduledTimer(timeInterval: 1.0 / 24.0, target: self, selector: #selector(animate), userInfo: nil, repeats: true)
        } else if !enabled {
            timer?.invalidate()
            timer = nil
        }
    }

    private func font(_ size: CGFloat, _ weight: NSFont.Weight = .regular) -> NSFont {
        NSFont.monospacedSystemFont(ofSize: size, weight: weight)
    }

    private func drawText(_ value: String, at point: NSPoint, size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) {
        NSString(string: value).draw(at: point, withAttributes: [.font: font(size, weight), .foregroundColor: color])
    }

    private func shortened(_ value: String, limit: Int) -> String {
        value.count <= limit ? value : String(value.prefix(max(1, limit - 1))) + "…"
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let a = accent
        let body = bounds.insetBy(dx: 2, dy: 2)
        let shell = NSBezierPath(roundedRect: body, xRadius: 16, yRadius: 16)
        NSColor(calibratedWhite: 0.025, alpha: 0.94).setFill(); shell.fill()
        a.withAlphaComponent(0.82).setStroke(); shell.lineWidth = 1.4; shell.stroke()

        let scanX = body.minX + ((sin(phase) + 1) / 2) * body.width
        let scan = NSBezierPath()
        scan.move(to: NSPoint(x: scanX, y: body.minY + 7))
        scan.line(to: NSPoint(x: scanX, y: body.maxY - 7))
        a.withAlphaComponent(0.08).setStroke(); scan.lineWidth = 12; scan.stroke()

        let compact = bounds.width < 380
        let core = NSPoint(x: compact ? 36 : 42, y: bounds.midY)
        for index in 0..<3 {
            let radius = CGFloat(9 + index * 6)
            let ring = NSBezierPath()
            ring.appendArc(withCenter: core, radius: radius, startAngle: phase * 90 + CGFloat(index * 37), endAngle: phase * 90 + CGFloat(index * 37 + 205))
            a.withAlphaComponent(0.75 - CGFloat(index) * 0.18).setStroke()
            ring.lineWidth = index == 0 ? 1.8 : 1.0
            ring.stroke()
        }
        let dotRadius: CGFloat = status == "running" ? 3.5 + sin(phase * 2) : 4
        let dot = NSBezierPath(ovalIn: NSRect(x: core.x - dotRadius, y: core.y - dotRadius, width: dotRadius * 2, height: dotRadius * 2))
        a.setFill(); dot.fill()

        let left = compact ? 68.0 : 78.0
        let elapsed = max(0, Int(Date().timeIntervalSince1970 - started))
        let elapsedText = String(format: "%02d:%02d", elapsed / 60, elapsed % 60)
        drawText("ORION // BACKGROUND", at: NSPoint(x: left, y: bounds.maxY - 23), size: compact ? 8 : 9, color: a, weight: .bold)
        drawText(elapsedText, at: NSPoint(x: bounds.maxX - (compact ? 49 : 57), y: bounds.maxY - 23), size: compact ? 8 : 9, color: .white.withAlphaComponent(0.58), weight: .medium)
        drawText(shortened(title, limit: compact ? 29 : 38), at: NSPoint(x: left, y: bounds.maxY - (compact ? 43 : 47)), size: compact ? 11 : 12.5, color: .white, weight: .bold)
        let phaseText = status == "completed" ? "✓ \(phaseLabel)" : status == "failed" ? "! \(phaseLabel)" : "› \(phaseLabel)"
        drawText(shortened(phaseText, limit: compact ? 47 : 62), at: NSPoint(x: left, y: bounds.maxY - (compact ? 59 : 67)), size: compact ? 8.2 : 9.3, color: a, weight: .medium)
        if !detail.isEmpty {
            drawText(shortened(detail, limit: compact ? 50 : 70), at: NSPoint(x: left, y: bounds.maxY - (compact ? 75 : 85)), size: compact ? 7.2 : 8.0, color: .white.withAlphaComponent(0.62))
        }

        let segments = max(1, totalSteps)
        let barX = left
        let barY: CGFloat = compact ? 12 : 14
        let gap: CGFloat = 4
        let barWidth = bounds.maxX - barX - 15
        let width = (barWidth - CGFloat(segments - 1) * gap) / CGFloat(segments)
        for index in 0..<segments {
            let rect = NSRect(x: barX + CGFloat(index) * (width + gap), y: barY, width: width, height: compact ? 3 : 4)
            let path = NSBezierPath(roundedRect: rect, xRadius: 2, yRadius: 2)
            let active = index < step
            (active ? a.withAlphaComponent(index == step - 1 && status == "running" ? 0.55 + 0.35 * abs(sin(phase)) : 0.85) : NSColor.white.withAlphaComponent(0.12)).setFill()
            path.fill()
        }
    }
}
