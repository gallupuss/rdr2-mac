# Verification and release limitations

## Evidence boundary

The known Apple M4 playable installation predates this app. It motivates the
compatibility approach; it does not prove the managed setup can reproduce it.
The original bottle, game files, credentials and running session are read-only
and out of scope. In particular, do not launch probes, stop Wine processes,
inspect mutable account state, change displays or foreground a test app while
that session is in use.

Source preparation alone establishes no clean-install or gameplay success.
At initial release preparation:

- Second-machine clean installation: **not performed**.
- New app-managed bottle Steam/Rockstar activation and gameplay: **not verified**.
- New-bottle runtime probes: **deferred while the original user session is playing**.
- Native setup UI: **rendered and visually inspected on a GitHub-hosted Mac**;
  no app or Wine session was launched on the gaming Mac.
- Developer ID signing/notarization: **not verified; no identity available**.

## Recorded checks — September 5, 2026

The [hosted verification run](https://github.com/gallupuss/rdr2-mac/actions/runs/33993273510)
passed for source commit `90092518344a75662b36fdbbb5bcfd871e701ab2`:

- Native arm64 Swift application and both x86-64 Windows helpers compiled.
- Standalone CPython 3.12.14 and its license inventory packaged successfully.
- All 16 isolated regression tests passed with bundled Python. They use temporary
  data, socket pairs and a Python fixture process—not Wine, Steam or game files.
- The real packaged HTTPS downloader fetched the upstream Wine checksum sidecar
  with certificate validation and matched the pinned runtime digest. No Wine
  runtime was installed or executed by this check.
- Packaged engine status and the native model's real process/JSON transport
  reported `needs_setup` without creating configuration or a bottle.
- The ad-hoc code signature verified both before and after those smoke checks.
  This proves bundle integrity, **not** Developer ID trust or notarization.
- The hosted setup-window screenshot was inspected and is shown in
  [the README](../README.md). This verifies initial rendering, not the installer
  dialogs, all interactions, or gameplay.

The downloaded draft ZIP was inspected: engine sources match the repository;
both helper resources are x86-64 PE executables with the engine's identity marker;
no Wine/vendor/game/account trees are bundled. Its size is 25,948,579 bytes and
SHA-256 is `4c6eaedd5657ce9b179e365645acad598d3e00718d040df773d7f39f55cb4e8f`.

Separately, local Python 3.14.4 passed all 16 isolated tests. A temporary real-CLI
smoke exercised fresh read-only status, configure/persist/read, rejection of an
invalid display option and privacy-safe diagnostics export. It created no Wine
bottle and did not touch the running game.

## Before a supported binary release

1. On an isolated Apple Silicon machine, build the app from the recorded commit;
   check arm64 Python, all upstream licenses, source-built PE helpers and absence
   of proprietary binaries, secrets, account files and original-machine paths.
2. Confirm status with a new custom config does not create files, configure is
   atomic, diagnostics contain only allowlisted redacted summaries, conflicting
   operations fail safely, and process cleanup is scoped to the managed prefix.
3. On a fresh user account with no developer Python, open the actual app and
   complete legal dependency acquisition, empty-bottle initialization, vendor
   installers, Steam login/download, Rockstar login/activation and first launch.
4. Exercise display choices, error recovery, Open Steam, Play, Stop, repair after
   supported vendor updates, diagnostics export, and close-during-session choice.
   Preserve vendor delegate exit codes and inherited handles; verify another Wine
   application's processes remain untouched.
5. Confirm optional game import creates an independent managed copy, never
   modifies the source, and Steam itself verifies/registers the installation.
6. Record macOS, chip, RAM, Wine/GPTK and vendor versions; test an actual gameplay
   session and subsequent relaunch. Do not publish personal paths or account data.
7. Sign, notarize, staple and validate on a machine with a valid identity. Verify
   Gatekeeper on a second Mac receiving the download normally.

A compile, process spawn, existing-machine screenshot, or fabricated appmanifest
is not a substitute for these end-to-end gates. Until they are met, identify
source/CI artifacts as experimental and keep consumer binary publication gated.
