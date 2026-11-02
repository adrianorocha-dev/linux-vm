#!/bin/sh
set -eu
GUEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
"$PYTHON" "$GUEST_DIR/build.py"
STAGE=$(mktemp -d "$GUEST_DIR/dist/.iso-stage.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
"$PYTHON" "$GUEST_DIR/build.py" --stage-iso "$STAGE"
hdiutil makehybrid -iso -joliet -default-volume-name LINUXVM-TOOLS \
    -o "$GUEST_DIR/dist/guest-tools.iso" "$STAGE" -ov
"$PYTHON" "$GUEST_DIR/build.py" --normalize-iso "$GUEST_DIR/dist/guest-tools.iso"
printf '%s\n' "$GUEST_DIR/dist/guest-tools.iso"
