import AppKit
import Foundation
import LinuxVMCore
import Observation
import Sparkle

/// Updates through Sparkle. A VM runs from inside the app bundle, and a bridge
/// that restarts after the bundle has been replaced cannot attach to the old
/// QEMU. So an update installs only after every VM has shut down.
@MainActor
@Observable
final class UpdateController: NSObject, SPUUpdaterDelegate {
    struct Prompt: Identifiable {
        enum Kind { case shutDown, notice }
        let kind: Kind
        let title: String
        let message: String
        var id: String { title + message }
    }

    /// A newer version that waits for the running VMs to shut down.
    private(set) var waitingVersion: String?
    private(set) var canCheck = false
    private(set) var shuttingDown = false
    var prompt: Prompt?

    @ObservationIgnored private var controller: SPUStandardUpdaterController?
    @ObservationIgnored private var canCheckObservation: NSKeyValueObservation?
    @ObservationIgnored private var postponedInstall: (() -> Void)?
    @ObservationIgnored private var askedByUser = false
    @ObservationIgnored private let model: LibraryModel

    /// Release builds name the update feed and its public key in Info.plist.
    static var isConfigured: Bool {
        let info = Bundle.main.infoDictionary ?? [:]
        return ["SUFeedURL", "SUPublicEDKey"].allSatisfy { !((info[$0] as? String) ?? "").isEmpty }
    }

    init(model: LibraryModel) {
        self.model = model
        super.init()
        let environment = ProcessInfo.processInfo.environment
        if environment["LINUXVM_SNAPSHOT"] != nil, let version = environment["LINUXVM_SNAPSHOT_UPDATE"] {
            // Development aid: shows a waiting update without checking for one.
            waitingVersion = version
            if environment["LINUXVM_SNAPSHOT_SHEET"] == "update" {
                prompt = shutDownPrompt(version: version)
            }
            return
        }
        guard Self.isConfigured else { return }
        let controller = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
        self.controller = controller
        canCheckObservation = controller.updater.observe(\.canCheckForUpdates, options: [.initial, .new]) { [weak self] updater, _ in
            MainActor.assumeIsolated { self?.canCheck = updater.canCheckForUpdates }
        }
    }

    private var running: [VMConfiguration] {
        model.machines.filter { model.state(of: $0.id) != .stopped }
    }

    /// The menu command. While VMs run, only looks for an update, so nothing
    /// downloads that would install under them when the app quits.
    func checkForUpdates() {
        guard let updater = controller?.updater else { return }
        if running.isEmpty {
            updater.checkForUpdates()
        } else {
            askedByUser = true
            updater.checkForUpdateInformation()
        }
    }

    /// The toolbar button for a waiting update.
    func installWaitingUpdate() {
        guard let version = waitingVersion else { return }
        if running.isEmpty {
            install()
        } else {
            prompt = shutDownPrompt(version: version)
        }
    }

    /// Asks every running VM to shut down, then installs the waiting update.
    func shutDownAndInstall() {
        guard !shuttingDown else { return }
        shuttingDown = true
        for machine in running { model.shutDown(machine.id) }
        Task {
            let deadline = ContinuousClock.now + .seconds(120)
            while !running.isEmpty, ContinuousClock.now < deadline {
                try? await Task.sleep(for: .milliseconds(500))
            }
            shuttingDown = false
            let remaining = running
            guard remaining.isEmpty else {
                let names = remaining.map(\.name).formatted(.list(type: .and))
                prompt = Prompt(
                    kind: .notice,
                    title: "The update is waiting",
                    message: "\(names) did not shut down. Shut down Linux from inside it, or use Force Stop, then click Update again."
                )
                return
            }
            install()
        }
    }

    private func install() {
        waitingVersion = nil
        if let install = postponedInstall {
            postponedInstall = nil
            install()
        } else {
            controller?.updater.checkForUpdates()
        }
    }

    private func shutDownPrompt(version: String) -> Prompt {
        let names = running.map(\.name)
        let subject = names.isEmpty ? "Your virtual machines" : names.formatted(.list(type: .and))
        return Prompt(
            kind: .shutDown,
            title: "Install Linux VM \(version)?",
            message: "\(subject) will shut down first, as if you pressed the power button in Linux. The update can't install while a virtual machine is running."
        )
    }

    // MARK: SPUUpdaterDelegate

    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate item: SUAppcastItem, updateCheck: SPUUpdateCheck) throws {
        guard updateCheck != .updateInformation, !running.isEmpty else { return }
        waitingVersion = item.displayVersionString
        throw NSError(domain: "dev.linuxvm.updates", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "Shut down your virtual machines to install Linux VM \(item.displayVersionString). The Update button in the Linux VM window does that for you.",
        ])
    }

    func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        guard askedByUser else { return }
        askedByUser = false
        waitingVersion = item.displayVersionString
        installWaitingUpdate()
    }

    func updaterDidNotFindUpdate(_ updater: SPUUpdater, error: any Error) {
        guard askedByUser else { return }
        askedByUser = false
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        prompt = Prompt(kind: .notice, title: "Linux VM is up to date", message: "Version \(version) is the newest version available.")
    }

    func updater(_ updater: SPUUpdater, didAbortWithError error: any Error) {
        guard askedByUser else { return }
        let error = error as NSError
        if error.domain == SUSparkleErrorDomain, error.code == Int(SUError.noUpdateError.rawValue) {
            updaterDidNotFindUpdate(updater, error: error)
            return
        }
        askedByUser = false
        prompt = Prompt(kind: .notice, title: "Couldn't check for updates", message: error.localizedDescription)
    }

    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem, untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        guard !running.isEmpty else { return false }
        postponedInstall = installHandler
        waitingVersion = item.displayVersionString
        prompt = shutDownPrompt(version: item.displayVersionString)
        return true
    }
}
