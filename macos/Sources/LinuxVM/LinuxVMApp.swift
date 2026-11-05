import LinuxVMCore
import SwiftUI

@main
struct LinuxVMApp: App {
    @State private var model: LibraryModel
    @State private var updates: UpdateController
    @State private var sheet: LibrarySheet?

    init() {
        let model = LibraryModel()
        _model = State(initialValue: model)
        _updates = State(initialValue: UpdateController(model: model))
    }

    /// The notices the build writes for every component the app ships.
    static let notices = Bundle.main.url(forResource: "NOTICES", withExtension: "txt", subdirectory: "Licenses")

    var body: some Scene {
        Window("Linux VM", id: "library") {
            LibraryView(model: model, updates: updates, sheet: $sheet)
                .frame(minWidth: 780, minHeight: 540)
                .onAppear {
                    if let initial = ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_SHEET"] {
                        sheet = LibrarySheet(rawValue: initial)
                    }
                    WindowSnapshot.scheduleIfRequested()
                }
        }
        .defaultSize(width: 920, height: 640)
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Check for Updates…") { updates.checkForUpdates() }
                    .disabled(!updates.canCheck)
            }
            CommandGroup(replacing: .newItem) {
                Button("New Virtual Machine…") { sheet = .create }
                    .keyboardShortcut("n")
                Button("Import Disk…") { sheet = .importDisk }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
            }
            CommandGroup(after: .help) {
                Button("Check Runtime…") { sheet = .runtime }
                Button("Third-Party Licenses") {
                    if let notices = Self.notices { NSWorkspace.shared.open(notices) }
                }
                .disabled(Self.notices == nil)
            }
        }
    }
}

enum LibrarySheet: String, Identifiable {
    case create
    case importDisk
    case runtime

    var id: String { rawValue }
}

struct LibraryView: View {
    @Bindable var model: LibraryModel
    @Bindable var updates: UpdateController
    @Binding var sheet: LibrarySheet?
    @State private var renaming: VMConfiguration?
    @State private var deleting: VMConfiguration?

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selection) {
                ForEach(model.machines) { machine in
                    MachineRow(machine: machine, state: model.state(of: machine.id))
                        .tag(machine.id)
                }
            }
            // Right-clicking a row acts on that VM, even when another one is selected.
            .contextMenu(forSelectionType: String.self) { ids in
                if let id = ids.first, let machine = model.machine(id) {
                    MachineContextMenu(model: model, machine: machine,
                                       rename: { renaming = machine }, delete: { deleting = machine })
                }
            }
            .sheet(item: $renaming) { machine in
                RenameMachineSheet(model: model, machine: machine)
            }
            .deleteConfirmation($deleting, model: model)
            .onAppear(perform: showRequestedSnapshotSheet)
            .navigationSplitViewColumnWidth(min: 220, ideal: 240)
            .overlay {
                if model.machines.isEmpty {
                    ContentUnavailableView {
                        Label("No Virtual Machines", systemImage: "desktopcomputer")
                    } description: {
                        Text("Create one from a Linux installer image, such as Ubuntu or Fedora.")
                    } actions: {
                        Button("New Virtual Machine…") { sheet = .create }
                    }
                }
            }
            .toolbar {
                ToolbarItem {
                    Menu {
                        Button("New Virtual Machine…") { sheet = .create }
                        Button("Import Disk…") { sheet = .importDisk }
                    } label: {
                        Label("Add", systemImage: "plus")
                    }
                }
            }
        } detail: {
            if let id = model.selection, let machine = model.machine(id) {
                MachineDetailView(model: model, machine: machine)
                    .id(id)
            } else {
                ContentUnavailableView("No Selection", systemImage: "sidebar.left")
            }
        }
        .toolbar {
            if let version = updates.waitingVersion {
                ToolbarItem(placement: .primaryAction) {
                    Button(action: updates.installWaitingUpdate) {
                        Label(updates.shuttingDown ? "Shutting Down…" : "Update to \(version)",
                              systemImage: updates.shuttingDown ? "hourglass" : "arrow.down.circle")
                    }
                    .labelStyle(.titleAndIcon)
                    .disabled(updates.shuttingDown)
                    .help("Install Linux VM \(version). Running virtual machines shut down first.")
                }
            }
        }
        .sheet(item: $sheet) { kind in
            switch kind {
            case .create: NewMachineSheet(model: model)
            case .importDisk: ImportDiskSheet(model: model)
            case .runtime: RuntimeCheckSheet(runtime: model.runtime)
            }
        }
        .alert(
            updates.prompt?.title ?? "",
            isPresented: Binding(get: { updates.prompt != nil }, set: { if !$0 { updates.prompt = nil } }),
            presenting: updates.prompt
        ) { prompt in
            if prompt.kind == .shutDown {
                Button("Shut Down and Install", action: updates.shutDownAndInstall)
                Button("Later", role: .cancel) {}
            } else {
                Button("OK", role: .cancel) {}
            }
        } message: { prompt in
            Text(prompt.message)
        }
        .alert("Something went wrong", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    /// Window snapshots: LINUXVM_SNAPSHOT_SHEET=rename or delete opens that sheet for the selected VM.
    private func showRequestedSnapshotSheet() {
        guard let machine = model.selection.flatMap(model.machine) else { return }
        switch ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_SHEET"] {
        case "rename": renaming = machine
        case "delete": deleting = machine
        default: break
        }
    }
}

/// Quick actions for a VM in the sidebar, matching the buttons on its page.
struct MachineContextMenu: View {
    let model: LibraryModel
    let machine: VMConfiguration
    let rename: () -> Void
    let delete: () -> Void

    var body: some View {
        let state = model.state(of: machine.id)
        let busy = model.busy.contains(machine.id)
        if state == .stopped {
            Button("Start") { model.start(machine.id) }
                .disabled(busy)
        } else {
            Button("Shut Down") { model.shutDown(machine.id) }
                .disabled(busy || state != .running)
            Button("Force Stop", role: .destructive) { model.forceStop(machine.id) }
        }
        Divider()
        Button("Rename…", action: rename)
        Button("Show in Finder") { showInFinder(model: model, id: machine.id) }
        Divider()
        Button("Delete…", role: .destructive, action: delete)
            .disabled(state != .stopped || busy)
    }
}

@MainActor
func showInFinder(model: LibraryModel, id: String) {
    NSWorkspace.shared.activateFileViewerSelecting([model.library.directory(for: id)])
}

extension View {
    /// Asks before moving a VM to the Trash, the same way wherever Delete is offered.
    func deleteConfirmation(_ machine: Binding<VMConfiguration?>, model: LibraryModel) -> some View {
        confirmationDialog(
            "Delete “\(machine.wrappedValue?.name ?? "")”?",
            isPresented: Binding(get: { machine.wrappedValue != nil }, set: { if !$0 { machine.wrappedValue = nil } }),
            presenting: machine.wrappedValue
        ) { target in
            Button("Move to Trash", role: .destructive) { model.delete(target.id) }
        } message: { _ in
            Text("The VM's disk and settings move to the Trash.")
        }
    }
}

struct MachineRow: View {
    let machine: VMConfiguration
    let state: VMState

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "desktopcomputer")
                .font(.title2)
                .foregroundStyle(.secondary)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(machine.name)
                    .lineLimit(1)
                HStack(spacing: 5) {
                    StateDot(state: state)
                    Text(state.label)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 3)
    }
}

struct StateDot: View {
    let state: VMState

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 7, height: 7)
    }

    private var color: Color {
        switch state {
        case .running: .green
        case .starting, .stopping, .paused: .orange
        case .stopped: .secondary.opacity(0.5)
        }
    }
}
