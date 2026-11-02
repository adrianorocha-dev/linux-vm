import Darwin
import Foundation

nonisolated(unsafe) private var receivedSignal: Int32 = 0

/// Owns one VM run: QEMU, its host bridges and the run state. It runs as its
/// own process (`linuxvmctl run`), so a VM outlives the app that started it.
public final class Supervisor {
    public static let shutdownGrace: TimeInterval = 90
    static let bridgeRestartLimit = 5

    private let library: VMLibrary
    private let runtime: Runtime
    private let id: String
    private var log: FileHandle?

    public init(library: VMLibrary, runtime: Runtime, id: String) {
        self.library = library
        self.runtime = runtime
        self.id = id
    }

    private func say(_ message: String) {
        let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        FileHandle.standardError.write(Data(line.utf8))
    }

    public func run() throws -> Int32 {
        var configuration = try library.load(id: id)
        try configuration.validate()
        for (name, url) in [("QEMU", runtime.qemu), ("firmware", runtime.firmware), ("bridge helper", runtime.helper)]
        where !FileManager.default.fileExists(atPath: url.path) {
            throw LibraryError.failed("The \(name) is missing: \(url.path)")
        }

        let lock = open(library.lockURL(for: id).path, O_RDWR | O_CREAT | O_CLOEXEC, 0o600)
        guard lock >= 0, flock(lock, LOCK_EX | LOCK_NB) == 0 else {
            throw LibraryError.failed("“\(configuration.name)” is already running.")
        }
        defer {
            try? FileManager.default.removeItem(at: library.runStateURL(for: id))
            flock(lock, LOCK_UN)
            close(lock)
        }

        if let media = configuration.installMedia, !FileManager.default.fileExists(atPath: media) {
            say("The installer image is gone; starting without it: \(media)")
            configuration.installMedia = nil
        }
        if let folder = configuration.sharedFolder, !FileManager.default.fileExists(atPath: folder) {
            say("The shared folder is gone; starting without it: \(folder)")
            configuration.sharedFolder = nil
        }

        var template = Array("/tmp/linuxvm.XXXXXX".utf8CString)
        guard let created = mkdtemp(&template) else { throw LibraryError.failed("Cannot create a run directory.") }
        let runDirectory = URL(fileURLWithPath: String(cString: created), isDirectory: true)
        defer { try? FileManager.default.removeItem(at: runDirectory) }
        let paths = QEMULaunch.Paths(runDirectory: runDirectory)
        try FileManager.default.createDirectory(at: paths.audioRoutes, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])

        let host = probeHost()
        try library.writeScrollScale(configuration)
        let logs = library.logsDirectory(for: id)
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        for name in ["qemu.log", "serial.log", "bridges.log"] {
            let current = logs.appending(path: name)
            let previous = logs.appending(path: "\(name).1")
            try? FileManager.default.removeItem(at: previous)
            try? FileManager.default.moveItem(at: current, to: previous)
        }

        let launch = QEMULaunch.make(configuration: configuration, library: library, runtime: runtime, paths: paths, host: host)
        let qemu = Process()
        qemu.executableURL = runtime.qemu
        qemu.arguments = launch.arguments
        qemu.environment = launch.environment
        qemu.standardInput = FileHandle.nullDevice
        let qemuLog = try Self.appendHandle(logs.appending(path: "qemu.log"))
        qemu.standardOutput = qemuLog
        qemu.standardError = qemuLog

        signal(SIGTERM) { receivedSignal = $0 }
        signal(SIGINT) { receivedSignal = $0 }
        signal(SIGHUP, SIG_IGN)
        signal(SIGPIPE, SIG_IGN)

        say("Starting “\(configuration.name)”: \(configuration.cpuCount) CPUs, \(configuration.memoryMiB) MiB")
        try qemu.run()
        var state = RunState(supervisorPID: getpid(), qemuPID: qemu.processIdentifier, phase: .starting,
                             controlSocket: nil, startedAt: Date())
        library.writeRunState(state, id: id)

        guard waitForMonitor(qemu: qemu, paths: paths) else {
            qemu.waitUntilExit()
            throw LibraryError.failed("QEMU exited during startup (status \(qemu.terminationStatus)). See \(logs.appending(path: "qemu.log").path)")
        }
        state.phase = .running
        state.controlSocket = paths.controlSocket
        library.writeRunState(state, id: id)
        say("Running. Control socket: \(paths.controlSocket)")

        let bridgeLog = try Self.appendHandle(logs.appending(path: "bridges.log"))
        var bridges: [QEMULaunch.Bridge: Process] = [:]
        var restarts: [QEMULaunch.Bridge: Int] = [:]
        func startBridge(_ bridge: QEMULaunch.Bridge) {
            let process = Process()
            process.executableURL = runtime.helper
            var arguments = [bridge.helperFlag, String(qemu.processIdentifier), paths.bridgeSocket(bridge)]
            if bridge == .audio { arguments.append(paths.audioRoutes.path) }
            process.arguments = arguments
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = bridgeLog
            process.standardError = bridgeLog
            do {
                try process.run()
                bridges[bridge] = process
            } catch {
                say("Cannot start the \(bridge.rawValue) bridge: \(error.localizedDescription)")
            }
        }
        QEMULaunch.Bridge.allCases.forEach(startBridge)

        var shutdownRequestedAt: Date?
        while qemu.isRunning {
            if receivedSignal != 0 {
                let signalNumber = receivedSignal
                receivedSignal = 0
                if shutdownRequestedAt == nil {
                    say("Signal \(signalNumber): asking Linux to shut down")
                    shutdownRequestedAt = Date()
                    state.phase = .stopping
                    library.writeRunState(state, id: id)
                    try? QMPClient(socketPath: paths.supervisorSocket).execute("system_powerdown")
                } else {
                    say("Second signal: stopping QEMU")
                    qemu.terminate()
                }
            }
            if let requested = shutdownRequestedAt, Date().timeIntervalSince(requested) > Self.shutdownGrace {
                say("Linux did not shut down within \(Int(Self.shutdownGrace)) seconds: stopping QEMU")
                qemu.terminate()
                shutdownRequestedAt = .distantFuture
            }
            for bridge in QEMULaunch.Bridge.allCases {
                guard let process = bridges[bridge], !process.isRunning else { continue }
                bridges[bridge] = nil
                // QEMU closes its sockets before it finishes exiting.
                Thread.sleep(forTimeInterval: 0.5)
                guard qemu.isRunning else { break }
                let count = restarts[bridge, default: 0]
                if count < Self.bridgeRestartLimit {
                    restarts[bridge] = count + 1
                    say("The \(bridge.rawValue) bridge exited (status \(process.terminationStatus)); restarting (\(count + 1)/\(Self.bridgeRestartLimit))")
                    startBridge(bridge)
                } else {
                    say("The \(bridge.rawValue) bridge is unavailable for the rest of this run")
                }
            }
            Thread.sleep(forTimeInterval: 0.1)
        }

        for process in bridges.values where process.isRunning {
            process.terminate()
        }
        for process in bridges.values {
            process.waitUntilExit()
        }
        say("QEMU exited with status \(qemu.terminationStatus)")
        return qemu.terminationStatus
    }

    private func waitForMonitor(qemu: Process, paths: QEMULaunch.Paths) -> Bool {
        let deadline = Date().addingTimeInterval(30)
        while Date() < deadline {
            guard qemu.isRunning else { return false }
            if FileManager.default.fileExists(atPath: paths.controlSocket),
               (try? QMPClient(socketPath: paths.supervisorSocket, timeout: 2)) != nil {
                return true
            }
            Thread.sleep(forTimeInterval: 0.1)
        }
        return false
    }

    private func probeHost() -> QEMULaunch.Host {
        func helper(_ arguments: [String]) -> String? {
            (try? ProcessRunner.output(runtime.helper, arguments))?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        var host = QEMULaunch.Host()
        if let geometry = helper(["--host-keyboard-geometry"]), ["ansi", "iso", "jis"].contains(geometry) {
            host.keyboardGeometry = geometry
        }
        host.timeZone = helper(["--host-timezone"])
        if let rate = helper(["--host-audio-frequency", "output", ""]).flatMap(Int.init), (8000...384_000).contains(rate) {
            host.audioFrequency = rate
        }
        return host
    }

    static func appendHandle(_ url: URL) throws -> FileHandle {
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        return handle
    }
}

extension VMLibrary {
    /// Starts the supervisor in its own session, so the VM keeps running if
    /// the app quits, and waits until it owns the VM.
    public func start(id: String, runtime: Runtime) throws {
        let configuration = try load(id: id)
        try configuration.validate()
        guard status(id: id).state == .stopped else { throw LibraryError.running(configuration.name) }
        guard FileManager.default.isExecutableFile(atPath: runtime.supervisor.path) else {
            throw LibraryError.failed("The VM supervisor is missing: \(runtime.supervisor.path)")
        }
        let logs = logsDirectory(for: id)
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let logURL = logs.appending(path: "supervisor.log")
        let logHandle = try Supervisor.appendHandle(logURL)
        let startOffset = try logHandle.offset()

        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT))
        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_adddup2(&actions, logHandle.fileDescriptor, 1)
        posix_spawn_file_actions_adddup2(&actions, logHandle.fileDescriptor, 2)

        var environment = ProcessInfo.processInfo.environment
        environment["LINUXVM_LIBRARY"] = root.path
        environment["LINUXVM_CONTENTS"] = runtime.contents.path
        let argv = [runtime.supervisor.path, "run", id]
        let envp = environment.map { "\($0.key)=\($0.value)" }
        var pid: pid_t = 0
        let result = Self.withCStrings(argv) { argvPointer in
            Self.withCStrings(envp) { envPointer in
                posix_spawn(&pid, runtime.supervisor.path, &actions, &attributes, argvPointer, envPointer)
            }
        }
        try? logHandle.close()
        guard result == 0 else { throw LibraryError.failed("Cannot start the supervisor: \(String(cString: strerror(result)))") }
        Thread.detachNewThread {
            var status: Int32 = 0
            waitpid(pid, &status, 0)
        }

        let deadline = Date().addingTimeInterval(45)
        while Date() < deadline {
            if status(id: id).state == .running { return }
            if kill(pid, 0) != 0 {
                let output = (try? Data(contentsOf: logURL)).map { String(decoding: $0.dropFirst(Int(startOffset)), as: UTF8.self) } ?? ""
                throw LibraryError.failed(output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "The VM stopped during startup." : output.trimmingCharacters(in: .whitespacesAndNewlines))
            }
            Thread.sleep(forTimeInterval: 0.2)
        }
    }

    static func withCStrings<T>(_ strings: [String], _ body: (UnsafePointer<UnsafeMutablePointer<CChar>?>) -> T) -> T {
        var pointers: [UnsafeMutablePointer<CChar>?] = strings.map { strdup($0) }
        pointers.append(nil)
        defer { pointers.forEach { free($0) } }
        return pointers.withUnsafeBufferPointer { body($0.baseAddress!) }
    }
}
