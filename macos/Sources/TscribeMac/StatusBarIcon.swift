import AppKit

/// A transcript page behind the microphone keeps tscribe distinct from macOS's mic indicator.
enum StatusBarIcon {
    static func image(isRecording: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 20, height: 18), flipped: false) { _ in
            NSColor.black.setStroke()
            let page = NSBezierPath()
            page.lineWidth = 1.5
            page.lineCapStyle = .round
            page.lineJoinStyle = .round
            page.move(to: NSPoint(x: 8, y: 1))
            page.line(to: NSPoint(x: 2.5, y: 1))
            page.curve(to: NSPoint(x: 1, y: 2.5), controlPoint1: NSPoint(x: 1.5, y: 1), controlPoint2: NSPoint(x: 1, y: 1.5))
            page.line(to: NSPoint(x: 1, y: 15.5))
            page.curve(to: NSPoint(x: 2.5, y: 17), controlPoint1: NSPoint(x: 1, y: 16.5), controlPoint2: NSPoint(x: 1.5, y: 17))
            page.line(to: NSPoint(x: 10, y: 17))
            page.line(to: NSPoint(x: 13, y: 14))
            page.line(to: NSPoint(x: 10, y: 14))
            page.line(to: NSPoint(x: 10, y: 17))
            page.stroke()

            let lines = NSBezierPath()
            lines.lineWidth = 1.25
            lines.lineCapStyle = .round
            for y in [11.5, 8.5, 5.5] {
                lines.move(to: NSPoint(x: 4, y: y))
                lines.line(to: NSPoint(x: 7.5, y: y))
            }
            lines.stroke()

            let symbol = isRecording ? "record.circle.fill" : "mic.fill"
            let foreground = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
            let frame = isRecording ? NSRect(x: 9, y: 1, width: 11, height: 11) : NSRect(x: 10, y: 0.5, width: 10, height: 13)
            foreground?.draw(in: frame)
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = isRecording ? "tscribe recording" : "tscribe"
        return image
    }
}
