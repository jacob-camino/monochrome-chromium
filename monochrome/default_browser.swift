import AppKit
import Foundation

// Build with: xcrun swiftc -parse-as-library default_browser.swift -o default-browser
// This helper only changes preferences when invoked with --set APP_PATH.
@main
struct DefaultBrowser {
    @MainActor
    static func main() async {
        let args = Array(CommandLine.arguments.dropFirst())
        let usage = "Usage: default-browser --status | --verify APP_PATH | --set APP_PATH"
        if args == ["--help"] || args == ["-h"] {
            print(usage)
            return
        }
        guard args == ["--status"] ||
                (args.count == 2 && ["--verify", "--set"].contains(args[0])) else {
            fail(usage, code: 2)
        }

        var expectedURL: URL?
        var expectedID: String?
        if args.count == 2 {
            let url = URL(fileURLWithPath: args[1]).standardizedFileURL.resolvingSymlinksInPath()
            guard url.pathExtension == "app",
                  let bundle = Bundle(url: url),
                  let bundleID = bundle.bundleIdentifier,
                  let executable = bundle.executableURL,
                  FileManager.default.isExecutableFile(atPath: executable.path) else {
                fail("Invalid or nonexecutable application bundle: \(url.path)", code: 2)
            }
            expectedURL = url
            expectedID = bundleID

            if args[0] == "--set" {
                do {
                    // Await the first consent result. A refusal must not cause a
                    // second prompt for HTTPS. This matches Chromium on macOS.
                    try await NSWorkspace.shared.setDefaultApplication(
                        at: url, toOpenURLsWithScheme: "http")
                    try await NSWorkspace.shared.setDefaultApplication(
                        at: url, toOpenURLsWithScheme: "https")
                } catch {
                    reportStatus(expectedURL: expectedURL, expectedID: expectedID)
                    fail("macOS did not complete the default-browser change: \(error.localizedDescription)", code: 3)
                }
            }
        }

        let matches = reportStatus(expectedURL: expectedURL, expectedID: expectedID)
        if expectedURL != nil && !matches {
            fail("HTTP and HTTPS do not both resolve to the requested application.", code: 4)
        }
    }

    @MainActor
    @discardableResult
    static func reportStatus(expectedURL: URL?, expectedID: String?) -> Bool {
        var matches = true
        var handlers: [[String: Any]] = []
        for scheme in ["http", "https"] {
            let query = URL(string: "\(scheme)://example.com")!
            let url = NSWorkspace.shared.urlForApplication(toOpen: query)?
                .standardizedFileURL.resolvingSymlinksInPath()
            let bundleID = url.flatMap { Bundle(url: $0)?.bundleIdentifier }
            let handlerMatches = expectedURL == nil ||
                (url?.path == expectedURL?.path && bundleID == expectedID)
            matches = matches && handlerMatches
            handlers.append([
                "scheme": scheme,
                "application": url?.path ?? NSNull() as Any,
                "bundle_identifier": bundleID ?? NSNull() as Any,
                "matches_requested_application": handlerMatches,
            ])
        }
        let result: [String: Any] = [
            "handlers": handlers,
            "requested_application": expectedURL?.path ?? NSNull() as Any,
            "verified": expectedURL == nil ? NSNull() as Any : matches,
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            fail("Could not serialize status: \(error.localizedDescription)", code: 1)
        }
        return matches
    }

    static func fail(_ message: String, code: Int32) -> Never {
        FileHandle.standardError.write(Data("\(message)\n".utf8))
        exit(code)
    }
}
