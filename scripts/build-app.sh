#!/bin/bash
#
# Assembles build/Linux VM.app from:
#   - this package's app and supervisor (swift build);
#   - Try Omarchy v1.3.0's patched QEMU runtime and bridge helper, built in
#     .deps/try-omarchy (see runtime/README.md);
#   - edk2 firmware from the same pinned QEMU source archive;
#   - the guest tools disc from guest/dist.
#
#   scripts/build-app.sh
#
# The app is signed ad hoc, for this Mac. To share it, set
# LINUXVM_SIGN_IDENTITY to a "Developer ID Application" identity, then run
# scripts/package-dmg.sh.

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
omarchy="$root/.deps/try-omarchy"
runtime_source="$omarchy/macos/.build/qemu-gpu-runtime"
source "$root/runtime/source-pins.sh"
archives=${OMARCHY_DOWNLOAD_CACHE:-"$root/.deps/source-archives"}
qemu_archive="$archives/qemu-$qemu_commit.tar.gz"
app="$root/build/Linux VM.app"
identity=${LINUXVM_SIGN_IDENTITY:--}

fail() {
  echo "build-app: $*" >&2
  exit 1
}

[[ -x $runtime_source/bin/qemu-system-aarch64 ]] || fail "build the QEMU runtime first: scripts/build-runtime.sh"
[[ -f $omarchy/macos/pinned-git-source.sh ]] || fail "prepare the runtime with scripts/build-runtime.sh"
source "$omarchy/macos/pinned-git-source.sh"
pinned_git_source_archive https://github.com/qemu/qemu.git "$qemu_commit" "qemu-$qemu_commit" "$qemu_archive" "$archives" ||
  fail "could not verify QEMU firmware source at $qemu_commit"

echo "[build-app] Building the app and supervisor"
swift build --package-path "$root/macos" -c release --product LinuxVM
swift build --package-path "$root/macos" -c release --product linuxvmctl
products=$(swift build --package-path "$root/macos" -c release --show-bin-path)

echo "[build-app] Building Try Omarchy's bridge helper"
swift build --package-path "$omarchy/macos" -c release --product omarchy-vm-helper
helper=$(swift build --package-path "$omarchy/macos" -c release --show-bin-path)/omarchy-vm-helper

staging="$root/build/.Linux VM.app.partial"
rm -rf "$staging"
mkdir -p "$staging/Contents/MacOS" "$staging/Contents/Helpers" "$staging/Contents/Resources/firmware"

install -m 0755 "$products/LinuxVM" "$staging/Contents/MacOS/LinuxVM"
install -m 0755 "$products/linuxvmctl" "$staging/Contents/Helpers/linuxvmctl"
install -m 0755 "$helper" "$staging/Contents/Helpers/omarchy-vm-helper"

# ditto keeps the runtime's signatures and the hypervisor entitlement. The
# binary keeps its name: the bridge helper only serves qemu-system-* targets.
ditto "$runtime_source" "$staging/Contents/Resources/runtime"

echo "[build-app] Extracting the edk2 firmware from the pinned QEMU source"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
tar -xzf "$qemu_archive" -C "$scratch" "qemu-$qemu_commit/pc-bios/edk2-aarch64-code.fd.bz2" "qemu-$qemu_commit/pc-bios/edk2-licenses.txt"
bunzip2 -c "$scratch/qemu-$qemu_commit/pc-bios/edk2-aarch64-code.fd.bz2" >"$staging/Contents/Resources/firmware/edk2-aarch64-code.fd"
[[ $(stat -f %z "$staging/Contents/Resources/firmware/edk2-aarch64-code.fd") == 67108864 ]] || fail "the firmware is not a 64 MiB flash image"
install -m 0644 "$scratch/qemu-$qemu_commit/pc-bios/edk2-licenses.txt" "$staging/Contents/Resources/firmware/"

guest_iso="$root/guest/dist/guest-tools.iso"
if [[ -f $guest_iso ]]; then
  # The app compares this version with the one each VM reports.
  guest_version=$(sed -n "s/^VERSION = '\([0-9.]*\)'$/\1/p" "$root/guest/build.py")
  [[ $guest_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "cannot read the guest tools version from guest/build.py"
  LC_ALL=C grep -a -q -F "linuxvm-guest_${guest_version}_all.deb" "$guest_iso" ||
    fail "$guest_iso does not hold linuxvm-guest $guest_version; rebuild it with guest/build-tools-iso.sh"
  install -m 0644 "$guest_iso" "$staging/Contents/Resources/guest-tools.iso"
  printf '%s\n' "$guest_version" >"$staging/Contents/Resources/guest-tools-version"
else
  echo "[build-app] warning: guest/dist/guest-tools.iso is missing; VMs will start without the guest tools disc" >&2
fi
if [[ -f $root/macos/Resources/AppIcon.icns ]]; then
  install -m 0644 "$root/macos/Resources/AppIcon.icns" "$staging/Contents/Resources/AppIcon.icns"
fi
install -m 0644 "$root/macos/Resources/Info.plist" "$staging/Contents/Info.plist"
install -m 0644 "$omarchy/LICENSE" "$staging/Contents/Resources/LICENSE.try-omarchy"

# Never sign with --deep: it would strip the QEMU runtime's entitlements.
if [[ $identity == - ]]; then
  # Ad hoc, for this Mac: the runtime keeps the signatures its build gave it.
  codesign --force --sign - "$staging/Contents/Helpers/linuxvmctl" "$staging/Contents/Helpers/omarchy-vm-helper"
  codesign --force --sign - "$staging/Contents/MacOS/LinuxVM"
  codesign --force --sign - "$staging"
else
  # For sharing: every executable gets the identity, the hardened runtime and
  # a secure timestamp, as notarization requires, from the inside out.
  echo "[build-app] Signing with $identity"
  sign=(codesign --force --sign "$identity" --options runtime --timestamp)
  for library in "$staging/Contents/Resources/runtime/lib"/*.dylib; do
    "${sign[@]}" "$library"
  done
  "${sign[@]}" "$staging/Contents/Resources/runtime/bin/zstd"
  "${sign[@]}" --entitlements "$root/macos/Resources/qemu.entitlements" "$staging/Contents/Resources/runtime/bin/qemu-system-aarch64"
  "${sign[@]}" "$staging/Contents/Helpers/omarchy-vm-helper"
  "${sign[@]}" --entitlements "$root/macos/Resources/app.entitlements" "$staging/Contents/Helpers/linuxvmctl"
  "${sign[@]}" --entitlements "$root/macos/Resources/app.entitlements" "$staging"
  codesign --verify --deep --strict "$staging" || fail "the signed app does not verify"
  team=$(codesign -dv "$staging" 2>&1 | sed -n 's/^TeamIdentifier=//p')
  while IFS= read -r -d '' file; do
    [[ $(file -b "$file") == Mach-O* ]] || continue
    details=$(codesign -dv "$file" 2>&1)
    [[ $details == *"TeamIdentifier=$team"* && $details == *"(runtime)"* && $details == *"Timestamp="* ]] ||
      fail "not signed for sharing: ${file#"$staging/"}"
  done < <(find "$staging" -type f -perm +111 -print0)
fi
codesign -d --entitlements - "$staging/Contents/Resources/runtime/bin/qemu-system-aarch64" 2>/dev/null | grep -q com.apple.security.hypervisor ||
  fail "the QEMU runtime lost its hypervisor entitlement"

rm -rf "$app"
mv "$staging" "$app"
LINUXVM_CONTENTS="$app/Contents" "$app/Contents/Helpers/linuxvmctl" check
echo "[build-app] Built $app"
