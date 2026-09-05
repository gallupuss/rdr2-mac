#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist/helpers}"
CC="${MINGW_CC:-x86_64-w64-mingw32-gcc}"
command -v "$CC" >/dev/null || { echo "Install MinGW-w64 (brew install mingw-w64), or set MINGW_CC." >&2; exit 1; }
mkdir -p "$OUT"
"$CC" -std=c11 -Os -Wall -Wextra -Werror -municode -mwindows -static -Wl,--no-insert-timestamp -DSTEAM_HELPER "$ROOT/scripts/helpers/helper.c" -lshell32 -o "$OUT/steamwebhelper.exe"
"$CC" -std=c11 -Os -Wall -Wextra -Werror -municode -mwindows -static -Wl,--no-insert-timestamp "$ROOT/scripts/helpers/helper.c" -lshell32 -o "$OUT/SocialClubHelper.exe"
