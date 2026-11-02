import Foundation

/// A short-lived connection to one of QEMU's QMP sockets.
public final class QMPClient {
    public struct Failure: LocalizedError {
        public let message: String
        public var errorDescription: String? { message }
    }

    private let descriptor: Int32
    private var disconnected = false
    private var buffer = Data()
    private let deadline: TimeInterval

    public init(socketPath: String, timeout: TimeInterval = 5) throws {
        deadline = ProcessInfo.processInfo.systemUptime + timeout
        descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw Failure(message: "socket: \(String(cString: strerror(errno)))") }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = Array(socketPath.utf8)
        guard pathBytes.count < MemoryLayout.size(ofValue: address.sun_path) else {
            close(descriptor)
            throw Failure(message: "QMP socket path is too long: \(socketPath)")
        }
        withUnsafeMutableBytes(of: &address.sun_path) { raw in
            raw.copyBytes(from: pathBytes)
            raw[pathBytes.count] = 0
        }
        var interval = timeval(tv_sec: Int(timeout), tv_usec: Int32((timeout - floor(timeout)) * 1_000_000))
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &interval, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &interval, socklen_t(MemoryLayout<timeval>.size))
        var noSigPipe: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &noSigPipe, socklen_t(MemoryLayout<Int32>.size))
        let connected = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else {
            let message = String(cString: strerror(errno))
            close(descriptor)
            throw Failure(message: "Cannot connect to QEMU: \(message)")
        }
        do {
            _ = try readMessage()
            _ = try execute("qmp_capabilities")
        } catch {
            close(descriptor)
            throw error
        }
    }

    deinit { disconnect() }

    func disconnect() {
        guard !disconnected else { return }
        disconnected = true
        close(descriptor)
    }

    @discardableResult
    public func execute(_ command: String, arguments: [String: Any]? = nil) throws -> Any {
        var request: [String: Any] = ["execute": command]
        if let arguments { request["arguments"] = arguments }
        var data = try JSONSerialization.data(withJSONObject: request)
        data.append(0x0A)
        try data.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                let written = write(descriptor, raw.baseAddress! + offset, raw.count - offset)
                guard written > 0 else { throw Failure(message: "QMP write failed") }
                offset += written
            }
        }
        while true {
            let reply = try readMessage()
            if let result = reply["return"] { return result }
            if let error = reply["error"] as? [String: Any] {
                throw Failure(message: "\(command): \(error["desc"] as? String ?? "QEMU error")")
            }
        }
    }

    private func readMessage() throws -> [String: Any] {
        while true {
            if let newline = buffer.firstIndex(of: 0x0A) {
                let line = buffer[buffer.startIndex..<newline]
                buffer.removeSubrange(buffer.startIndex...newline)
                guard let object = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
                    throw Failure(message: "QEMU sent an invalid QMP message")
                }
                return object
            }
            var chunk = [UInt8](repeating: 0, count: 65536)
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            guard remaining > 0 else { throw Failure(message: "QMP deadline expired") }
            var readiness = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
            guard poll(&readiness, 1, Int32(remaining * 1000)) > 0 else { throw Failure(message: "QMP read timed out") }
            let count = read(descriptor, &chunk, chunk.count)
            guard count > 0 else { throw Failure(message: "QEMU closed the QMP connection") }
            buffer.append(contentsOf: chunk[0..<count])
            guard buffer.count < 16 * 1_048_576 else { throw Failure(message: "QMP message too large") }
        }
    }
}

// QEMU accepts only one client on the supervisor socket, including during host sleep.
final class SupervisorMonitor: @unchecked Sendable {
    private let lock = NSLock()
    private let path: String

    init(path: String) { self.path = path }

    func withClient<T>(timeout: TimeInterval = 5, _ body: (QMPClient) throws -> T) throws -> T {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        guard lock.lock(before: Date().addingTimeInterval(timeout)) else {
            throw QMPClient.Failure(message: "Supervisor monitor is busy")
        }
        defer { lock.unlock() }
        let remaining = deadline - ProcessInfo.processInfo.systemUptime
        guard remaining > 0 else { throw QMPClient.Failure(message: "Supervisor monitor deadline expired") }
        let client = try QMPClient(socketPath: path, timeout: remaining)
        defer { client.disconnect() }
        return try body(client)
    }
}
