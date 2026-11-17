import Foundation

public enum DiskImageCheck {
    /// Rejects unusable headers and images that would make QEMU open other host files.
    public static func validate(_ url: URL, format: DiskFormat) throws {
        if format == .raw { return }
        do {
            let file = try FileHandle(forReadingFrom: url)
            defer { try? file.close() }
            var header = try read(72, from: file)
            guard uint32(header, at: 0) == 0x514649fb,
                  [2, 3].contains(uint32(header, at: 4)),
                  (9...21).contains(uint32(header, at: 20)) else {
                throw invalid
            }
            let clusterSize = 1 << Int(uint32(header, at: 20))
            header.append(try read(clusterSize - header.count, from: file))
            guard uint64(header, at: 8) == 0, uint32(header, at: 16) == 0 else {
                throw LibraryError.failed("This disk image refers to another file on your Mac (a backing file), so Linux VM won't use it.")
            }
            guard uint32(header, at: 32) == 0 else {
                throw LibraryError.failed("This disk image is encrypted, which Linux VM doesn't support.")
            }
            var offset = 72
            if uint32(header, at: 4) == 3 {
                let features = uint64(header, at: 72)
                guard features & (1 << 2) == 0 else { throw externalDataFile }
                guard features & ~UInt64(0x1f) == 0 else {
                    throw LibraryError.failed("This disk image uses QCOW2 features that Linux VM doesn't support.")
                }
                offset = Int(uint32(header, at: 100))
                guard offset >= 104, offset <= clusterSize, offset % 8 == 0 else { throw invalid }
            }
            while offset <= clusterSize - 8 {
                let type = uint32(header, at: offset)
                let length = Int(uint32(header, at: offset + 4))
                let paddedLength = (length + 7) & ~7
                guard paddedLength <= clusterSize - offset - 8 else { throw invalid }
                if type == 0 {
                    guard length == 0 else { throw invalid }
                    return
                }
                guard type != 0x44415441 else { throw externalDataFile }
                offset += 8 + paddedLength
            }
            throw invalid
        } catch let error as LibraryError {
            throw error
        } catch {
            throw invalid
        }
    }

    private static var invalid: LibraryError {
        .failed("This disk image isn't a valid QCOW2 file.")
    }

    private static var externalDataFile: LibraryError {
        .failed("This disk image refers to another file on your Mac (an external data file), so Linux VM won't use it.")
    }

    private static func read(_ count: Int, from file: FileHandle) throws -> Data {
        var data = Data()
        while data.count < count {
            guard let part = try file.read(upToCount: count - data.count), !part.isEmpty else { throw invalid }
            data.append(part)
        }
        return data
    }

    private static func uint32(_ data: Data, at offset: Int) -> UInt32 {
        data[offset..<(offset + 4)].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
    }

    private static func uint64(_ data: Data, at offset: Int) -> UInt64 {
        data[offset..<(offset + 8)].reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
    }
}
