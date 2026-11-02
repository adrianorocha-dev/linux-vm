import Foundation
import LinuxVMCore
import Observation

@MainActor
@Observable
final class LibraryModel {
    let library = VMLibrary()
    let runtime = Runtime.locate()
    let host = HostResources.current

    private(set) var machines: [VMConfiguration] = []
    private(set) var states: [String: VMState] = [:]
    /// Operations in flight, so buttons can show progress and stay disabled.
    private(set) var busy: Set<String> = []
    var selection: String?
    var errorMessage: String?
    private var refreshTask: Task<Void, Never>?

    init() {
        reload()
        selection = machines.first?.id
        refreshTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                self?.refreshStates()
            }
        }
    }

    func reload() {
        machines = library.list()
        refreshStates()
        if let selection, !machines.contains(where: { $0.id == selection }) {
            self.selection = machines.first?.id
        }
    }

    func refreshStates() {
        var updated: [String: VMState] = [:]
        for machine in machines {
            updated[machine.id] = library.status(id: machine.id).state
        }
        if updated != states { states = updated }
    }

    func state(of id: String) -> VMState { states[id] ?? .stopped }
    func machine(_ id: String) -> VMConfiguration? { machines.first { $0.id == id } }

    // MARK: Editing

    /// Saves a change at once; running VMs pick up name and scroll speed live.
    func update(_ id: String, _ change: (inout VMConfiguration) -> Void) {
        guard var configuration = machine(id) else { return }
        change(&configuration)
        do {
            try library.save(configuration)
            if let index = machines.firstIndex(where: { $0.id == id }) { machines[index] = configuration }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: Lifecycle

    func start(_ id: String) {
        perform(id) { library, runtime in try library.start(id: id, runtime: runtime) }
    }

    func shutDown(_ id: String) {
        perform(id) { library, _ in try library.requestShutdown(id: id) }
    }

    func forceStop(_ id: String) {
        perform(id) { library, _ in try library.forceStop(id: id) }
    }

    func insertMedia(_ id: String, path: String) {
        update(id) { $0.installMedia = path }
        guard state(of: id) == .running else { return }
        perform(id) { library, _ in try library.insertInstallMedia(id: id, path: path) }
    }

    func ejectMedia(_ id: String) {
        update(id) { $0.installMedia = nil }
        guard state(of: id) == .running else { return }
        perform(id) { library, _ in try library.ejectInstallMedia(id: id) }
    }

    func delete(_ id: String) {
        perform(id) { library, _ in try library.delete(id: id) }
    }

    func growDisk(_ id: String, toGiB gib: Int) {
        guard let configuration = machine(id) else { return }
        perform(id) { library, _ in try library.growDisk(of: configuration, toGiB: gib) }
    }

    func create(name: String, installMedia: String, cpuCount: Int, memoryMiB: Int, diskGiB: Int, startAfterwards: Bool) {
        let library = library
        Task {
            do {
                let configuration = try await Task.detached {
                    try library.create(name: name, installMedia: installMedia, cpuCount: cpuCount,
                                       memoryMiB: memoryMiB, diskGiB: diskGiB)
                }.value
                reload()
                selection = configuration.id
                if startAfterwards { start(configuration.id) }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func importDisk(name: String, disk: URL, variables: URL?, cpuCount: Int, memoryMiB: Int) {
        let library = library
        Task {
            do {
                let configuration = try await Task.detached {
                    try library.importDisk(name: name, disk: disk, variables: variables, cpuCount: cpuCount, memoryMiB: memoryMiB)
                }.value
                reload()
                selection = configuration.id
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func perform(_ id: String, _ operation: @escaping @Sendable (VMLibrary, Runtime) throws -> Void) {
        guard !busy.contains(id) else { return }
        busy.insert(id)
        let library = library
        let runtime = runtime
        Task {
            do {
                try await Task.detached { try operation(library, runtime) }.value
            } catch {
                errorMessage = error.localizedDescription
            }
            busy.remove(id)
            reload()
        }
    }

    // MARK: Presentation helpers

    var memoryChoices: [Int] {
        [2048, 3072, 4096, 6144, 8192, 12288, 16384, 24576, 32768, 49152, 65536]
            .filter { $0 <= host.maximumMemoryMiB }
    }

    func diskDescription(_ configuration: VMConfiguration) -> String {
        guard let size = library.diskSize(of: configuration) else { return "Missing" }
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        let used = formatter.string(fromByteCount: Int64(size.allocated))
        switch configuration.diskFormat {
        case .raw:
            let capacity = formatter.string(fromByteCount: Int64(size.logical))
            return "\(capacity) disk, \(used) used on the Mac"
        case .qcow2:
            return "QCOW2 disk, \(used) used on the Mac"
        }
    }
}

extension VMState {
    var label: String {
        switch self {
        case .stopped: "Stopped"
        case .starting: "Starting"
        case .running: "Running"
        case .paused: "Paused"
        case .stopping: "Shutting Down"
        }
    }
}

func formatMemory(_ mib: Int) -> String {
    mib % 1024 == 0 ? "\(mib / 1024) GB" : String(format: "%.1f GB", Double(mib) / 1024)
}
