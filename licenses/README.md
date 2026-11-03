# Bundle licenses and provenance

`manifest.json` records the shipped components, source and bottle pins, license expressions, bundle paths and every Guest Tools package member.
`texts/` preserves upstream license texts and source copyright notices from the pinned inputs.
Source notice collections retain headers from entire upstream archives, including code this configuration does not build.
`LGPL-REPLACEMENT.txt` explains how to replace the LGPL libraries in a personal copy.
The build copies these files to `Contents/Resources/Licenses/` and generates `NOTICES.txt` there.
The old Try Omarchy and firmware notices remain at their original paths too.

## Checks

Run `python3 scripts/license-notices.py --inputs` to check the installed dependency inputs.
Run `python3 scripts/license-notices.py --bundle "build/Linux VM.app"` to check a bundle.
Ad hoc builds check local license hashes and coverage before signing and check the complete bundle again afterward.
Developer ID builds also run `--inputs` before compilation.
Tests run the full pin and archive checks.
The ordinary path does not clone a repository or download an archive.
Every bundle file needs an exact manifest path.
The checker also rejects unlisted directories and symlinks.
Only the outer app's exact XML code-signature metadata path is exempt.
Files inside the Guest Tools ISO and Debian package are checked separately against the inventory.
Adding a file inside an already covered directory does not bypass the check.

Pin checks clone the pinned Try Omarchy commit into a temporary directory and apply our current diff.
They use `.deps/try-omarchy` as a local clone source when it exists.
Otherwise they clone the pinned tag from GitHub, as the runtime build tests do.
They compare the real patched builder and `runtime/source-pins.sh` against the manifest.
With `.deps/` installed, they also compare the actual build scripts, helper source, source objects, archive checksums, license bytes, versions and runtime files.
Supplemental source and release archives are downloaded to `build/license-inputs/` and verified by checksum.
No dependency checkout or archive in `.deps/` is modified by these checks.
Without `.deps/`, actual archive and runtime tests report a skip.
The runtime's build tools are recorded as build-only inputs because their code is not shipped.
libfdt and keycodemapdb are shipped inside QEMU and have component entries of their own.

## Updating the inventory

Add a component entry with its version, SPDX expression, exact bundle paths, input IDs and license filenames.
Add immutable source or bottle URLs and SHA-256 values under `inputs`.
Gitiles `+archive` downloads change bytes on every request. Pin those with `content_sha256`, the digest of their members, instead of `sha256`.
For git sources, record the repository URL and commit.
Verify the git objects with `git fsck` and compare archive members against those objects.
Locally generated QEMU and keycodemapdb archives have no transport checksum pin.
Do not describe locally generated git archives as the bytes served by GitLab.
Copy the matching upstream license text into `texts/` and record its input, member and SHA-256 under `license_texts`.
Keep required copyright notices, including embedded third-party notices.
Use an explicit provenance blocker if the pinned input cannot establish the license.
Sparkle lists its framework files individually, including the nested updater app and signature metadata.
Record framework symlinks in the component's `bundle_symlinks` map, from bundle path to relative target.
The checker verifies each target and rejects links that escape the bundle.

Original app and Guest Tools source files have no manifest checksums or aggregate snapshot.
The notices read the app version from `macos/Resources/Info.plist` and the Guest Tools version from `guest/build.py`.
Changing our code or versions does not require a manifest edit.
Every file in the bundle, disc and package still needs an inventory entry.
Add new Guest Tools member paths to `guest_files` and rebuild the disc after guest changes.
The package's internal md5sums and generated version are checked for consistency.
Review changes for new third-party code and update its pins and notices when needed.
Third-party source, patch, archive, package and license checks remain enforced by `--inputs` and tests.
Run the test commands in the root README and build the app.

For patches, the manifest records our diff checksum and the upstream source archive checksum.
The runtime build script pins every applied patch by checksum.
The source offer must include all patches and the build and installation scripts.
Keep the corresponding source for every distributed binary, including Homebrew's formula patches and bottle build configuration.
A bottle URL and upstream repository alone are not the corresponding source.
Do not delete retained release source during the offer period.

## Source and release blockers

Each release publishes its complete corresponding source next to its DMG, as `linux-vm-VERSION-source.tar.gz` on the GitHub release.
GPLv2 and LGPLv2.1 count source offered from the same place as the binary as distributing it, so no written offer is needed.
The notices name that release page, using the repository in `scripts/release-config.json`.
`offer_contact` in `manifest.json` is where questions and source requests go: the repository's Issues page.
A Developer ID build fails before compilation while the contact or the repository is unset.
The archive covers GPL and LGPL source, patches, interface definitions and build and installation scripts.

ANGLE is pinned to the commit recorded in its shipped library.
Its full license and embedded dependency notices come from immutable source revisions.
External notice revisions are the ones that commit's DEPS names, while the bottle fetched moving build-day heads.
These libraries impose no corresponding-source distribution obligation.
The Bison generated parser exception also permits this larger work without such an obligation.
ANGLE is no longer a release blocker.
The bottle's tag/formula checksum mismatch remains a finding.
See [the audit](ANGLE-AUDIT.md) for the graph, revisions, licenses and remaining provenance limits.
Zstandard's checksum-pinned 1.5.7 source establishes xxHash and libdivsufsort-lite notices.
The library and CLI retain those notices and the full source copyright collection.
The app icon is original artwork drawn with paths and has no SF Symbols blocker.
The unset source-offer contact is the only current release blocker.
An ad hoc build reports it in its notices.
The checker cannot prove that an opaque prebuilt bottle contains only the subcomponents declared by its producer.

## Retaining release source

Run this after building the release from a clean committed checkout:

```sh
python3 scripts/retain-release-source.py --output /path/to/retained/linux-vm-VERSION-source.tar.gz
```

The archive is outside the app. `scripts/release.py` runs this for every release and attaches the result to the release.
Don't delete a release's source archive while that version is distributed.
Only a complete run may be published.

The collector requires all copyleft source and build inputs, including bottle formulas, resources and patches.
It also retains manifest archives, including bottles and build tools.
ANGLE source and its permissive notice reference inputs are best effort.
Failures for those inputs are recorded separately and do not hide a missing required input.
It retains every pinned git source and recursively follows its submodule commits.
It includes the full Linux VM checkout at the release commit, including our diffs, patches, guest sources, build scripts and installation scripts.
It extracts each bottle's exact formula and fetches its checksum-pinned upstream source and resources.
The source plan is `source-inputs.json`.
It also includes libepoxy's implementation commit and the tap archives containing its patches.
GLib's formula patch is pinned to the Homebrew commit that added it in October 2025.
The patch path has no later changes before this bottle's July 2026 build.
Every download is checked against its SHA-256.
Every git source is checked against its commit and with `git fsck`.
A failed local git fetch retries the pinned upstream URL without modifying the original repository.

`SOURCE-INDEX.json` records revisions, source URLs, pins, retained hashes and artifact sizes.
`SHA256SUMS` covers every retained file.
The script reads back and verifies the container before naming the final archive.
An adjacent `.sha256` file covers the complete archive.
It never writes to `.deps/`.
Its download and git cache defaults to `build/source-retention-cache/`.
`--inputs` selects the read-only bottle and runtime input directory.
That directory must contain the release's pinned bottles so their formulas can be checked.

A full run requires a clean committed checkout and marks its index `complete: true` only after every required source succeeds.
The index preserves provenance findings and any optional ANGLE failures.
The final archive's reported size is the measured size, not an estimate.
To test a small subset, use:

```sh
python3 scripts/retain-release-source.py --subset keycodemap,zstd-source,bottle-lz4-upstream,glib-hardcoded-paths,source-try-omarchy,sparkle-release,angle-build-source,epoxy-upstream --output build/source-retention-subset.tar.gz
```

A subset always has `complete: false` in its index.
It is a test artifact and must not be published with a release.
See [verification](VERIFICATION.md) for measured build overhead, test results and the retained archive result.

## Legal review points

The LGPL replacement procedure preserves QEMU's entitlements while removing library validation in a personal ad hoc copy.
Apple documents that hardened-runtime library validation otherwise restricts loading code from a different signing team in its [entitlement reference](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-library-validation).
The procedure leaves the release signing settings intact.
It was checked with ad hoc signatures only.
Developer ID signing, notarization and a replacement library built by another team still need verification.

Publishing the source next to the binary relies on the last paragraph of [GPLv2 section 3](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) and on [LGPLv2.1 sections 4 and 6](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
The archive is meant to cover the complete linked QEMU work, including the library source and QEMU source needed to rebuild it.
Whether that also satisfies section 4 for separately shipped dylibs needs legal review.
The bundled instructions expressly permit modification and reverse engineering to debug library changes.
No license has been selected for the original app, artwork, guest code or local patch contributions.
Their third-party portions retain their upstream licenses.
The Homebrew VirGL tap formula declares MIT, but its patch archive has no separate license notice.
The edk2 composite notice establishes the firmware's release and aggregate terms, but does not establish an exact OpenSSL version inside the firmware.
These are recorded limitations, not a claim of complete legal clearance for a public release.
