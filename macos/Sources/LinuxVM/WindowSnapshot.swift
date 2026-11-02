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
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            for (index, window) in NSApp.windows.enumerated() where window.isVisible {
                guard let view = window.contentView?.superview ?? window.contentView,
                      let representation = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { continue }
                view.cacheDisplay(in: view.bounds, to: representation)
                try? representation.representation(using: .png, properties: [:])?
                    .write(to: URL(fileURLWithPath: "\(prefix)-\(index).png"))
            }
        }
    }
}
