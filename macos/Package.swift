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
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.10.0"),
    ],
    targets: [
        .target(name: "LinuxVMCore"),
        .executableTarget(name: "linuxvmctl", dependencies: ["LinuxVMCore"]),
        .executableTarget(
            name: "LinuxVM",
            dependencies: ["LinuxVMCore", .product(name: "Sparkle", package: "Sparkle")],
            // The app bundle keeps Sparkle.framework in Contents/Frameworks.
            linkerSettings: [.unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks"])]
        ),
        .testTarget(name: "LinuxVMCoreTests", dependencies: ["LinuxVMCore"]),
    ],
    swiftLanguageModes: [.v6]
)
