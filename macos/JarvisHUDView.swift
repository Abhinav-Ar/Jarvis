import AppKit

final class JarvisHUDView: NSView {
    var state = "planning"
    var label = "Planning…"
    var detail = ""
    var goal = ""
    var steps: [String] = []
    var messages: [[String: String]] = []
    var actions: [[String: String]] = []
    var eventCount = 0
    private var phase: CGFloat = 0
    private var animationTimer: Timer?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        animationTimer = Timer.scheduledTimer(timeInterval: 1.0 / 24.0, target: self, selector: #selector(animate), userInfo: nil, repeats: true)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    @objc private func animate() {
        phase += 0.035
        needsDisplay = true
    }

    private var accent: NSColor {
        let colors: [String: NSColor] = [
            "session": .systemCyan, "speaking": .systemGreen,
            "transcribing": .systemYellow, "planning": .systemCyan,
            "working": .systemPurple, "verifying": .systemBlue,
            "needs_input": .systemOrange, "error": .systemRed,
        ]
        return colors[state] ?? .systemCyan
    }

    private func text(_ value: String, at point: NSPoint, size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) {
        value.draw(at: point, withAttributes: [
            .font: NSFont.monospacedSystemFont(ofSize: size, weight: weight),
            .foregroundColor: color,
        ])
    }

    private func textBlock(_ value: String, in rect: NSRect, size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byWordWrapping
        paragraph.maximumLineHeight = size + 5
        NSString(string: value).draw(in: rect, withAttributes: [
            .font: NSFont.monospacedSystemFont(ofSize: size, weight: weight),
            .foregroundColor: color,
            .paragraphStyle: paragraph,
        ])
    }

    private func cleanGoal(_ value: String) -> String {
        if let range = value.range(of: "User:", options: [.caseInsensitive, .backwards]) {
            return String(value[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return value.replacingOccurrences(of: "\n", with: " ")
    }

    private func cleanMessage(_ value: String) -> String {
        value.replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "`", with: "")
            .replacingOccurrences(of: "\n", with: " ")
    }

    private func messagePage(_ value: String, width: CGFloat, height: CGFloat, fontSize: CGFloat) -> (String, Int, Int) {
        let clean = cleanMessage(value)
        let columns = max(18, Int(width / (fontSize * 0.62)))
        let rows = max(2, Int(height / (fontSize + 5)))
        let capacity = max(40, columns * rows)
        let characters = Array(clean)
        let pageCount = max(1, Int(ceil(Double(characters.count) / Double(capacity))))
        let page = pageCount == 1 ? 0 : Int(phase / 4.0) % pageCount
        let start = min(characters.count, page * capacity)
        let end = min(characters.count, start + capacity)
        return (String(characters[start..<end]), page + 1, pageCount)
    }

    private func rounded(_ rect: NSRect, radius: CGFloat, fill: NSColor, stroke: NSColor) {
        let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
        fill.setFill(); path.fill()
        stroke.setStroke(); path.lineWidth = 1; path.stroke()
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let a = accent
        let compact = bounds.width < 1800 || bounds.height < 1000
        let margin: CGFloat = compact ? 22 : 56
        NSColor.black.withAlphaComponent(0.14).setFill()
        bounds.fill()

        // Scanning grid across the entire desktop.
        let grid = NSBezierPath()
        let spacing: CGFloat = 48
        var x: CGFloat = phase.truncatingRemainder(dividingBy: spacing)
        while x < bounds.width { grid.move(to: NSPoint(x: x, y: 0)); grid.line(to: NSPoint(x: x, y: bounds.height)); x += spacing }
        var y: CGFloat = phase.truncatingRemainder(dividingBy: spacing)
        while y < bounds.height { grid.move(to: NSPoint(x: 0, y: y)); grid.line(to: NSPoint(x: bounds.width, y: y)); y += spacing }
        a.withAlphaComponent(0.08).setStroke(); grid.lineWidth = 0.7; grid.stroke()

        // Futuristic corner brackets.
        let corner = NSBezierPath()
        let m: CGFloat = compact ? 18 : 28, l: CGFloat = compact ? 48 : 80
        corner.move(to: NSPoint(x: m, y: bounds.height - m - l)); corner.line(to: NSPoint(x: m, y: bounds.height - m)); corner.line(to: NSPoint(x: m + l, y: bounds.height - m))
        corner.move(to: NSPoint(x: bounds.width - m - l, y: bounds.height - m)); corner.line(to: NSPoint(x: bounds.width - m, y: bounds.height - m)); corner.line(to: NSPoint(x: bounds.width - m, y: bounds.height - m - l))
        corner.move(to: NSPoint(x: m, y: m + l)); corner.line(to: NSPoint(x: m, y: m)); corner.line(to: NSPoint(x: m + l, y: m))
        corner.move(to: NSPoint(x: bounds.width - m - l, y: m)); corner.line(to: NSPoint(x: bounds.width - m, y: m)); corner.line(to: NSPoint(x: bounds.width - m, y: m + l))
        a.withAlphaComponent(0.8).setStroke(); corner.lineWidth = 2; corner.stroke()

        // Central command core.
        let core = NSPoint(x: bounds.width * (compact ? 0.74 : 0.61), y: bounds.height * (compact ? 0.43 : 0.48))
        for index in 0..<3 {
            let radius = CGFloat((compact ? 48 : 72) + index * (compact ? 15 : 22)) + sin(phase * 2 + CGFloat(index)) * 4
            let ring = NSBezierPath()
            ring.appendArc(withCenter: core, radius: radius, startAngle: phase * 45 + CGFloat(index * 40), endAngle: phase * 45 + CGFloat(230 + index * 25))
            a.withAlphaComponent(0.65 - CGFloat(index) * 0.13).setStroke(); ring.lineWidth = 2; ring.stroke()
        }
        let pulse = NSBezierPath(ovalIn: NSRect(x: core.x - 18, y: core.y - 18, width: 36, height: 36))
        a.withAlphaComponent(0.55 + 0.25 * sin(phase * 3)).setFill(); pulse.fill()

        // Orbiting telemetry particles.
        for index in 0..<28 {
            let angle = phase * (0.35 + CGFloat(index % 4) * 0.08) + CGFloat(index) * 0.61
            let radius = CGFloat((compact ? 82 : 125) + (index % 7) * (compact ? 11 : 18))
            let point = NSPoint(x: core.x + cos(angle) * radius, y: core.y + sin(angle) * radius * 0.58)
            let dot = NSBezierPath(ovalIn: NSRect(x: point.x - 1.5, y: point.y - 1.5, width: 3, height: 3))
            a.withAlphaComponent(0.22 + CGFloat(index % 4) * 0.12).setFill(); dot.fill()
        }

        // Responsive, paged live conversation panel.
        let chatWidth = compact ? min(bounds.width * 0.70, 980) : min(940, bounds.width * 0.48)
        let chatHeight = compact ? min(255, bounds.height * 0.31) : min(430, bounds.height * 0.46)
        let chatPanel = NSRect(x: margin, y: bounds.height - chatHeight - margin, width: chatWidth, height: chatHeight)
        rounded(chatPanel, radius: 16, fill: NSColor.black.withAlphaComponent(0.76), stroke: a.withAlphaComponent(0.8))
        text("JARVIS // LIVE CONVERSATION", at: NSPoint(x: chatPanel.minX + 22, y: chatPanel.maxY - 31), size: 12, color: a, weight: .bold)
        text(label.uppercased(), at: NSPoint(x: chatPanel.maxX - 145, y: chatPanel.maxY - 31), size: 11, color: a, weight: .bold)
        let visibleMessages = Array(messages.suffix(compact ? 2 : 4))
        let previous = Array(visibleMessages.dropLast().suffix(compact ? 1 : 3))
        var cursorY = chatPanel.maxY - 58
        for message in previous {
            let role = message["role"] ?? "assistant"
            let isUser = role == "user"
            let bubbleX = isUser ? chatPanel.minX + 105 : chatPanel.minX + 20
            let bubbleWidth = chatPanel.width - 125
            let bubble = NSRect(x: bubbleX, y: cursorY - 38, width: bubbleWidth, height: 34)
            rounded(bubble, radius: 10, fill: (isUser ? NSColor.systemBlue : a).withAlphaComponent(0.18), stroke: (isUser ? NSColor.systemBlue : a).withAlphaComponent(0.48))
            text(isUser ? "YOU" : "JARVIS", at: NSPoint(x: isUser ? chatPanel.minX + 60 : chatPanel.maxX - 79, y: bubble.minY + 11), size: 8, color: isUser ? .systemBlue : a, weight: .bold)
            let snippet = cleanMessage(message["text"] ?? "")
            textBlock(String(snippet.prefix(max(60, Int(bubbleWidth / 6)))), in: NSRect(x: bubble.minX + 10, y: bubble.minY + 7, width: bubble.width - 20, height: 20), size: 10, color: NSColor.white.withAlphaComponent(0.72))
            cursorY -= 42
        }
        if let latest = visibleMessages.last {
            let role = latest["role"] ?? "assistant"
            let isUser = role == "user"
            let bubble = NSRect(x: chatPanel.minX + 20, y: chatPanel.minY + 18, width: chatPanel.width - 40, height: max(80, cursorY - chatPanel.minY - 24))
            rounded(bubble, radius: 12, fill: (isUser ? NSColor.systemBlue : a).withAlphaComponent(0.22), stroke: (isUser ? NSColor.systemBlue : a).withAlphaComponent(0.75))
            text(isUser ? "YOU // LATEST" : "JARVIS // LATEST", at: NSPoint(x: bubble.minX + 13, y: bubble.maxY - 24), size: 9, color: isUser ? .systemBlue : a, weight: .bold)
            let textRect = NSRect(x: bubble.minX + 13, y: bubble.minY + 12, width: bubble.width - 26, height: bubble.height - 43)
            let page = messagePage(latest["text"] ?? "", width: textRect.width, height: textRect.height, fontSize: compact ? 10 : 12)
            textBlock(page.0, in: textRect, size: compact ? 10 : 12, color: .white)
            if page.2 > 1 {
                text("AUTO-SCROLL  (page.1)/(page.2)", at: NSPoint(x: bubble.maxX - 125, y: bubble.maxY - 24), size: 8, color: a, weight: .bold)
            }
        } else {
            let waiting = cleanGoal(goal.isEmpty ? "Say what you need. I’m listening." : goal)
            textBlock(waiting, in: NSRect(x: chatPanel.minX + 24, y: chatPanel.midY - 40, width: chatPanel.width - 48, height: 80), size: 14, color: NSColor.white.withAlphaComponent(0.75), weight: .medium)
        }

        // Detailed action telemetry, responsive to each display size.
        let consoleWidth = compact ? bounds.width * 0.43 : min(540, bounds.width * 0.30)
        let consoleHeight = compact ? min(185, bounds.height * 0.22) : min(390, bounds.height * 0.40)
        let console = NSRect(x: margin, y: margin + 22, width: consoleWidth, height: consoleHeight)
        rounded(console, radius: 14, fill: NSColor.black.withAlphaComponent(0.76), stroke: a.withAlphaComponent(0.65))
        text("ACTION TELEMETRY // \(actions.count) EVENTS", at: NSPoint(x: console.minX + 18, y: console.maxY - 28), size: 10, color: a, weight: .bold)
        let actionRows = Array(actions.suffix(compact ? 3 : 6))
        for (index, action) in actionRows.enumerated() {
            let rowHeight: CGFloat = compact ? 39 : 49
            let row = NSRect(x: console.minX + 14, y: console.maxY - 50 - CGFloat(index + 1) * rowHeight, width: console.width - 28, height: rowHeight - 6)
            let status = action["status"] ?? "running"
            let color: NSColor = status == "complete" ? .systemGreen : status == "failed" ? .systemRed : a
            rounded(row, radius: 7, fill: color.withAlphaComponent(status == "running" ? 0.24 : 0.10), stroke: color.withAlphaComponent(0.65))
            text(status == "complete" ? "✓" : status == "failed" ? "×" : "▶", at: NSPoint(x: row.minX + 9, y: row.midY - 6), size: 13, color: color, weight: .bold)
            textBlock(action["label"] ?? "ACTION", in: NSRect(x: row.minX + 30, y: row.midY - 1, width: row.width * 0.42, height: 17), size: 9, color: .white, weight: .bold)
            textBlock(action["target"] ?? "", in: NSRect(x: row.minX + row.width * 0.47, y: row.midY - 1, width: row.width * 0.50, height: 17), size: 9, color: NSColor.white.withAlphaComponent(0.68))
        }
        if actionRows.isEmpty {
            text("STANDING BY FOR AUTHORIZED ACTIONS", at: NSPoint(x: console.minX + 20, y: console.midY), size: 10, color: NSColor.white.withAlphaComponent(0.50))
        }

        // Dependency/step stack on the right.
        let stackWidth = compact ? bounds.width - console.maxX - margin * 2 : min(470, bounds.width * 0.27)
        let stackX = bounds.width - stackWidth - margin
        let stackTop = console.maxY - 8
        text("EXECUTION PATH", at: NSPoint(x: stackX, y: stackTop), size: 10, color: a, weight: .bold)
        for (index, step) in steps.prefix(compact ? 4 : 6).enumerated() {
            let rect = NSRect(x: stackX, y: stackTop - 43 - CGFloat(index * 40), width: stackWidth, height: 31)
            let active = index == min(eventCount, max(0, steps.count - 1))
            rounded(rect, radius: 8, fill: (active ? a : NSColor.black).withAlphaComponent(active ? 0.28 : 0.65), stroke: a.withAlphaComponent(active ? 0.9 : 0.28))
            textBlock("\(index < eventCount ? "✓" : active ? "▶" : "○")  \(step)", in: NSRect(x: rect.minX + 10, y: rect.minY + 8, width: rect.width - 20, height: 17), size: 9, color: active ? .white : NSColor.white.withAlphaComponent(0.65))
        }

        // Exaggerated active-action beacon.
        if let activeAction = actions.last, activeAction["status"] == "running" {
            let bannerWidth = min(compact ? 390 : 700, bounds.width * 0.46)
            let banner = NSRect(x: core.x - bannerWidth / 2, y: core.y - 110, width: bannerWidth, height: 58)
            for ring in 0..<3 {
                let expansion = CGFloat(ring * 9) + 4 * sin(phase * 3 + CGFloat(ring))
                let glow = NSBezierPath(roundedRect: banner.insetBy(dx: -expansion, dy: -expansion * 0.5), xRadius: 12, yRadius: 12)
                a.withAlphaComponent(0.28 - CGFloat(ring) * 0.07).setStroke(); glow.lineWidth = 2; glow.stroke()
            }
            rounded(banner, radius: 10, fill: NSColor.black.withAlphaComponent(0.86), stroke: a)
            text("EXECUTING NOW", at: NSPoint(x: banner.minX + 18, y: banner.maxY - 23), size: 9, color: a, weight: .bold)
            textBlock("\(activeAction["label"] ?? "ACTION")  //  \(activeAction["target"] ?? "")", in: NSRect(x: banner.minX + 18, y: banner.minY + 10, width: banner.width - 36, height: 20), size: 11, color: .white, weight: .bold)
        }

        // Moving scan line.
        let scanY = bounds.height * (0.15 + 0.7 * ((sin(phase * 0.45) + 1) / 2))
        let scan = NSBezierPath(); scan.move(to: NSPoint(x: 30, y: scanY)); scan.line(to: NSPoint(x: bounds.width - 30, y: scanY))
        a.withAlphaComponent(0.18).setStroke(); scan.lineWidth = 1; scan.stroke()

        // Animated signal waveform.
        let wave = NSBezierPath()
        let waveStart = bounds.width * 0.40
        let waveEnd = bounds.width - 70
        var wx = waveStart
        while wx <= waveEnd {
            let amplitude = 8 + 7 * sin(phase * 1.3)
            let wy = 48 + sin((wx - waveStart) * 0.045 + phase * 5) * amplitude * sin((wx - waveStart) * 0.012)
            if wx == waveStart { wave.move(to: NSPoint(x: wx, y: wy)) } else { wave.line(to: NSPoint(x: wx, y: wy)) }
            wx += 4
        }
        a.withAlphaComponent(0.55).setStroke(); wave.lineWidth = 1.4; wave.stroke()
    }
}
