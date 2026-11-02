import Foundation
import Testing
@testable import LinuxVMCore

struct ConfigurationTests {
    let host = HostResources(logicalCPUs: 10, memoryMiB: 16384)

    func machine() -> VMConfiguration {
        VMConfiguration(name: "Ubuntu", cpuCount: 4, memoryMiB: 4096, diskFileName: "disk.img", diskFormat: .raw)
    }

    @Test func acceptsDefaults() throws {
        try machine().validate(host: host)
    }

    @Test func rejectsOutOfRangeResources() {
        var configuration = machine()
        configuration.cpuCount = 11
        #expect(throws: ConfigurationError.self) { try configuration.validate(host: host) }
        configuration = machine()
        configuration.memoryMiB = 16384
        #expect(throws: ConfigurationError.self) { try configuration.validate(host: host) }
        configuration = machine()
        configuration.scrollScale = 9
        #expect(throws: ConfigurationError.self) { try configuration.validate(host: host) }
    }

    @Test func rejectsCommasInPathsAndDuplicateForwards() {
        var configuration = machine()
        configuration.sharedFolder = "/Users/a,b"
        #expect(throws: ConfigurationError.self) { try configuration.validate(host: host) }
        configuration = machine()
        configuration.portForwards = [PortForward(hostPort: 2222, guestPort: 22), PortForward(hostPort: 2222, guestPort: 80)]
        #expect(throws: ConfigurationError.self) { try configuration.validate(host: host) }
    }

    @Test func macAddressIsStableAndLocal() {
        let configuration = VMConfiguration(id: "0A1B2C3D-4E5F-6071-8293-A4B5C6D7E8F9", name: "x", cpuCount: 1,
                                            memoryMiB: 2048, diskFileName: "disk.img", diskFormat: .raw)
        #expect(configuration.macAddress == "52:54:00:0a:1b:2c")
    }

    @Test func hostCredentialCarriesZoneAndFolderName() throws {
        var configuration = machine()
        configuration.sharedFolder = "/Users/me/Work Stuff"
        let encoded = QEMULaunch.hostCredential(configuration: configuration, host: .init(timeZone: "Asia/Tokyo"))
        let text = String(decoding: try #require(Data(base64Encoded: encoded)), as: UTF8.self)
        #expect(text == "timezone=Asia/Tokyo\nshared_folder_name=V29yayBTdHVmZg\n")
    }

    @Test func launchUsesContractPortNames() {
        let library = VMLibrary(root: URL(fileURLWithPath: "/tmp/linuxvm-tests"))
        let runtime = Runtime(contents: URL(fileURLWithPath: "/nonexistent"))
        let paths = QEMULaunch.Paths(runDirectory: URL(fileURLWithPath: "/tmp/r"))
        let launch = QEMULaunch.make(configuration: machine(), library: library, runtime: runtime, paths: paths, host: .init())
        let joined = launch.arguments.joined(separator: " ")
        for name in ["dev.linuxvm.clipboard", "dev.linuxvm.audio", "dev.linuxvm.timezone", "virtio-pinch-pci", "show-cursor=off", "immersive=on"] {
            #expect(joined.contains(name))
        }
        #expect(launch.environment["TRYOMARCHY_NOTCH"] == "0")
        #expect(!joined.contains("mount_tag=mac"))
    }
}
