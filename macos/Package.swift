// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "LinuxVM",
    platforms: [.macOS("15.0")],
    products: [
        .library(name: "LinuxVMCore", targets: ["LinuxVMCore"]),
        .executable(name: "linuxvmctl", targets: ["linuxvmctl"]),
        .executable(name: "LinuxVM", targets: ["LinuxVM"]),
    ],
    targets: [
        .target(name: "LinuxVMCore"),
        .executableTarget(name: "linuxvmctl", dependencies: ["LinuxVMCore"]),
        .executableTarget(name: "LinuxVM", dependencies: ["LinuxVMCore"]),
        .testTarget(name: "LinuxVMCoreTests", dependencies: ["LinuxVMCore"]),
    ],
    swiftLanguageModes: [.v6]
)
