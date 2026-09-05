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
- Runtime probes and graphical UI smoke: **deferred while the original user
  session is playing**.
- Developer ID signing/notarization: **not verified; no identity available**.
- Packaging and isolated source checks: record actual command outcomes in the
  release notes; do not infer success from the existence of this document.

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
