import AppKit
import SwiftUI

@main
struct RDR2MacApp: App {
    @NSApplicationDelegateAdaptor(LauncherAppDelegate.self) private var delegate

    var body: some Scene {
        Window("RDR2 for Mac (unofficial)", id: "launcher") {
            LauncherView(model: delegate.model)
        }
        .defaultSize(width: 760, height: 840)
        .commands {
            CommandGroup(replacing: .newItem) { }
            CommandGroup(replacing: .appInfo) {
                Button("About RDR2 for Mac") {
                    NSApplication.shared.orderFrontStandardAboutPanel(options: [
                        .applicationName: "RDR2 for Mac (unofficial)",
                        .credits: NSAttributedString(string: "An independent compatibility launcher for a legally owned Steam copy. Not affiliated with the game or dependency vendors.")
                    ])
                }
            }
        }
    }
}

@MainActor
final class LauncherAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = LauncherModel()
    private var allowQuit = false
    private var quitRequested = false
    private var windowObserver: NSObjectProtocol?

    func applicationDidFinishLaunching(_ notification: Notification) {
        windowObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didBecomeMainNotification, object: nil, queue: .main
        ) { [weak self] notification in
            guard let window = notification.object as? NSWindow,
                  window.identifier?.rawValue == "launcher" || window.title == "RDR2 for Mac (unofficial)" else { return }
            MainActor.assumeIsolated { window.delegate = self }
        }
        for window in NSApp.windows where window.title == "RDR2 for Mac (unofficial)" {
            window.delegate = self
        }
        model.onStopped = { [weak self] in
            guard let self, self.quitRequested else { return }
            self.allowQuit = true
            NSApp.terminate(nil)
        }
        if CommandLine.arguments.contains("--smoke") {
            // This path runs the same process transport and decoder as the UI, against the real engine.
            model.refresh { success in
                let payload: [String: Any] = ["ui_model_smoke": success, "state": self.model.state,
                                              "ready": self.model.ready]
                if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) {
                    FileHandle.standardOutput.write(data)
                    FileHandle.standardOutput.write(Data([10]))
                }
                exit(success ? 0 : 1)
            }
        } else {
            model.refresh()
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        requestQuit() ? .terminateNow : .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if requestQuit() {
            allowQuit = true
            NSApp.terminate(nil)
        }
        return false
    }

    private func requestQuit() -> Bool {
        if allowQuit { return true }
        if model.hasSession || model.isStopping {
            let alert = NSAlert()
            alert.messageText = "Stop the managed session before quitting?"
            alert.informativeText = "Quitting requires orderly Wine cleanup and may lose unsaved game progress. Keep the app open to continue playing. No unrelated Wine sessions will be stopped."
            alert.alertStyle = .warning
            alert.addButton(withTitle: "Keep Open")
            alert.addButton(withTitle: "Stop and Quit")
            if alert.runModal() == .alertSecondButtonReturn {
                quitRequested = true
                if !model.isStopping { model.stop() }
            } else {
                quitRequested = false
            }
            return false
        }
        if model.busy {
            let alert = NSAlert()
            alert.messageText = "An operation is still in progress"
            alert.informativeText = "Keep this app open until the current operation finishes. Complete any vendor installer prompts in its own window."
            alert.addButton(withTitle: "Keep Open")
            alert.runModal()
            return false
        }
        return true
    }
}
