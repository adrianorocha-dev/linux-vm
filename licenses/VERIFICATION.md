# License integration verification

Verified on 3 November 2026 in the `t3/license-source-retention` worktree.
The earlier license branch is merged and adapted to current main.
The runtime has two executables and 15 dylibs.
Sparkle 2.10.0 adds its framework, Autoupdate and nested Updater.app.
The inventory has 24 shipped components and 28 Guest Tools file entries.
Original app code, artwork, guest code and local contributions still have no selected license.

## Provenance changes

QEMU is pinned to `c3d48b7d1e89604920e5b81b91140c2ad39a1943`.
keycodemapdb is pinned to `f5772a62ec52591ff6870b7e8ef32482371f22c6`.
Their generated archives have no checksum pin.
The checker verifies git objects and compares archive members against those objects.
It compares the manifest against `runtime/source-pins.sh`, the actual patched runtime builder and the app's firmware fetch command.
It clones the pinned Try Omarchy source and applies our current diff for its reference.
There are no checked-in copies of upstream build scripts under `licenses/pins/`.
The no-dependency-checkout path was also verified against a fresh remote clone.

Sparkle's SwiftPM revision is `eef1a539a373c1f1a320624b1130fc5de7b2e100`.
Its complete LICENSE comes from the release archive with SHA-256 `c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c`.
That LICENSE includes the embedded bsdiff, sais-lite, Ed25519 and signature-verifier notices.
Every retained framework file and symlink has an explicit inventory entry.
Removed XPC services, headers and modules are not covered as shipped files.

The app icon is drawn with paths.
Its asset and renderer hashes have been refreshed.
There is no SF Symbols blocker.
No UI source was edited.

Zstandard's formula source archive has SHA-256 `37d7284556b20954e56e1ca85b80226768902e2edabd3b649e9e72c0c9012ee3`.
The CMake library target includes common, compression, decompression, dictionary-builder and legacy sources.
This compiles xxHash and libdivsufsort-lite into libzstd.
Their notices come from that same source archive.
The CLI compiles `programs/*.c` and links the shared libzstd.
It also links the separately inventoried LZ4 and liblzma dylibs and macOS zlib.
The formula's BSD-2-Clause entries are `zstdgrep` and `libzstd.pc.in`, which the app does not ship.
The full source copyright collection is retained too.
The Zstandard blocker is resolved.

## Remaining gates

The source-offer contact remains `SOURCE_OFFER_CONTACT_UNSET`.
A Developer ID gate run exits 1 with only the instruction to set `offer_contact`.
A temporary manifest with a test contact then fails on ANGLE alone.
No real identity is used or signed.

ANGLE remains an enforced provenance blocker.
Its bottle's embedded formula source is pinned to tap commit `97987d9531ea8feeaf0fcc126be2bd97ffdf6479` and passes SHA-256 verification.
Its build fetches moving ANGLE and dependency revisions and writes an unset variable to `commit.txt`.
The v1.0.16 tag formula additionally has a source checksum mismatch.
See [ANGLE-AUDIT.md](ANGLE-AUDIT.md) for the evidence and the missing revisions and build records.
No unrelated revision's LICENSE is substituted for the missing matching notices.
A contact-only release clearance is therefore not established.

## Commands and results

Commands run from the worktree root.
Logs and disposable artifacts are in the ignored `build/` directory.
The main checkout's dependencies are read through a symlink.
Firmware archiving uses a private cache so it cannot rewrite those shared archives.
The helper builds with a private scratch path.

| Command | Result |
| --- | --- |
| `ln -s ~/ccsandbox/linux-vm/.deps .deps` | Linked the existing inputs. |
| `mkdir -p build/app-source-cache/git` | Created the private firmware cache. |
| `git clone --bare --shared .deps/source-archives/git/qemu-c3d48b7d1e89604920e5b81b91140c2ad39a1943.git build/app-source-cache/git/qemu-c3d48b7d1e89604920e5b81b91140c2ad39a1943.git` | Reused verified objects without writing to the original repository. Git warns that its transport repository has no refs. |
| `python3 guest/build.py` | Exit 0; Guest Tools 0.2.1. |
| `guest/build-tools-iso.sh` | Exit 0; existing ISO volume-ID warning. |
| `OMARCHY_DOWNLOAD_CACHE="$PWD/build/app-source-cache" scripts/build-app.sh > build/license-build.log 2>&1` | Exit 0; ad hoc app; ended with `linuxvmctl check`. |
| `python3 scripts/license-notices.py --inputs --bundle "build/Linux VM.app"` | Exit 0; actual sources, licenses, disc and bundle coverage pass; one provenance blocker, ANGLE. |
| `python3 scripts/license-notices.py --identity 'Developer ID Application: license-gate-test'` | Expected exit 1 for the unset contact. No signing occurs. |
| `swift test --package-path macos > build/license-swift-tests.log 2>&1` | Exit 0; 31 tests in five suites. |
| `/opt/homebrew/bin/python3.14 -m unittest discover guest/tests > build/license-guest-tests.log 2>&1` | Exit 0; 34 tests. |
| `python3 -m unittest discover scripts/harness/tests > build/license-harness-tests.log 2>&1` | Exit 0; 27 tests. |
| `python3 -m unittest discover scripts/tests > build/license-python-tests.log 2>&1` | Exit 0; includes license, runtime and source-retention checks. No installed-input skips. |

Intentional rejection checks use disposable copies and a temporary manifest.
Removing GLib returns `bottle-glib: missing component entry`.
An added runtime dylib returns `uncovered bundle file`.
An added file inside Sparkle's existing framework directory also returns `uncovered bundle file`.
Unit tests cover these failures, framework symlink targets, missing notices, commit-pin changes, archive-member corruption and source-bundle corruption.

No VM was started.
Nothing was copied to `/Applications`.
Nothing was pushed or merged to main.
No shared dependency was edited.

## Source retention

The source collector is a separate commit.
See [README.md](README.md#retaining-release-source) for its command and retained contents.
The full run refuses to claim completeness while ANGLE's source revisions are unknown.
The subset run is explicitly incomplete and is not sufficient to fulfill a source request.
Full download size is unknown because ANGLE's exact dependency set is unknown.
The collector reports actual archive bytes, retained artifact bytes and each artifact's checksum and size.
Retain a complete archive through at least three years after the last distribution of its release.

The original legal review points in [README.md](README.md#legal-review-points) still apply.
This work does not establish public-release clearance for ANGLE or select a license for our own code.
