import AppKit
import SwiftUI

struct LauncherView: View {
    @ObservedObject var model: LauncherModel
    @State private var showSetup = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                session
                if let error = model.error {
                    Label {
                        Text(error).textSelection(.enabled)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill")
                    }
                    .foregroundStyle(.red)
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.red.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
                    .accessibilityIdentifier("engineError")
                }
                DisclosureGroup("Installation & display", isExpanded: $showSetup) {
                    setup.padding(.top, 14)
                }
                .font(.headline)
                if !model.checks.isEmpty { checks }
                footer
            }
            .padding(28)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .frame(minWidth: 660, minHeight: 680)
        .onChange(of: model.setupComplete) { _, complete in
            if complete { showSetup = false }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            Image(systemName: "desktopcomputer")
                .font(.system(size: 30, weight: .light))
                .frame(width: 58, height: 58)
                .background(.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 14))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text("RDR2 for Mac").font(.largeTitle.weight(.semibold))
                Text("Unofficial launcher · Apple Silicon")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer()
        }
    }

    private var session: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                if model.busy { ProgressView().controlSize(.small) }
                else {
                    Image(systemName: model.ready ? "checkmark.circle.fill" : "info.circle")
                        .foregroundStyle(model.ready ? Color.green : Color.secondary)
                }
                Text(model.stateTitle).font(.title3.weight(.semibold))
                Spacer()
            }
            Text(model.message)
                .font(.body).foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("engineStatus")
            HStack(spacing: 10) {
                Button { model.save(then: "play") } label: {
                    Label("Play", systemImage: "play.fill").frame(minWidth: 64)
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.busy || model.hasSession || !model.ready)
                .keyboardShortcut(.return, modifiers: [.command])
                Button { model.save(then: "steam") } label: {
                    Label("Open Steam", systemImage: "arrow.up.forward.app")
                }
                .disabled(model.busy || model.hasSession || !model.setupComplete)
                Button(role: .destructive) { model.stop() } label: {
                    Label("Stop", systemImage: "stop.fill")
                }
                .disabled(!model.canStop)
                Spacer()
            }
            .controlSize(.large)
            Text("Sign in and download the game in Steam. Keep all credential entry in the Steam and Rockstar windows.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(20)
        .background(.background, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(.primary.opacity(0.08)))
    }

    private var setup: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Use a legally owned Steam copy. Setup can download a verified Wine runtime into this app’s managed storage. Apple’s toolkit and the game require your own licensed downloads. Existing bottles and account state are never adopted.")
                .font(.callout).foregroundStyle(.secondary)
            directory("WineCX runtime (optional)", placeholder: "Leave empty to download during setup", text: $model.runtimePath, keyPath: \.runtimePath)
            directory("Game Porting Toolkit", placeholder: "Toolkit root containing lib/external", text: $model.gptkPath, keyPath: \.gptkPath)
            directory("Import game (optional)", placeholder: "Import a separate copy, or download in Steam", text: $model.gamePath, keyPath: \.gamePath)
            Text("An optional existing game is imported as an independent copy, using an APFS clone when available. The source is not modified. Leave this empty to install the game through Steam.")
                .font(.caption).foregroundStyle(.secondary)
            Text("For Apple’s toolkit: follow the official link below, accept Apple’s terms, and download the toolkit. Open its disk image, then the nested redistributable disk image. Copy the redistributable folder to a stable location and choose the folder containing lib/external above. Rosetta is required for Intel Windows compatibility.")
                .font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline) {
                Text("Display").frame(width: 165, alignment: .leading)
                Picker("Display", selection: $model.displayMode) {
                    Text("Automatic").tag("auto")
                    Text("1080p").tag("1080p")
                    Text("900p").tag("900p")
                }
                .labelsHidden()
                .pickerStyle(.segmented)
            }
            Text("Automatic uses the native display configuration. No external screen is required.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Save Settings") { model.save() }
                Button(model.setupComplete ? "Run Setup Again" : "Install & Set Up") { model.save(then: "install") }
                Spacer()
            }
            Text("Setup creates a separate managed bottle. Complete the vendor installer and any consent prompts in its own window; setup is not finished until the engine confirms it.")
                .font(.caption).foregroundStyle(.secondary)
            Divider()
            HStack(spacing: 18) {
                Link("CrossOver / Wine information ↗", destination: URL(string: "https://www.codeweavers.com/crossover")!)
                Link("Apple toolkit information ↗", destination: URL(string: "https://developer.apple.com/games/game-porting-toolkit/")!)
            }
            .font(.caption)
            Text("These are vendor information pages, not bundled dependencies or a guarantee of compatibility. Obtain dependencies under their own licenses. Clean-install playability on a second Mac has not been verified.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .font(.body)
        .disabled(model.busy || model.hasSession)
    }

    private func directory(_ title: String, placeholder: String, text: Binding<String>,
                           keyPath: ReferenceWritableKeyPath<LauncherModel, String>) -> some View {
        HStack {
            Text(title).frame(width: 165, alignment: .leading)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel(title)
            Button("Choose…") { model.chooseDirectory(keyPath) }
                .accessibilityLabel("Choose \(title)")
        }
    }

    private var checks: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Readiness checks").font(.headline)
            ForEach(model.checks) { check in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: check.ok ? "checkmark.circle" : "exclamationmark.circle")
                        .foregroundStyle(check.ok ? Color.green : Color.orange)
                        .accessibilityLabel(check.ok ? "Passed" : "Needs attention")
                    VStack(alignment: .leading, spacing: 3) {
                        Text(check.name).font(.callout.weight(.medium))
                        Text(check.detail).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
            }
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            HStack {
                Button("Refresh Status") { model.refresh() }.disabled(model.busy || model.hasSession)
                Button("Repair Helpers") { model.repair() }.disabled(model.busy || model.hasSession || !model.setupComplete)
                Spacer()
                Button("Export Diagnostics…") { model.exportDiagnostics() }.disabled(model.busy)
            }
            Button("Show Local Logs in Finder") { model.showLocalLogs() }
                .buttonStyle(.link)
            Text("Local logs may contain private vendor information. Review them before sharing; prefer Export Diagnostics for privacy-safe support.")
                .font(.caption).foregroundStyle(.secondary)
            if let url = model.diagnosticsURL {
                Button("Show exported diagnostics in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                }
                .buttonStyle(.link)
            }
            Text("Diagnostics contain allowlisted, privacy-safe summaries, not account data or raw vendor logs. RDR2 for Mac is not affiliated with Rockstar Games, Valve, Apple, or CodeWeavers.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}
