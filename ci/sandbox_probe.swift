// Nightmare TV: what does the App Sandbox allow with our exact entitlements?
//
// Built into a tiny .app, ad-hoc signed with a copy of the app's
// Release.entitlements (and a second variant with the entitlements we plan
// to add), launched with `open`, and asked to do what the real app does on
// macOS: run system tools and a Homebrew ffmpeg, write to Downloads /
// Movies / Documents, use the Keychain, bind a listening socket.
// Results go to probe.json inside the sandbox container.
import Foundation
import Security

var results: [[String: String]] = []
func record(_ name: String, _ ok: Bool, _ detail: String) {
    results.append(["test": name, "ok": ok ? "yes" : "no", "detail": String(detail.prefix(300))])
}

func run(_ name: String, _ path: String, _ args: [String]) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    let out = Pipe(); let err = Pipe()
    p.standardOutput = out; p.standardError = err
    do {
        try p.run()
        p.waitUntilExit()
        let o = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let e = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        record(name, p.terminationStatus == 0, "exit=\(p.terminationStatus) out=\(o.prefix(120)) err=\(e.prefix(160))")
    } catch {
        record(name, false, "launch failed: \(error)")
    }
}

func write(_ name: String, _ path: String) {
    do {
        try FileManager.default.createDirectory(atPath: (path as NSString).deletingLastPathComponent,
                                                withIntermediateDirectories: true)
        try "probe".write(toFile: path, atomically: false, encoding: .utf8)
        record(name, true, path)
    } catch {
        record(name, false, "\(path): \(error.localizedDescription)")
    }
}

let realHome = String(cString: getpwuid(getuid())!.pointee.pw_dir)
let container = NSHomeDirectory()
record("container_home", true, container)
let ffmpeg = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "/usr/local/bin/ffmpeg"
let lavfi = ["-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2", "-c:v", "mpeg2video"]

run("exec_ioreg", "/usr/sbin/ioreg", ["-rd1", "-c", "IOPlatformExpertDevice"])
run("exec_pmset", "/usr/bin/pmset", ["-g", "batt"])
run("exec_scutil_proxy", "/usr/sbin/scutil", ["--proxy"])
run("exec_security_roots", "/usr/bin/security", ["find-certificate", "-a", "-p",
    "/System/Library/Keychains/SystemRootCertificates.keychain"])
run("exec_curl", "/usr/bin/curl", ["-sI", "--max-time", "10", "https://example.com"])
run("exec_brew_ffmpeg_version", ffmpeg, ["-hide_banner", "-version"])
try? FileManager.default.createDirectory(atPath: container + "/Documents/Nightmare", withIntermediateDirectories: true)
run("exec_brew_ffmpeg_record_container", ffmpeg, lavfi + [container + "/Documents/Nightmare/rec.ts"])
try? FileManager.default.createDirectory(atPath: realHome + "/Movies/Nightmare", withIntermediateDirectories: true)
run("exec_brew_ffmpeg_record_movies", ffmpeg, lavfi + [realHome + "/Movies/Nightmare/rec.ts"])

write("write_container_documents", container + "/Documents/Nightmare/x.txt")
write("write_container_downloads_link", container + "/Downloads/x.txt")
write("write_real_downloads", realHome + "/Downloads/nightmare_probe.txt")
write("write_real_movies", realHome + "/Movies/Nightmare/x.txt")
write("write_real_documents", realHome + "/Documents/nightmare_probe.txt")

// Keychain: data protection keychain (flutter_secure_storage default) and legacy file keychain
for (label, dp) in [("keychain_dataprotection", true), ("keychain_legacy", false)] {
    var q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                            kSecAttrService as String: "tv.nightmare.probe",
                            kSecAttrAccount as String: label,
                            kSecValueData as String: "v".data(using: .utf8)!]
    if dp { q[kSecUseDataProtectionKeychain as String] = true }
    SecItemDelete(q as CFDictionary)
    let st = SecItemAdd(q as CFDictionary, nil)
    record(label, st == errSecSuccess, "OSStatus \(st)")
}

// Listening socket, as the loopback relay and the LAN API do
let fd = socket(AF_INET, SOCK_STREAM, 0)
var addr = sockaddr_in()
addr.sin_family = sa_family_t(AF_INET)
addr.sin_port = in_port_t(UInt16(8086).bigEndian)
addr.sin_addr = in_addr(s_addr: 0)
let b = withUnsafePointer(to: &addr) {
    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
}
record("bind_0.0.0.0_8086", b == 0 && listen(fd, 1) == 0, "errno \(errno)")
close(fd)

let data = try! JSONSerialization.data(withJSONObject: results, options: [.prettyPrinted])
try! data.write(to: URL(fileURLWithPath: container + "/probe.json"))
