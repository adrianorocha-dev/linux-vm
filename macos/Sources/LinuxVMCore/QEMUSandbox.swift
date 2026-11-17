import Darwin
import Foundation

/// A macOS sandbox profile for one QEMU run, so that a guest that escapes QEMU
/// still cannot change the Mac or read the user's files. QEMU may write only
/// its VM folder, its run directory and its temporary folders, and may read
/// file contents in the home folder and on external drives only for what the
/// VM uses. It cannot start other programs.
public struct QEMUSandbox: Sendable, Equatable {
    public static let tool = URL(fileURLWithPath: "/usr/bin/sandbox-exec")

    public var profile: String
    public var parameters: [(String, String)]

    public static func == (lhs: QEMUSandbox, rhs: QEMUSandbox) -> Bool {
        lhs.profile == rhs.profile && lhs.parameters.elementsEqual(rhs.parameters, by: ==)
    }

    public struct Paths: Sendable {
        public var home: String
        public var machine: String
        public var run: String
        public var temporary: [String]
        public var runtime: String
        public var qemu: String
        public var sharedFolder: String?
        public var sharedFolderWritable: Bool
        public var installMedia: String?
    }

    public static func paths(configuration: VMConfiguration, library: VMLibrary, runtime: Runtime,
                             runDirectory: URL) -> Paths {
        Paths(
            home: resolved(homeDirectory()),
            machine: resolved(library.directory(for: configuration.id).path),
            run: resolved(runDirectory.path),
            temporary: [_CS_DARWIN_USER_TEMP_DIR, _CS_DARWIN_USER_CACHE_DIR].compactMap(userDirectory).map(resolved),
            runtime: resolved(runtime.contents.path),
            qemu: resolved(runtime.qemu.path),
            sharedFolder: configuration.sharedFolder.map(resolved),
            sharedFolderWritable: configuration.isolation.sharedFolderWritable,
            installMedia: configuration.installMedia.map(resolved))
    }

    public init(paths: Paths) {
        var parameters: [(String, String)] = [
            ("HOME", paths.home), ("MACHINE", paths.machine), ("RUN", paths.run),
            ("RUNTIME", paths.runtime), ("QEMU", paths.qemu),
        ]
        var writable = [#"(subpath (param "MACHINE"))"#, #"(subpath (param "RUN"))"#]
        var readable = [#"(subpath (param "MACHINE"))"#, #"(subpath (param "RUN"))"#, #"(subpath (param "RUNTIME"))"#]
        for (index, directory) in paths.temporary.enumerated() {
            parameters.append(("TEMPORARY\(index)", directory))
            writable.append(#"(subpath (param "TEMPORARY\#(index)"))"#)
            readable.append(#"(subpath (param "TEMPORARY\#(index)"))"#)
        }
        if let folder = paths.sharedFolder {
            parameters.append(("SHARED", folder))
            readable.append(#"(subpath (param "SHARED"))"#)
            if paths.sharedFolderWritable { writable.append(#"(subpath (param "SHARED"))"#) }
        }
        if let media = paths.installMedia {
            parameters.append(("MEDIA", media))
            readable.append(#"(literal (param "MEDIA"))"#)
        }
        let indent = "\n    "
        profile = """
        (version 1)
        (allow default)
        (deny process-exec*)
        (allow process-exec* (literal (param "QEMU")))
        (deny file-write*)
        (allow file-write*\(indent)\(writable.joined(separator: indent))\(indent)(literal "/dev/null")\(indent)(literal "/dev/zero")\(indent)(literal "/dev/dtracehelper")\(indent)(regex #"^/dev/tty")\(indent)(regex #"^/dev/fd/"))
        (deny file-read-data file-read-xattr\(indent)(subpath (param "HOME"))\(indent)(subpath "/Volumes"))
        (allow file-read-data file-read-xattr\(indent)\(readable.joined(separator: indent)))

        """
        self.parameters = parameters
    }

    /// The command that starts QEMU inside the sandbox.
    public func command(qemu: URL, arguments: [String]) -> (executable: URL, arguments: [String]) {
        var command: [String] = []
        for (name, value) in parameters { command += ["-D", "\(name)=\(value)"] }
        return (Self.tool, command + ["-p", profile, qemu.path] + arguments)
    }

    static func homeDirectory() -> String {
        if let entry = getpwuid(getuid()), let directory = entry.pointee.pw_dir {
            return String(cString: directory)
        }
        return FileManager.default.homeDirectoryForCurrentUser.path
    }

    static func userDirectory(_ name: Int32) -> String? {
        let length = confstr(name, nil, 0)
        guard length > 0 else { return nil }
        var buffer = [CChar](repeating: 0, count: length)
        guard confstr(name, &buffer, length) > 0 else { return nil }
        return String(decoding: buffer.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
    }

    /// Sandbox rules match real paths: /tmp is /private/tmp, and so on.
    /// A path that doesn't exist yet keeps its resolved parent.
    static func resolved(_ path: String) -> String {
        var url = URL(fileURLWithPath: path).standardizedFileURL
        var suffix: [String] = []
        while url.path != "/" {
            if let real = realpath(url.path, nil) {
                defer { free(real) }
                var result = URL(fileURLWithPath: String(cString: real))
                for component in suffix.reversed() { result.append(path: component) }
                return result.path
            }
            suffix.append(url.lastPathComponent)
            url.deleteLastPathComponent()
        }
        return path
    }
}
