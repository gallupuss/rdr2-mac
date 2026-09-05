# Third-party notices

## SocialClub compatibility helper

The SocialClub flag selection and inherited-handle delegation behavior in
`scripts/helpers/helper.c` are adapted from the SocialClubHelper shim by
Matthias Schedel (2026), provided under the following license. The original
source used for attribution was `rdr2-socialclub-shim/src/socialclubhelper-shim.c`.
The implementation here replaces string substitution with bounded argv parsing
and Microsoft command-line quoting.

> MIT License
>
> Copyright (c) 2026 Matthias Schedel
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Standalone CPython

Release packaging embeds the Apple Silicon `aarch64-apple-darwin` CPython build
from [python-build-standalone](https://github.com/astral-sh/python-build-standalone),
pinned in `scripts/python-release.env`. CPython is covered by the PSF license;
its embedded libraries have their own licenses. The python-build-standalone
repository's license is not a substitute for those runtime licenses.

The app's `Contents/Resources/Notices/python/` contains upstream `PYTHON.json`
and the matching full build's license files. Packaging refuses to proceed if
that inventory is absent. See the upstream
[licensing instructions](https://gregoryszorc.com/docs/python-build-standalone/main/running.html#licensing).
Build provenance, archive URLs and SHA-256 values are included beside the notices.

## External software, not redistributed

Wine/CrossOver, Apple's Game Porting Toolkit, Steam, Rockstar Games Launcher,
Visual C++ redistributables, and Red Dead Redemption 2 are not covered by this
project's MIT license. This repository and its app bundle contain none of their
executables, game assets, account files, or activation data. Vendor installers
may be obtained separately during setup subject to their own terms.

Wine is LGPL-licensed; third-party Wine distributions can include components
with additional terms. No claim of redistribution permission is made for the
mixed runtime present on a developer's machine. Apple's evaluation environment
has Apple-specific terms: possession of a download does not establish permission
to redistribute it or permission for every intended use. Read and accept the
actual agreement before use. See [dependencies](docs/DEPENDENCIES.md).

Red Dead Redemption, Rockstar Games, Steam, CrossOver, and Apple are trademarks
of their respective owners. This is an independent, unofficial project and is
not endorsed by any of them.
