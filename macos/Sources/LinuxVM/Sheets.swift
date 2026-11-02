import AppKit
import LinuxVMCore
import SwiftUI
import UniformTypeIdentifiers

struct NewMachineSheet: View {
    let model: LibraryModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = "Ubuntu"
    @State private var installer: URL?
    @State private var cpuCount = 4
    @State private var memoryMiB = 4096
    @State private var diskGiB = 64
    @State private var startAfterwards = true
    @State private var choosingInstaller = false

    var body: some View {
        VStack(spacing: 0) {
            SheetTitle("New Virtual Machine")
            Form {
                Section {
                    TextField("Name", text: $name)
                    LabeledContent("Installer image") {
                        HStack {
                            Text(installer?.lastPathComponent ?? "None")
                                .foregroundStyle(installer == nil ? .secondary : .primary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Button("Choose…") { choosingInstaller = true }
                        }
                    }
                } footer: {
                    HStack(spacing: 4) {
                        Text("Use an ARM64 installer, such as Ubuntu Desktop for ARM.")
                        Link("Download Ubuntu", destination: URL(string: "https://ubuntu.com/download/desktop")!)
                            .foregroundStyle(.tint)
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10)
                }
                Section("Resources") {
                    Picker("CPUs", selection: $cpuCount) {
                        ForEach(1...model.host.logicalCPUs, id: \.self) { Text("\($0)").tag($0) }
                    }
                    Picker("Memory", selection: $memoryMiB) {
                        ForEach(model.memoryChoices, id: \.self) { Text(formatMemory($0)).tag($0) }
                    }
                    Picker("Disk", selection: $diskGiB) {
                        ForEach([32, 64, 128, 256, 512], id: \.self) { Text("\($0) GB").tag($0) }
                    }
                }
                Section {
                    Toggle("Start the installer now", isOn: $startAfterwards)
                } footer: {
                    FormNote("The disk uses space on the Mac only as Linux writes to it.")
                }
            }
            .formStyle(.grouped)
            .fileImporter(isPresented: $choosingInstaller, allowedContentTypes: [UTType(filenameExtension: "iso") ?? .diskImage, .diskImage]) { result in
                if case .success(let url) = result {
                    installer = url
                }
            }
            Divider()
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Create") {
                    guard let installer else { return }
                    model.create(name: name.trimmingCharacters(in: .whitespacesAndNewlines), installMedia: installer.path,
                                 cpuCount: cpuCount, memoryMiB: memoryMiB, diskGiB: diskGiB, startAfterwards: startAfterwards)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(installer == nil || name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(16)
        }
        .frame(width: 480, height: 510)
        .navigationTitle("New Virtual Machine")
        .onAppear {
            cpuCount = model.host.defaultCPUs
            memoryMiB = model.host.defaultMemoryMiB
        }
    }
}

struct ImportDiskSheet: View {
    let model: LibraryModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = "Ubuntu"
    @State private var disk: URL?
    @State private var variables: URL?
    @State private var cpuCount = 4
    @State private var memoryMiB = 4096
    @State private var choosing: Choice?

    enum Choice { case disk, variables }

    var body: some View {
        VStack(spacing: 0) {
            SheetTitle("Import Disk")
            Form {
                Section {
                    TextField("Name", text: $name)
                    LabeledContent("Disk image") {
                        HStack {
                            Text(disk?.lastPathComponent ?? "None")
                                .foregroundStyle(disk == nil ? .secondary : .primary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Button("Choose…") { choosing = .disk }
                        }
                    }
                    LabeledContent("UEFI variables") {
                        HStack {
                            Text(variables?.lastPathComponent ?? "Optional")
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                            Button("Choose…") { choosing = .variables }
                        }
                    }
                } footer: {
                    FormNote("Raw and QCOW2 ARM64 disks work. The app keeps its own copy; on APFS the copy takes no space until either changes. Never import the disk of a VM that another app is running.")
                }
                Section("Resources") {
                    Picker("CPUs", selection: $cpuCount) {
                        ForEach(1...model.host.logicalCPUs, id: \.self) { Text("\($0)").tag($0) }
                    }
                    Picker("Memory", selection: $memoryMiB) {
                        ForEach(model.memoryChoices, id: \.self) { Text(formatMemory($0)).tag($0) }
                    }
                }
            }
            .formStyle(.grouped)
            .fileImporter(isPresented: Binding(get: { choosing != nil }, set: { if !$0 { choosing = nil } }),
                          allowedContentTypes: [.data]) { result in
                guard case .success(let url) = result else { return }
                if choosing == .variables { variables = url } else { disk = url }
                choosing = nil
            }
            Divider()
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Import") {
                    guard let disk else { return }
                    model.importDisk(name: name.trimmingCharacters(in: .whitespacesAndNewlines), disk: disk,
                                     variables: variables, cpuCount: cpuCount, memoryMiB: memoryMiB)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(disk == nil || name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(16)
        }
        .frame(width: 480, height: 460)
        .onAppear {
            cpuCount = model.host.defaultCPUs
            memoryMiB = model.host.defaultMemoryMiB
        }
    }
}

struct RuntimeCheckSheet: View {
    let runtime: Runtime
    @Environment(\.dismiss) private var dismiss
    @State private var checks: [Runtime.Check]?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Runtime")
                .font(.headline)
            if let checks {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(checks) { check in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: check.passed ? "checkmark.circle.fill" : "xmark.octagon.fill")
                                .foregroundStyle(check.passed ? .green : .red)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(check.name)
                                Text(check.detail)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                                    .truncationMode(.middle)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }
            } else {
                ProgressView("Checking…")
                    .frame(maxWidth: .infinity, minHeight: 200)
            }
            HStack {
                Spacer()
                Button("Done") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 520)
        .task {
            let runtime = runtime
            checks = await Task.detached { runtime.check() }.value
        }
    }
}

struct LogsView: View {
    let directory: URL
    @State private var log = LogFile.supervisor
    @State private var text = ""

    enum LogFile: String, CaseIterable, Identifiable {
        case supervisor = "supervisor.log"
        case qemu = "qemu.log"
        case serial = "serial.log"
        case bridges = "bridges.log"

        var id: String { rawValue }
        var title: String {
            switch self {
            case .supervisor: "Lifecycle"
            case .qemu: "QEMU"
            case .serial: "Serial Console"
            case .bridges: "Mac Bridges"
            }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Picker("Log", selection: $log) {
                    ForEach(LogFile.allCases) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
                Spacer()
                Button("Show in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([directory.appending(path: log.rawValue)])
                }
            }
            .padding(12)
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    Text(text.isEmpty ? "Nothing logged yet." : text)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(text.isEmpty ? .secondary : .primary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                    Color.clear.frame(height: 1).id("end")
                }
                .onChange(of: text) { proxy.scrollTo("end") }
            }
        }
        .task(id: log) {
            while !Task.isCancelled {
                text = Self.tail(directory.appending(path: log.rawValue))
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    /// The last 64 KiB, with terminal escape sequences removed.
    static func tail(_ url: URL) -> String {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return "" }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        try? handle.seek(toOffset: size > 65536 ? size - 65536 : 0)
        let data = (try? handle.readToEnd()) ?? Data()
        let raw = String(decoding: data, as: UTF8.self)
        return raw.replacingOccurrences(of: "\u{1B}\\[[0-9;?]*[ -/]*[@-~]|\u{1B}\\][^\u{07}\u{1B}]*(\u{07}|\u{1B}\\\\)|\r", with: "", options: .regularExpression)
    }
}

struct SheetTitle: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title)
            .font(.headline)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.top, 18)
    }
}
