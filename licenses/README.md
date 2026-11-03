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
The build runs both checks before signing and checks the complete bundle again afterward.
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

When original app sources change, update the app component's `source.files` path-to-SHA-256 map.
Its aggregate `source.sha256` is the SHA-256 of `json.dumps(files, sort_keys=True).encode()`.
When Guest Tools change, update the explicit `guest_files` entries and their SHA-256 values.
The guest component's aggregate source checksum uses the same JSON format over its source path-to-SHA-256 map.
Review those changes for new third-party code before updating the checksums.
Update component versions when the corresponding app, guest, source or bottle version changes.
Rebuild the disc after guest changes.
Run the test commands in the root README and build the app.

For patches, the manifest records our diff checksum and the upstream source archive checksum.
The runtime build script pins every applied patch by checksum.
The source offer must include all patches and the build and installation scripts.
Keep the corresponding source for every distributed binary, including Homebrew's formula patches and bottle build configuration.
A bottle URL and upstream repository alone are not the corresponding source.
Do not delete retained release source during the offer period.

## Source offer and release blockers

Set `offer_contact` in `manifest.json` to the distributor's durable contact address.
That is the only source-offer contact setting.
A Developer ID build fails before compilation while that setting is unset.
The written offer covers any third party and lasts at least three years after the last distribution of a version.
It promises complete corresponding source at no more than physical distribution cost.
It covers GPL and LGPL source, patches, interface definitions and build and installation scripts.
The distributor must actually retain and provide those materials.

ANGLE remains a provenance blocker.
Its bottle's verified formula source fetches moving ANGLE and dependency revisions and leaves `commit.txt` empty.
The tag formula also has a source checksum mismatch.
See [the audit](ANGLE-AUDIT.md) for the exact evidence and what is missing.
Zstandard's checksum-pinned 1.5.7 source establishes xxHash and libdivsufsort-lite notices.
The library and CLI retain those notices and the full source copyright collection.
The app icon is original artwork drawn with paths and has no SF Symbols blocker.
An ad hoc build reports the remaining ANGLE gap in its notices.
The checker cannot prove that an opaque prebuilt bottle contains only the subcomponents declared by its producer.

## Legal review points

The LGPL replacement procedure preserves QEMU's entitlements while removing library validation in a personal ad hoc copy.
Apple documents that hardened-runtime library validation otherwise restricts loading code from a different signing team in its [entitlement reference](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-library-validation).
The procedure leaves the release signing settings intact.
It was checked with ad hoc signatures only.
Developer ID signing, notarization and a replacement library built by another team still need verification.

Review the written offer against [GPLv2 section 3](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) and [LGPLv2.1 sections 4 and 6](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html) before release.
The LGPL offer is intended to cover the complete linked QEMU work under section 6(c), including the library source and QEMU source needed to rebuild it.
Whether that also satisfies section 4 for separately shipped dylibs needs legal review.
The bundled instructions expressly permit modification and reverse engineering to debug library changes.
No license has been selected for the original app, artwork, guest code or local patch contributions.
Their third-party portions retain their upstream licenses.
The Homebrew VirGL tap formula declares MIT, but its patch archive has no separate license notice.
The edk2 composite notice establishes the firmware's release and aggregate terms, but does not establish an exact OpenSSL version inside the firmware.
These are recorded limitations, not a claim of complete legal clearance for a public release.
