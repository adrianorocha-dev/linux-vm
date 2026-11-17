import Foundation
import Testing
@testable import LinuxVMCore

struct IsolationTests {
    let library = VMLibrary(root: URL(fileURLWithPath: "/tmp/linuxvm-tests"))
    let runtime = Runtime(contents: URL(fileURLWithPath: "/nonexistent"))
    let paths = QEMULaunch.Paths(runDirectory: URL(fileURLWithPath: "/tmp/r"))

    func machine(_ isolation: IsolationSettings = IsolationSettings()) -> VMConfiguration {
        var configuration = VMConfiguration(name: "Linux", cpuCount: 2, memoryMiB: 4096, diskFileName: "disk.img",
                                            diskFormat: .raw, isolation: isolation)
        configuration.sharedFolder = "/Users/someone/Projects"
        return configuration
    }

    func arguments(_ configuration: VMConfiguration) -> String {
        QEMULaunch.make(configuration: configuration, library: library, runtime: runtime, paths: paths, host: .init())
            .arguments.joined(separator: " ")
    }

    @Test func configurationsWithoutIsolationKeepTodaysAccess() throws {
        let data = try JSONEncoder().encode(machine())
        var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        object.removeValue(forKey: "isolation")
        let decoded = try JSONDecoder().decode(VMConfiguration.self, from: JSONSerialization.data(withJSONObject: object))
        #expect(decoded.isolation == IsolationSettings())
        #expect(!decoded.isolation.isHardened)

        object["isolation"] = ["clipboard": false]
        let partial = try JSONDecoder().decode(VMConfiguration.self, from: JSONSerialization.data(withJSONObject: object))
        #expect(!partial.isolation.clipboard)
        #expect(partial.isolation.macServices && partial.isolation.localNetwork)
        #expect(partial.isolation.microphone && partial.isolation.sharedFolderWritable)
    }

    @Test func hardenedRoundTrips() throws {
        let configuration = machine(.hardened)
        #expect(configuration.isolation.isHardened)
        let decoded = try JSONDecoder().decode(VMConfiguration.self, from: JSONEncoder().encode(configuration))
        #expect(decoded.isolation == .hardened)
    }

    @Test func openVMKeepsEveryChannel() {
        let joined = arguments(machine())
        #expect(joined.contains("-netdev user,id=net0 "))
        #expect(!joined.contains("host-loopback"))
        #expect(!joined.contains("local-network"))
        #expect(joined.contains("hda-micro,bus=hda.0"))
        #expect(joined.contains("name=dev.linuxvm.clipboard"))
        #expect(!joined.contains("guest_owner_gid=1000,readonly=on"))
    }

    @Test func hardenedVMClosesEachChannel() {
        let joined = arguments(machine(.hardened))
        #expect(joined.contains("-netdev user,id=net0,host-loopback=off,local-network=off"))
        #expect(joined.contains("hda-output,bus=hda.0"))
        #expect(!joined.contains("hda-micro"))
        #expect(!joined.contains("dev.linuxvm.clipboard"))
        #expect(!joined.contains("clipboard.sock"))
        #expect(joined.contains("guest_owner_gid=1000,readonly=on"))
        // Port numbers stay put without the clipboard.
        #expect(joined.contains("nr=2,chardev=audio,name=dev.linuxvm.audio"))
        #expect(joined.contains("nr=3,chardev=timezone,name=dev.linuxvm.timezone"))
        #expect(joined.contains("nr=4,chardev=status,name=dev.linuxvm.status"))
        #expect(QEMULaunch.Bridge.enabled(for: machine(.hardened)) == [.audio, .timezone])
    }

    @Test func portForwardsStayWithHostLoopbackOff() {
        var configuration = machine(.hardened)
        configuration.portForwards = [PortForward(hostPort: 2222, guestPort: 22)]
        #expect(arguments(configuration).contains("user,id=net0,host-loopback=off,local-network=off,hostfwd=tcp:127.0.0.1:2222-:22"))
    }

    @Test func localNetworkTurnsOffOnItsOwn() {
        var isolation = IsolationSettings()
        isolation.localNetwork = false
        let joined = arguments(machine(isolation))
        #expect(joined.contains("-netdev user,id=net0,local-network=off "))
        #expect(!joined.contains("host-loopback"))
        #expect(!isolation.isHardened)
    }

    func sandbox(writable: Bool, media: String? = "/Users/someone/Downloads/linux.iso") -> QEMUSandbox {
        QEMUSandbox(paths: .init(
            home: "/Users/someone", machine: "/Users/someone/Library/Application Support/Linux VM/VMs/ID",
            run: "/private/tmp/linuxvm.abc", temporary: ["/private/var/folders/x/T", "/private/var/folders/x/C"],
            runtime: "/Applications/Linux VM.app/Contents",
            qemu: "/Applications/Linux VM.app/Contents/Resources/runtime/bin/qemu-system-aarch64",
            sharedFolder: "/Users/someone/Projects", sharedFolderWritable: writable, installMedia: media))
    }

    @Test func sandboxConfinesWritesAndHomeReads() {
        let profile = sandbox(writable: true).profile
        #expect(profile.contains("(deny file-write*)"))
        #expect(profile.contains("(deny process-exec*)"))
        #expect(profile.contains(#"(allow process-exec* (literal (param "QEMU")))"#))
        #expect(profile.contains(#"(deny file-read-data file-read-xattr"#))
        #expect(profile.contains(#"(subpath (param "HOME"))"#))
        #expect(profile.contains(#"(subpath "/Volumes")"#))
        #expect(profile.contains(#"(literal (param "MEDIA"))"#))
        let allowWrite = profile.components(separatedBy: "(allow file-write*")[1].components(separatedBy: "(deny")[0]
        #expect(allowWrite.contains(#"(param "SHARED")"#))
        #expect(!allowWrite.contains(#"(param "HOME")"#))
    }

    @Test func readOnlyShareIsReadableNotWritable() {
        let profile = sandbox(writable: false, media: nil).profile
        let allowWrite = profile.components(separatedBy: "(allow file-write*")[1].components(separatedBy: "(deny")[0]
        let allowRead = profile.components(separatedBy: "(allow file-read-data")[1]
        #expect(!allowWrite.contains(#"(param "SHARED")"#))
        #expect(allowRead.contains(#"(subpath (param "SHARED"))"#))
        #expect(!profile.contains("MEDIA"))
    }

    @Test func sandboxCommandPassesPathsAsParameters() {
        let qemu = URL(fileURLWithPath: "/Applications/Linux VM.app/Contents/Resources/runtime/bin/qemu-system-aarch64")
        let command = sandbox(writable: true).command(qemu: qemu, arguments: ["-name", "Linux"])
        #expect(command.executable.path == "/usr/bin/sandbox-exec")
        #expect(command.arguments.contains("SHARED=/Users/someone/Projects"))
        #expect(command.arguments.suffix(3) == [qemu.path, "-name", "Linux"])
        #expect(command.arguments[command.arguments.count - 5] == "-p")
    }

    @Test func sandboxPathsAreReal() {
        #expect(QEMUSandbox.resolved("/tmp") == "/private/tmp")
        #expect(QEMUSandbox.resolved("/tmp/linuxvm-missing/run") == "/private/tmp/linuxvm-missing/run")
    }

    @Test func failedInsertKeepsTheAttachedImageInTheConfiguration() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "linuxvm-media-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let attached = root.appending(path: "attached.iso")
        FileManager.default.createFile(atPath: attached.path, contents: Data())
        let library = VMLibrary(root: root)
        let machine = try library.create(name: "Media", installMedia: attached.path, cpuCount: 1, memoryMiB: 2048, diskGiB: 8)
        // Look running: hold the supervisor's lock and write its run state.
        let lock = open(library.lockURL(for: machine.id).path, O_RDWR | O_CREAT, 0o600)
        defer { close(lock) }
        #expect(flock(lock, LOCK_EX | LOCK_NB) == 0)
        library.writeRunState(RunState(supervisorPID: getpid(), qemuPID: nil, phase: .running,
                                       controlSocket: "/nonexistent/control.sock", startedAt: Date()), id: machine.id)
        #expect(throws: (any Error).self) {
            try library.setInstallMedia(id: machine.id, path: root.appending(path: "missing.iso").path)
        }
        #expect(try library.load(id: machine.id).installMedia == attached.path)
    }

    @Test func versionGateRequiresTheSecurityFixes() {
        #expect(!Runtime.hasSecurityFixes(version: "QEMU emulator version 11.1.1"))
        #expect(Runtime.hasSecurityFixes(version: "QEMU emulator version 11.1.2"))
        #expect(Runtime.hasSecurityFixes(version: "QEMU emulator version 11.1.3"))
        #expect(Runtime.hasSecurityFixes(version: "QEMU emulator version 11.2.0"))
        #expect(!Runtime.hasSecurityFixes(version: "unavailable"))
    }

    @Test func broadSharedFoldersWarn() {
        let home = "/Users/someone"
        #expect(VMConfiguration.sharedFolderWarning("/", home: home) != nil)
        #expect(VMConfiguration.sharedFolderWarning(home, home: home) != nil)
        #expect(VMConfiguration.sharedFolderWarning("\(home)/", home: home) != nil)
        #expect(VMConfiguration.sharedFolderWarning("\(home)/Library/LaunchAgents", home: home) != nil)
        #expect(VMConfiguration.sharedFolderWarning("\(home)/.ssh", home: home) != nil)
        #expect(VMConfiguration.sharedFolderWarning("\(home)/Projects/linux", home: home) == nil)
        #expect(VMConfiguration.sharedFolderWarning("/Volumes/USB/Share", home: home) == nil)
    }
}
