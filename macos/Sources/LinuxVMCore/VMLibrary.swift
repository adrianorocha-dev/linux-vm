import Darwin
import ImageIO
import Foundation

public enum VMState: String, Codable, Sendable {
    case stopped
    case starting
    case running
    case paused
    case stopping
}

/// Written by the supervisor while it owns a VM; removed when it exits.
public struct RunState: Codable, Sendable {
    public var supervisorPID: Int32
    public var qemuPID: Int32?
    public var phase: VMState
    public var controlSocket: String?
    public var startedAt: Date
}

public struct VMStatus: Sendable {
    public var state: VMState
    public var run: RunState?
}

public enum LibraryError: LocalizedError {
    case notFound(String)
    case running(String)
    case failed(String)

    public var errorDescription: String? {
        switch self {
        case .notFound(let name): "No VM named or identified as “\(name)”."
        case .running(let name): "“\(name)” is running. Shut it down first."
        case .failed(let message): message
        }
    }
}

/// VMs on disk: one folder per VM under `<root>/VMs/<id>`, holding
/// `config.json`, the disk, the UEFI variable store and `logs/`.
public struct VMLibrary: Sendable {
    public let root: URL

    public init(root: URL = VMLibrary.defaultRoot) {
        self.root = root
    }

    public static var defaultRoot: URL {
        if let override = ProcessInfo.processInfo.environment["LINUXVM_LIBRARY"], override.hasPrefix("/") {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Application Support/Linux VM", directoryHint: .isDirectory)
    }

    public var machinesDirectory: URL { root.appending(path: "VMs", directoryHint: .isDirectory) }

    public func directory(for id: String) -> URL { machinesDirectory.appending(path: id, directoryHint: .isDirectory) }
    public func configurationURL(for id: String) -> URL { directory(for: id).appending(path: "config.json") }
    public func logsDirectory(for id: String) -> URL { directory(for: id).appending(path: "logs", directoryHint: .isDirectory) }
    public func diskURL(for configuration: VMConfiguration) -> URL { directory(for: configuration.id).appending(path: configuration.diskFileName) }
    public func variablesURL(for id: String) -> URL { directory(for: id).appending(path: "efi-vars.fd") }
    public func scrollScaleURL(for id: String) -> URL { directory(for: id).appending(path: "scroll-scale") }
    func runStateURL(for id: String) -> URL { directory(for: id).appending(path: "run.json") }
    func lockURL(for id: String) -> URL { directory(for: id).appending(path: "lock") }

    // MARK: Listing and lookup

    public func list() -> [VMConfiguration] {
        let ids = (try? FileManager.default.contentsOfDirectory(atPath: machinesDirectory.path)) ?? []
        return ids.compactMap { try? load(id: $0) }
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    public func load(id: String) throws -> VMConfiguration {
        guard UUID(uuidString: id) != nil else { throw LibraryError.notFound(id) }
        let data = try Data(contentsOf: configurationURL(for: id))
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let configuration = try decoder.decode(VMConfiguration.self, from: data)
        guard configuration.id == id else { throw LibraryError.failed("The configuration in \(id) names another VM.") }
        return configuration
    }

    /// Finds a VM by identifier, identifier prefix or exact name.
    public func find(_ reference: String) throws -> VMConfiguration {
        let machines = list()
        if let match = machines.first(where: { $0.id.caseInsensitiveCompare(reference) == .orderedSame || $0.name == reference }) {
            return match
        }
        let prefixed = machines.filter { $0.id.lowercased().hasPrefix(reference.lowercased()) }
        if prefixed.count == 1 { return prefixed[0] }
        throw LibraryError.notFound(reference)
    }

    public func save(_ configuration: VMConfiguration) throws {
        try configuration.validate()
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(configuration).write(to: configurationURL(for: configuration.id), options: .atomic)
        try writeScrollScale(configuration)
    }

    /// The running QEMU re-reads this file at the start of every scroll.
    public func writeScrollScale(_ configuration: VMConfiguration) throws {
        try "\(configuration.scrollScale)\n".write(to: scrollScaleURL(for: configuration.id), atomically: true, encoding: .utf8)
    }

    // MARK: Creating

    public func create(name: String, installMedia: String?, cpuCount: Int, memoryMiB: Int, diskGiB: Int) throws -> VMConfiguration {
        guard (8...4096).contains(diskGiB) else { throw ConfigurationError.invalid("The disk must be 8 to 4096 GiB.") }
        if let installMedia, !FileManager.default.fileExists(atPath: installMedia) {
            throw ConfigurationError.invalid("The installer image does not exist: \(installMedia)")
        }
        let configuration = VMConfiguration(
            name: name, cpuCount: cpuCount, memoryMiB: memoryMiB,
            diskFileName: "disk.img", diskFormat: .raw, installMedia: installMedia)
        try configuration.validate()
        try prepareDirectory(for: configuration) { directory in
            let disk = directory.appending(path: configuration.diskFileName)
            try Self.createSparseFile(disk, bytes: UInt64(diskGiB) << 30)
        }
        return configuration
    }

    /// Clones an existing disk (raw or qcow2) and, optionally, its UEFI
    /// variable store. APFS clones cost no space until either copy changes.
    public func importDisk(name: String, disk source: URL, variables: URL?, cpuCount: Int, memoryMiB: Int) throws -> VMConfiguration {
        let format = try Self.detectFormat(source)
        let configuration = VMConfiguration(
            name: name, cpuCount: cpuCount, memoryMiB: memoryMiB,
            diskFileName: format == .raw ? "disk.img" : "disk.qcow2", diskFormat: format)
        try configuration.validate()
        try prepareDirectory(for: configuration) { directory in
            try Self.clone(source, to: directory.appending(path: configuration.diskFileName))
            if let variables {
                try Self.clone(variables, to: directory.appending(path: "efi-vars.fd"))
            }
        }
        return configuration
    }

    private func prepareDirectory(for configuration: VMConfiguration, populate: (URL) throws -> Void) throws {
        let fileManager = FileManager.default
        try fileManager.createDirectory(at: machinesDirectory, withIntermediateDirectories: true)
        let partial = machinesDirectory.appending(path: ".\(configuration.id).partial", directoryHint: .isDirectory)
        try? fileManager.removeItem(at: partial)
        try fileManager.createDirectory(at: partial.appending(path: "logs"), withIntermediateDirectories: true,
                                        attributes: [.posixPermissions: 0o700])
        do {
            try populate(partial)
            let variables = partial.appending(path: "efi-vars.fd")
            if !fileManager.fileExists(atPath: variables.path) {
                try Self.createSparseFile(variables, bytes: 64 << 20)
            }
            try fileManager.moveItem(at: partial, to: directory(for: configuration.id))
            try save(configuration)
        } catch {
            try? fileManager.removeItem(at: partial)
            try? fileManager.removeItem(at: directory(for: configuration.id))
            throw error
        }
    }

    public func delete(id: String) throws {
        let configuration = try load(id: id)
        guard status(id: id).state == .stopped else { throw LibraryError.running(configuration.name) }
        try FileManager.default.trashItem(at: directory(for: id), resultingItemURL: nil)
    }

    public func diskSize(of configuration: VMConfiguration) -> (logical: UInt64, allocated: UInt64)? {
        let url = diskURL(for: configuration)
        guard let values = try? url.resourceValues(forKeys: [.fileSizeKey, .totalFileAllocatedSizeKey]),
              let logical = values.fileSize else { return nil }
        return (UInt64(logical), UInt64(values.totalFileAllocatedSize ?? 0))
    }

    /// Grows a raw disk while the VM is stopped. The guest grows its
    /// partition itself (Ubuntu's growpart, or the Disks app).
    public func growDisk(of configuration: VMConfiguration, toGiB gib: Int) throws {
        guard configuration.diskFormat == .raw else { throw LibraryError.failed("Only raw disks can be grown here.") }
        guard status(id: configuration.id).state == .stopped else { throw LibraryError.running(configuration.name) }
        let bytes = UInt64(gib) << 30
        guard let current = diskSize(of: configuration)?.logical, bytes > current, gib <= 4096 else {
            throw ConfigurationError.invalid("The new size must be larger than the current disk and at most 4096 GiB.")
        }
        let handle = try FileHandle(forWritingTo: diskURL(for: configuration))
        defer { try? handle.close() }
        try handle.truncate(atOffset: bytes)
    }

    // MARK: Status

    /// A VM runs while its supervisor holds the folder's lock.
    public func status(id: String) -> VMStatus {
        let path = lockURL(for: id).path
        let descriptor = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { return VMStatus(state: .stopped, run: nil) }
        defer { close(descriptor) }
        if flock(descriptor, LOCK_EX | LOCK_NB) == 0 {
            flock(descriptor, LOCK_UN)
            return VMStatus(state: .stopped, run: nil)
        }
        let run = readRunState(id: id)
        return VMStatus(state: run?.phase ?? .starting, run: run)
    }

    func readRunState(id: String) -> RunState? {
        guard let data = try? Data(contentsOf: runStateURL(for: id)) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(RunState.self, from: data)
    }

    func writeRunState(_ state: RunState, id: String) {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try? encoder.encode(state).write(to: runStateURL(for: id), options: .atomic)
    }

    // MARK: Control of a running VM

    func control(id: String) throws -> QMPClient {
        guard let socket = status(id: id).run?.controlSocket else {
            throw LibraryError.failed("The VM is not running.")
        }
        return try QMPClient(socketPath: socket)
    }

    /// Asks Linux to shut down, as the power button would. It stays a
    /// request: Linux may wait for unsaved work, and pressing it again must
    /// not stop QEMU. The supervisor's own SIGTERM path is the one with a
    /// deadline.
    public func requestShutdown(id: String) throws {
        try control(id: id).execute("system_powerdown")
    }

    /// Stops QEMU at once. Unsaved guest data is lost.
    public func forceStop(id: String) throws {
        if let pid = status(id: id).run?.qemuPID, pid > 1 {
            kill(pid, SIGKILL)
        } else {
            try control(id: id).execute("quit")
        }
    }

    public func insertInstallMedia(id: String, path: String) throws {
        try control(id: id).execute("blockdev-change-medium", arguments: [
            "id": "install-cd", "filename": path, "format": "raw", "read-only-mode": "read-only",
        ])
    }

    public func ejectInstallMedia(id: String) throws {
        try control(id: id).execute("eject", arguments: ["id": "install-cd", "force": true])
    }

    /// Saves the guest display as PNG. The runtime has no libpng, so QEMU
    /// writes PPM and this converts it.
    public func screenshot(id: String, to path: String) throws {
        let ppm = URL(fileURLWithPath: NSTemporaryDirectory()).appending(path: "linuxvm-\(UUID().uuidString).ppm")
        defer { try? FileManager.default.removeItem(at: ppm) }
        try control(id: id).execute("screendump", arguments: ["filename": ppm.path])
        try Self.convertPPMToPNG(ppm, to: URL(fileURLWithPath: path))
    }

    static func convertPPMToPNG(_ source: URL, to destination: URL) throws {
        let data = try Data(contentsOf: source)
        var fields: [String] = []
        var index = data.startIndex
        while fields.count < 4, index < data.endIndex {
            while index < data.endIndex, [0x20, 0x0A, 0x0D, 0x09].contains(data[index]) { index += 1 }
            let start = index
            while index < data.endIndex, ![0x20, 0x0A, 0x0D, 0x09].contains(data[index]) { index += 1 }
            fields.append(String(decoding: data[start..<index], as: UTF8.self))
        }
        index += 1
        guard fields.count == 4, fields[0] == "P6", let width = Int(fields[1]), let height = Int(fields[2]), fields[3] == "255",
              width > 0, height > 0, data.endIndex - index >= width * height * 3 else {
            throw LibraryError.failed("QEMU wrote an unexpected screenshot format.")
        }
        let pixels = data[index..<(index + width * height * 3)]
        guard let provider = CGDataProvider(data: Data(pixels) as CFData),
              let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 24, bytesPerRow: width * 3,
                                  space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                                  provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent),
              let output = CGImageDestinationCreateWithURL(destination as CFURL, "public.png" as CFString, 1, nil) else {
            throw LibraryError.failed("Cannot convert the screenshot.")
        }
        CGImageDestinationAddImage(output, image, nil)
        guard CGImageDestinationFinalize(output) else { throw LibraryError.failed("Cannot write \(destination.path)") }
    }

    // MARK: Files

    static func createSparseFile(_ url: URL, bytes: UInt64) throws {
        guard FileManager.default.createFile(atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            throw LibraryError.failed("Cannot create \(url.path)")
        }
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.truncate(atOffset: bytes)
    }

    static func clone(_ source: URL, to destination: URL) throws {
        if clonefile(source.path, destination.path, 0) != 0 {
            try FileManager.default.copyItem(at: source, to: destination)
        }
        chmod(destination.path, 0o600)
    }

    static func detectFormat(_ url: URL) throws -> DiskFormat {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let magic = try handle.read(upToCount: 4) ?? Data()
        return magic == Data([0x51, 0x46, 0x49, 0xFB]) ? .qcow2 : .raw
    }
}
