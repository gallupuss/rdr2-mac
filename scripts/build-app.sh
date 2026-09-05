#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IDENTITY="${SIGNING_IDENTITY:-}"
PROFILE="${NOTARY_PROFILE:-}"
SWIFT_JOBS="${SWIFT_JOBS:-1}"
[[ "$SWIFT_JOBS" =~ ^[1-9][0-9]*$ ]] || { echo 'SWIFT_JOBS must be a positive integer.' >&2; exit 2; }
while (($#)); do
    case "$1" in
        --identity) IDENTITY="${2:?Missing signing identity}"; shift 2 ;;
        --notary-profile) PROFILE="${2:?Missing notarytool keychain profile}"; shift 2 ;;
        *) echo "Usage: $0 [--identity 'Developer ID Application: …'] [--notary-profile PROFILE]" >&2; exit 2 ;;
    esac
done
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo 'Build on an Apple Silicon Mac.' >&2; exit 1; }
[[ -z "$PROFILE" || -n "$IDENTITY" ]] || { echo 'Notarization requires a signing identity.' >&2; exit 2; }
for tool in swift curl shasum tar zstd ditto codesign; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
source "$ROOT/scripts/python-release.env"
CACHE="$ROOT/.build/release-inputs"
mkdir -p "$CACHE" "$ROOT/dist"
fetch() {
    local url="$1" checksum="$2" destination="$3"
    if [[ ! -f "$destination" ]]; then
        curl --fail --location --proto '=https' --tlsv1.2 --retry 3 "$url" -o "$destination.partial"
        mv "$destination.partial" "$destination"
    fi
    local actual
    actual="$(shasum -a 256 "$destination")"
    [[ "${actual%% *}" == "$checksum" ]] || { echo "Checksum mismatch: $destination; remove this cached download and retry." >&2; exit 1; }
}
fetch "$PYTHON_URL" "$PYTHON_SHA256" "$CACHE/python.tar.gz"
fetch "$PYTHON_FULL_URL" "$PYTHON_FULL_SHA256" "$CACHE/python-full.tar.zst"
STAGE="$(mktemp -d "$ROOT/.build/package.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/RDR2 for Mac.app"
RES="$APP/Contents/Resources"
mkdir -p "$APP/Contents/MacOS" "$RES/engine" "$RES/Notices/python" "$STAGE/full"
swift build --package-path "$ROOT" --configuration release --arch arm64 --jobs "$SWIFT_JOBS"
BIN="$(swift build --package-path "$ROOT" --configuration release --arch arm64 --show-bin-path)"
cp "$BIN/RDR2Mac" "$APP/Contents/MacOS/RDR2Mac"
# Explicit allowlist: only engine Python sources, not logs, credentials or local state.
while IFS= read -r -d '' file; do
    relative="${file#"$ROOT/engine/"}"
    mkdir -p "$RES/engine/$(dirname "$relative")"
    cp "$file" "$RES/engine/$relative"
done < <(/usr/bin/find "$ROOT/engine" -type f -name '*.py' -print0)
[[ -f "$RES/engine/launcher.py" ]] || { echo 'Engine launcher missing.' >&2; exit 1; }
"$ROOT/scripts/build-helpers.sh" "$RES/helpers"
tar -xzf "$CACHE/python.tar.gz" -C "$RES"
zstd --decompress --stdout "$CACHE/python-full.tar.zst" | tar -xf - -C "$STAGE/full"
"$RES/python/bin/python3" -I -B "$ROOT/scripts/collect-python-notices.py" "$STAGE/full/python" "$RES/Notices/python" "$ROOT/scripts/python-notices"
cp "$ROOT/scripts/python-release.env" "$RES/Notices/python/provenance.env"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$RES/Notices/"
cp "$ROOT/scripts/Info.plist" "$APP/Contents/Info.plist"
# Sign nested Mach-O code first. Symlinks are excluded to avoid signing twice.
SIGN="${IDENTITY:--}"
while IFS= read -r -d '' file; do
    if /usr/bin/file -b "$file" | /usr/bin/grep -q 'Mach-O'; then
        if [[ -n "$IDENTITY" ]]; then
            codesign --force --sign "$SIGN" --timestamp --options runtime "$file"
        else
            codesign --force --sign - "$file"
        fi
    fi
done < <(/usr/bin/find "$RES/python" -type f -print0)
LABEL=UNSIGNED
if [[ -n "$IDENTITY" ]]; then
    codesign --force --sign "$IDENTITY" --timestamp --options runtime "$APP"
    LABEL=SIGNED-NOT-NOTARIZED
else
    codesign --force --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"
if [[ -n "$PROFILE" ]]; then
    ditto -c -k --keepParent "$APP" "$STAGE/notarize.zip"
    xcrun notarytool submit "$STAGE/notarize.zip" --keychain-profile "$PROFILE" --wait
    xcrun stapler staple "$APP"
    xcrun stapler validate "$APP"
    LABEL=SIGNED-NOTARIZED
fi
OUTPUT="$ROOT/dist/RDR2Mac-$LABEL.zip"
# Create a fresh archive, then atomically replace any earlier artifact on this volume.
ditto -c -k --keepParent "$APP" "$STAGE/release.zip"
mv -f "$STAGE/release.zip" "$OUTPUT"
shasum -a 256 "$OUTPUT"
printf 'Created %s\n' "$OUTPUT"
