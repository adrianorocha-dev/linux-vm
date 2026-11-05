import AppKit
import LinuxVMCore
import SwiftUI
import UniformTypeIdentifiers

struct MachineDetailView: View {
    let model: LibraryModel
    let machine: VMConfiguration
    @State private var tab = Tab(rawValue: ProcessInfo.processInfo.environment["LINUXVM_SNAPSHOT_TAB"] ?? "") ?? .settings

    enum Tab: String, CaseIterable, Identifiable {
        case settings = "Settings"
        case logs = "Logs"
        var id: String { rawValue }
    }

    private var state: VMState { model.state(of: machine.id) }
    private var busy: Bool { model.busy.contains(machine.id) }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            switch tab {
            case .settings: MachineSettingsForm(model: model, machine: machine, editable: state == .stopped && !busy)
            case .logs: LogsView(directory: model.library.logsDirectory(for: machine.id))
            }
        }
        .navigationTitle(machine.name)
        .toolbar(removing: .title)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Picker("View", selection: $tab) {
                    ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 14) {
            Image(systemName: "desktopcomputer")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 3) {
                Text(machine.name)
                    .font(.title2.weight(.semibold))
                HStack(spacing: 6) {
                    StateDot(state: state)
                    Text(summary)
                }
                .font(.callout)
                .foregroundStyle(.secondary)
            }
            Spacer()
            if busy {
                ProgressView().controlSize(.small)
            }
            controls
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
    }

    private var summary: String {
        "\(state.label) · \(machine.cpuCount) CPUs · \(formatMemory(machine.memoryMiB))"
    }

    @ViewBuilder
    private var controls: some View {
        switch state {
        case .stopped:
            Button {
                model.start(machine.id)
            } label: {
                Label("Start", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(busy)
        case .starting, .running, .stopping, .paused:
            HStack(spacing: 8) {
                Button {
                    model.shutDown(machine.id)
                } label: {
                    Label("Shut Down", systemImage: "power")
                }
                .controlSize(.large)
                .disabled(busy || state != .running)
                Menu {
                    Button("Force Stop", role: .destructive) { model.forceStop(machine.id) }
                } label: {
                    Image(systemName: "ellipsis")
                }
                .menuStyle(.button)
                .menuIndicator(.hidden)
                .controlSize(.large)
                .fixedSize()
                .help("Force Stop stops the VM at once. Unsaved work in Linux is lost.")
            }
        }
    }
}

struct MachineSettingsForm: View {
    let model: LibraryModel
    let machine: VMConfiguration
    let editable: Bool
    @State private var name = ""
    @State private var choosingMedia = false
    @State private var choosingFolder = false
    @State private var confirmingDelete = false
    @State private var growing = false
    @State private var newHostPort = ""
    @State private var newGuestPort = ""

    private var running: Bool { model.state(of: machine.id) != .stopped }

    var body: some View {
        Form {
            Section {
                TextField("Name", text: $name)
                    .onSubmit(commitName)
                    .onAppear { name = machine.name }
                    .onChange(of: machine.name) { _, value in name = value }
            }

            Section {
                Picker("CPUs", selection: binding(\.cpuCount)) {
                    ForEach(1...model.host.logicalCPUs, id: \.self) { Text("\($0)").tag($0) }
                }
                Picker("Memory", selection: binding(\.memoryMiB)) {
                    ForEach(memoryOptions, id: \.self) { Text(formatMemory($0)).tag($0) }
                }
                LabeledContent("Disk") {
                    HStack {
                        Text(model.diskDescription(machine))
                            .foregroundStyle(.secondary)
                        if machine.diskFormat == .raw {
                            Button("Enlarge…") { growing = true }
                                .disabled(!editable)
                        }
                    }
                }
            } header: {
                Text("Resources")
            } footer: {
                if running {
                    FormNote("Shut down the VM to change its resources, sharing and network.")
                }
            }
            .disabled(!editable)

            Section("Installer Disc") {
                LabeledContent("Image") {
                    HStack {
                        Text(machine.installMedia.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "None")
                            .foregroundStyle(machine.installMedia == nil ? .secondary : .primary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .help(machine.installMedia ?? "")
                        Button("Choose…") { choosingMedia = true }
                        if machine.installMedia != nil {
                            Button("Eject") { model.ejectMedia(machine.id) }
                        }
                    }
                }
                Text("After installing Linux, eject the disc so the VM starts from its own disk.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .fileImporter(isPresented: $choosingMedia, allowedContentTypes: [UTType(filenameExtension: "iso") ?? .diskImage, .diskImage]) { result in
                if case .success(let url) = result { model.insertMedia(machine.id, path: url.path) }
            }

            GuestToolsSection(report: model.reports[machine.id], disc: model.discGuestTools)

            Section("Sharing") {
                LabeledContent("Mac folder") {
                    HStack {
                        Text(machine.sharedFolder.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "None")
                            .foregroundStyle(machine.sharedFolder == nil ? .secondary : .primary)
                            .help(machine.sharedFolder ?? "")
                        Button("Choose…") { choosingFolder = true }
                        if machine.sharedFolder != nil {
                            Button("Stop Sharing") { model.update(machine.id) { $0.sharedFolder = nil } }
                        }
                    }
                }
                .disabled(!editable)
            }
            .fileImporter(isPresented: $choosingFolder, allowedContentTypes: [.folder]) { result in
                if case .success(let url) = result { model.update(machine.id) { $0.sharedFolder = url.path } }
            }

            Section {
                LabeledContent("Scroll speed") {
                    HStack {
                        Slider(value: Binding(
                            get: { machine.scrollScale },
                            set: { value in model.update(machine.id) { $0.scrollScale = (value * 20).rounded() / 20 } }
                        ), in: 0.1...1.0)
                            .frame(maxWidth: 220)
                        Text(machine.scrollScale.formatted(.number.precision(.fractionLength(2))))
                            .monospacedDigit()
                            .foregroundStyle(.secondary)
                            .frame(width: 36, alignment: .trailing)
                        Button("Reset") { model.update(machine.id) { $0.scrollScale = VMConfiguration.defaultScrollScale } }
                            .disabled(machine.scrollScale == VMConfiguration.defaultScrollScale)
                    }
                }
                Toggle("Hide the menu bar and Dock in full screen", isOn: binding(\.display.immersive))
                    .disabled(!editable)
                Toggle("Use the area beside the camera in full screen", isOn: binding(\.display.coverNotch))
                    .disabled(!editable)
                Toggle("Show the Mac pointer over Linux", isOn: binding(\.display.showMacCursor))
                    .disabled(!editable)
            } header: {
                Text("Display and Trackpad")
            } footer: {
                FormNote("Scroll speed applies to the next scroll, even while the VM runs. Linux doesn't know where the camera is, so anything it shows there, such as the clock in GNOME's top bar, is hidden when Linux uses that area.")
            }

            Section {
                Toggle("Pause while the Mac sleeps", isOn: binding(\.pauseDuringSleep))
            } header: {
                Text("Sleep")
            } footer: {
                FormNote("This applies the next time the Mac sleeps, even while the VM runs. When the Mac wakes, Linux sets its clock forward with guest tools 0.2.0 or later.")
            }

            Section("Network") {
                ForEach(machine.portForwards, id: \.self) { forward in
                    LabeledContent("Mac port \(String(forward.hostPort))") {
                        HStack {
                            Text("Linux port \(String(forward.guestPort))")
                                .foregroundStyle(.secondary)
                            Button {
                                model.update(machine.id) { $0.portForwards.removeAll { $0 == forward } }
                            } label: {
                                Image(systemName: "minus.circle")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                LabeledContent("Forward a port") {
                    HStack {
                        TextField("Mac", text: $newHostPort, prompt: Text("Mac"))
                            .frame(width: 70)
                        Image(systemName: "arrow.right")
                            .foregroundStyle(.secondary)
                        TextField("Linux", text: $newGuestPort, prompt: Text("Linux"))
                            .frame(width: 70)
                        Button("Add", action: addForward)
                            .disabled(Int(newHostPort) == nil || Int(newGuestPort) == nil)
                    }
                    .labelsHidden()
                }
            }
            .disabled(!editable)

            Section {
                HStack {
                    Button("Show in Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting([model.library.directory(for: machine.id)])
                    }
                    Spacer()
                    Button("Delete Virtual Machine…", role: .destructive) { confirmingDelete = true }
                        .disabled(!editable)
                }
            }
        }
        .formStyle(.grouped)
        .confirmationDialog("Delete “\(machine.name)”?", isPresented: $confirmingDelete) {
            Button("Move to Trash", role: .destructive) { model.delete(machine.id) }
        } message: {
            Text("The VM's disk and settings move to the Trash.")
        }
        .sheet(isPresented: $growing) {
            GrowDiskSheet(model: model, machine: machine)
        }
    }

    private var memoryOptions: [Int] {
        Array(Set(model.memoryChoices + [machine.memoryMiB])).sorted()
    }

    private func binding<Value>(_ keyPath: WritableKeyPath<VMConfiguration, Value>) -> Binding<Value> {
        Binding(
            get: { machine[keyPath: keyPath] },
            set: { value in model.update(machine.id) { $0[keyPath: keyPath] = value } }
        )
    }

    private func commitName() {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != machine.name else {
            name = machine.name
            return
        }
        model.update(machine.id) { $0.name = trimmed }
    }

    private func addForward() {
        guard let host = Int(newHostPort), let guest = Int(newGuestPort) else { return }
        model.update(machine.id) { configuration in
            configuration.portForwards.removeAll { $0.hostPort == host }
            configuration.portForwards.append(PortForward(hostPort: host, guestPort: guest))
        }
        newHostPort = ""
        newGuestPort = ""
    }
}

/// What a VM's guest tools last reported, compared with this app's disc.
struct GuestToolsSection: View {
    let report: GuestReport?
    let disc: String?

    private static let howToInstall = "open the LINUXVM-TOOLS disc in Linux's file manager, run sh install.sh in a terminal there, then log out and back in."

    private var discIsNewer: Bool {
        guard let report, let disc else { return false }
        return GuestToolsVersion.compare(report.package, disc) == .orderedAscending
    }

    var body: some View {
        Section {
            if let report {
                LabeledContent("Installed") {
                    HStack(spacing: 8) {
                        Text(report.package)
                        if discIsNewer, let disc {
                            Label("\(disc) on the disc", systemImage: "arrow.down.circle")
                                .foregroundStyle(.orange)
                        }
                    }
                }
                LabeledContent("Linux") {
                    Text([report.os, report.desktopLabel].compactMap { $0 }.joined(separator: ", "))
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                LabeledContent("Clipboard") {
                    Label(clipboard.text, systemImage: clipboard.symbol)
                        .foregroundStyle(clipboard.color)
                }
            } else {
                LabeledContent("Installed") {
                    Text("Not reported")
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Guest Tools")
        } footer: {
            FormNote(note)
        }
    }

    private var clipboard: (text: String, symbol: String, color: Color) {
        let gnome = report?.isGNOME ?? false
        let product = report?.desktopName == "KDE" ? "Plasma" : (report?.desktopName ?? "desktop")
        switch report?.clipboardState ?? .unknown {
        case .active: return ("On", "checkmark.circle.fill", .green)
        case .inactive: return ("Turned off", "xmark.circle", .orange)
        case .outdated: return ("Off for this \(product) version", "exclamationmark.triangle.fill", .orange)
        case .pending: return (gnome ? "Not loaded yet" : "Starts at next login", "clock", .secondary)
        case .unsupported: return ("Not available on this desktop", "xmark.circle", .orange)
        case .error: return (gnome ? "Failed to load" : "Failed to start", "exclamationmark.triangle.fill", .red)
        case .unknown: return ("Unknown", "questionmark.circle", .secondary)
        }
    }

    private var note: String {
        guard let report else {
            return "Guest tools 0.2.0 and later report here while someone is logged in to Linux. To install them, \(Self.howToInstall)"
        }
        if discIsNewer, let disc {
            return "Version \(disc) is on the Guest Tools disc. To update, \(Self.howToInstall)"
        }
        let reported = "Reported \(report.receivedAt.formatted(.relative(presentation: .named)))."
        let stillWork = "Audio, time zone and folder sharing still work."
        switch report.clipboardState {
        case .active, .unknown:
            return reported
        case .inactive:
            return report.isGNOME
                ? "Turn on LinuxVM Clipboard in Linux's Extensions app to share the clipboard. \(reported)"
                : "The shared clipboard is turned off in Linux. \(reported)"
        case .outdated:
            let version = report.desktopLabel ?? "this desktop version"
            return "These guest tools do not support \(version) yet, so the shared clipboard is off. \(stillWork) \(reported)"
        case .pending:
            return report.isGNOME
                ? "Log out of Linux and back in to load the clipboard extension. \(reported)"
                : "Log out of Linux and back in to start the shared clipboard. \(reported)"
        case .unsupported:
            let desktop = report.desktopLabel ?? "This desktop"
            return "\(desktop) offers no clipboard access the guest tools can use, so the shared clipboard is off. \(stillWork) \(reported)"
        case .error:
            return report.isGNOME
                ? "The clipboard extension failed to load; Linux's Extensions app shows its error. \(reported)"
                : "The shared clipboard failed to start. In a Linux terminal, journalctl --user -u linuxvm-clipboard shows why. \(reported)"
        }
    }
}

struct GrowDiskSheet: View {
    let model: LibraryModel
    let machine: VMConfiguration
    @Environment(\.dismiss) private var dismiss
    @State private var gib = 0

    private var currentGiB: Int {
        Int((model.library.diskSize(of: machine)?.logical ?? 0) >> 30)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Enlarge Disk")
                .font(.headline)
            Text("The disk is \(currentGiB) GB. It uses space on the Mac only as Linux writes to it. Afterwards, grow the partition inside Linux with the Disks app.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Stepper("New size: \(gib) GB", value: $gib, in: (currentGiB + 1)...4096, step: 8)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Enlarge") {
                    model.growDisk(machine.id, toGiB: gib)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 400)
        .onAppear { gib = ((currentGiB / 8) + 1) * 8 }
    }
}

/// A section footer aligned with the section's content.
struct FormNote: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10)
    }
}
