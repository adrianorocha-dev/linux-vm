import Foundation
import LinuxVMCore

let usage = """
Usage: linuxvmctl <command> [arguments]

  list                                   VMs and their state
  check                                  runtime capability report
  create --name N [--iso PATH] [--cpus N] [--memory MIB] [--disk GIB]
  import --name N --disk PATH [--efi-vars PATH] [--cpus N] [--memory MIB]
  show VM                                configuration as JSON
  set VM [--name N] [--cpus N] [--memory MIB] [--iso PATH|none]
         [--shared-folder PATH|none] [--scroll-scale X] [--mac-cursor on|off]
         [--immersive on|off] [--cover-notch on|off] [--forward HOST:GUEST|none]
         [--grow-disk GIB] [--pause-during-sleep on|off]
  start VM                               start in the background
  run VM                                 supervise in the foreground
  stop VM [--force]                      shut down (or stop QEMU at once)
  status VM
  insert VM PATH | eject VM              change the installer disc while running
  screenshot VM PATH                     save the guest display as PNG
  delete VM                              move a stopped VM to the Trash

VM is a name, an identifier, or a unique identifier prefix.
"""

struct UsageError: Error {}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("linuxvmctl: \(message)\n".utf8))
    exit(1)
}

func options(_ arguments: ArraySlice<String>, allowed: Set<String>) throws -> [String: String] {
    var result: [String: String] = [:]
    var iterator = arguments.makeIterator()
    while let key = iterator.next() {
        guard key.hasPrefix("--"), allowed.contains(key), let value = iterator.next() else { throw UsageError() }
        result[key] = value
    }
    return result
}

func integer(_ value: String?, _ name: String) throws -> Int? {
    guard let value else { return nil }
    guard let number = Int(value) else { throw ConfigurationError.invalid("\(name) must be a whole number.") }
    return number
}

func boolean(_ value: String?) throws -> Bool? {
    switch value {
    case nil: nil
    case "on": true
    case "off": false
    default: throw ConfigurationError.invalid("Use on or off.")
    }
}

func absolutePath(_ path: String) -> String {
    URL(fileURLWithPath: path).standardizedFileURL.path
}

func formatBytes(_ bytes: UInt64) -> String {
    ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
}

let library = VMLibrary()
let runtime = Runtime.locate()
let host = HostResources.current
let arguments = CommandLine.arguments.dropFirst()

do {
    guard let command = arguments.first else { throw UsageError() }
    let rest = arguments.dropFirst()
    switch command {
    case "list":
        for machine in library.list() {
            let state = library.status(id: machine.id).state.rawValue
            print("\(machine.id.prefix(8))  \(state.padding(toLength: 9, withPad: " ", startingAt: 0))  \(machine.name)")
        }
    case "check":
        var passed = true
        for check in runtime.check() {
            passed = passed && check.passed
            print("\(check.passed ? "ok  " : "FAIL")  \(check.name): \(check.detail)")
        }
        exit(passed ? 0 : 1)
    case "create":
        let values = try options(rest, allowed: ["--name", "--iso", "--cpus", "--memory", "--disk"])
        guard let name = values["--name"] else { throw UsageError() }
        let machine = try library.create(
            name: name,
            installMedia: values["--iso"].map(absolutePath),
            cpuCount: try integer(values["--cpus"], "CPUs") ?? host.defaultCPUs,
            memoryMiB: try integer(values["--memory"], "Memory") ?? host.defaultMemoryMiB,
            diskGiB: try integer(values["--disk"], "Disk size") ?? 64)
        print(machine.id)
    case "import":
        let values = try options(rest, allowed: ["--name", "--disk", "--efi-vars", "--cpus", "--memory"])
        guard let name = values["--name"], let disk = values["--disk"] else { throw UsageError() }
        let machine = try library.importDisk(
            name: name,
            disk: URL(fileURLWithPath: absolutePath(disk)),
            variables: values["--efi-vars"].map { URL(fileURLWithPath: absolutePath($0)) },
            cpuCount: try integer(values["--cpus"], "CPUs") ?? host.defaultCPUs,
            memoryMiB: try integer(values["--memory"], "Memory") ?? host.defaultMemoryMiB)
        print(machine.id)
    case "show":
        guard rest.count == 1 else { throw UsageError() }
        let machine = try library.find(rest.first!)
        print(String(decoding: try Data(contentsOf: library.configurationURL(for: machine.id)), as: UTF8.self))
        if let size = library.diskSize(of: machine) {
            print("disk: \(formatBytes(size.logical)) capacity, \(formatBytes(size.allocated)) used")
        }
    case "set":
        guard let reference = rest.first else { throw UsageError() }
        var machine = try library.find(reference)
        let values = try options(rest.dropFirst(), allowed: [
            "--name", "--cpus", "--memory", "--iso", "--shared-folder", "--scroll-scale",
            "--mac-cursor", "--immersive", "--cover-notch", "--forward", "--grow-disk", "--pause-during-sleep",
        ])
        let running = library.status(id: machine.id).state != .stopped
        let liveKeys: Set<String> = ["--scroll-scale", "--name", "--pause-during-sleep"]
        if running, !Set(values.keys).isSubset(of: liveKeys) {
            throw LibraryError.failed("Only --name, --scroll-scale and --pause-during-sleep can change while “\(machine.name)” runs.")
        }
        if let value = try boolean(values["--pause-during-sleep"]) { machine.pauseDuringSleep = value }
        if let name = values["--name"] { machine.name = name }
        if let cpus = try integer(values["--cpus"], "CPUs") { machine.cpuCount = cpus }
        if let memory = try integer(values["--memory"], "Memory") { machine.memoryMiB = memory }
        if let iso = values["--iso"] { machine.installMedia = iso == "none" ? nil : absolutePath(iso) }
        if let folder = values["--shared-folder"] { machine.sharedFolder = folder == "none" ? nil : absolutePath(folder) }
        if let scale = values["--scroll-scale"] {
            guard let number = Double(scale) else { throw ConfigurationError.invalid("The scroll scale must be a number.") }
            machine.scrollScale = number
        }
        if let value = try boolean(values["--mac-cursor"]) { machine.display.showMacCursor = value }
        if let value = try boolean(values["--immersive"]) { machine.display.immersive = value }
        if let value = try boolean(values["--cover-notch"]) { machine.display.coverNotch = value }
        if let forward = values["--forward"] {
            if forward == "none" {
                machine.portForwards = []
            } else {
                let parts = forward.split(separator: ":").compactMap { Int($0) }
                guard parts.count == 2 else { throw ConfigurationError.invalid("Use --forward HOSTPORT:GUESTPORT.") }
                machine.portForwards.removeAll { $0.hostPort == parts[0] }
                machine.portForwards.append(PortForward(hostPort: parts[0], guestPort: parts[1]))
            }
        }
        try library.save(machine)
        if let gib = try integer(values["--grow-disk"], "Disk size") {
            try library.growDisk(of: machine, toGiB: gib)
        }
    case "start":
        guard rest.count == 1 else { throw UsageError() }
        let machine = try library.find(rest.first!)
        try library.start(id: machine.id, runtime: runtime)
        print("\(machine.name) is running")
    case "run":
        guard rest.count == 1 else { throw UsageError() }
        let machine = try library.find(rest.first!)
        exit(try Supervisor(library: library, runtime: runtime, id: machine.id).run())
    case "stop":
        guard let reference = rest.first, rest.count <= 2 else { throw UsageError() }
        let machine = try library.find(reference)
        if rest.dropFirst().first == "--force" {
            try library.forceStop(id: machine.id)
        } else {
            guard rest.count == 1 else { throw UsageError() }
            try library.requestShutdown(id: machine.id)
        }
    case "status":
        guard rest.count == 1 else { throw UsageError() }
        let machine = try library.find(rest.first!)
        let status = library.status(id: machine.id)
        print(status.state.rawValue)
        if let run = status.run {
            print("since \(run.startedAt), supervisor \(run.supervisorPID), QEMU \(run.qemuPID.map(String.init) ?? "-")")
        }
        if let report = library.guestReport(id: machine.id) {
            let desktop = report.desktopLabel.map { ", \($0)" } ?? ""
            print("guest tools \(report.package)\(desktop), clipboard \(report.clipboardState.rawValue), received \(report.receivedAt)")
            if let bundled = runtime.guestToolsVersion,
               GuestToolsVersion.compare(report.package, bundled) == .orderedAscending {
                print("Guest tools are older than the bundled disc (\(bundled)).")
            }
        }
    case "insert":
        guard rest.count == 2 else { throw UsageError() }
        var machine = try library.find(rest.first!)
        machine.installMedia = absolutePath(rest.last!)
        try library.save(machine)
        if library.status(id: machine.id).state != .stopped {
            try library.insertInstallMedia(id: machine.id, path: machine.installMedia!)
        }
    case "eject":
        guard rest.count == 1 else { throw UsageError() }
        var machine = try library.find(rest.first!)
        machine.installMedia = nil
        try library.save(machine)
        if library.status(id: machine.id).state != .stopped {
            try library.ejectInstallMedia(id: machine.id)
        }
    case "screenshot":
        guard rest.count == 2 else { throw UsageError() }
        try library.screenshot(id: try library.find(rest.first!).id, to: absolutePath(rest.last!))
    case "delete":
        guard rest.count == 1 else { throw UsageError() }
        try library.delete(id: try library.find(rest.first!).id)
    case "help", "--help", "-h":
        print(usage)
    default:
        throw UsageError()
    }
} catch is UsageError {
    FileHandle.standardError.write(Data(usage.utf8))
    exit(64)
} catch {
    fail(error.localizedDescription)
}
