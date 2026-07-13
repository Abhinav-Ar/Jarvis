import AppKit

final class JarvisHUDView: NSView {
    var state = "planning"
    var label = "Planning…"
    var detail = ""
    var goal = ""
    var steps: [String] = []
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

    private func rounded(_ rect: NSRect, radius: CGFloat, fill: NSColor, stroke: NSColor) {
        let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
        fill.setFill(); path.fill()
        stroke.setStroke(); path.lineWidth = 1; path.stroke()
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let a = accent
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
        let m: CGFloat = 28, l: CGFloat = 80
        corner.move(to: NSPoint(x: m, y: bounds.height - m - l)); corner.line(to: NSPoint(x: m, y: bounds.height - m)); corner.line(to: NSPoint(x: m + l, y: bounds.height - m))
        corner.move(to: NSPoint(x: bounds.width - m - l, y: bounds.height - m)); corner.line(to: NSPoint(x: bounds.width - m, y: bounds.height - m)); corner.line(to: NSPoint(x: bounds.width - m, y: bounds.height - m - l))
        corner.move(to: NSPoint(x: m, y: m + l)); corner.line(to: NSPoint(x: m, y: m)); corner.line(to: NSPoint(x: m + l, y: m))
        corner.move(to: NSPoint(x: bounds.width - m - l, y: m)); corner.line(to: NSPoint(x: bounds.width - m, y: m)); corner.line(to: NSPoint(x: bounds.width - m, y: m + l))
        a.withAlphaComponent(0.8).setStroke(); corner.lineWidth = 2; corner.stroke()

        // Central command core.
        let core = NSPoint(x: bounds.midX, y: bounds.midY + 70)
        for index in 0..<3 {
            let radius = CGFloat(72 + index * 22) + sin(phase * 2 + CGFloat(index)) * 4
            let ring = NSBezierPath()
            ring.appendArc(withCenter: core, radius: radius, startAngle: phase * 45 + CGFloat(index * 40), endAngle: phase * 45 + CGFloat(230 + index * 25))
            a.withAlphaComponent(0.65 - CGFloat(index) * 0.13).setStroke(); ring.lineWidth = 2; ring.stroke()
        }
        let pulse = NSBezierPath(ovalIn: NSRect(x: core.x - 18, y: core.y - 18, width: 36, height: 36))
        a.withAlphaComponent(0.55 + 0.25 * sin(phase * 3)).setFill(); pulse.fill()

        // Command header.
        let header = NSRect(x: 56, y: bounds.height - 154, width: bounds.width - 112, height: 96)
        rounded(header, radius: 12, fill: NSColor.black.withAlphaComponent(0.72), stroke: a.withAlphaComponent(0.8))
        text("JARVIS // ACTIVE TASK", at: NSPoint(x: header.minX + 24, y: header.maxY - 29), size: 12, color: a, weight: .bold)
        let shownGoal = cleanGoal(goal.isEmpty ? detail : goal)
        textBlock(String(shownGoal.prefix(180)), in: NSRect(x: header.minX + 24, y: header.minY + 13, width: header.width - 48, height: 43), size: 15, color: .white, weight: .medium)

        // Live action console.
        let console = NSRect(x: 56, y: 70, width: min(460, bounds.width * 0.34), height: 220)
        rounded(console, radius: 14, fill: NSColor.black.withAlphaComponent(0.76), stroke: a.withAlphaComponent(0.65))
        text("COMMAND STREAM", at: NSPoint(x: console.minX + 22, y: console.maxY - 34), size: 11, color: a, weight: .bold)
        text("● \(label.uppercased())", at: NSPoint(x: console.minX + 22, y: console.maxY - 67), size: 17, color: .white, weight: .bold)
        text(String(detail.prefix(64)), at: NSPoint(x: console.minX + 22, y: console.maxY - 98), size: 12, color: NSColor.white.withAlphaComponent(0.72))
        text("ACTIONS EXECUTED  \(eventCount)", at: NSPoint(x: console.minX + 22, y: console.minY + 25), size: 11, color: a)

        // Dependency/step stack on the right.
        let stackWidth = min(430, bounds.width * 0.32)
        let stackX = bounds.width - stackWidth - 56
        text("EXECUTION PATH", at: NSPoint(x: stackX, y: 276), size: 11, color: a, weight: .bold)
        for (index, step) in steps.prefix(5).enumerated() {
            let rect = NSRect(x: stackX, y: 222 - CGFloat(index * 42), width: stackWidth, height: 32)
            let active = index == min(eventCount, max(0, steps.count - 1))
            rounded(rect, radius: 8, fill: (active ? a : NSColor.black).withAlphaComponent(active ? 0.28 : 0.65), stroke: a.withAlphaComponent(active ? 0.9 : 0.28))
            text("\(index < eventCount ? "✓" : active ? "▶" : "○")  \(String(step.prefix(48)))", at: NSPoint(x: rect.minX + 12, y: rect.minY + 9), size: 11, color: active ? .white : NSColor.white.withAlphaComponent(0.65))
        }

        // Moving scan line.
        let scanY = bounds.height * (0.15 + 0.7 * ((sin(phase * 0.45) + 1) / 2))
        let scan = NSBezierPath(); scan.move(to: NSPoint(x: 30, y: scanY)); scan.line(to: NSPoint(x: bounds.width - 30, y: scanY))
        a.withAlphaComponent(0.18).setStroke(); scan.lineWidth = 1; scan.stroke()
    }
}
