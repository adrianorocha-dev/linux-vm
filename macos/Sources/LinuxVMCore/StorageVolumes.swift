import Darwin
import DiskArbitration
import Foundation

protocol StorageVolumeMonitoring: AnyObject {
    func watch(path: String) -> StorageWatch?
    func start(queue: DispatchQueue, approve: @escaping @Sendable (StorageVolume) -> String?,
               removed: @escaping @Sendable (StorageVolume) -> Void)
    func stop()
}

func canonicalStoragePath(_ path: String) -> String {
    URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL.path
}

func storageDevice(at path: String) -> Int32? {
    var info = stat()
    return stat(path, &info) == 0 ? info.st_dev : nil
}

final class DiskArbitrationStorageVolumes: StorageVolumeMonitoring, @unchecked Sendable {
    private let session: DASession
    private let bootDevices: Set<Int32>
    private var mounted: [String: StorageVolume] = [:]
    private var wholeDisks: [String: String] = [:]
    private var approve: (@Sendable (StorageVolume) -> String?)?
    private var removed: (@Sendable (StorageVolume) -> Void)?

    init() throws {
        guard let session = DASessionCreate(kCFAllocatorDefault) else {
            throw LibraryError.failed("Cannot create a DiskArbitration session.")
        }
        self.session = session
        bootDevices = Set(["/", "/System/Volumes/Data"].compactMap { storageDevice(at: $0) })
        for url in FileManager.default.mountedVolumeURLs(includingResourceValuesForKeys: nil) ?? [] {
            if let disk = DADiskCreateFromVolumePath(kCFAllocatorDefault, session, url as CFURL) { remember(disk) }
        }
    }

    func watch(path: String) -> StorageWatch? {
        let path = canonicalStoragePath(path)
        if let volume = volume(at: path) { return StorageWatch(path: path, volume: volume) }
        // DA mount points still identify a newly inserted disc after its drive vanishes.
        if let volume = mounted.values.filter({ StoragePolicy.contains(path, mountPath: $0.mountPath) })
            .max(by: { $0.mountPath.count < $1.mountPath.count }) {
            return StorageWatch(path: path, volume: volume)
        }
        return nil
    }

    private func volume(at path: String) -> StorageVolume? {
        var info = statfs()
        guard statfs(path, &info) == 0, let device = storageDevice(at: path) else { return nil }
        let mount = withUnsafePointer(to: &info.f_mntonname) {
            $0.withMemoryRebound(to: CChar.self, capacity: Int(MAXPATHLEN)) { String(cString: $0) }
        }
        return StorageVolume(mountPath: canonicalStoragePath(mount), device: device,
                             isBoot: bootDevices.contains(device))
    }

    private func key(_ disk: DADisk) -> String? { DADiskGetBSDName(disk).map { String(cString: $0) } }

    private func remember(_ disk: DADisk) {
        guard let key = key(disk) else { return }
        if let whole = DADiskCopyWholeDisk(disk), let name = self.key(whole) { wholeDisks[key] = name }
        let description = DADiskCopyDescription(disk) as? [String: Any]
        if let url = description?[kDADiskDescriptionVolumePathKey as String] as? URL,
           let volume = volume(at: url.path) { mounted[key] = volume }
    }

    private func approval(_ disk: DADisk) -> Unmanaged<DADissenter>? {
        guard let key = key(disk) else { return nil }
        let volumes: [StorageVolume]
        if let volume = mounted[key] { volumes = [volume] }
        else { volumes = mounted.compactMap { wholeDisks[$0.key] == key ? $0.value : nil } }
        for volume in volumes {
            if let message = approve?(volume) {
                return Unmanaged.passRetained(DADissenterCreate(kCFAllocatorDefault, DAReturn(kDAReturnBusy), message as CFString))
            }
        }
        return nil
    }

    private func disappeared(_ disk: DADisk) {
        guard let key = key(disk), let volume = mounted[key] else { return }
        removed?(volume)
        mounted[key] = nil
        wholeDisks[key] = nil
    }

    private func changed(_ disk: DADisk) {
        guard let key = key(disk) else { return }
        let old = mounted.removeValue(forKey: key)
        remember(disk)
        if let old, mounted[key] != old { removed?(old) }
    }

    func start(queue: DispatchQueue, approve: @escaping @Sendable (StorageVolume) -> String?,
               removed: @escaping @Sendable (StorageVolume) -> Void) {
        self.approve = approve; self.removed = removed
        let context = Unmanaged.passUnretained(self).toOpaque()
        DARegisterDiskUnmountApprovalCallback(session, nil, { disk, context in
            Unmanaged<DiskArbitrationStorageVolumes>.fromOpaque(context!).takeUnretainedValue().approval(disk)
        }, context)
        DARegisterDiskEjectApprovalCallback(session, nil, { disk, context in
            Unmanaged<DiskArbitrationStorageVolumes>.fromOpaque(context!).takeUnretainedValue().approval(disk)
        }, context)
        DARegisterDiskDisappearedCallback(session, nil, { disk, context in
            Unmanaged<DiskArbitrationStorageVolumes>.fromOpaque(context!).takeUnretainedValue().disappeared(disk)
        }, context)
        DARegisterDiskDescriptionChangedCallback(session, nil, [kDADiskDescriptionVolumePathKey] as CFArray, { disk, _, context in
            Unmanaged<DiskArbitrationStorageVolumes>.fromOpaque(context!).takeUnretainedValue().changed(disk)
        }, context)
        DARegisterDiskAppearedCallback(session, nil, { disk, context in
            Unmanaged<DiskArbitrationStorageVolumes>.fromOpaque(context!).takeUnretainedValue().remember(disk)
        }, context)
        DASessionSetDispatchQueue(session, queue)
    }

    func stop() { DASessionSetDispatchQueue(session, nil) }
}
