import AppKit
import Foundation
import SwiftUI

struct LauncherCheck: Identifiable, Decodable {
    var id: String { name }
    let name: String
    let ok: Bool
    let detail: String
}

private struct EngineConfiguration: Decodable {
    let runtime_path: String?
    let gptk_path: String?
    let game_path: String?
    let display_mode: String?
    let setup_complete: Bool?
}

private struct EngineEvent: Decodable {
    let type: String
    let message: String
    let state: String?
    let config: EngineConfiguration?
    let checks: [LauncherCheck]?
    let ready: Bool?
    let path: String?
}

@MainActor
final class LauncherModel: ObservableObject {
    @Published var runtimePath = ""
    @Published var gptkPath = ""
    @Published var gamePath = ""
    @Published var displayMode = "auto"
    @Published private(set) var state = "needs_setup"
    @Published private(set) var message = "Checking your installation…"
    @Published private(set) var error: String?
    @Published private(set) var checks: [LauncherCheck] = []
    @Published private(set) var ready = false
    @Published private(set) var setupComplete = false
    @Published private(set) var operation: String?
    @Published private(set) var isStopping = false
    @Published private(set) var diagnosticsURL: URL?
    @Published private var sessionNeedsCleanup = false

    private var process: Process?
    private var stopProcess: Process?
    private var pendingCommand: String?
    private var receivedEvent = false
    private var receivedTerminal = false
    private var commandFailed = false
    private var stopConfirmed = false
    private var stopFailed = false
    private var completion: ((Bool) -> Void)?
    var onStopped: (() -> Void)?

    var busy: Bool { operation != nil || isStopping }
    var hasSession: Bool {
        ["launching", "running", "waiting_for_login", "stopping"].contains(state)
            || sessionNeedsCleanup || operation == "play" || operation == "steam"
    }
    var canStop: Bool { hasSession && !isStopping }
    var stateTitle: String {
        switch state {
        case "idle": return ready ? "Ready to play" : "Idle"
        case "needs_setup": return "Setup needed"
        case "installing": return "Setting up"
        case "waiting_for_login": return "Continue in Steam or Rockstar"
        case "launching": return "Starting game"
        case "running": return "Session active"
        case "stopping": return "Stopping safely"
        case "error": return "Needs attention"
        default: return "Checking installation"
        }
    }

    func refresh(completion: ((Bool) -> Void)? = nil) {
        guard !busy else { completion?(false); return }
        self.completion = completion
        launch("status")
    }

    func save(then command: String? = nil) {
        guard !busy, !hasSession else { return }
        pendingCommand = command
        let config: [String: Any] = ["runtime_path": runtimePath, "gptk_path": gptkPath,
                                     "game_path": gamePath, "display_mode": displayMode]
        do {
            let data = try JSONSerialization.data(withJSONObject: config)
            guard let json = String(data: data, encoding: .utf8) else {
                throw LauncherFailure.invalidConfiguration
            }
            launch("configure", extra: ["--json", json])
        } catch { fail(error.localizedDescription) }
    }

    func repair() {
        guard !busy, !hasSession else { return }
        launch("repair")
    }

    func exportDiagnostics() {
        guard !busy else { return }
        let panel = NSSavePanel()
        panel.title = "Export privacy-safe diagnostics"
        panel.nameFieldStringValue = "RDR2Mac-diagnostics.json"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        diagnosticsURL = nil
        launch("diagnostics", extra: ["--output", url.path])
    }

    func showLocalLogs() {
        let root: URL
        if let config = ProcessInfo.processInfo.environment["RDR2MAC_CONFIG"], !config.isEmpty {
            root = URL(fileURLWithPath: config).deletingLastPathComponent()
        } else {
            root = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/RDR2Mac", isDirectory: true)
        }
        let logs = root.appendingPathComponent("Logs", isDirectory: true)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: logs.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            fail("No local logs folder exists yet. Run setup or a managed session first; Export Diagnostics is available for privacy-safe troubleshooting.")
            return
        }
        NSWorkspace.shared.activateFileViewerSelecting([logs])
    }

    func chooseDirectory(_ keyPath: ReferenceWritableKeyPath<LauncherModel, String>) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        self[keyPath: keyPath] = url.path
    }

    func stop() {
        guard canStop else { return }
        isStopping = true
        stopConfirmed = false
        stopFailed = false
        error = nil
        message = "Requesting managed-session cleanup…"
        // The Python supervisor handles SIGTERM and cleans up only its own prefix.
        if let process, process.isRunning, operation == "play" {
            process.terminate()
            return
        }
        do {
            let child = try makeProcess("stop", extra: [])
            stopProcess = child
            run(child, onLine: { [weak self] line in self?.receiveStop(line) }, onExit: { [weak self] code in
                guard let self else { return }
                self.stopProcess = nil
                self.isStopping = false
                if code != 0 || self.stopFailed {
                    self.fail("Could not stop the managed session (exit \(code)). Retry Stop; no unrelated Wine processes were targeted.")
                } else if self.stopConfirmed {
                    self.onStopped?()
                } else {
                    self.fail("The engine did not confirm session cleanup. Keep the app open and retry Stop.")
                }
            })
        } catch {
            isStopping = false
            fail(error.localizedDescription)
        }
    }

    private func makeProcess(_ command: String, extra: [String]) throws -> Process {
        let environment = ProcessInfo.processInfo.environment
        let resources = environment["RDR2MAC_RESOURCE_DIR"].map { URL(fileURLWithPath: $0, isDirectory: true) }
            ?? Bundle.main.resourceURL
        guard let resources else { throw LauncherFailure.missingResources }
        let script = resources.appendingPathComponent("engine/launcher.py")
        let python = environment["RDR2MAC_PYTHON"].map { URL(fileURLWithPath: $0) }
            ?? resources.appendingPathComponent("python/bin/python3")
        guard FileManager.default.fileExists(atPath: script.path),
              FileManager.default.isExecutableFile(atPath: python.path) else {
            throw LauncherFailure.missingResources
        }
        let child = Process()
        child.executableURL = python
        child.arguments = ["-B", "-E", "-s", "-u", script.path, command]
        if let config = environment["RDR2MAC_CONFIG"], !config.isEmpty {
            child.arguments?.append(contentsOf: ["--config", config])
        }
        child.arguments?.append(contentsOf: extra)
        child.environment = environment
        child.standardInput = FileHandle.nullDevice
        return child
    }

    private func launch(_ command: String, extra: [String] = []) {
        error = nil
        receivedEvent = false
        receivedTerminal = false
        commandFailed = false
        operation = command
        do {
            let child = try makeProcess(command, extra: extra)
            process = child
            run(child, onLine: { [weak self] line in self?.receive(line) }, onExit: { [weak self] code in
                self?.finished(command: command, code: code)
            })
        } catch {
            operation = nil
            process = nil
            pendingCommand = nil
            fail(error.localizedDescription)
            completion?(false)
            completion = nil
        }
    }

    // One reader queue preserves line order and drains both pipes without blocking the UI.
    // Accumulating bytes (not strings) also handles split UTF-8 characters correctly.
    private func run(_ child: Process, onLine: @escaping @MainActor (Data) -> Void,
                     onExit: @escaping @MainActor (Int32) -> Void) {
        let stdout = Pipe()
        let stderr = Pipe()
        child.standardOutput = stdout
        child.standardError = stderr
        do { try child.run() } catch {
            fail("Unable to start the bundled engine: \(error.localizedDescription)")
            onExit(-1)
            return
        }
        DispatchQueue.global(qos: .utility).async {
            while !stderr.fileHandleForReading.availableData.isEmpty { /* Never expose raw vendor output. */ }
            try? stderr.fileHandleForReading.close()
        }
        DispatchQueue.global(qos: .utility).async {
            var buffer = Data()
            var oversizedLine = false
            while true {
                let chunk = stdout.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                for byte in chunk {
                    if byte == 10 {
                        let line = oversizedLine ? Data("invalid".utf8) : buffer
                        if !line.isEmpty { DispatchQueue.main.async { onLine(line) } }
                        buffer.removeAll(keepingCapacity: true)
                        oversizedLine = false
                    } else if !oversizedLine {
                        if buffer.count < 1_048_576 { buffer.append(byte) }
                        else { buffer.removeAll(keepingCapacity: true); oversizedLine = true }
                    }
                }
            }
            if oversizedLine || !buffer.isEmpty {
                let line = oversizedLine ? Data("invalid".utf8) : buffer
                DispatchQueue.main.async { onLine(line) }
            }
            try? stdout.fileHandleForReading.close()
            child.waitUntilExit()
            let code = child.terminationStatus
            DispatchQueue.main.async { onExit(code) }
        }
    }

    private func receive(_ data: Data) {
        guard let event = try? JSONDecoder().decode(EngineEvent.self, from: data),
              ["status", "progress", "error", "result"].contains(event.type) else {
            commandFailed = true
            fail("The engine returned an invalid response. Reinstall the app or export diagnostics.")
            return
        }
        receivedEvent = true
        if event.type == "status" || event.type == "result" { receivedTerminal = true }
        apply(event, updatesSession: operation != "diagnostics")
        if event.type == "error" { commandFailed = true; error = event.message }
    }

    private func receiveStop(_ data: Data) {
        guard let event = try? JSONDecoder().decode(EngineEvent.self, from: data),
              ["status", "progress", "error", "result"].contains(event.type) else {
            stopFailed = true
            fail("The engine returned an invalid cleanup response.")
            return
        }
        apply(event)
        if event.type == "error" { stopFailed = true; error = event.message }
        if ["status", "result"].contains(event.type), event.state == "idle" || event.state == "needs_setup" {
            stopConfirmed = true
        }
    }

    private func apply(_ event: EngineEvent, updatesSession: Bool = true) {
        message = event.message
        if !updatesSession {
            if event.type == "result", let path = event.path {
                diagnosticsURL = URL(fileURLWithPath: path)
            }
            return
        }
        if let state = event.state {
            self.state = state
            if ["launching", "running", "waiting_for_login", "stopping"].contains(state) {
                sessionNeedsCleanup = true
            } else if ["idle", "needs_setup"].contains(state), ["status", "result"].contains(event.type) {
                sessionNeedsCleanup = false
            }
        }
        if let ready = event.ready { self.ready = ready }
        if let checks = event.checks { self.checks = checks }
        if let config = event.config {
            runtimePath = config.runtime_path ?? ""
            gptkPath = config.gptk_path ?? ""
            gamePath = config.game_path ?? ""
            displayMode = config.display_mode ?? "auto"
            setupComplete = config.setup_complete ?? false
        }
    }

    private func finished(command: String, code: Int32) {
        process = nil
        operation = nil
        let stopping = isStopping && stopProcess == nil
        if stopping { isStopping = false }
        let success = code == 0 && receivedEvent && receivedTerminal && !commandFailed
        if !success && error == nil {
            fail(code == 0 ? "The engine ended without a complete response. Export diagnostics and retry."
                 : "The \(command) operation failed (exit \(code)). Review the setup checks and retry.")
        }
        let next = pendingCommand
        pendingCommand = nil
        if success, command == "configure", let next {
            launch(next)
            return
        }
        completion?(success)
        completion = nil
        if stopping, success, state == "idle" || state == "needs_setup" { onStopped?() }
    }

    private func fail(_ detail: String) {
        error = detail
        message = detail
        // Session state is engine-owned: a transport failure must not hide Stop.
    }
}

private enum LauncherFailure: LocalizedError {
    case missingResources, invalidConfiguration
    var errorDescription: String? {
        switch self {
        case .missingResources:
            return "The bundled Python engine is missing or not executable. Move a complete RDR2Mac.app to Applications, or reinstall it."
        case .invalidConfiguration: return "The setup values could not be encoded. Review your directory selections."
        }
    }
}
