import Foundation
import Testing
@testable import LinuxVMCore

private extension Data {
    func removingKey(_ key: String) -> Data {
        guard var object = (try? JSONSerialization.jsonObject(with: self)) as? [String: Any] else { return self }
        object.removeValue(forKey: key)
        return (try? JSONSerialization.data(withJSONObject: object)) ?? self
    }
}

struct GuestReportTests {
    func line(_ changes: [String: Any] = [:]) throws -> Data {
        var object: [String: Any] = ["type": "status", "package": "0.2.0", "os": "Ubuntu", "shell": "50.1", "extension": "active"]
        object.merge(changes) { _, new in new }
        return try JSONSerialization.data(withJSONObject: object)
    }
    @Test func validReportAndUnknownFields() throws {
        let now = Date()
        let report = try #require(GuestReport.parse(line(["future": ["anything": true]]), receivedAt: now))
        #expect(report.package == "0.2.0")
        #expect(report.os == "Ubuntu")
        #expect(report.shell == "50.1")
        #expect(report.extensionState == .active)
        #expect(report.receivedAt == now)
        #expect(try GuestReport.parse(line(["extension": "future"]))?.extensionState == .unknown)
        var object = try #require(JSONSerialization.jsonObject(with: line()) as? [String: Any])
        object.removeValue(forKey: "shell")
        #expect(GuestReport.parse(try JSONSerialization.data(withJSONObject: object))?.shell == nil)
    }
    @Test func rejectsInvalidLines() throws {
        for changes: [String: Any] in [
            ["package": "1.2"], ["package": "12345.0.0"], ["package": "1.2.3\n"],
            ["package": 2], ["os": true], ["shell": 12], ["extension": false], ["type": "other"],
            ["os": "a\nb"], ["os": "a\u{7f}b"], ["shell": "a\tb"],
            ["os": String(repeating: "a", count: 129)], ["shell": String(repeating: "a", count: 33)]
        ] { #expect(try GuestReport.parse(line(changes)) == nil) }
        for bytes in [Data("{bad}".utf8), Data("[]".utf8), Data([0xff]), Data(repeating: 32, count: 4097)] {
            #expect(GuestReport.parse(bytes) == nil)
        }
    }
    @Test func desktopAndClipboardKeys() throws {
        let kde = try #require(GuestReport.parse(line([
            "package": "0.3.0", "os": "Fedora Linux 45 (KDE Plasma Desktop Edition)",
            "desktop": "KDE", "desktopVersion": "6.8.1", "clipboard": "active", "extension": "unknown",
        ]).removingKey("shell")))
        #expect(kde.desktopLabel == "KDE Plasma 6.8.1")
        #expect(kde.clipboardState == .active)
        #expect(!kde.isGNOME)
        // 0.2 guests: GNOME only, the clipboard follows the extension.
        let old = try #require(GuestReport.parse(line(["extension": "missing"])))
        #expect(old.desktopLabel == "GNOME 50.1")
        #expect(old.clipboardState == .pending)
        #expect(old.isGNOME)
        #expect(try GuestReport.parse(line(["clipboard": "future"]))?.clipboardState == .unknown)
        #expect(try GuestReport.parse(line(["clipboard": "unsupported", "extension": "unknown"]))?.clipboardState == .unsupported)
        #expect(try GuestReport.parse(line(["desktop": ""]))?.desktop == nil)
        let unknownDesktop = try #require(GuestReport.parse(line().removingKey("shell")))
        #expect(unknownDesktop.desktopLabel == nil)
        for changes: [String: Any] in [["desktop": 5], ["desktopVersion": true], ["clipboard": 1],
                                       ["desktop": String(repeating: "a", count: 33)], ["desktop": "a\nb"]] {
            #expect(try GuestReport.parse(line(changes)) == nil)
        }
    }
    @Test func boundedFramingRecoversAfterOversizedLine() throws {
        var framing = GuestStatusLines()
        var lines: [Data?] = []
        framing.append(Data(repeating: 97, count: 100_000)) { lines.append($0) }
        #expect(lines.isEmpty)
        framing.append(Data([10]) + (try line()) + Data([10])) { lines.append($0) }
        #expect(lines.count == 2)
        #expect(lines[0] == nil)
        #expect(GuestReport.parse(try #require(lines[1])) != nil)
    }
    @Test func numericVersions() {
        #expect(GuestToolsVersion.compare("0.10.0", "0.2.9") == .orderedDescending)
        #expect(GuestToolsVersion.compare("1.0.0", "1.0.0") == .orderedSame)
        #expect(GuestToolsVersion.compare("1.0.0", "2.0.0") == .orderedAscending)
        #expect(GuestToolsVersion.compare("01.0.0", "1.0.0") == .orderedSame)
        for bad in ["1.2", "v1.2.3", "1.2.3\n", "1.2.3.4", "-1.0.0", "10000.0.0"] {
            #expect(GuestToolsVersion.compare(bad, "1.0.0") == nil)
            #expect(GuestToolsVersion.compare("1.0.0", bad) == nil)
        }
    }
    @Test func reportPersistenceAndBundledVersion() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let library = VMLibrary(root: root)
        let id = UUID().uuidString
        try FileManager.default.createDirectory(at: library.directory(for: id), withIntermediateDirectories: true)
        let report = try #require(GuestReport.parse(line(), receivedAt: Date(timeIntervalSince1970: 1000)))
        try library.writeGuestReport(report, id: id)
        #expect(library.guestReport(id: id) == report)
        let kde = try #require(GuestReport.parse(line(["desktop": "KDE", "desktopVersion": "6.6.6", "clipboard": "active"]),
                                                 receivedAt: Date(timeIntervalSince1970: 2000)))
        try library.writeGuestReport(kde, id: id)
        #expect(library.guestReport(id: id) == kde)
        // A report saved by an app before 0.3 has no desktop keys.
        try Data(#"{"package":"0.2.2","os":"Ubuntu","shell":"50.1","extension":"active","receivedAt":"2026-11-03T11:40:03Z"}"#.utf8)
            .write(to: library.directory(for: id).appending(path: "guest.json"))
        #expect(library.guestReport(id: id)?.desktopLabel == "GNOME 50.1")
        let runtime = Runtime(contents: root)
        #expect(runtime.guestToolsVersion == nil)
        try FileManager.default.createDirectory(at: root.appending(path: "Resources"), withIntermediateDirectories: true)
        let version = root.appending(path: "Resources/guest-tools-version")
        try "0.2.0\n".write(to: version, atomically: true, encoding: .utf8)
        #expect(runtime.guestToolsVersion == "0.2.0")
        try "0.2.0\nextra".write(to: version, atomically: true, encoding: .utf8)
        #expect(runtime.guestToolsVersion == nil)
    }
}
