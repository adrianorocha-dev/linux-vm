#!/bin/bash
#
# Packages build/Linux VM.app, signed for sharing by scripts/build-app.sh, as a
# disk image, then has Apple notarize it and staples the ticket:
#
#   LINUXVM_SIGN_IDENTITY="Developer ID Application: Name (TEAMID)" scripts/build-app.sh
#   LINUXVM_SIGN_IDENTITY="…" LINUXVM_NOTARY_PROFILE=linuxvm-notary scripts/package-dmg.sh
#
# LINUXVM_NOTARY_PROFILE names notarytool credentials in the keychain
# (xcrun notarytool store-credentials). Without it the image is signed but
# not notarized, which is only good for checking the steps before.

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
app="$root/build/Linux VM.app"
identity=${LINUXVM_SIGN_IDENTITY:-}
profile=${LINUXVM_NOTARY_PROFILE:-}

fail() {
  echo "package-dmg: $*" >&2
  exit 1
}

[[ -n $identity && $identity != - ]] || fail "set LINUXVM_SIGN_IDENTITY to the identity build-app.sh signed with"
[[ -d $app ]] || fail "build the app first: scripts/build-app.sh"
codesign --verify --deep --strict "$app" || fail "the app does not verify"
details=$(codesign -dv "$app" 2>&1)
[[ $details == *"(runtime)"* && $details == *"Timestamp="* ]] ||
  fail "the app is not signed for sharing; rebuild it with LINUXVM_SIGN_IDENTITY set"
authority=$(codesign -dvv "$app" 2>&1 | sed -n 's/^Authority=//p' | head -1)
if [[ -n $profile && $authority != "Developer ID Application:"* ]]; then
  fail "Apple notarizes only Developer ID signatures; the app is signed by \"$authority\""
fi

version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")
dmg="$root/build/Linux VM $version.dmg"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

echo "[package-dmg] Creating $(basename "$dmg")"
mkdir "$scratch/image"
ditto "$app" "$scratch/image/Linux VM.app"
ln -s /Applications "$scratch/image/Applications"
rm -f "$dmg"
hdiutil create -volname "Linux VM" -srcfolder "$scratch/image" -fs APFS -format UDZO \
  -imagekey zlib-level=9 "$dmg" >/dev/null
codesign --sign "$identity" --timestamp "$dmg"
codesign --verify --strict "$dmg"

if [[ -n $profile ]]; then
  echo "[package-dmg] Submitting to Apple's notary service; this usually takes a few minutes"
  xcrun notarytool submit "$dmg" --keychain-profile "$profile" --wait --timeout 1h |
    tee "$scratch/notary.log"
  grep -q "status: Accepted" "$scratch/notary.log" ||
    fail "Apple did not accept the image; see: xcrun notarytool log <submission id> --keychain-profile $profile"
  xcrun stapler staple "$dmg"
  xcrun stapler validate "$dmg"
  # The ticket covers the app too; staple the local copy for builds shared
  # without the image.
  xcrun stapler staple "$app"
  spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"
  spctl --assess --type execute --verbose=2 "$app"
else
  echo "[package-dmg] warning: LINUXVM_NOTARY_PROFILE is not set, so the image is not notarized" >&2
fi
echo "[package-dmg] Built $dmg"
