import Foundation

/// A VM name suggested from an installer or disk image's file name, such as
/// "Fedora KDE" for Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso.
public enum InstallerName {
    public static let fallback = "Linux"

    public static func suggest(for fileName: String) -> String {
        let name = fileName.lowercased()
        func has(_ word: String) -> Bool {
            name.range(of: "(^|[^a-z])\(word)([^a-z]|$)", options: .regularExpression) != nil
        }
        if has("kubuntu") { return "Kubuntu" }
        if has("ubuntu") { return "Ubuntu" }
        if has("fedora") { return has("kde") ? "Fedora KDE" : "Fedora" }
        if has("debian") { return "Debian" }
        if has("opensuse") { return "openSUSE" }
        if has("archlinux") || has("arch") { return "Arch Linux" }
        return fallback
    }
}
