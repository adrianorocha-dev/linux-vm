# Workstream 1 implementation and verification

Verified on 3 November 2026 in the `t3/license-provenance-notices` worktree.

The manifest, notices builder, coverage gate and tests are implemented.
The ad hoc app builds and passes its runtime capability check.
This is not a complete public-release license clearance.
The supplied inputs leave three enforced release blockers and the legal review points below.

## Manifest summary

The inventory has 23 shipped component entries, 26 pinned archive inputs and 28 explicit Guest Tools file entries.
The runtime contains two executables and 15 dylibs.
The manifest includes original app and guest sources, the icon, Try Omarchy code, our diff, static libfdt and generated keycodemapdb tables.
Build-only tools are also recorded as inputs and marked as not shipped.

| Component | Version | License |
| --- | --- | --- |
| Linux VM app, supervisor and artwork | 0.1.0 | LicenseRef-Linux-VM-Undecided |
| AppIcon with Apple SF Symbol chevron.right | Checked-in asset SHA-256, recorded in manifest; SF Symbols version unknown | LicenseRef-Linux-VM-Undecided AND LicenseRef-Apple-SF-Symbols-Unverified |
| Linux VM Guest Tools | 0.2.1 | LicenseRef-Linux-VM-Undecided AND MIT |
| Try Omarchy helper, runtime patches and adapted Guest Tools | 1.3.0 | MIT |
| Linux VM runtime and helper modifications | try-omarchy-v1.3.0.diff | LicenseRef-Linux-VM-Undecided AND GPL-2.0-only AND MIT |
| QEMU | 11.1.1 | GPL-2.0-only |
| dtc / libfdt | 1.6.1 at b6910bec11614980a21e46fbccc35934b671bd81 | GPL-2.0-or-later OR BSD-2-Clause |
| keycodemapdb generated tables | f5772a62ec52591ff6870b7e8ef32482371f22c6 | GPL-2.0-or-later OR BSD-3-Clause |
| virglrenderer with Homebrew tap patches | 1.3.0 | MIT |
| libslirp (patched source build) | 4.9.4 | BSD-3-Clause AND BSD-2-Clause AND MIT |
| GLib | 2.88.3 | LGPL-2.1-or-later |
| pixman | 0.46.4 | MIT |
| libusb | 1.0.30 | LGPL-2.1-or-later |
| sdl2-compat | 2.32.70 | Zlib |
| SDL3 | 3.4.14 | Zlib |
| GNU gettext / libintl | 1.0 | LGPL-2.1-or-later |
| PCRE2 with JIT | 10.47 (Homebrew revision 1) | (BSD-3-Clause WITH PCRE2-exception) AND BSD-2-Clause |
| LZ4 library | 1.10.0 | BSD-2-Clause |
| XZ Utils / liblzma | 5.8.3 | 0BSD |
| libepoxy | 1.5.11 (tap bottle 1.0.5) | MIT |
| ANGLE | 1.0.16 (tap bottle; source commit absent) | BSD-2-Clause |
| Zstandard | 1.5.7 (Homebrew revision 1) | (BSD-3-Clause OR GPL-2.0-only) AND BSD-2-Clause AND MIT |
| edk2 firmware | edk2-stable202408 (08/13/2024) | BSD-2-Clause-Patent AND BSD-2-Clause AND BSD-3-Clause AND MIT AND OpenSSL |

ANGLE’s expression is the bottle declaration, not a verified license conclusion.
Its evidence files do not replace the missing license text.
The Zstandard expression follows its bottle SBOM and includes unverified embedded notices.
The edk2 expression summarizes the supplied composite notice, including its historical terms.

## Verification commands and results

Commands ran from the worktree root.
Inspection commands read the main checkout’s `.deps/` without modifying it.
The bridge helper now builds with `--scratch-path "$root/build/omarchy-helper"` so the build does not write into that shared checkout.

| Command | Result |
| --- | --- |
| `ln -s ~/ccsandbox/linux-vm/.deps .deps` | Linked the read-only dependency inputs. The ignore rule now also covers this symlink. |
| `python3 guest/build.py` | Built linuxvm-guest 0.2.1. |
| `guest/build-tools-iso.sh` | Rebuilt the disc locally. xorriso emitted its existing volume-ID warning. |
| `scripts/build-app.sh > /tmp/linuxvm-license-build.log 2>&1` | Exit 0, ad hoc. Ended with `linuxvmctl check`; QEMU 11.1.1, all 17 devices, Cocoa, touch scaling and HVF passed. |
| `swift test --package-path macos > /tmp/linuxvm-license-swift.log 2>&1` | Exit 0. 31 Swift Testing tests passed in five suites. |
| `python3 -m unittest discover guest/tests > /tmp/linuxvm-license-guest.log 2>&1` | Exit 0. 34 tests passed. |
| `python3 -m unittest discover scripts/harness/tests > /tmp/linuxvm-license-harness.log 2>&1` | Exit 0. 27 tests passed. |
| `python3 -m unittest discover scripts/tests > /tmp/linuxvm-license-python.log 2>&1` | Exit 0. 12 tests passed, with actual archives, the rebuilt disc and all 15 runtime dylibs present. No skips. |
| `python3 scripts/license-notices.py --inputs --bundle "build/Linux VM.app"` | Exit 0. Actual scripts, patches, archives, versions, license bytes, bundle files and Guest Tools members passed. Three unresolved release blockers are reported. |
| `python3 scripts/license-notices.py --identity 'Developer ID Application: license-gate-test'` | Expected exit 1: set `offer_contact` before Developer ID signing. This invokes no signing command. |
| `python3 build/license-verification/check-rejections.py` | Both intentional failures below returned 1. The original app remained intact. |
| `bash build/license-verification/replace-libraries.sh > /tmp/linuxvm-license-replacement.log 2>&1` | Exit 0 after following the bundled instructions on a disposable bundle copy. QEMU `--version`, preserved hypervisor/microphone entitlements and `linuxvmctl check` passed. |
| `ls -1 "build/Linux VM.app/Contents/Resources/Licenses"` | Listing reproduced below. |
| `git diff --cached --check -- . ':!licenses/texts' ':!licenses/pins'` | Exit 0 for authored files. An unrestricted staged check flags preserved upstream whitespace in copied notices. |

The final input check initially failed after the shared dependency checkout changed concurrently to a different source-fetching workflow.
The checker reported `actual runtime script differs: build-qemu-gpu-runtime.sh`.
No shared files were restored or edited.
A private dependency view was created from the same pinned upstream commit and this branch's diff.
The archives and built runtime still come from the main checkout.
The final build and license tests use this isolated view.
Its setup commands were:

```sh
mkdir -p build/license-deps
git clone --shared --no-checkout ~/ccsandbox/linux-vm/.deps/try-omarchy build/license-deps/try-omarchy
git -C build/license-deps/try-omarchy checkout --detach 13d63df8da2947f833c04025ff5ade187d39ba81
git -C build/license-deps/try-omarchy apply "$PWD/runtime/try-omarchy-v1.3.0.diff"
ln -s ~/ccsandbox/linux-vm/.deps/source-archives build/license-deps/source-archives
mkdir -p build/license-deps/try-omarchy/macos/.build
ln -s ~/ccsandbox/linux-vm/.deps/try-omarchy/macos/.build/qemu-gpu-runtime build/license-deps/try-omarchy/macos/.build/qemu-gpu-runtime
rm .deps
ln -s "$PWD/build/license-deps" .deps
```

The current one-command-runtime workstream will need to update these pin comparisons when integrated.
This branch deliberately continues to enforce its own checked-in runtime diff.

The disposable verification scripts are in the ignored `build/license-verification/` folder.
Their rejection checks are also covered by the checked-in unit tests.
The re-signing check re-signed copies of the existing libraries.
It did not test a modified library implementation or any Developer ID signature.
The first re-signing attempt exposed that `codesign --display --entitlements -` emits a human-readable dictionary on this macOS.
The bundled command now adds `--xml`, and the corrected procedure passed.

Expected rejection output:

```text
Removed GLib entry: 1 license-notices: bottle-glib: missing component entry
Added uncovered dylib: 1 license-notices: uncovered bundle file: Contents/Resources/runtime/lib/uncovered.dylib
```

The tests also reject missing license texts, missing bundled notices, new Mach-O tools, new data components, unknown directories and unreviewed symlinks.
They compare the pins after applying our diff to the checked-in original Try Omarchy script.
They verify the actual shared checkout and every runtime file when those inputs are installed.

Bundle license directory:

```text
ANGLE-bottle-metadata.json
ANGLE-header-notice.txt
AppIcon-provenance.txt
GLib-notice.txt
GPL-2.0.txt
Guest-Tools-attribution.txt
LGPL-2.1.txt
LGPL-REPLACEMENT.txt
LZ4-BSD.txt
Linux-VM.txt
NOTICES.txt
PCRE2-LICENCE.txt
QEMU-LICENSE.txt
QEMU-source-notices.txt
SDL3-Zlib.txt
Try-Omarchy-MIT.txt
XZ-0BSD.txt
XZ-COPYING.txt
Zstandard-BSD.txt
Zstandard-GPL.txt
edk2-licenses.txt
keycodemapdb-BSD.txt
keycodemapdb-README.txt
libepoxy-MIT.txt
libfdt-BSD.txt
libfdt-source-notices.txt
libintl-notice.txt
libslirp-COPYRIGHT.txt
libslirp-LICENSE.txt
libslirp-source-notices.txt
libusb-AUTHORS.txt
libusb-LGPL.txt
manifest.json
pixman-MIT.txt
sdl2-compat-Zlib.txt
virglrenderer-MIT.txt
virglrenderer-source-notices.txt
```

## Release blockers and legal review

1. The source-offer contact is unset. Fill `offer_contact` in `manifest.json`. The build rejects Developer ID signing while it is unset.
2. ANGLE’s pinned bottle has no license text or third-party notices. Its source commit file is empty. BSD-2-Clause is only the bottle metadata declaration. The exact upstream version and complete license terms could not be established from the supplied input.
3. Zstandard’s bottle SBOM also declares BSD-2-Clause and MIT code. The bottle omits the corresponding embedded-component notices. The exact source must be audited to establish which subcomponents were actually compiled into the shipped binaries.
4. `scripts/render-icon.swift` renders the Apple SF Symbol `chevron.right` into AppIcon.icns. Its SF Symbols version and matching license text are unrecorded. Apple’s [SF Symbols guidance](https://developer.apple.com/design/human-interface-guidelines/sf-symbols) prohibits use in app icons. The artwork was left unchanged because this task excludes UI work.

The contact is a separate gate from the three provenance blockers.
Removing the blocker descriptions alone does not clear entries marked as having incomplete license evidence.
No missing upstream license was invented or fetched from an unrelated current version.
Ad hoc development builds explicitly preserve the gaps instead of claiming complete redistribution clearance.

Review the offer against [GPLv2 section 3](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) and [LGPLv2.1 sections 4 and 6](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
The LGPL offer is intended to supply the complete linked QEMU work under section 6(c), including library and QEMU source.
Whether this satisfies section 4 for the separately shipped dylibs needs legal review.
Complete source retention and an operational source-request process were not verified.
The required source includes the actual Homebrew source versions, formula patches and build configuration, plus all local patches and compilation and installation scripts.
The offer alone does not recover absent corresponding source.

Apple’s [library-validation documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-library-validation) explains the signing-team restriction.
The instructions preserve the release signing settings and instead let a user re-sign a personal copy ad hoc without runtime library validation.
That copy retains QEMU’s hypervisor and microphone entitlements.
An actual Developer ID build, notarization and a replacement library from another team remain untested, as required by the task’s signing constraint.

The Homebrew VirGL tap formula declares MIT, but its archive contains no separate license for its patches.
The supplied edk2 notice names Berkeley SoftFloat Release 3e and OpenSSL, but does not identify the exact embedded OpenSSL version.
The original Linux VM code and artwork have no selected license.
Opaque bottle internals cannot be fully audited from the shipped binary and metadata alone.

## Scope and deviations

No VM was started.
Nothing was copied to `/Applications`.
No identity other than ad hoc was used for signing.
No file under `macos/Sources` was changed.
Nothing in the main checkout’s `.deps/` was changed.
No source archives were bundled.
The notices include complete upstream copyright-comment collections, not source implementations.
The existing signing order, hardened-runtime options, entitlements and signature checks remain intact.

The requirement to ship every actual license text could not be completed for the missing ANGLE and embedded Zstandard notices, or the unrecorded Apple symbol license.
Those gaps are explicit in the manifest and development notices, and prevent Developer ID builds.
This is stricter than the requested contact-only release gate because allowing a public release would conceal unresolved input provenance.
The icon was audited but not redesigned.
The source snapshots make original-code changes reviewable and require updating their hashes after review.
A new component can be added through manifest entries, exact file paths, explicit framework symlinks, input pins and license records.

The work is committed on this worktree’s branch and was not pushed or merged.
