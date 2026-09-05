# Development and release

## Build

On Apple Silicon macOS with Swift 6/Xcode command-line tools:

```sh
brew install mingw-w64 zstd
./scripts/build-app.sh
```

The script verifies both pinned Python archives before extraction. It builds the
Swift executable and x86-64 Windows helper executables from source, carries only
engine `.py` files into resources, collects Python license inventory, signs
nested Mach-O files, verifies the bundle signature, and emits a ZIP plus SHA-256
on stdout. Download cache: `.build/release-inputs`; outputs: `dist`.
`MINGW_CC` can select another compatible MinGW-w64 compiler. The output is
Apple Silicon only and requires macOS 14+. Pin the Xcode/MinGW toolchain in your
release record when comparing builds; code signatures and ZIP timestamps are
not promised byte-for-byte reproducible.
`SWIFT_JOBS` defaults to `1` to limit build contention; set a positive integer
explicitly when a dedicated builder can support more parallel work. Each build
creates a fresh ZIP before replacing the previous artifact, so reruns cannot
retain stale archive entries.

An unsigned artifact is locally ad-hoc signed for bundle integrity, **not** a
Developer ID-signed or notarized distribution. It is labeled `UNSIGNED`.
GitHub CI uploads an expiring experimental unsigned artifact, never automatically
publishes a release. Do not promote it as a verified consumer download. During
initial bring-up, keep binary releases draft pending the verification gates.

Hosted CI runs the engine unittest suite using the extracted bundle's Python,
then packaged `status` and native `--smoke` against a fresh runner-temporary
`RDR2MAC_CONFIG`. It verifies that no config or bottle is created by those
read-only checks and uploads their output as separate evidence. Timeouts bound
the job and each verification step. CI does not acquire GPTK, initialize Wine,
launch vendor applications or validate gameplay; this is build/model proof only.
After required checks, an optional one-minute hosted-only step opens the setup
window without clicking Install or Play and attempts a screenshot. It terminates
only the app process it started. Screen capture failure is recorded as unavailable
and cannot turn a failed required check into success. A captured image is labeled
unreviewed until a human inspects it; this never substitutes for runtime testing.

## Source-mode smoke run (developers only)

After obtaining/building standalone Python and the helpers, set
`RDR2MAC_RESOURCE_DIR` to a directory containing `engine/`, `python/`, and
`helpers/`, and optionally `RDR2MAC_PYTHON` to a Python executable. Run the Swift
executable built by SwiftPM. These are developer overrides, not an end-user setup
requirement. Do not use source mode against a live/original game environment.
The engine supports a separate `--config` path for isolated CLI checks; use a
throwaway location for testing, never a copied real account or existing bottle.

## Local signing and notarization

Install your own Developer ID Application certificate in your keychain. Create
an existing notarytool keychain profile using Apple's documented credential
setup, outside this repository. Do not commit or print its secret values.

```sh
./scripts/build-app.sh \
  --identity 'Developer ID Application: Your Name (TEAMID)' \
  --notary-profile YOUR_EXISTING_PROFILE
```

Equivalent environment variables are `SIGNING_IDENTITY` and `NOTARY_PROFILE`.
An identity without a profile produces `SIGNED-NOT-NOTARIZED`; both produce
`SIGNED-NOTARIZED` only after notarytool succeeds and the ticket is stapled and
validated. No certificate or credential is bundled. The local manual path is
intentional: untrusted PR code must never run on a signing host. Apple's
[notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
explains certificate/profile requirements. No valid Developer ID identity was
available during initial source preparation, so notarization remains unverified.

## Release gates

Follow [VERIFICATION.md](VERIFICATION.md), preserve the results, update the
changelog and bundle version, and include artifact checksums and the exact
commit/toolchain in release notes. Separate source/build verification from
fresh-machine setup, activation and gameplay evidence. Recheck vendor layout
support and license inventories when updating a dependency; update URLs and
hashes from upstream release evidence, not guessed asset names. Review Apple's
actual agreement for the selected version; we do not redistribute Apple code.
No existing playable machine is an integration test fixture.
