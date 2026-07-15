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
    var actions: [[String: String]] = [] { didSet { if actions.count != oldValue.count { actionOffset = 0 } } }
    var eventCount = 0
    var backgroundLuminance: CGFloat = 0.25
    private var phase: CGFloat = 0
    private var chatOffset: CGFloat = 0
    private var actionOffset: CGFloat = 0
    private var chatMaximum: CGFloat = 0
    private var actionMaximum: CGFloat = 0
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
        if location.y > bounds.height * 0.43 {
            chatOffset = min(chatMaximum, max(0, chatOffset + amount))
        } else {
            actionOffset = min(actionMaximum, max(0, actionOffset + amount))
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
        section(rect, title: "LIVE COMMAND CHANNEL", badge: messages.count > 1 ? "SCROLL" : "LIVE")
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

    private func drawActions(_ rect: NSRect) {
        section(rect, title: "EXECUTION TELEMETRY", badge: "\(actions.count) EVENTS")
        let viewport = NSRect(x: rect.minX + 10, y: rect.minY + 10, width: rect.width - 20, height: rect.height - 49)
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: viewport).addClip()
        let rowHeight: CGFloat = 58
        actionMaximum = max(0, CGFloat(actions.count) * (rowHeight + 7) - viewport.height)
        actionOffset = min(actionOffset, actionMaximum)
        var y = viewport.maxY - CGFloat(actions.count) * (rowHeight + 7) + actionOffset
        for action in actions {
            let status = action["status"] ?? "running"
            let color: NSColor = status == "complete" ? jarvisColor : status == "failed" ? .systemRed : accent
            let row = NSRect(x: viewport.minX, y: y, width: viewport.width, height: rowHeight)
            if row.maxY >= viewport.minY && row.minY <= viewport.maxY {
                rounded(row, radius: 9, fill: color.withAlphaComponent(status == "running" ? 0.20 : 0.09), stroke: color.withAlphaComponent(0.62))
                text(status == "complete" ? "✓" : status == "failed" ? "×" : "▶", at: NSPoint(x: row.minX + 11, y: row.maxY - 25), size: 14, color: color, weight: .bold)
                block(action["label"] ?? "ACTION", in: NSRect(x: row.minX + 34, y: row.maxY - 27, width: row.width - 46, height: 18), size: 10, color: .white, weight: .bold)
                let result = (action["result"]?.isEmpty == false) ? action["result"]! : (action["target"] ?? "")
                block(result, in: NSRect(x: row.minX + 34, y: row.minY + 9, width: row.width - 46, height: 19), size: 9, color: NSColor.white.withAlphaComponent(0.68))
            }
            y += rowHeight + 7
        }
        if actions.isEmpty { text("WAITING FOR AUTHORIZED ACTIONS", at: NSPoint(x: viewport.minX + 8, y: viewport.midY), size: 9, color: NSColor.white.withAlphaComponent(0.48)) }
        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawPath(_ rect: NSRect) {
        section(rect, title: "EXECUTION PATH", badge: steps.isEmpty ? "READY" : "\(min(eventCount, steps.count))/\(steps.count)")
        let visible = Array(steps.suffix(4))
        var y = rect.maxY - 53
        for (index, step) in visible.enumerated() {
            let originalIndex = max(0, steps.count - visible.count) + index
            let done = originalIndex < eventCount
            let active = originalIndex == min(eventCount, max(0, steps.count - 1))
            let color = done ? jarvisColor : active ? accent : NSColor.white.withAlphaComponent(0.34)
            let marker = done ? "✓" : active ? "▶" : "○"
            text(marker, at: NSPoint(x: rect.minX + 16, y: y), size: 10, color: color, weight: .bold)
            block(step, in: NSRect(x: rect.minX + 36, y: y - 2, width: rect.width - 50, height: 26), size: 9, color: active ? .white : NSColor.white.withAlphaComponent(0.65), weight: active ? .bold : .regular)
            y -= 31
        }
        if steps.isEmpty { text("NO ACTIVE DEPENDENCIES", at: NSPoint(x: rect.minX + 16, y: rect.midY), size: 9, color: NSColor.white.withAlphaComponent(0.42)) }
    }

    private func layoutRects() -> (rail: NSRect, chat: NSRect, actions: NSRect, path: NSRect) {
        let compact = bounds.width < 1800 || bounds.height < 1000
        let margin: CGFloat = compact ? 18 : 32
        let chatWidth = min(compact ? 610 : 900, bounds.width * (compact ? 0.43 : 0.46))
        let rail = NSRect(x: margin, y: bounds.maxY - margin - 48, width: chatWidth, height: 48)
        let chatHeight = min(compact ? 245 : 385, bounds.height * (compact ? 0.29 : 0.34))
        let chat = NSRect(x: margin, y: rail.minY - 10 - chatHeight, width: chatWidth, height: chatHeight)
        let actionWidth = min(compact ? 475 : 650, bounds.width * 0.36)
        let actionHeight = min(compact ? 178 : 280, bounds.height * 0.25)
        let actionsRect = NSRect(x: margin, y: margin, width: actionWidth, height: actionHeight)
        let pathWidth = min(compact ? 500 : 700, bounds.width * 0.37)
        let pathHeight = min(compact ? 155 : 235, bounds.height * 0.21)
        let path = NSRect(x: bounds.maxX - margin - pathWidth, y: margin, width: pathWidth, height: pathHeight)
        return (rail, chat, actionsRect, path)
    }

    private func composerRect(in chat: NSRect) -> NSRect {
        let height: CGFloat = bounds.width < 1800 || bounds.height < 1000 ? 58 : 68
        return NSRect(x: chat.minX + 10, y: chat.minY + 10, width: chat.width - 20, height: height)
    }

    func containsComposerPoint(_ point: NSPoint) -> Bool {
        composerRect(in: layoutRects().chat).contains(point)
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
        text(label.uppercased(), at: NSPoint(x: rail.minX + 14, y: rail.minY + 8), size: 9, color: .white, weight: .bold)
        let pulseX = rail.maxX - 24 - CGFloat(Int(phase * 35) % max(1, Int(rail.width - 48)))
        let pulse = NSBezierPath(ovalIn: NSRect(x: pulseX, y: rail.midY - 3, width: 6, height: 6))
        a.setFill(); pulse.fill()

        drawConversation(rects.chat)
        drawActions(rects.actions)
        drawPath(rects.path)

        if !detail.isEmpty {
            let detailRect = NSRect(x: 18, y: rail.midY - 7, width: rail.width - 145, height: 15)
            block(detail, in: detailRect, size: 8, color: NSColor.white.withAlphaComponent(0.62))
        }

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
