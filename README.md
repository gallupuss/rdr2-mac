# RDR2 for Mac (unofficial)

A native SwiftUI launcher and managed Wine setup for a **legally owned Steam
copy of Red Dead Redemption 2** on Apple Silicon. It is not a game port, a game
download, an activation bypass, or a promise that every Mac can run the game.
Steam and Rockstar account entry stays in their own applications.

## Status: experimental, clean installation not yet verified

A pre-existing Apple M4 installation provided evidence that the underlying
compatibility approach can be playable. That installation is not a clean test
of this app and is not distributed, adopted, or modified by it. **A second-machine
clean installation has not been verified.** Packaging, unit checks and a UI
smoke run do not establish that Steam download, Rockstar activation, and gameplay
work end-to-end from an empty bottle. See [verification](docs/VERIFICATION.md).

Public source: [gallupuss/rdr2-mac](https://github.com/gallupuss/rdr2-mac).
The initial publication is experimental source; consumer binary publication is
gated on fresh-install/end-to-end checks and signing. Draft binaries and CI
artifacts must not be presented as a verified release.

## Requirements

- Apple Silicon Mac. The app interface targets macOS 14 or later; this is **not**
  a game-compatibility guarantee. The original playable setup used M4, macOS
  Tahoe, WineCX 26.3.0 and GPTK 4 beta 2. Follow Apple's OS requirements for the
  toolkit you supply, and allow ample storage for a separate Windows prefix
  and the game's current Steam storage requirements.
- A Steam license for RDR2, vendor accounts, internet access, and any required
  Rockstar activation. Supported here: Steam app **1174180**, not Epic or console.
- A compatible neutral WineCX runtime and Apple's Game Porting Toolkit evaluation
  libraries. Setup can acquire the pinned Wine runtime; supply Apple libraries
  yourself. **Read Apple's actual license before use.** Neither is bundled;
  see [acquisition and licensing](docs/DEPENDENCIES.md).

## Using the app

1. Build from source for isolated evaluation, or obtain an explicitly experimental
   artifact if available. CI artifacts are **unsigned** developer builds, not
   notarized public releases. A supported consumer download is not yet claimed;
   never disable Gatekeeper globally.
2. Open **RDR2 for Mac (unofficial)**. Leave runtime blank for the pinned download
   or select a compatible neutral root. Select the GPTK root containing
   `lib/external`. Optionally choose an existing RDR2 game source: setup makes an
   independent managed copy, never modifies the source, and may need extra disk.
   Steam's Install action must discover/verify it and register the installation;
   the app does not fabricate Steam installation state.
3. Save settings, install the managed environment, and complete any vendor
   installer windows. Open Steam to sign in and install/download RDR2. Run RDR2
   from Steam once to complete the official Rockstar prerequisites, then use
   Stop and Repair to install the compatibility helpers before using Play.
   No terminal is required for app users, and no credentials should be pasted
   into the app.
4. Select Automatic, 1080p, or 900p and choose Play. Stop performs cleanup scoped
   to the managed prefix; it does not kill other Wine applications.
5. Use Repair only while stopped after vendor updates. If helper delegation or a
   vendor layout is unsupported, follow the actionable error instead of renaming
   arbitrary executables. Export Diagnostics creates a redacted summary, not a
   raw account/log archive.

Configuration and the new bottle live under
`~/Library/Application Support/RDR2Mac/`. Existing CrossOver bottles and the
original working installation are never automatically imported. Quitting with
an active session requires keeping the app open or an orderly stop. Keep enough
time for Steam/Rockstar first-run dialogs; a spawned process is not readiness.

## Building and releasing

Developers need Xcode command-line tools with Swift 6, `curl`, MinGW-w64 and zstd
(`brew install mingw-w64 zstd`). The build downloads checksum-pinned standalone
Apple Silicon Python; end users do **not** need Apple's developer Python.

```sh
./scripts/build-app.sh
```

The output is `dist/RDR2Mac-UNSIGNED.zip`. The bundle includes the Swift app,
engine, standalone Python with dependency license inventory, and two PE helper
shims compiled from this repository. No Wine, GPTK, vendor client, or game files
are included. Reproducible here means pinned Python inputs and repeatable build
steps, not bit-identical Swift or signed archives across different Xcode versions.

For developer source runs, see [development and release](docs/RELEASING.md).
Release signing and notarization use a local identity and existing notarytool
keychain profile; never commit certificates, credentials, game files, or bottles.

## License

Project code is MIT; the SocialClub behavior includes attributed MIT work by
Matthias Schedel. Bundled Python includes separate upstream licenses. See
[LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
