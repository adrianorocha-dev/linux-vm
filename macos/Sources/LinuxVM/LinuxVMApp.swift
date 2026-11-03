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

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selection) {
                ForEach(model.machines) { machine in
                    MachineRow(machine: machine, state: model.state(of: machine.id))
                        .tag(machine.id)
                }
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 240)
            .overlay {
                if model.machines.isEmpty {
                    ContentUnavailableView {
                        Label("No Virtual Machines", systemImage: "desktopcomputer")
                    } description: {
                        Text("Create one from an Ubuntu installer image.")
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
