// Renders macos/Resources/AppIcon.icns: a terminal glyph on a rounded tile.
//   swift scripts/render-icon.swift <output.icns>
import AppKit

let output = CommandLine.arguments[1]
let iconset = URL(fileURLWithPath: NSTemporaryDirectory()).appending(path: "AppIcon.iconset")
try? FileManager.default.removeItem(at: iconset)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func render(_ pixels: Int) -> Data {
    let size = CGFloat(pixels)
    let representation = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
                                          samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                          colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: representation)
    let inset = size * 0.1
    let tile = NSRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset)
    let path = NSBezierPath(roundedRect: tile, xRadius: tile.width * 0.225, yRadius: tile.width * 0.225)
    NSGradient(colors: [NSColor(red: 0.95, green: 0.42, blue: 0.16, alpha: 1), NSColor(red: 0.62, green: 0.13, blue: 0.36, alpha: 1)])!
        .draw(in: path, angle: -90)
    let screen = tile.insetBy(dx: tile.width * 0.16, dy: tile.height * 0.22)
    NSColor(white: 0.08, alpha: 0.85).setFill()
    NSBezierPath(roundedRect: screen, xRadius: screen.width * 0.08, yRadius: screen.width * 0.08).fill()
    let configuration = NSImage.SymbolConfiguration(pointSize: screen.height * 0.5, weight: .bold)
    if let glyph = NSImage(systemSymbolName: "chevron.right", accessibilityDescription: nil)?.withSymbolConfiguration(configuration) {
        let tinted = NSImage(size: glyph.size, flipped: false) { rect in
            glyph.draw(in: rect)
            NSColor.white.set()
            rect.fill(using: .sourceAtop)
            return true
        }
        let glyphRect = NSRect(x: screen.minX + screen.width * 0.12, y: screen.midY - glyph.size.height / 2,
                               width: glyph.size.width, height: glyph.size.height)
        tinted.draw(in: glyphRect)
        NSColor.white.setFill()
        NSRect(x: glyphRect.maxX + screen.width * 0.06, y: glyphRect.minY + glyph.size.height * 0.05,
               width: screen.width * 0.28, height: screen.height * 0.09).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    return representation.representation(using: .png, properties: [:])!
}

for points in [16, 32, 128, 256, 512] {
    try render(points).write(to: iconset.appending(path: "icon_\(points)x\(points).png"))
    try render(points * 2).write(to: iconset.appending(path: "icon_\(points)x\(points)@2x.png"))
}
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", iconset.path, "-o", output]
try process.run()
process.waitUntilExit()
exit(process.terminationStatus)
