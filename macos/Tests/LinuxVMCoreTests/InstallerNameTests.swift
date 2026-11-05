import Testing
@testable import LinuxVMCore

struct InstallerNameTests {
    @Test func suggestsTheDistribution() {
        #expect(InstallerName.suggest(for: "ubuntu-26.04.1-desktop-arm64.iso") == "Ubuntu")
        #expect(InstallerName.suggest(for: "kubuntu-26.04-desktop-amd64.iso") == "Kubuntu")
        #expect(InstallerName.suggest(for: "Fedora-Workstation-Live-44-1.7.aarch64.iso") == "Fedora")
        #expect(InstallerName.suggest(for: "Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso") == "Fedora KDE")
        #expect(InstallerName.suggest(for: "debian-13.1.0-arm64-netinst.iso") == "Debian")
        #expect(InstallerName.suggest(for: "openSUSE-Tumbleweed-DVD-aarch64-Current.iso") == "openSUSE")
        #expect(InstallerName.suggest(for: "archlinuxarm-aarch64.iso") == InstallerName.fallback)
        #expect(InstallerName.suggest(for: "Ubuntu.qcow2") == "Ubuntu")
        // Words inside other words don't count.
        #expect(InstallerName.suggest(for: "research-arm64.iso") == InstallerName.fallback)
        #expect(InstallerName.suggest(for: "install.iso") == InstallerName.fallback)
    }
}
