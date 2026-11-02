import Foundation
import Testing
@testable import LinuxVMCore

@Suite("Storage removal policy")
struct StorageTests {
    let a = StorageVolume(mountPath: "/Volumes/Data", device: 100, isBoot: false)
    let b = StorageVolume(mountPath: "/Volumes/Data 1", device: 101, isBoot: false)
    let boot = StorageVolume(mountPath: "/", device: 1, isBoot: true)

    func policy(_ kind: StoragePathKind, volume: StorageVolume) -> StoragePolicy {
        let watch = StorageWatch(path: volume.mountPath + "/file", volume: volume)
        var policy = StoragePolicy(name: "Test", machine: StorageWatch(path: "/vm", volume: boot))
        switch kind {
        case .machine: policy.machine = watch
        case .disc: policy.disc = watch
        case .sharedFolder: policy.sharedFolder = watch
        }
        return policy
    }

    @Test("polite library removal names the VM and refuses")
    func politeMachine() {
        #expect(policy(.machine, volume: a).actions(for: a, polite: true) == [
            .dissent("Linux VM “Test” is running from this drive. Shut it down first.")
        ])
    }

    @Test("polite disc removal ejects it, shared-folder removal refuses")
    func politeMedia() {
        #expect(policy(.disc, volume: a).actions(for: a, polite: true) == [.ejectDisc])
        #expect(policy(.sharedFolder, volume: a).actions(for: a, polite: true) == [
            .dissent("This drive is shared with Linux VM “Test”. Shut it down first.")
        ])
    }

    @Test("forced removal stops only the library, ejects only the disc, and logs the share")
    func forcedRemoval() {
        #expect(policy(.machine, volume: a).actions(for: a, polite: false) == [.stopVM])
        #expect(policy(.disc, volume: a).actions(for: a, polite: false) == [.ejectDisc])
        #expect(policy(.sharedFolder, volume: a).actions(for: a, polite: false) == [.logSharedFolderLoss])
    }

    @Test("a refusal wins over a disc on the same volume")
    func overlappingPaths() {
        var policy = policy(.sharedFolder, volume: a)
        policy.disc = StorageWatch(path: "/Volumes/Data/a.iso", volume: a)
        #expect(policy.actions(for: a, polite: true).count == 1)
        #expect(policy.actions(for: a, polite: false) == [.ejectDisc, .logSharedFolderLoss])
        policy.machine = policy.disc!
        #expect(policy.actions(for: a, polite: false) == [.stopVM])
    }

    @Test("similar volume names, mount point reuse, and different mounts never match")
    func exactVolume() {
        let policy = policy(.machine, volume: a)
        #expect(policy.actions(for: b, polite: false).isEmpty)
        #expect(policy.actions(for: StorageVolume(mountPath: a.mountPath, device: 102, isBoot: false), polite: false).isEmpty)
        #expect(policy.actions(for: StorageVolume(mountPath: b.mountPath, device: a.device, isBoot: false), polite: false).isEmpty)
        #expect(!StoragePolicy.contains("/Volumes/Data 1/file", mountPath: a.mountPath))
        #expect(StoragePolicy.contains("/Volumes/Data/file", mountPath: a.mountPath))
    }

    @Test("path normalization resolves symlinks, tmp aliases and trailing slashes")
    func symlinks() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "storage-tests-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let target = directory.appending(path: "Data")
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: false)
        let link = directory.appending(path: "link")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: target)
        #expect(canonicalStoragePath(link.path + "/./") == canonicalStoragePath(target.path))
        #expect(canonicalStoragePath("/tmp/") == canonicalStoragePath("/private/tmp"))
        let volumes = try DiskArbitrationStorageVolumes()
        #expect(volumes.watch(path: link.path) == volumes.watch(path: target.path))
    }

    @Test("QMP current media replaces the old watch and an empty tray clears it")
    func changedDisc() {
        var policy = policy(.disc, volume: a)
        let blocks: [[String: Any]] = [
            ["device": "root", "inserted": ["file": "/disk.img"]],
            ["device": "install", "qdev": "/machine/peripheral/install-cd", "inserted": ["file": "/Volumes/Data 1/new.iso"]]
        ]
        let file = StoragePolicy.installerFile(in: blocks)
        #expect(file == "/Volumes/Data 1/new.iso")
        let changed = policy.updateDisc(file: file, resolved: StorageWatch(path: file!, volume: b))
        #expect(changed)
        #expect(policy.actions(for: a, polite: false).isEmpty)
        #expect(policy.actions(for: b, polite: true) == [.ejectDisc])
        // A missing file after detach must retain its original volume identity.
        let unchanged = policy.updateDisc(file: file, resolved: nil)
        #expect(!unchanged)
        #expect(policy.actions(for: b, polite: false) == [.ejectDisc])
        let empty = StoragePolicy.installerFile(in: [["device": "install", "tray_open": true]])
        #expect(empty == nil)
        let ejected = policy.updateDisc(file: empty, resolved: nil)
        #expect(ejected)
        #expect(policy.actions(for: b, polite: false).isEmpty)
        #expect(StoragePolicy.installerFile(in: [["qdev": "/machine/peripheral/install-cd", "inserted": ["file": "/x.iso"]]]) == "/x.iso")
    }


    @Test("unchanged QMP filenames retain the resolved volume when a symlink target disappears")
    func vanishedSymlinkTarget() {
        var policy = policy(.disc, volume: a)
        let watch = policy.disc!
        let inserted = policy.updateDisc(file: "/tmp/disc-link.iso", resolved: watch)
        #expect(inserted)
        let changed = policy.updateDisc(file: "/tmp/disc-link.iso", resolved: nil)
        #expect(!changed)
        #expect(policy.disc == watch)
        #expect(policy.actions(for: a, polite: false) == [.ejectDisc])
    }

    @Test("absent optional paths and boot/data volumes produce no action")
    func absentAndBootPaths() {
        for kind in StoragePathKind.allCases {
            #expect(policy(kind, volume: boot).actions(for: boot, polite: true).isEmpty)
            #expect(policy(kind, volume: boot).actions(for: boot, polite: false).isEmpty)
        }
        let policy = StoragePolicy(name: "Test", machine: StorageWatch(path: "/vm", volume: boot))
        #expect(policy.actions(for: a, polite: true).isEmpty)
        #expect(policy.actions(for: a, polite: false).isEmpty)
        #expect(StoragePolicy.installerFile(in: []) == nil)
    }

    @Test("fallback detects disappearance and st_dev replacement, ignoring boot volume")
    func fallback() throws {
        let watch = StorageWatch(path: a.mountPath + "/vm", volume: a)
        #expect(!StoragePolicy.isLost(watch, currentDevice: a.device))
        #expect(StoragePolicy.isLost(watch, currentDevice: nil))
        #expect(StoragePolicy.isLost(watch, currentDevice: b.device))
        #expect(!StoragePolicy.isLost(StorageWatch(path: "/vm", volume: boot), currentDevice: nil))
        let directory = FileManager.default.temporaryDirectory.appending(path: "storage-stat-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        #expect(storageDevice(at: directory.path) != nil)
        try FileManager.default.removeItem(at: directory)
        #expect(storageDevice(at: directory.path) == nil)
    }
}


@Suite("Storage monitor integration")
struct StorageMonitorTests {
    @Test("volume callbacks refuse polite removal and kill the owned process if QMP is unavailable")
    func callbacksAndFailedQuit() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: "storage-monitor-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let device = try #require(storageDevice(at: directory.path))
        let volume = StorageVolume(mountPath: directory.path, device: device, isBoot: false)
        let watch = StorageWatch(path: directory.path, volume: volume)
        let volumes = TestStorageVolumes(watch: watch)
        let child = Process()
        child.executableURL = URL(fileURLWithPath: "/bin/sleep")
        child.arguments = ["10"]
        try child.run()
        defer {
            if child.isRunning { child.terminate(); child.waitUntilExit() }
        }
        let storage = SupervisorStorage(name: "Callback test", machine: watch, sharedFolder: nil, qemu: child,
                                        monitor: SupervisorMonitor(path: directory.appending(path: "missing.sock").path),
                                        volumes: volumes, log: { _ in })
        storage.start()
        defer { storage.stop() }
        #expect(volumes.requestUnmount() == "Linux VM “Callback test” is running from this drive. Shut it down first.")
        #expect(child.isRunning)
        volumes.disconnect()
        child.waitUntilExit()
        #expect(storage.storageDisconnected)
        #expect(child.terminationReason == .uncaughtSignal)
        #expect(child.terminationStatus == 9)
    }
}

private final class TestStorageVolumes: StorageVolumeMonitoring {
    let watched: StorageWatch
    private var queue: DispatchQueue?
    private var approve: (@Sendable (StorageVolume) -> String?)?
    private var removed: (@Sendable (StorageVolume) -> Void)?

    init(watch: StorageWatch) { watched = watch }
    func watch(path: String) -> StorageWatch? { watched }
    func start(queue: DispatchQueue, approve: @escaping @Sendable (StorageVolume) -> String?,
               removed: @escaping @Sendable (StorageVolume) -> Void) {
        self.queue = queue; self.approve = approve; self.removed = removed
    }
    func stop() {}
    func requestUnmount() -> String? { queue?.sync { approve?(watched.volume) } }
    func disconnect() { queue?.sync { removed?(watched.volume) } }
}
