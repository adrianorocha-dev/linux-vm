import Foundation
import XCTest
@testable import LinuxVMCore

final class DiskImageCheckTests: XCTestCase {
    private let invalid = "This disk image isn't a valid QCOW2 file."
    private let backingFile = "This disk image refers to another file on your Mac (a backing file), so Linux VM won't use it."
    private let externalDataFile = "This disk image refers to another file on your Mac (an external data file), so Linux VM won't use it."

    func testCleanV3WithFeatureNameTable() throws {
        var bytes = header()
        put(0x6803f857, at: 104, in: &bytes)
        put(48, at: 108, in: &bytes)
        bytes[112] = 0
        bytes[113] = 0
        bytes.replaceSubrange(114..<119, with: Array("dirty".utf8))
        try validate(bytes)
    }

    func testCleanV2() throws {
        try validate(header(version: 2))
    }

    func testBackingFileV2() throws {
        try rejectsBackingFile(version: 2)
    }

    func testBackingFileV3() throws {
        try rejectsBackingFile(version: 3)
    }

    func testExternalDataFeatureBit() throws {
        var bytes = header()
        put(1 << 2, at: 72, width: 8, in: &bytes)
        try rejects(bytes, message: externalDataFile)
    }

    func testExternalDataExtensionWithoutFeatureBit() throws {
        for version: UInt32 in [2, 3] {
            var bytes = header(version: version)
            let start = version == 2 ? 72 : 104
            put(0x44415441, at: start, in: &bytes)
            put(9, at: start + 4, in: &bytes)
            bytes.replaceSubrange((start + 8)..<(start + 17), with: Array("/tmp/data".utf8))
            try rejects(bytes, message: externalDataFile)
        }
    }

    func testUnknownIncompatibleFeature() throws {
        for bit in 5...63 {
            var bytes = header()
            put(UInt64(1) << bit, at: 72, width: 8, in: &bytes)
            try rejects(bytes, message: "This disk image uses QCOW2 features that Linux VM doesn't support.")
        }
    }

    func testEncrypted() throws {
        for version: UInt32 in [2, 3] {
            for method: UInt64 in [1, 2] {
                var bytes = header(version: version)
                put(method, at: 32, in: &bytes)
                try rejects(bytes, message: "This disk image is encrypted, which Linux VM doesn't support.")
            }
        }
    }

    func testTruncatedFile() throws {
        for count in [0, 3, 23, 71, 72, 103, 104, 111, 511] {
            try rejects(Array(header().prefix(count)), message: invalid)
        }
    }

    func testBadMagic() throws {
        var bytes = header()
        bytes[0] = 0
        try rejects(bytes, message: invalid)
    }

    func testUnsupportedVersion() throws {
        for version: UInt32 in [0, 1, 4, .max] {
            try rejects(header(version: version), message: invalid)
        }
    }

    func testInvalidClusterBits() throws {
        for bits: UInt64 in [0, 8, 22, .max >> 32] {
            var bytes = header()
            put(bits, at: 20, in: &bytes)
            try rejects(bytes, message: invalid)
        }
    }

    func testMaximumClusterSize() throws {
        var bytes = header()
        put(21, at: 20, in: &bytes)
        bytes.append(contentsOf: repeatElement(0, count: (1 << 21) - bytes.count))
        try validate(bytes)
    }

    func testInvalidHeaderLength() throws {
        for length: UInt64 in [0, 72, 103, 105, 512, 520, UInt64(UInt32.max)] {
            var bytes = header()
            put(length, at: 100, in: &bytes)
            try rejects(bytes, message: invalid)
        }
    }

    func testExtendedHeaderLength() throws {
        var bytes = header()
        put(112, at: 100, in: &bytes)
        bytes[104] = 1
        try validate(bytes)
    }

    func testExtensionLengthPastCluster() throws {
        for length: UInt64 in [401, 512, UInt64(UInt32.max)] {
            var bytes = header()
            put(0x6803f857, at: 104, in: &bytes)
            put(length, at: 108, in: &bytes)
            bytes.append(contentsOf: repeatElement(0, count: 512))
            try rejects(bytes, message: invalid)
        }
    }

    func testExtensionPadding() throws {
        var bytes = header()
        put(0x12345678, at: 104, in: &bytes)
        put(9, at: 108, in: &bytes)
        for offset in 112..<128 { bytes[offset] = 0xff }
        try validate(bytes)
    }

    func testUnterminatedExtensions() throws {
        var bytes = header()
        for offset in stride(from: 104, to: 512, by: 8) {
            put(0x12345678, at: offset, in: &bytes)
        }
        bytes.append(contentsOf: repeatElement(0, count: 512))
        try rejects(bytes, message: invalid)
    }

    func testEndMarkerAtClusterBoundary() throws {
        var bytes = header()
        put(0x12345678, at: 104, in: &bytes)
        put(392, at: 108, in: &bytes)
        try validate(bytes)
    }

    func testRawAlwaysPassesEvenWithQCOWMagic() throws {
        var bytes = header()
        put(1, at: 8, width: 8, in: &bytes)
        put(1 << 2, at: 72, width: 8, in: &bytes)
        try validate(bytes, format: .raw)
        try validate([], format: .raw)
        try DiskImageCheck.validate(URL(fileURLWithPath: "/nonexistent/\(UUID().uuidString)"), format: .raw)
    }

    func testUnreadableFile() {
        XCTAssertThrowsError(try DiskImageCheck.validate(URL(fileURLWithPath: "/nonexistent/\(UUID().uuidString)"), format: .qcow2)) {
            self.assertFailure($0, message: self.invalid)
        }
    }

    private func rejectsBackingFile(version: UInt32) throws {
        for (offset, width) in [(8, 8), (16, 4)] {
            var bytes = header(version: version)
            put(1, at: offset, width: width, in: &bytes)
            try rejects(bytes, message: backingFile)
        }
    }

    private func header(version: UInt32 = 3) -> [UInt8] {
        var bytes = [UInt8](repeating: 0, count: 512)
        put(0x514649fb, at: 0, in: &bytes)
        put(UInt64(version), at: 4, in: &bytes)
        put(9, at: 20, in: &bytes)
        put(1 << 20, at: 24, width: 8, in: &bytes)
        if version == 3 {
            put(4, at: 96, in: &bytes)
            put(104, at: 100, in: &bytes)
        }
        return bytes
    }

    private func put(_ value: UInt64, at offset: Int, width: Int = 4, in bytes: inout [UInt8]) {
        for index in 0..<width {
            bytes[offset + index] = UInt8(truncatingIfNeeded: value >> ((width - index - 1) * 8))
        }
    }

    private func validate(_ bytes: [UInt8], format: DiskFormat = .qcow2) throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DiskImageCheckTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("disk.img")
        try Data(bytes).write(to: url)
        try DiskImageCheck.validate(url, format: format)
    }

    private func rejects(_ bytes: [UInt8], message: String, file: StaticString = #filePath, line: UInt = #line) throws {
        XCTAssertThrowsError(try validate(bytes), file: file, line: line) {
            self.assertFailure($0, message: message, file: file, line: line)
        }
    }

    private func assertFailure(_ error: Error, message: String, file: StaticString = #filePath, line: UInt = #line) {
        guard case LibraryError.failed(let actual) = error else {
            XCTFail("Expected LibraryError.failed, got \(error)", file: file, line: line)
            return
        }
        XCTAssertEqual(actual, message, file: file, line: line)
    }
}
