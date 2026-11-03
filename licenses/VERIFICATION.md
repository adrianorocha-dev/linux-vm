# License and source-retention verification

Verified on 3 November 2026 on this Mac in `t3/license-notice-performance`.
Merge commit `(commit)` brings in `t3/license-source-retention`, including (commit), (commit) and (commit).
Implementation commit `(commit)` contains the ANGLE notices, dynamic original-code versions, fast build checks and source-retention changes.
The verification commit changes documentation only.
The final notice refinement adds Vulkan Utility Libraries’ complete Apache text from its own pinned archive and labels Chromium’s zlib additions BSD-3-Clause.

## Inputs and build commands

Commands ran from the worktree root.
Logs and disposable artifacts are in the ignored `build/` directory.
The main checkout's `.deps` was read through a symlink.
Its source archives and repositories were never used as writable caches.
The firmware helper always recreates its archive, so these builds used a separate cache.
The Try Omarchy helper used the build script's private `build/omarchy-helper` scratch path.
The existing Guest Tools disc was copied from the main checkout.

```sh
ln -s ~/ccsandbox/linux-vm/.deps .deps
mkdir -p guest/dist build/firmware-source/git
cp ~/ccsandbox/linux-vm/guest/dist/* guest/dist/
cp -R .deps/source-archives/git/qemu-c3d48b7d1e89604920e5b81b91140c2ad39a1943.git build/firmware-source/git/
OMARCHY_DOWNLOAD_CACHE="$PWD/build/firmware-source" /usr/bin/time -p scripts/build-app.sh > build/build-final.log 2>&1
```

The final build exited 0 in 17.94 seconds.
It ended with `linuxvmctl check` and reported the QEMU version, all 17 required virtual devices, Cocoa display, patched touch scrolling and HVF as available.
The first build in the fresh worktree took 57.77 seconds, including compilation.
Both builds signed ad hoc.
No VM was started.
Nothing was copied to `/Applications`.
No real signing identity was used.
Nothing was pushed or merged to main.

## License overhead

The measurement sums the three license commands that `build-app.sh` invokes.
It excludes compilation, firmware archiving, bundle copying, signing and `linuxvmctl check`.
A pristine copy of merge commit `(commit)` in `build/license-baseline` supplied the old checker, manifest and texts.
It used the same read-only dependency tree and warmed supplemental archives.
The old bundle was copied to `build/license-baseline/Timing.app` for the measurement.
Each row was timed with Python's `time.monotonic()` around `subprocess.run`.
All six commands exited 0.

| Phase | Before command | Before seconds | After command | After seconds |
| --- | --- | ---: | --- | ---: |
| Preflight | `python3 build/license-baseline/scripts/license-notices.py --inputs` | 5.195 | `python3 scripts/license-notices.py` | 0.097 |
| Write and check | `python3 build/license-baseline/scripts/license-notices.py --bundle build/license-baseline/Timing.app --write` | 0.381 | `python3 scripts/license-notices.py --bundle 'build/Linux VM.app' --write` | 0.151 |
| Check signed bundle | `python3 build/license-baseline/scripts/license-notices.py --bundle build/license-baseline/Timing.app` | 0.370 | `python3 scripts/license-notices.py --bundle 'build/Linux VM.app'` | 0.110 |
| Total | | 5.946 | | 0.358 |

The first old-checker measurement, including initial supplemental downloads, totaled 8.49 seconds.
The earlier new-checker measurement totaled 0.30 seconds.
The expanded full input verification took 5.33 seconds during the source-edit check.
It still clones Try Omarchy and verifies all third-party pins, actual scripts, git archives, archive checksums and upstream notice bytes.
Tests and Developer ID builds run it.
Ordinary ad hoc builds do not clone or download inputs.
They still verify all local license hashes and exact bundle, framework, disc and package coverage.

## Source-edit regression

The temporary edit appended `// Temporary license-check regression probe.` to `macos/Sources/LinuxVMCore/Runtime.swift`.
A Python `try/finally` restored the original bytes after these commands.
The build received `OMARCHY_DOWNLOAD_CACHE="$PWD/build/firmware-source"` through its environment.

| Command with the temporary edit present | Result |
| --- | --- |
| `scripts/build-app.sh` | Exit 0 in 25.13 seconds; ended with the runtime check. |
| `python3 scripts/license-notices.py --inputs` | Exit 0 in 5.33 seconds. |
| `python3 scripts/license-notices.py --bundle 'build/Linux VM.app'` | Exit 0 in 0.12 seconds. |

`git diff --exit-code HEAD -- macos/Sources` confirmed restoration.
The final build used the restored sources.
Unit tests also change both version source files in a scratch directory and verify the notices use the new values without a manifest edit.

## Release gates and rejection checks

`python3 scripts/license-notices.py --inputs` exits 0 and reports one release blocker: the unset source-offer contact.
ANGLE is no longer a blocker.
The following build exits 1 before compilation or signing:

```sh
LINUXVM_SIGN_IDENTITY='Developer ID Application: license gate test (not a signing identity)' OMARCHY_DOWNLOAD_CACHE="$PWD/build/firmware-source" scripts/build-app.sh
```

Its only failure is `set offer_contact in licenses/manifest.json before Developer ID signing`.
A disposable manifest with `offer_contact` set to `source@example.invalid` passes the complete gate:

```sh
python3 scripts/license-notices.py --manifest build/contact-gate-test.json --inputs --identity 'Developer ID Application: test only'
```

It exits 0 with zero release blockers.
This checks the gate and never invokes a signer.
The real manifest's contact remains unset.

| Intentional mutation and exact check | Expected result |
| --- | --- |
| Remove GLib in `build/removed-component.json`; `python3 scripts/license-notices.py --manifest build/removed-component.json` | Exit 1: `bottle-glib: missing component entry`. |
| Add `Contents/Resources/runtime/lib/uncovered.dylib`; `python3 scripts/license-notices.py --bundle 'build/Linux VM.app'` | Exit 1: uncovered bundle file at that path. |
| Add `Contents/Frameworks/Sparkle.framework/Versions/B/Resources/uncovered.txt`; same bundle command | Exit 1: uncovered bundle file at that path. |

Both injected files were removed in `finally` blocks.
Tests also reject missing licenses, changed third-party pins, incorrect component versions, invalid framework symlinks, unlisted directories, changed git archive members and corrupted retained archives.
Retention tests prove an optional ANGLE failure permits a complete archive while a missing required source fails.
They reject attempts to mark QEMU, GLib, libintl or libusb as best effort.

## Tests

| Exact command | Result |
| --- | --- |
| `swift test --package-path macos` | Exit 0; 31 tests in five suites. |
| `python3 -m unittest discover guest/tests` | Exit 0; 34 tests. |
| `python3 -m unittest discover scripts/harness/tests` | Exit 0; 27 tests. |
| `python3 -m unittest discover scripts/tests` | Exit 0; 28 tests, including actual installed-input verification. |

The Swift compiler's existing unused-result warnings and the runtime diff's trailing-blank-line warning remain.

## Full source archive

A clean checkout at implementation commit `(commit)` ran:

```sh
python3 scripts/retain-release-source.py --output build/linux-vm-complete-source.tar.gz
shasum -a 256 build/linux-vm-complete-source.tar.gz
```

The collector exited 0.
It verified the final container before renaming it.
The independent checksum matched the adjacent `.sha256` file.

| Index field | Result |
| --- | --- |
| Archive bytes | 398,169,355 bytes, or 379.72 MiB |
| Retained artifact bytes | 401,418,640 bytes, or 382.82 MiB |
| Artifacts | 97, including 37 in QEMU's recursive source tree |
| `complete` | `true` |
| `subset` | `null` |
| `gaps` | `[]` |
| `optional_failures` | `{}` |
| SHA-256 | `8a2bf2fe451922713a01d2d6a683194e0e57108758e21d2eaccd117f198707fe` |

All optional ANGLE reference sources were retained too.
The index records the external build-revision uncertainty and the tag/formula checksum mismatch as findings.
Its completeness concerns the required corresponding source, not recovery of every permissive library's historical build revision.
The archive is a verification artifact for the implementation commit.
Create and preserve a new complete archive at the actual release commit before distribution.
Keep release source through at least three years after the last distribution of that version.

## Audit decisions

The ANGLE version string resolves its main source revision despite the empty `commit.txt`.
Its BSD-3-Clause license and the third-party notice revisions are listed in [ANGLE-AUDIT.md](ANGLE-AUDIT.md).
The earlier BSD-2-Clause label was corrected because ANGLE's license has a non-endorsement clause.
Conservative inclusion covers candidates outside the enabled graph.
The Bison parser skeleton's explicit exception permits this larger work without a source-distribution obligation.
No unexcepted copyleft dependency was found in the enabled ANGLE graph.
All other GPL and LGPL source requirements remain enforced.
The original app and Guest Tools license choice is still open.
