struct StorageVolume: Equatable, Sendable {
    let mountPath: String
    let device: Int32
    let isBoot: Bool
}

enum StoragePathKind: CaseIterable, Sendable {
    case machine, disc, sharedFolder
}

struct StorageWatch: Equatable, Sendable {
    let path: String
    let volume: StorageVolume
}

struct StoragePolicy: Sendable {
    enum Action: Equatable {
        case dissent(String)
        case ejectDisc
        case stopVM
        case logSharedFolderLoss
    }

    let name: String
    var machine: StorageWatch
    var disc: StorageWatch?
    private(set) var discFile: String?
    var sharedFolder: StorageWatch?

    func watch(_ kind: StoragePathKind) -> StorageWatch? {
        switch kind {
        case .machine: machine
        case .disc: disc
        case .sharedFolder: sharedFolder
        }
    }

    func actions(for volume: StorageVolume, polite: Bool) -> [Action] {
        actions(for: StoragePathKind.allCases.filter { kind in
            guard let watch = watch(kind), !watch.volume.isBoot, !volume.isBoot else { return false }
            return watch.volume.device == volume.device && watch.volume.mountPath == volume.mountPath
        }, polite: polite)
    }

    func actions(for kinds: [StoragePathKind], polite: Bool) -> [Action] {
        if kinds.contains(.machine) {
            return polite ? [.dissent("Linux VM “\(name)” is running from this drive. Shut it down first.")] : [.stopVM]
        }
        if polite, kinds.contains(.sharedFolder) {
            return [.dissent("This drive is shared with Linux VM “\(name)”. Shut it down first.")]
        }
        var result: [Action] = []
        if kinds.contains(.disc) { result.append(.ejectDisc) }
        if !polite, kinds.contains(.sharedFolder) { result.append(.logSharedFolderLoss) }
        return result
    }

    mutating func updateDisc(file: String?, resolved: StorageWatch?) -> Bool {
        guard file != discFile else { return false }
        discFile = file
        disc = resolved
        return true
    }

    static func isLost(_ watch: StorageWatch, currentDevice: Int32?) -> Bool {
        !watch.volume.isBoot && currentDevice != watch.volume.device
    }

    static func contains(_ path: String, mountPath: String) -> Bool {
        path == mountPath || path.hasPrefix(mountPath == "/" ? "/" : mountPath + "/")
    }

    /// A disc inserted while the VM runs is an fd set (`/dev/fdset/N`); its
    /// `opaque` holds the image's path.
    static func installerPath(_ file: String, fdsets: [[String: Any]]) -> String? {
        guard file.hasPrefix("/dev/fdset/"), let id = Int(file.dropFirst("/dev/fdset/".count)) else { return file }
        let set = fdsets.first { $0["fdset-id"] as? Int == id }
        let fds = set?["fds"] as? [[String: Any]] ?? []
        return fds.lazy.compactMap { $0["opaque"] as? String }.first { $0.hasPrefix("/") }
    }

    static func installerFile(in blocks: [[String: Any]]) -> String? {
        let drive = blocks.first { block in
            block["device"] as? String == "install" ||
                (block["qdev"] as? String)?.split(separator: "/").last == "install-cd"
        }
        guard let inserted = drive?["inserted"] as? [String: Any],
              let file = inserted["file"] as? String, !file.isEmpty else { return nil }
        return file
    }
}
