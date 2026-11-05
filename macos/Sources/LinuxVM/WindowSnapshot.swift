import AppKit

/// Development aid: with LINUXVM_SNAPSHOT=/path/prefix set, saves each of the
/// app's own windows as PNG a moment after launch. Capturing its own windows
/// needs no Screen Recording permission.
enum WindowSnapshot {
    @MainActor
    static func scheduleIfRequested() {
        guard let prefix = ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT"], prefix.hasPrefix("/") else { return }
        let delay = Double(ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_DELAY"] ?? "") ?? 2
        if let height = Double(ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_HEIGHT"] ?? "") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                for window in NSApp.windows where window.isVisible && window.sheetParent == nil {
                    var frame = window.frame
                    frame.size.height = height
                    window.setFrame(frame, display: true)
                }
            }
        }
        // LINUXVM_SNAPSHOT_SCROLL=end shows the bottom of scrolling content.
        if ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_SCROLL"] == "end" {
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0.5, delay - 1)) {
                for window in NSApp.windows where window.isVisible {
                    window.contentView.map(scrollToEnd)
                }
            }
        }
        // LINUXVM_SNAPSHOT_TYPE=text replaces the selection in the focused field of the open
        // sheet (or the key window) with text, then presses Return, through the field's own
        // text editor. Windows of an app that isn't in front ignore key events.
        if let text = ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_TYPE"] {
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0.5, delay - 1)) {
                let window = NSApp.windows.first(where: { $0.isVisible && $0.sheetParent != nil }) ?? NSApp.keyWindow
                guard let editor = window?.firstResponder as? NSTextView else {
                    FileHandle.standardError.write(Data("snapshot: no focused text field to type into\n".utf8))
                    return
                }
                editor.insertText(text, replacementRange: editor.selectedRange())
                editor.insertNewline(nil)
            }
        }
        // LINUXVM_SNAPSHOT_PRESS=title presses the button with that title in the open sheet.
        if let title = ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_PRESS"] {
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0.5, delay - 1)) {
                let sheets = NSApp.windows.filter { $0.isVisible && $0.sheetParent != nil }
                guard let button = sheets.lazy.compactMap({ $0.contentView.flatMap { findButton(title, in: $0) } }).first else {
                    FileHandle.standardError.write(Data("snapshot: no button titled \(title) in an open sheet\n".utf8))
                    return
                }
                button.performClick(nil)
            }
        }
        // LINUXVM_SNAPSHOT_MENU=N right-clicks row N of the sidebar, saves PREFIX-menu.png
        // with its context menu open, then quits. The click is an event the app sends
        // itself. An open menu blocks the main thread, so another thread captures it.
        if let row = Int(ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_MENU"] ?? "") {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                guard let main = NSApp.windows.first(where: { $0.isVisible && $0.sheetParent == nil && $0.styleMask.contains(.titled) })
                else { return }
                let number = CGWindowID(main.windowNumber)
                let url = URL(fileURLWithPath: "\(prefix)-menu.png")
                DispatchQueue.global().async {
                    // The menu can take a moment to appear, then fades in.
                    let deadline = Date.now.addingTimeInterval(5)
                    while windowsInFront(of: number).isEmpty, Date.now < deadline { Thread.sleep(forTimeInterval: 0.1) }
                    Thread.sleep(forTimeInterval: 0.4)
                    writeComposite(window: number, to: url)
                    exit(0)
                }
                rightClick(row: row, in: main)
            }
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            for (index, window) in NSApp.windows.enumerated() where window.isVisible {
                guard let representation = capture(window) else { continue }
                try? representation.representation(using: .png, properties: [:])?
                    .write(to: URL(fileURLWithPath: "\(prefix)-\(index).png"))
            }
            // With a sheet open, PREFIX-composite.png shows it in place over its window.
            if let main = NSApp.windows.first(where: { $0.isVisible && $0.attachedSheet != nil }) {
                writeComposite(window: CGWindowID(main.windowNumber), to: URL(fileURLWithPath: "\(prefix)-composite.png"))
            }
        }
    }

    @MainActor
    private static func capture(_ window: NSWindow) -> NSBitmapImageRep? {
        guard let view = window.contentView?.superview ?? window.contentView,
              let representation = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return nil }
        view.cacheDisplay(in: view.bounds, to: representation)
        return representation
    }

    @MainActor
    private static func rightClick(row: Int, in window: NSWindow) {
        guard let content = window.contentView, let table = firstTable(in: content), row < table.numberOfRows else { return }
        let rect = table.rect(ofRow: row)
        let point = table.convert(NSPoint(x: rect.minX + 70, y: rect.midY), to: nil)
        guard let event = NSEvent.mouseEvent(with: .rightMouseDown, location: point, modifierFlags: [],
                                             timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
                                             context: nil, eventNumber: 0, clickCount: 1, pressure: 1) else { return }
        window.sendEvent(event)
    }

    @MainActor
    private static func findButton(_ title: String, in view: NSView) -> NSButton? {
        if let button = view as? NSButton, button.title == title { return button }
        for subview in view.subviews {
            if let button = findButton(title, in: subview) { return button }
        }
        return nil
    }

    @MainActor
    private static func firstTable(in view: NSView) -> NSTableView? {
        if let table = view as? NSTableView { return table }
        for subview in view.subviews {
            if let table = firstTable(in: subview) { return table }
        }
        return nil
    }

    /// The app's on-screen windows in front of `main`, front to back, as Core Graphics describes them.
    private static func windowsInFront(of main: CGWindowID) -> [[String: Any]] {
        let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
        let own = info.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == getpid() }
        guard own.contains(where: { ($0[kCGWindowNumber as String] as? Int) == Int(main) }) else { return [] }
        return Array(own.prefix { ($0[kCGWindowNumber as String] as? Int) != Int(main) })
    }

    /// Draws the app's windows in front of the library window, such as an open menu or
    /// sheet, over it as they appear on screen. This uses Core Graphics: AppKit doesn't
    /// list a menu's window among the app's windows.
    private static func writeComposite(window main: CGWindowID, to url: URL) {
        typealias CreateImage = @convention(c) (CGRect, CGWindowListOption, CGWindowID, CGWindowImageOption) -> Unmanaged<CGImage>?
        guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "CGWindowListCreateImage"),
              let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] else { return }
        let create = unsafeBitCast(symbol, to: CreateImage.self)
        let own = info.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == getpid() }
        func bounds(_ window: [String: Any]) -> CGRect? {
            (window[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation: $0 as CFDictionary) }
        }
        func image(_ number: CGWindowID) -> CGImage? {
            create(.null, .optionIncludingWindow, number, [.boundsIgnoreFraming, .bestResolution])?.takeRetainedValue()
        }
        guard let mainInfo = own.first(where: { ($0[kCGWindowNumber as String] as? Int) == Int(main) }),
              let mainBounds = bounds(mainInfo), let mainImage = image(main) else {
            FileHandle.standardError.write(Data("snapshot: could not capture the library window\n".utf8))
            return
        }
        // Draw the windows in front of the library window from back to front.
        let front = windowsInFront(of: main).reversed()
        let scale = CGFloat(mainImage.width) / mainBounds.width
        guard let context = CGContext(data: nil, width: mainImage.width, height: mainImage.height, bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
        context.draw(mainImage, in: CGRect(x: 0, y: 0, width: mainImage.width, height: mainImage.height))
        for window in front {
            guard let frame = bounds(window), let number = window[kCGWindowNumber as String] as? Int,
                  let windowImage = image(CGWindowID(number)) else { continue }
            // Core Graphics window bounds start at the top left; the context starts at the bottom left.
            let x = (frame.minX - mainBounds.minX) * scale
            let y = (mainBounds.maxY - frame.maxY) * scale
            context.draw(windowImage, in: CGRect(x: x, y: y, width: frame.width * scale, height: frame.height * scale))
        }
        guard let composite = context.makeImage() else { return }
        try? NSBitmapImageRep(cgImage: composite).representation(using: .png, properties: [:])?.write(to: url)
    }

    @MainActor
    private static func scrollToEnd(_ view: NSView) {
        if let scrollView = view as? NSScrollView, let document = scrollView.documentView {
            let clip = scrollView.contentView
            let end = document.isFlipped ? max(0, document.frame.height - clip.bounds.height) : 0
            clip.scroll(to: NSPoint(x: clip.bounds.minX, y: end))
            scrollView.reflectScrolledClipView(clip)
        }
        view.subviews.forEach(scrollToEnd)
    }
}
