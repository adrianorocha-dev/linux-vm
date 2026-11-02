import Foundation

/// QEMU's command line and environment for one VM run.
public struct QEMULaunch: Sendable {
    public var arguments: [String]
    public var environment: [String: String]

    public struct Host: Sendable {
        public var keyboardGeometry: String
        public var timeZone: String?
        public var audioFrequency: Int

        public init(keyboardGeometry: String = "ansi", timeZone: String? = nil, audioFrequency: Int = 48000) {
            self.keyboardGeometry = keyboardGeometry
            self.timeZone = timeZone
            self.audioFrequency = audioFrequency
        }
    }

    /// Paths of one run. Sockets live in a short private directory because
    /// UNIX socket paths are limited to 104 bytes.
    public struct Paths: Sendable {
        public var runDirectory: URL
        public var supervisorSocket: String { runDirectory.appending(path: "supervisor.sock").path }
        public var statusSocket: String { runDirectory.appending(path: "status.sock").path }
        public var controlSocket: String { runDirectory.appending(path: "control.sock").path }
        public var audioRoutes: URL { runDirectory.appending(path: "audio-routes", directoryHint: .isDirectory) }
        public func bridgeSocket(_ bridge: Bridge) -> String { runDirectory.appending(path: "\(bridge.rawValue).sock").path }
    }

    public enum Bridge: String, CaseIterable, Sendable {
        case clipboard
        case audio
        case timezone

        public var portName: String { "dev.linuxvm.\(rawValue)" }
        var helperFlag: String { "--bridge-native-\(rawValue)" }
    }

    public static func make(
        configuration: VMConfiguration,
        library: VMLibrary,
        runtime: Runtime,
        paths: Paths,
        host: Host
    ) -> QEMULaunch {
        func escaped(_ path: String) -> String { path.replacingOccurrences(of: ",", with: ",,") }
        let disk = library.diskURL(for: configuration).path
        let variables = library.variablesURL(for: configuration.id).path
        let logs = library.logsDirectory(for: configuration.id)
        let cpus = configuration.cpuCount
        let display = configuration.display

        var arguments: [String] = [
            "-name", configuration.name,
            "-machine", "virt,gic-version=3",
            "-accel", "hvf",
            "-cpu", "host,pmu=off",
            "-smp", "\(cpus),sockets=1,cores=\(cpus),threads=1",
            "-m", "\(configuration.memoryMiB)M",
            "-nodefaults",
            "-action", "reboot=reset,shutdown=poweroff",
            "-drive", "if=pflash,format=raw,readonly=on,file=\(escaped(runtime.firmware.path))",
            "-drive", "if=pflash,format=raw,file=\(escaped(variables))",
            "-smbios", "type=11,value=io.systemd.credential.binary:linuxvm.host=\(hostCredential(configuration: configuration, host: host))",
            "-drive", "if=none,id=root,file=\(escaped(disk)),format=\(configuration.diskFormat.rawValue),media=disk,cache=writeback,discard=unmap",
            "-device", "virtio-blk-pci,drive=root,bootindex=0",
            "-device", "qemu-xhci,id=usb,streams=off",
            "-device", "usb-kbd,bus=usb.0",
        ]

        var install = "if=none,id=install,media=cdrom,readonly=on"
        if let media = configuration.installMedia {
            install += ",file=\(escaped(media)),format=raw"
        }
        arguments += [
            "-drive", install,
            "-device", "usb-bot,id=install-bot,bus=usb.0",
            "-device", "scsi-cd,id=install-cd,bus=install-bot.0,drive=install,bootindex=1",
        ]
        if FileManager.default.fileExists(atPath: runtime.guestTools.path) {
            arguments += [
                "-drive", "if=none,id=tools,media=cdrom,readonly=on,file=\(escaped(runtime.guestTools.path)),format=raw",
                "-device", "usb-bot,id=tools-bot,bus=usb.0",
                "-device", "scsi-cd,id=tools-cd,bus=tools-bot.0,drive=tools",
            ]
        }

        var netdev = "user,id=net0"
        for forward in configuration.portForwards {
            netdev += ",hostfwd=tcp:127.0.0.1:\(forward.hostPort)-:\(forward.guestPort)"
        }
        let frequency = host.audioFrequency
        arguments += [
            "-netdev", netdev,
            "-device", "virtio-net-pci,netdev=net0,mac=\(configuration.macAddress),romfile=",
            "-audiodev", "sdl,id=audio0,timer-period=1000,out.buffer-count=8,out.frequency=\(frequency),in.frequency=\(frequency)",
            "-device", "intel-hda,id=hda,romfile=",
            "-device", "hda-micro,bus=hda.0,audiodev=audio0",
            "-device", "virtio-gpu-gl-pci,max_outputs=1,xres=1920,yres=1080,romfile=",
            "-display", "cocoa,gl=on,show-cursor=\(display.showMacCursor ? "on" : "off"),zoom-to-fit=on,full-screen=off,immersive=\(display.immersive ? "on" : "off"),full-grab=off,swap-opt-cmd=off",
            "-device", "virtio-keyboard-pci,romfile=",
            "-device", "virtio-tablet-pci,romfile=",
            "-device", "virtio-pinch-pci,romfile=",
            "-object", "rng-random,id=rng0,filename=/dev/urandom",
            "-device", "virtio-rng-pci,rng=rng0",
            "-device", "virtio-balloon-pci,free-page-reporting=on",
            "-device", "virtio-serial-pci,id=serial0",
        ]
        for (index, bridge) in Bridge.allCases.enumerated() {
            arguments += [
                "-chardev", "socket,id=\(bridge.rawValue),path=\(escaped(paths.bridgeSocket(bridge))),server=on,wait=off",
                "-device", "virtserialport,bus=serial0.0,nr=\(index + 1),chardev=\(bridge.rawValue),name=\(bridge.portName)",
            ]
        }
        arguments += [
            "-chardev", "socket,id=status,path=\(escaped(paths.statusSocket)),server=on,wait=off",
            "-device", "virtserialport,bus=serial0.0,nr=4,chardev=status,name=dev.linuxvm.status",
        ]
        if let folder = configuration.sharedFolder {
            arguments += [
                "-fsdev", "local,id=share,path=\(folder),security_model=none,multidevs=remap,guest_owner_uid=1000,guest_owner_gid=1000",
                "-device", "virtio-9p-pci,fsdev=share,mount_tag=mac,romfile=",
            ]
        }
        arguments += [
            "-serial", "file:\(escaped(logs.appending(path: "serial.log").path))",
            "-monitor", "none",
            "-qmp", "unix:\(escaped(paths.supervisorSocket)),server=on,wait=off",
            "-qmp", "unix:\(escaped(paths.controlSocket)),server=on,wait=off",
        ]

        var environment = ProcessInfo.processInfo.environment
        environment["TRYOMARCHY_KEYBOARD"] = host.keyboardGeometry
        environment["TRYOMARCHY_TOUCH_SCROLL_SCALE_FILE"] = library.scrollScaleURL(for: configuration.id).path
        environment["OMARCHY_SDL_AUDIO_CONTROL_DIRECTORY"] = paths.audioRoutes.path
        if display.coverNotch {
            environment.removeValue(forKey: "TRYOMARCHY_NOTCH")
        } else {
            environment["TRYOMARCHY_NOTCH"] = "0"
        }
        if FileManager.default.fileExists(atPath: runtime.icon.path) {
            environment["TRYOMARCHY_PRODUCT_ICON"] = runtime.icon.path
        }
        environment.removeValue(forKey: "SDL_AUDIO_DEVICE_NAME")
        return QEMULaunch(arguments: arguments, environment: environment)
    }

    /// The `linuxvm.host` systemd credential (docs/host-guest-contract.md).
    static func hostCredential(configuration: VMConfiguration, host: Host) -> String {
        var lines: [String] = []
        if let zone = host.timeZone, zone.range(of: #"^[A-Za-z0-9_+/-]{1,128}$"#, options: .regularExpression) != nil {
            lines.append("timezone=\(zone)")
        }
        if let folder = configuration.sharedFolder {
            let name = URL(fileURLWithPath: folder).lastPathComponent
            let encoded = Data(name.utf8).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
            lines.append("shared_folder_name=\(encoded)")
        }
        return Data((lines.joined(separator: "\n") + "\n").utf8).base64EncodedString()
    }
}
