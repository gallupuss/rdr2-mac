# Dependency acquisition and licensing

## WineCX runtime

The known compatibility route uses WineCX 26.3.0. A publicly accessible upstream
artifact, independently recorded for provenance (not a redistribution grant), is:

- Publisher: [Silo releases](https://github.com/mikaelhug/Silo/releases/tag/wine-cx-26.3.0)
- Archive: https://github.com/mikaelhug/Silo/releases/download/wine-cx-26.3.0/wine.tar.xz
- SHA-256: `045cc60af1a0de2a40a3406690d48dbcf7010aa8269ad103506b6942a2b15238`
- Size: 88,454,244 bytes.

Leave runtime blank for setup to download this checksum-pinned artifact into
app-owned storage, or select an independently acquired neutral Wine root.
Wine is LGPL, but the archive's complete third-party license/source inventory
has not been audited for mirroring. The app build therefore does not download
or bundle it; setup obtains it directly from upstream. A paid CrossOver installation is governed by
[CodeWeavers' terms](https://www.codeweavers.com/); ownership does not make its
bottle or credentials redistributable. Do not point setup at a working bottle
or a previously mixed Wine/GPTK overlay.

## Apple Game Porting Toolkit

Use [Apple Developer Downloads](https://developer.apple.com/download/all/?q=game%20porting%20toolkit)
with your own Apple account; access can be login-gated. The GPTK 4 beta 2 nested evaluation-environment DMG
contains agreement **EA18380, dated August 17, 2023**. Section 2A permits use for
developing, testing, or evaluating video games and permits noncommercial
distribution subject to the agreement. Section 2C permits the entire Framework
or portions of `/redist` to be distributed separately, with required notices.
This is not a blanket prohibition on redistribution, nor unrestricted consumer
use permission. Read the complete agreement supplied with your version and do
not proceed if your intended use is outside it. Our conservative packaging
decision is still **user-supplied Apple libraries only**: no Apple archive,
translated binary, or extracted library is included in the release.

The expected selected root contains `lib/external`. In GPTK 4 distributions,
Apple may place the evaluation environment inside a nested disk image, with the
libraries under `redist/lib`. Mount your own download and locate the appropriate
root according to the app's checks; do not rename incompatible files merely to
satisfy a check. An xxHash notice inside a framework is not the GPTK agreement.
Version layout and supported hardware remain subject to Apple's release notes.

After a successful installation import, the selected Apple libraries and required
PE modules live in the app-managed `RuntimeOverlay`; configuration updates to
that managed path. You can then eject the source disk image. This is a local
import from your legally acquired copy, not redistribution in the app bundle,
and does not establish that runtime or gameplay verification has passed.

## Steam, Rockstar and Microsoft

Own the game on [Steam](https://store.steampowered.com/app/1174180/Red_Dead_Redemption_2/).
Use [Valve's Steam installer](https://store.steampowered.com/about/) and vendor
windows for account entry/download. Rockstar activation remains mandatory. The
helpers in this project are launch delegates, not replacements for the original
vendor implementations and not DRM bypasses.

If setup requires Visual C++ runtime installation, acquire it only through
[Microsoft's supported redistributable guidance](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170).
Vendor installer availability is not permission to include it in the app bundle.

## Python in the release

`scripts/python-release.env` records immutable python-build-standalone release
URLs and SHA-256 digests. Both runtime and full-build license-source archive are
verified before use. The install-only Apple Silicon interpreter is bundled at
`Contents/Resources/python/bin/python3`; full-build `PYTHON.json` and license
files are retained in `Contents/Resources/Notices/python`. See
[upstream distribution documentation](https://gregoryszorc.com/docs/python-build-standalone/main/running.html).
This packaging route does not rely on `/usr/bin/python3`, Homebrew Python, or
an installed development toolchain on the end user's Mac.
