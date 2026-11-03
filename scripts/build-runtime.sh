#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
source "$root/runtime/source-pins.sh"
omarchy="$root/.deps/try-omarchy"

fail() {
  echo "build-runtime: $*" >&2
  exit 1
}

[[ $# == 0 ]] || fail "usage: scripts/build-runtime.sh"
[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || fail "requires an Apple Silicon Mac with macOS 15 or newer"
[[ $(sw_vers -productVersion | cut -d. -f1) -ge 15 ]] || fail "requires macOS 15 or newer"
for tool in git xcode-select xcrun codesign pkg-config; do
  command -v "$tool" >/dev/null || fail "missing $tool; install Xcode command line tools (xcode-select --install) and pkg-config (brew install pkgconf)"
done
xcode-select -p >/dev/null 2>&1 && xcrun --find clang >/dev/null 2>&1 && xcrun --show-sdk-path >/dev/null 2>&1 ||
  fail "install Xcode command line tools with xcode-select --install"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
python=
[[ -z ${LINUXVM_PYTHON:-} || -x $LINUXVM_PYTHON ]] || fail "LINUXVM_PYTHON is not executable: $LINUXVM_PYTHON"
for candidate in "${LINUXVM_PYTHON:-}" /opt/homebrew/bin/python3.14 "$(command -v python3 || true)"; do
  [[ -n $candidate && -x $candidate ]] || continue
  if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' &&
      "$candidate" -m venv "$scratch/venv" >"$scratch/python.log" 2>&1 &&
      "$scratch/venv/bin/python3" -c 'import sys; assert sys.prefix != sys.base_prefix' >>"$scratch/python.log" 2>&1; then
    python=$("$candidate" -c 'import sys; print(sys.executable)')
    break
  fi
  rm -rf "$scratch/venv"
  [[ -z ${LINUXVM_PYTHON:-} ]] || fail "LINUXVM_PYTHON must name Python >= 3.11 with working venvs; try brew install python@3.14"
done
[[ -n $python ]] || fail "Python >= 3.11 with working venvs is required; run brew install python@3.14 (uv-managed Python may not work)"
echo "[build-runtime] Using $python"

mkdir -p "$root/.deps"
[[ ! -L $omarchy ]] || fail "refusing a symlink at $omarchy"
if [[ ! -e $omarchy ]]; then
  git clone --branch "$try_omarchy_tag" --depth 1 https://github.com/omacom/try-omarchy.git "$omarchy"
fi
[[ $(git -C "$omarchy" rev-parse --show-toplevel) == "$omarchy" ]] || fail "not a Try Omarchy checkout: $omarchy"
[[ $(git -C "$omarchy" rev-parse HEAD) == "$try_omarchy_commit" &&
   $(git -C "$omarchy" rev-parse "$try_omarchy_tag^{commit}") == "$try_omarchy_commit" ]] ||
  fail "Try Omarchy must be $try_omarchy_tag at $try_omarchy_commit; existing checkout was left alone"
git -C "$omarchy" diff --cached --quiet "$try_omarchy_commit" -- || fail "Try Omarchy has staged changes; existing checkout was left alone"

expected_index="$scratch/index"
GIT_INDEX_FILE="$expected_index" git -C "$omarchy" read-tree "$try_omarchy_commit"
GIT_INDEX_FILE="$expected_index" git -C "$omarchy" apply --cached "$root/runtime/try-omarchy-v1.3.0.diff"
expected_tree=$(GIT_INDEX_FILE="$expected_index" git -C "$omarchy" write-tree)
matches_tree() {
  GIT_INDEX_FILE="$expected_index" git -C "$omarchy" read-tree "$1"
  GIT_INDEX_FILE="$expected_index" git -C "$omarchy" update-index --refresh >/dev/null 2>&1 || return 1
  GIT_INDEX_FILE="$expected_index" git -C "$omarchy" diff-files --quiet -- &&
    [[ -z $(GIT_INDEX_FILE="$expected_index" git -C "$omarchy" ls-files --others --exclude-standard) ]]
}
if matches_tree "$expected_tree"; then
  echo "[build-runtime] Try Omarchy already has the exact runtime diff"
elif matches_tree "$try_omarchy_commit"; then
  git -C "$omarchy" apply "$root/runtime/try-omarchy-v1.3.0.diff"
else
  fail "Try Omarchy has unexpected changes; existing checkout was left alone"
fi

mkdir -p "$root/.deps/build-tools"
ln -sf "$python" "$root/.deps/build-tools/python3"
export PATH="$root/.deps/build-tools:$PATH"
export OMARCHY_DOWNLOAD_CACHE=${OMARCHY_DOWNLOAD_CACHE:-"$root/.deps/source-archives"}
mkdir -p "$OMARCHY_DOWNLOAD_CACHE"
export OMARCHY_DOWNLOAD_CACHE=$(cd "$OMARCHY_DOWNLOAD_CACHE" && pwd -P)
"$omarchy/macos/build-qemu-gpu-runtime.sh"
qemu="$omarchy/macos/.build/qemu-gpu-runtime/bin/qemu-system-aarch64"
[[ -x $qemu ]] || fail "the runtime build did not produce $qemu"
codesign --verify --strict "$qemu" || fail "the QEMU signature does not verify"
codesign -d --entitlements - --xml "$qemu" 2>/dev/null | "$python" -c '
import plistlib, sys
sys.exit(plistlib.loads(sys.stdin.buffer.read()).get("com.apple.security.hypervisor") is not True)
' || fail "the QEMU runtime lost its hypervisor entitlement"
echo "[build-runtime] Built $omarchy/macos/.build/qemu-gpu-runtime"
