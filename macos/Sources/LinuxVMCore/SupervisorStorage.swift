import Darwin
import Foundation

final class SupervisorStorage: @unchecked Sendable {
    private let queue = DispatchQueue(label: "dev.linuxvm.storage")
    private let volumes: any StorageVolumeMonitoring
    private let qemu: Process
    private let monitor: SupervisorMonitor
    private let log: @Sendable (String) -> Void
    private let machine: StorageWatch
    private var policy: StoragePolicy
    private var lostKinds: Set<StoragePathKind> = []
    private let lossLock = NSLock()
    private var machineLost = false
    private var pollPending = false
    private var lastPoll: TimeInterval = -.infinity
    private var stopped = false
    private var discQueryFailing = false
    private var monitorReady = false

    init(name: String, machine: StorageWatch, sharedFolder: StorageWatch?, qemu: Process, monitor: SupervisorMonitor,
         volumes: any StorageVolumeMonitoring, log: @escaping @Sendable (String) -> Void) {
        self.machine = machine
        self.qemu = qemu; self.monitor = monitor; self.volumes = volumes; self.log = log
        policy = StoragePolicy(name: name, machine: machine, sharedFolder: sharedFolder)
    }

    var storageDisconnected: Bool { lossLock.withLock { machineLost } }

    func start() {
        queue.sync {
            volumes.start(queue: queue, approve: { [weak self] in self?.approve($0) },
                          removed: { [weak self] in self?.removed($0) })
        }
    }

    /// Until QEMU's monitor answers, the periodic check skips the disc query.
    func monitorDidStart() {
        queue.async { self.monitorReady = true }
    }

    func stop() {
        volumes.stop()
        queue.sync { stopped = true }
    }

    // Called at most once a second, independent of QMP work queued by host sleep.
    func poll() {
        let now = ProcessInfo.processInfo.systemUptime
        guard lossLock.withLock({
            if now - lastPoll < 1 { return false }
            lastPoll = now
            return true
        }) else { return }
        if StoragePolicy.isLost(machine, currentDevice: storageDevice(at: machine.path)) { stopForMachineLoss() }
        let shouldPoll = lossLock.withLock {
            if pollPending { return false }
            pollPending = true
            return true
        }
        guard shouldPoll else { return }
        queue.async { [self] in
            defer { lossLock.withLock { pollPending = false } }
            guard !stopped, qemu.isRunning, !storageDisconnected else { return }
            guard monitorReady else { return }
            refreshDisc()
            let lost = [StoragePathKind.disc, .sharedFolder].filter { kind in
                guard !lostKinds.contains(kind), let watch = policy.watch(kind) else { return false }
                return StoragePolicy.isLost(watch, currentDevice: storageDevice(at: watch.path))
            }
            perform(policy.actions(for: lost, polite: false))
            lostKinds.formUnion(lost.filter { $0 != .disc })
        }
    }

    @discardableResult
    private func refreshDisc(removedVolume: StorageVolume? = nil) -> Bool {
        do {
            let blocks = try monitor.withClient(timeout: 0.5) { try $0.execute("query-block") as? [[String: Any]] ?? [] }
            discQueryFailing = false
            let file = StoragePolicy.installerFile(in: blocks)
            if file == policy.discFile { return true }
            let path = file.map(canonicalStoragePath)
            let resolved = file.flatMap { file in
                if let removedVolume, let path, StoragePolicy.contains(path, mountPath: removedVolume.mountPath) {
                    return StorageWatch(path: path, volume: removedVolume)
                }
                return volumes.watch(path: file)
            }
            if policy.updateDisc(file: file, resolved: resolved) { lostKinds.remove(.disc) }
            return true
        } catch {
            // The once-a-second check fails while QEMU starts or is busy; say so once.
            if !discQueryFailing { log("Cannot query the installer disc: \(error.localizedDescription)") }
            discQueryFailing = true
            return false
        }
    }

    private func approve(_ volume: StorageVolume) -> String? {
        guard !stopped, qemu.isRunning else { return nil }
        if volume.isBoot { return nil }
        if storageDevice(at: volume.mountPath) != volume.device {
            removed(volume)
            return nil
        }
        let fixedActions = policy.actions(for: volume, polite: true)
        for action in fixedActions {
            if case .dissent(let message) = action { log(message); return message }
        }
        guard refreshDisc() else {
            return "Cannot check the installer disc in Linux VM “\(policy.name)”. Try again, or shut it down first."
        }
        let actions = policy.actions(for: volume, polite: true)
        for action in actions {
            if case .dissent(let message) = action { log(message); return message }
        }
        if actions.contains(.ejectDisc) {
            do { try ejectDisc(); log("Ejected the installer disc before unmounting \(volume.mountPath)") }
            catch {
                let message = "Cannot eject the installer disc from Linux VM “\(policy.name)”. Try again after shutting it down."
                log("\(message) \(error.localizedDescription)")
                return message
            }
        }
        return nil
    }

    private func removed(_ volume: StorageVolume) {
        guard !stopped, qemu.isRunning else { return }
        // Protect the VM before querying removable media, even if QMP is unresponsive.
        if policy.actions(for: volume, polite: false).contains(.stopVM) { stopForMachineLoss(); return }
        refreshDisc(removedVolume: volume)
        let kinds = StoragePathKind.allCases.filter { kind in
            guard !lostKinds.contains(kind), let watch = policy.watch(kind) else { return false }
            return watch.volume == volume && !volume.isBoot
        }
        perform(policy.actions(for: kinds, polite: false))
        lostKinds.formUnion(kinds.filter { $0 != .disc })
    }

    private func ejectDisc() throws {
        try monitor.withClient(timeout: 0.5) { try $0.execute("eject", arguments: ["id": "install-cd", "force": true]) }
        _ = policy.updateDisc(file: nil, resolved: nil)
    }

    private func perform(_ actions: [StoragePolicy.Action]) {
        for action in actions {
            switch action {
            case .stopVM: stopForMachineLoss()
            case .ejectDisc:
                do { try ejectDisc(); log("The installer disc's drive was disconnected; ejected the disc") }
                catch { log("Cannot eject the disconnected installer disc: \(error.localizedDescription)") }
            case .logSharedFolderLoss: log("The drive shared with Linux VM “\(policy.name)” was disconnected; keeping the VM running")
            case .dissent: break
            }
        }
    }

    private func stopForMachineLoss() {
        let first = lossLock.withLock {
            if machineLost { return false }
            machineLost = true
            return true
        }
        guard first else { return }
        // The watchdog must not wait for a blocked monitor operation.
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { [qemu] in
            if qemu.isRunning { kill(qemu.processIdentifier, SIGKILL) }
        }
        DispatchQueue.global().async { [self] in
            guard qemu.isRunning else { return }
            do { try monitor.withClient(timeout: 0.5) { try $0.execute("quit") } }
            catch {
                if qemu.isRunning { kill(qemu.processIdentifier, SIGKILL) }
            }
        }
        log("The drive holding the VM was disconnected; stopping QEMU immediately")
    }
}
