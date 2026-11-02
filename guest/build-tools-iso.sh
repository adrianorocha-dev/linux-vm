#!/bin/sh
set -eu
GUEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
XORRISO=$(command -v xorriso || true)
if [ -z "$XORRISO" ] && [ -x /opt/homebrew/bin/xorriso ]; then XORRISO=/opt/homebrew/bin/xorriso; fi
[ -n "$XORRISO" ] || { echo 'xorriso is required (brew install xorriso).' >&2; exit 1; }
"$PYTHON" "$GUEST_DIR/build.py"
STAGE=$(mktemp -d "$GUEST_DIR/dist/.iso-stage.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
"$PYTHON" "$GUEST_DIR/build.py" --stage-iso "$STAGE"
"$XORRISO" -as mkisofs -R -J -V LINUXVM-TOOLS -uid 0 -gid 0 \
    --modification-date=2000010100000000 --set_all_file_dates 2000010100000000 \
    -o "$GUEST_DIR/dist/guest-tools.iso" "$STAGE"
printf '%s\n' "$GUEST_DIR/dist/guest-tools.iso"
