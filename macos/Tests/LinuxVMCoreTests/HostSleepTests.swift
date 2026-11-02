import Foundation
import Testing
@testable import LinuxVMCore

// Policy cases adapted from Try Omarchy (MIT).
@Suite("VM host sleep lifecycle")
struct VMHostSleepCoordinatorTests {
    @Test("one successful pause owns exactly one matching resume")
    func idempotentSleepWakeCycle() throws {
        let controller = FakeHostSleepController(pauseResult: true)
        let coordinator = VMHostSleepCoordinator(controller: controller)

        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)
        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)
        #expect(controller.pauseCalls == 1)
        #expect(coordinator.pausedForHostSleep)

        try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        #expect(controller.resumeCalls == 1)
        #expect(!coordinator.pausedForHostSleep)
    }

    @Test("a VM paused by another cause is never resumed on host wake")
    func doesNotOwnExistingPause() throws {
        let controller = FakeHostSleepController(pauseResult: false)
        let coordinator = VMHostSleepCoordinator(controller: controller)

        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)
        try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)

        #expect(controller.pauseCalls == 1)
        #expect(controller.resumeCalls == 0)
        #expect(!coordinator.pausedForHostSleep)
    }

    @Test("pause failure and inactive lifecycle states cannot create resume ownership")
    func failedAndInactivePausesDoNotResume() throws {
        let controller = FakeHostSleepController(pauseResult: true)
        let coordinator = VMHostSleepCoordinator(controller: controller)

        try coordinator.prepareForHostSleep(vmIsRunning: false, isStopping: false)
        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: true)
        #expect(controller.pauseCalls == 0)

        controller.pauseError = TestControlError.expected
        #expect(throws: TestControlError.self) {
            try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)
        }
        #expect(!coordinator.pausedForHostSleep)
        try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        #expect(controller.resumeCalls == 0)
    }

    @Test("an ambiguous stop acknowledgement is recovered on wake")
    func ambiguousPauseStillOwnsRecovery() throws {
        let controller = FakeHostSleepController(pauseResult: true)
        controller.pauseError = VMHostSleepControlError.pauseOutcomeUnknown("reply lost")
        let coordinator = VMHostSleepCoordinator(controller: controller)

        #expect(throws: VMHostSleepControlError.self) {
            try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)
        }
        #expect(coordinator.pausedForHostSleep)

        try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        #expect(controller.resumeCalls == 1)
        #expect(!coordinator.pausedForHostSleep)
    }

    @Test("a failed wake retains ownership so a delayed retry can recover")
    func failedWakeCanRetry() throws {
        let controller = FakeHostSleepController(pauseResult: true)
        let coordinator = VMHostSleepCoordinator(controller: controller)
        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)

        controller.resumeError = TestControlError.expected
        #expect(throws: TestControlError.self) {
            try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        }
        #expect(coordinator.pausedForHostSleep)

        controller.resumeError = nil
        try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        #expect(controller.resumeCalls == 2)
        #expect(!coordinator.pausedForHostSleep)
    }

    @Test("an abnormal QEMU stop is left untouched and releases sleep ownership")
    func unsafeWakeRelinquishesOwnership() throws {
        let controller = FakeHostSleepController(pauseResult: true)
        let coordinator = VMHostSleepCoordinator(controller: controller)
        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)

        controller.resumeError = VMHostSleepControlError.unsafeResumeState("io-error")
        #expect(throws: VMHostSleepControlError.self) {
            try coordinator.resumeAfterHostWake(vmIsRunning: true, isStopping: false)
        }
        #expect(!coordinator.pausedForHostSleep)
    }

    @Test("wake retry backoff is bounded and resettable")
    func boundedWakeRetryPolicy() {
        var policy = VMHostWakeRetryPolicy()
        #expect(policy.nextDelay() == 0.25)
        #expect(policy.nextDelay() == 0.75)
        #expect(policy.nextDelay() == 1.5)
        #expect(policy.nextDelay() == 3)
        #expect(policy.nextDelay() == nil)
    }

    @Test("child exit while asleep drops the control session without resuming it")
    func exitWhileAsleepClearsOwnership() throws {
        let controller = FakeHostSleepController(pauseResult: true)
        let coordinator = VMHostSleepCoordinator(controller: controller)
        try coordinator.prepareForHostSleep(vmIsRunning: true, isStopping: false)

        coordinator.disconnect()
        try coordinator.resumeAfterHostWake(vmIsRunning: false, isStopping: false)

        #expect(controller.resumeCalls == 0)
        #expect(!coordinator.pausedForHostSleep)
    }
}

private enum TestControlError: Error {
    case expected
}

private final class FakeHostSleepController: VMHostSleepControlling {
    let pauseResult: Bool
    var pauseError: Error?
    var resumeError: Error?
    private(set) var pauseCalls = 0
    private(set) var resumeCalls = 0
    private(set) var closeCalls = 0

    init(pauseResult: Bool) {
        self.pauseResult = pauseResult
    }

    func pauseIfRunning() throws -> Bool {
        pauseCalls += 1
        if let pauseError { throw pauseError }
        return pauseResult
    }

    func resume() throws {
        resumeCalls += 1
        if let resumeError { throw resumeError }
    }

    func close() {
        closeCalls += 1
    }
}

