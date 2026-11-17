import Foundation

public enum DiskFormat: String, Codable, Sendable, CaseIterable {
    case raw
    case qcow2
}

public struct PortForward: Codable, Equatable, Hashable, Sendable {
    public var hostPort: Int
    public var guestPort: Int

    public init(hostPort: Int, guestPort: Int) {
        self.hostPort = hostPort
        self.guestPort = guestPort
    }

    public var description: String { "127.0.0.1:\(hostPort) → guest:\(guestPort)" }
}

public struct DisplaySettings: Codable, Equatable, Sendable {
    /// Draws the macOS arrow over the guest. Off by default: the guest's own
    /// cursor then carries its shapes and was measured to follow without lag.
    public var showMacCursor = false
    /// Full screen hides the macOS menu bar and Dock.
    public var immersive = true
    /// Full screen extends beside the camera housing. GNOME's top bar has no
    /// notch support, so its clock would sit behind the housing.
    public var coverNotch = false

    public init() {}
}

/// What Linux may reach on the Mac. A VM made with the Hardened option
/// starts with every one of these closed.
public struct IsolationSettings: Codable, Equatable, Sendable {
    /// Linux reaches services listening only on the Mac's loopback (127.0.0.1)
    /// through the host address, 10.0.2.2.
    public var macServices = true
    /// Linux reaches the networks around the Mac: its LAN, VPNs, and
    /// private, link-local and multicast addresses. The internet stays reachable.
    public var localNetwork = true
    /// The clipboard is shared both ways.
    public var clipboard = true
    /// Linux records from the Mac's microphone.
    public var microphone = true
    /// Linux can change files in the shared Mac folder.
    public var sharedFolderWritable = true

    public init() {}

    public static let hardened: IsolationSettings = {
        var settings = IsolationSettings()
        settings.macServices = false
        settings.localNetwork = false
        settings.clipboard = false
        settings.microphone = false
        settings.sharedFolderWritable = false
        return settings
    }()

    public var isHardened: Bool { self == .hardened }

    enum CodingKeys: String, CodingKey {
        case macServices, localNetwork, clipboard, microphone, sharedFolderWritable
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        macServices = try c.decodeIfPresent(Bool.self, forKey: .macServices) ?? true
        localNetwork = try c.decodeIfPresent(Bool.self, forKey: .localNetwork) ?? true
        clipboard = try c.decodeIfPresent(Bool.self, forKey: .clipboard) ?? true
        microphone = try c.decodeIfPresent(Bool.self, forKey: .microphone) ?? true
        sharedFolderWritable = try c.decodeIfPresent(Bool.self, forKey: .sharedFolderWritable) ?? true
    }
}

public struct VMConfiguration: Codable, Equatable, Identifiable, Sendable {
    public static let currentFormat = 1
    public static let defaultScrollScale = 0.4

    public var format = VMConfiguration.currentFormat
    public let id: String
    public var name: String
    public var cpuCount: Int
    public var memoryMiB: Int
    public var diskFileName: String
    public var diskFormat: DiskFormat
    public var installMedia: String?
    public var sharedFolder: String?
    public var display = DisplaySettings()
    /// Touch-scroll travel relative to Try Omarchy's. GNOME has no touchpad
    /// scroll factor, so the host applies Omarchy's 0.4 instead.
    public var scrollScale = VMConfiguration.defaultScrollScale
    public var pauseDuringSleep = true
    public var portForwards: [PortForward] = []
    public var isolation = IsolationSettings()
    public var createdAt: Date

    public init(
        id: String = UUID().uuidString,
        name: String,
        cpuCount: Int,
        memoryMiB: Int,
        diskFileName: String,
        diskFormat: DiskFormat,
        installMedia: String? = nil,
        isolation: IsolationSettings = IsolationSettings(),
        createdAt: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.cpuCount = cpuCount
        self.memoryMiB = memoryMiB
        self.diskFileName = diskFileName
        self.diskFormat = diskFormat
        self.installMedia = installMedia
        self.isolation = isolation
        self.createdAt = createdAt
    }

    enum CodingKeys: String, CodingKey {
        case format, id, name, cpuCount, memoryMiB, diskFileName, diskFormat
        case installMedia, sharedFolder, display, scrollScale, pauseDuringSleep, portForwards, isolation, createdAt
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        format = try c.decode(Int.self, forKey: .format)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        cpuCount = try c.decode(Int.self, forKey: .cpuCount)
        memoryMiB = try c.decode(Int.self, forKey: .memoryMiB)
        diskFileName = try c.decode(String.self, forKey: .diskFileName)
        diskFormat = try c.decode(DiskFormat.self, forKey: .diskFormat)
        installMedia = try c.decodeIfPresent(String.self, forKey: .installMedia)
        sharedFolder = try c.decodeIfPresent(String.self, forKey: .sharedFolder)
        display = try c.decode(DisplaySettings.self, forKey: .display)
        scrollScale = try c.decode(Double.self, forKey: .scrollScale)
        pauseDuringSleep = try c.decodeIfPresent(Bool.self, forKey: .pauseDuringSleep) ?? true
        portForwards = try c.decode([PortForward].self, forKey: .portForwards)
        isolation = try c.decodeIfPresent(IsolationSettings.self, forKey: .isolation) ?? IsolationSettings()
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }

    /// A stable locally administered MAC address, so the guest keeps its
    /// network configuration across launches.
    public var macAddress: String {
        let hex = id.replacingOccurrences(of: "-", with: "").lowercased()
        let bytes = stride(from: 0, to: 6, by: 2).map { offset -> String in
            let start = hex.index(hex.startIndex, offsetBy: offset)
            return String(hex[start..<hex.index(start, offsetBy: 2)])
        }
        return "52:54:00:" + bytes.joined(separator: ":")
    }
}

public struct HostResources: Sendable {
    public let logicalCPUs: Int
    public let memoryMiB: Int

    public static var current: HostResources {
        HostResources(
            logicalCPUs: ProcessInfo.processInfo.activeProcessorCount,
            memoryMiB: Int(ProcessInfo.processInfo.physicalMemory / 1_048_576)
        )
    }

    public var defaultCPUs: Int { min(logicalCPUs, 8) }
    public var defaultMemoryMiB: Int { memoryMiB >= 16384 ? 8192 : 4096 }
    public var maximumMemoryMiB: Int { max(2048, memoryMiB - 4096) }
}

public enum ConfigurationError: LocalizedError, Equatable {
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case .invalid(let message): message
        }
    }
}

extension VMConfiguration {
    /// Why sharing this folder gives Linux more than it likely needs, or nil.
    /// Linux could then change files that macOS runs, such as shell profiles
    /// and login items.
    public static func sharedFolderWarning(_ path: String, home: String = NSHomeDirectory()) -> String? {
        let folder = URL(fileURLWithPath: path).standardizedFileURL.path
        let home = URL(fileURLWithPath: home).standardizedFileURL.path
        if folder == "/" || folder == "/Users" || folder == "/System" || folder == "/Applications" {
            return "This shares a system folder with Linux."
        }
        if folder == home {
            return "This shares your whole home folder with Linux, including its settings and keys."
        }
        if folder.hasPrefix(home + "/Library") || folder.hasPrefix(home + "/.") {
            return "This shares a folder where apps keep their settings and data."
        }
        return nil
    }

    public static let minimumMemoryMiB = 2048
    public static let scrollScaleRange = 0.05...4.0

    public func validate(host: HostResources = .current) throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 64 else {
            throw ConfigurationError.invalid("The name must be 1 to 64 characters.")
        }
        guard UUID(uuidString: id) != nil else {
            throw ConfigurationError.invalid("The VM identifier is invalid.")
        }
        guard (1...host.logicalCPUs).contains(cpuCount) else {
            throw ConfigurationError.invalid("CPUs must be between 1 and \(host.logicalCPUs).")
        }
        guard (Self.minimumMemoryMiB...host.maximumMemoryMiB).contains(memoryMiB) else {
            throw ConfigurationError.invalid(
                "Memory must be between \(Self.minimumMemoryMiB) and \(host.maximumMemoryMiB) MiB.")
        }
        guard Self.scrollScaleRange.contains(scrollScale) else {
            throw ConfigurationError.invalid("The scroll scale must be between 0.05 and 4.")
        }
        guard diskFileName == "disk.\(diskFormat == .raw ? "img" : "qcow2")" else {
            throw ConfigurationError.invalid("The disk file name does not match its format.")
        }
        for path in [installMedia, sharedFolder].compactMap({ $0 }) {
            guard path.hasPrefix("/"), !path.contains(","), !path.contains("\n") else {
                throw ConfigurationError.invalid("Paths must be absolute and cannot contain commas: \(path)")
            }
        }
        var hostPorts = Set<Int>()
        for forward in portForwards {
            guard (1024...65535).contains(forward.hostPort), (1...65535).contains(forward.guestPort),
                  hostPorts.insert(forward.hostPort).inserted else {
                throw ConfigurationError.invalid("Port forwards need unique host ports from 1024 to 65535.")
            }
        }
    }
}
