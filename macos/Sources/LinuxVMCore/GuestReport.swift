import Darwin
import Foundation

public struct GuestReport: Codable, Equatable, Sendable {
    public enum ExtensionState: String, Codable, Sendable {
        case active, inactive, outdated, error, missing, unknown
    }
    public var package: String
    public var os: String
    public var shell: String?
    public var extensionState: ExtensionState
    public var receivedAt: Date

    enum CodingKeys: String, CodingKey {
        case package, os, shell, receivedAt
        case extensionState = "extension"
    }

    public init(package: String, os: String, shell: String?, extensionState: ExtensionState, receivedAt: Date) {
        self.package = package
        self.os = os
        self.shell = shell
        self.extensionState = extensionState
        self.receivedAt = receivedAt
    }

    static func parse(_ data: Data, receivedAt: Date = Date()) -> GuestReport? {
        func safe(_ text: String, limit: Int) -> Bool {
            text.count <= limit && !text.unicodeScalars.contains { CharacterSet.controlCharacters.contains($0) }
        }
        guard data.count <= 4096, String(data: data, encoding: .utf8) != nil,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["type"] as? String == "status",
              let package = object["package"] as? String, GuestToolsVersion.components(package) != nil,
              let os = object["os"] as? String, safe(os, limit: 128),
              let state = object["extension"] as? String else { return nil }
        let shell = object["shell"] as? String
        guard object["shell"] == nil || shell != nil,
              shell.map({ safe($0, limit: 32) }) ?? true else { return nil }
        return GuestReport(package: package, os: os, shell: shell,
                           extensionState: ExtensionState(rawValue: state) ?? .unknown, receivedAt: receivedAt)
    }
}

public enum GuestToolsVersion {
    static func components(_ version: String) -> [Int]? {
        guard version.range(of: #"\A[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}\z"#, options: .regularExpression) != nil else { return nil }
        return version.split(separator: ".").compactMap { Int($0) }
    }
    public static func compare(_ a: String, _ b: String) -> ComparisonResult? {
        guard let lhs = components(a), let rhs = components(b) else { return nil }
        for (a, b) in zip(lhs, rhs) where a != b { return a < b ? .orderedAscending : .orderedDescending }
        return .orderedSame
    }
}

extension Runtime {
    public var guestToolsVersion: String? {
        guard let text = try? String(contentsOf: contents.appending(path: "Resources/guest-tools-version"), encoding: .utf8) else { return nil }
        let version = text.hasSuffix("\n") ? String(text.dropLast()) : text
        return GuestToolsVersion.components(version) == nil ? nil : version
    }
}

extension VMLibrary {
    public func guestReport(id: String) -> GuestReport? {
        guard UUID(uuidString: id) != nil,
              let data = try? Data(contentsOf: directory(for: id).appending(path: "guest.json")) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(GuestReport.self, from: data)
    }
    func writeGuestReport(_ report: GuestReport, id: String) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(report).write(to: directory(for: id).appending(path: "guest.json"), options: .atomic)
    }
}

/// Bounded framing: after an oversized line discard bytes until its newline.
struct GuestStatusLines {
    private var line = Data()
    private var oversized = false
    mutating func append(_ bytes: Data, consume: (Data?) -> Void) {
        for byte in bytes {
            if byte == 10 {
                consume(oversized ? nil : line)
                line.removeAll(keepingCapacity: true)
                oversized = false
            } else if !oversized {
                if line.count == 4096 { line.removeAll(keepingCapacity: true); oversized = true }
                else { line.append(byte) }
            }
        }
    }
}

final class GuestStatusReader: @unchecked Sendable {
    private let lock = NSLock()
    private var stopped = false
    private var descriptor: Int32 = -1
    private let finished = DispatchGroup()

    func start(path: String, library: VMLibrary, id: String, log: @escaping @Sendable (String) -> Void) {
        finished.enter()
        DispatchQueue.global(qos: .utility).async { [self] in
            defer { finished.leave() }
            var lastInvalid = -Double.infinity
            while !lock.withLock({ stopped }) {
                let fd = socket(AF_UNIX, SOCK_STREAM, 0)
                guard fd >= 0 else { break }
                var address = sockaddr_un()
                address.sun_family = sa_family_t(AF_UNIX)
                let bytes = Array(path.utf8)
                guard bytes.count < MemoryLayout.size(ofValue: address.sun_path) else { close(fd); break }
                withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: bytes + [0]) }
                var noPipe: Int32 = 1
                setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noPipe, socklen_t(MemoryLayout<Int32>.size))
                lock.withLock { descriptor = fd }
                let connected = withUnsafePointer(to: &address) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
                }
                if connected == 0 && !lock.withLock({ stopped }) {
                    let query = Array("{\"type\":\"query\"}\n".utf8)
                    _ = query.withUnsafeBytes { write(fd, $0.baseAddress, $0.count) }
                    var framing = GuestStatusLines()
                    var chunk = [UInt8](repeating: 0, count: 4096)
                    while !lock.withLock({ stopped }) {
                        let count = read(fd, &chunk, chunk.count)
                        if count < 0 && errno == EINTR { continue }
                        guard count > 0 else { break }
                        framing.append(Data(chunk.prefix(count))) { line in
                            if let line, let report = GuestReport.parse(line) {
                                do { try library.writeGuestReport(report, id: id) }
                                catch { log("Cannot save guest status: \(error.localizedDescription)") }
                            } else if ProcessInfo.processInfo.systemUptime - lastInvalid >= 30 {
                                lastInvalid = ProcessInfo.processInfo.systemUptime
                                log("Dropped invalid guest status line (further drops suppressed for 30 seconds)")
                            }
                        }
                    }
                }
                lock.withLock { descriptor = -1; close(fd) }
                // Interruptible two-second reconnect delay.
                for _ in 0..<20 {
                    if lock.withLock({ stopped }) { break }
                    Thread.sleep(forTimeInterval: 0.1)
                }
            }
        }
    }
    func stop() {
        lock.withLock { stopped = true; if descriptor >= 0 { shutdown(descriptor, SHUT_RDWR) } }
        finished.wait()
    }
}
