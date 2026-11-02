import Darwin
import Foundation
import IOKit
import IOKit.pwr_mgt
import notify

// IOMessage.h macros use iokit_common_msg, which Swift cannot import.
private let canSystemSleep: UInt32 = 0xe0000270
private let systemWillSleep: UInt32 = 0xe0000280
private let systemHasPoweredOn: UInt32 = 0xe0000300

// Pause ownership and wake backoff adapted from Try Omarchy's
// VMHostSleepController.swift (MIT, Try Omarchy contributors).
enum VMHostSleepControlError: Error {
    case pauseOutcomeUnknown(String)
    case unsafeResumeState(String)
}
protocol VMHostSleepControlling: AnyObject {
    func pauseIfRunning() throws -> Bool
    func resume() throws
}
final class QMPHostSleepController: VMHostSleepControlling {
    let monitor: SupervisorMonitor
    init(monitor: SupervisorMonitor) { self.monitor = monitor }
    func pauseIfRunning() throws -> Bool {
        // One five-second deadline includes greeting, capabilities, status and stop.
        try monitor.withClient { client in
            let status = try client.execute("query-status") as? [String: Any]
            guard status?["running"] as? Bool == true, status?["status"] as? String == "running" else { return false }
            do { try client.execute("stop") }
            catch { throw VMHostSleepControlError.pauseOutcomeUnknown(error.localizedDescription) }
            return true
        }
    }
    func resume() throws {
        try monitor.withClient { client in
            let status = try client.execute("query-status") as? [String: Any]
            if status?["status"] as? String == "running" { return }
            guard status?["status"] as? String == "paused" else {
                throw VMHostSleepControlError.unsafeResumeState(status?["status"] as? String ?? "unknown")
            }
            try client.execute("cont")
        }
    }
}

final class VMHostSleepCoordinator {
    let controller: any VMHostSleepControlling
    private(set) var pausedForHostSleep = false
    init(controller: any VMHostSleepControlling) { self.controller = controller }
    func prepareForHostSleep(vmIsRunning: Bool, isStopping: Bool) throws {
        guard vmIsRunning, !isStopping, !pausedForHostSleep else { return }
        do { pausedForHostSleep = try controller.pauseIfRunning() }
        catch {
            if case VMHostSleepControlError.pauseOutcomeUnknown = error { pausedForHostSleep = true }
            throw error
        }
    }
    func resumeAfterHostWake(vmIsRunning: Bool, isStopping: Bool) throws {
        guard pausedForHostSleep else { return }
        guard vmIsRunning, !isStopping else { disconnect(); return }
        do { try controller.resume(); pausedForHostSleep = false }
        catch {
            if case VMHostSleepControlError.unsafeResumeState = error { pausedForHostSleep = false }
            throw error
        }
    }
    func disconnect() { pausedForHostSleep = false }
}

struct VMHostWakeRetryPolicy {
    private var index = 0
    mutating func nextDelay() -> TimeInterval? {
        let delays: [TimeInterval] = [0.25, 0.75, 1.5, 3]
        guard index < delays.count else { return nil }
        defer { index += 1 }
        return delays[index]
    }
}

/// Power state and callbacks belong to queue; monitor access also takes the storage lock.
final class SupervisorPower: @unchecked Sendable {
    let queue = DispatchQueue(label: "dev.linuxvm.power")
    let monitor: SupervisorMonitor
    private let qemu: Process
    private let library: VMLibrary
    private let id: String
    private let log: @Sendable (String) -> Void
    private var state: RunState
    private let coordinator: VMHostSleepCoordinator
    private var generation = 0
    private var awake = true
    private var wakePosted = false
    private var lastWakeClockOffset: TimeInterval?
    private var retry = VMHostWakeRetryPolicy()
    private var root: io_connect_t = 0
    private var port: IONotificationPortRef?
    private var notifier: io_object_t = 0

    init(qemu: Process, library: VMLibrary, id: String, monitor: SupervisorMonitor, state: RunState,
         log: @escaping @Sendable (String) -> Void) {
        self.qemu = qemu; self.library = library; self.id = id
        self.state = state; self.log = log
        self.monitor = monitor
        coordinator = VMHostSleepCoordinator(controller: QMPHostSleepController(monitor: monitor))
    }
    func start() {
        root = IORegisterForSystemPower(Unmanaged.passUnretained(self).toOpaque(), &port, { context, _, message, argument in
            guard let context else { return }
            let owner = Unmanaged<SupervisorPower>.fromOpaque(context).takeUnretainedValue()
            switch message {
            case canSystemSleep:
                IOAllowPowerChange(owner.root, Int(bitPattern: argument))
            case systemWillSleep:
                owner.willSleep()
                IOAllowPowerChange(owner.root, Int(bitPattern: argument))
            case systemHasPoweredOn: owner.didWake()
            default: break
            }
        }, &notifier)
        if root != 0, let port { IONotificationPortSetDispatchQueue(port, queue) }
        else { log("Cannot register system power notifications") }
    }
    func stop() {
        if let port { IONotificationPortSetDispatchQueue(port, nil) }
        queue.sync { generation += 1; coordinator.disconnect() }
        if notifier != 0 { IODeregisterForSystemPower(&notifier) }
        if root != 0 { IOServiceClose(root) }
        if let port { IONotificationPortDestroy(port) }
    }
    private func phase(_ phase: VMState) {
        state.phase = phase
        library.writeRunState(state, id: id)
    }
    func simulate(sleep: Bool) { queue.sync { if sleep { willSleep() } else { didWake() } } }
    private func willSleep() {
        generation += 1
        awake = false
        wakePosted = false
        retry = VMHostWakeRetryPolicy()
        guard (try? library.load(id: id).pauseDuringSleep) == true else { return }
        do {
            let owned = coordinator.pausedForHostSleep
            try coordinator.prepareForHostSleep(vmIsRunning: qemu.isRunning && state.phase == .running,
                                                isStopping: state.phase == .stopping)
            if !owned && coordinator.pausedForHostSleep { log("Paused QEMU for host sleep") }
        } catch { log("Host sleep pause: \(error)") }
        if coordinator.pausedForHostSleep && state.phase != .stopping { phase(.paused) }
    }
    private func didWake() {
        // Permit a wake with a missing sleep event; suppress duplicate wakes.
        let clockOffset = Date().timeIntervalSince1970 - ProcessInfo.processInfo.systemUptime
        if awake && wakePosted, let previous = lastWakeClockOffset, abs(clockOffset - previous) < 1 { return }
        awake = true
        generation += 1
        retry = VMHostWakeRetryPolicy()
        resume(generation: generation)
    }
    private func resume(generation expected: Int) {
        guard expected == generation, awake else { return }
        do {
            let owned = coordinator.pausedForHostSleep
            try coordinator.resumeAfterHostWake(vmIsRunning: qemu.isRunning, isStopping: state.phase == .stopping)
            if owned && qemu.isRunning && state.phase != .stopping {
                phase(.running); log("Resumed QEMU after host wake")
            }
        } catch VMHostSleepControlError.unsafeResumeState(let status) {
            log("Refusing host wake resume: QEMU status \(status)")
        } catch {
            log("Host wake resume failed: \(error)")
            if qemu.isRunning, state.phase != .stopping, let delay = retry.nextDelay() {
                queue.asyncAfter(deadline: .now() + delay) { [self] in resume(generation: expected) }
                return
            }
        }
        postWake()
    }
    private func postWake() {
        guard qemu.isRunning, !wakePosted else { return }
        wakePosted = true
        lastWakeClockOffset = Date().timeIntervalSince1970 - ProcessInfo.processInfo.systemUptime
        let result = notify_post("dev.tryomarchy.host-wake")
        log("Posted host wake notification (result \(result))")
    }
    func requestShutdown() {
        queue.sync { () -> Void in
            generation += 1
            phase(.stopping)
            // A powerdown event cannot be handled by a guest we have paused.
            // Relinquish our pause for shutdown, but still refuse abnormal stops.
            do {
                let owned = coordinator.pausedForHostSleep
                try coordinator.resumeAfterHostWake(vmIsRunning: qemu.isRunning, isStopping: false)
                if owned { log("Resumed sleep pause for guest shutdown") }
            } catch { log("Cannot resume sleep pause for shutdown: \(error)") }
            try? monitor.withClient(timeout: 2) { client -> Void in
                try client.execute("system_powerdown")
            }
        }
    }
}
