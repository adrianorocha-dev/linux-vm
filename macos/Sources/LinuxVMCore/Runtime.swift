import Foundation

/// The files a VM needs, laid out as in the app bundle's `Contents`:
/// `Resources/runtime/bin/<QEMU>`, `Resources/firmware/edk2-aarch64-code.fd`,
/// `Resources/guest-tools.iso`, `Helpers/omarchy-vm-helper` and
/// `Helpers/linuxvmctl`.
public struct Runtime: Sendable {
    public static let qemuName = "qemu-system-aarch64"
    public let contents: URL

    public init(contents: URL) {
        self.contents = contents
    }

    /// `LINUXVM_CONTENTS` overrides; otherwise the bundle that holds the
    /// running executable (in `Contents/MacOS` or `Contents/Helpers`).
    public static func locate() -> Runtime {
        if let override = ProcessInfo.processInfo.environment["LINUXVM_CONTENTS"], override.hasPrefix("/") {
            return Runtime(contents: URL(fileURLWithPath: override, isDirectory: true))
        }
        let executable = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        return Runtime(contents: executable.deletingLastPathComponent().deletingLastPathComponent())
    }

    public var qemu: URL { contents.appending(path: "Resources/runtime/bin/\(Self.qemuName)") }
    public var firmware: URL { contents.appending(path: "Resources/firmware/edk2-aarch64-code.fd") }
    public var guestTools: URL { contents.appending(path: "Resources/guest-tools.iso") }
    public var icon: URL { contents.appending(path: "Resources/AppIcon.icns") }
    public var helper: URL { contents.appending(path: "Helpers/omarchy-vm-helper") }
    public var supervisor: URL { contents.appending(path: "Helpers/linuxvmctl") }

    public struct Check: Identifiable, Sendable {
        public let name: String
        public let passed: Bool
        public let detail: String
        public var id: String { name }
    }

    public static let requiredDevices = [
        "virtio-gpu-gl-pci", "virtio-pinch-pci", "virtio-tablet-pci", "virtio-keyboard-pci",
        "virtio-blk-pci", "virtio-net-pci", "virtio-serial-pci", "virtserialport", "virtio-9p-pci",
        "virtio-balloon-pci", "virtio-rng-pci", "qemu-xhci", "usb-kbd", "usb-bot", "scsi-cd",
        "intel-hda", "hda-micro",
    ]

    /// Verifies capabilities rather than inferring them from a version.
    public func check() -> [Check] {
        var checks: [Check] = []
        let fileManager = FileManager.default
        func file(_ name: String, _ url: URL, executable: Bool = false) {
            let present = executable ? fileManager.isExecutableFile(atPath: url.path) : fileManager.fileExists(atPath: url.path)
            checks.append(Check(name: name, passed: present, detail: url.path))
        }
        file("QEMU runtime", qemu, executable: true)
        file("UEFI firmware", firmware)
        file("Bridge helper", helper, executable: true)
        file("VM supervisor", supervisor, executable: true)
        file("Guest tools disc", guestTools)

        guard fileManager.isExecutableFile(atPath: qemu.path) else { return checks }
        let version = (try? ProcessRunner.output(qemu, ["--version"]))?
            .split(separator: "\n").first.map(String.init) ?? "unavailable"
        checks.append(Check(name: "QEMU version", passed: version.contains("11.1"), detail: version))

        let devices = (try? ProcessRunner.output(qemu, ["-machine", "virt", "-device", "help"])) ?? ""
        let missing = Self.requiredDevices.filter { !devices.contains("name \"\($0)\"") }
        checks.append(Check(
            name: "Virtual devices",
            passed: missing.isEmpty,
            detail: missing.isEmpty ? "All \(Self.requiredDevices.count) required devices" : "Missing: \(missing.joined(separator: ", "))"))

        let help = (try? ProcessRunner.output(qemu, ["-help"])) ?? ""
        let cocoa = help.contains("-display cocoa") && help.contains("immersive=on|off")
        checks.append(Check(name: "Cocoa display with immersive mode", passed: cocoa, detail: cocoa ? "Available" : "Not built in"))

        let binary = (try? Data(contentsOf: qemu, options: .alwaysMapped)) ?? Data()
        let scroll = binary.range(of: Data("TRYOMARCHY_TOUCH_SCROLL_SCALE_FILE".utf8)) != nil
        checks.append(Check(name: "Adjustable touch scrolling", passed: scroll, detail: scroll ? "Patched" : "Missing the scroll-scale patch"))

        let accelerator = (try? ProcessRunner.output(qemu, ["-accel", "help"])) ?? ""
        checks.append(Check(name: "Hypervisor (HVF)", passed: accelerator.contains("hvf"), detail: accelerator.contains("hvf") ? "Available" : "Missing"))
        return checks
    }
}

enum ProcessRunner {
    struct Failure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    /// Runs a short command and returns its standard output.
    static func output(_ executable: URL, _ arguments: [String], environment: [String: String]? = nil) throws -> String {
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        if let environment { process.environment = environment }
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        process.standardInput = FileHandle.nullDevice
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let text = String(decoding: data, as: UTF8.self)
        guard process.terminationStatus == 0 else {
            throw Failure(message: "\(executable.lastPathComponent) \(arguments.first ?? ""): \(text.trimmingCharacters(in: .whitespacesAndNewlines))")
        }
        return text
    }
}
