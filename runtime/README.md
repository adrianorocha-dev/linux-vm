# QEMU runtime

The app bundles Try Omarchy's patched QEMU runtime with our changes on top. `try-omarchy-v1.3.0.diff` applies to Try Omarchy at tag `v1.3.0` (commit `13d63df`, MIT):

- **`macos/patches/qemu-cocoa-touch-scroll-scale.patch`:** scales the touch-scroll contacts' travel. The scale is read from `TRYOMARCHY_TOUCH_SCROLL_SCALE_FILE` at every landing, so it can be tuned while a VM runs.
- **`macos/build-qemu-gpu-runtime.sh`:**
  - applies that patch;
  - re-pins the QEMU and keycodemapdb archives. gitlab.com archives sit behind a Cloudflare challenge, so they are built with `git archive` from the GitHub mirrors at the same pinned commits. Upstream's checksums are kept in comments.

## Building

The build inputs live in `.deps/`, which git ignores. From the repository root:

```sh
git clone https://github.com/omacom/try-omarchy.git .deps/try-omarchy
git -C .deps/try-omarchy checkout v1.3.0
git -C .deps/try-omarchy apply ../../runtime/try-omarchy-v1.3.0.diff
```

Create the two source archives in `.deps/source-archives/`:

```sh
mkdir -p .deps/source-archives
for spec in qemu:c3d48b7d1e89604920e5b81b91140c2ad39a1943 keycodemapdb:f5772a62ec52591ff6870b7e8ef32482371f22c6; do
  name=${spec%%:*}
  commit=${spec#*:}
  git init -q /tmp/$name
  git -C /tmp/$name fetch -q --depth 1 https://github.com/qemu/$name.git $commit
  git -C /tmp/$name archive --format=tar --prefix=$name-$commit/ FETCH_HEAD | gzip -n > .deps/source-archives/$name-$commit.tar.gz
done
```

Then build. QEMU's configure needs Python 3.11 or newer with working venvs; `.deps/build-tools/python3` links to Homebrew's Python 3.14. The uv-managed standalone Pythons break venv creation.

```sh
mkdir -p .deps/build-tools && ln -sf /opt/homebrew/bin/python3.14 .deps/build-tools/python3
(cd .deps/try-omarchy && PATH="$PWD/../build-tools:$PATH" OMARCHY_DOWNLOAD_CACHE="$PWD/../source-archives" ./macos/build-qemu-gpu-runtime.sh)
```

If your git or gzip writes different bytes, the build reports a checksum mismatch. The commits are what matter: re-pin the two `*_sha256` values in the build script to your archives. `scripts/build-app.sh` reads the runtime from `.deps/try-omarchy/macos/.build/qemu-gpu-runtime`.
