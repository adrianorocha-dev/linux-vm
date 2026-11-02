# QEMU runtime

The app bundles Try Omarchy's patched QEMU runtime with our changes on top. `try-omarchy-v1.3.0.diff` applies to Try Omarchy at tag `v1.3.0` (commit `13d63df`, MIT):

- **`macos/patches/qemu-cocoa-touch-scroll-scale.patch`:** scales the touch-scroll contacts' travel. The scale is read from `TRYOMARCHY_TOUCH_SCROLL_SCALE_FILE` at every landing, so it can be tuned while a VM runs.
- **`macos/build-qemu-gpu-runtime.sh`:**
  - applies that patch;
  - re-pins the QEMU and keycodemapdb archives. gitlab.com archives sit behind a Cloudflare challenge, so they are built with `git archive` from the GitHub mirrors at the same pinned commits. Upstream's checksums are kept in comments.

## Building

```sh
git clone https://github.com/omacom/try-omarchy.git ../ubuntu-qemu-prototype/try-omarchy-src
cd ../ubuntu-qemu-prototype/try-omarchy-src
git checkout v1.3.0
git apply ../../linux-vm/runtime/try-omarchy-v1.3.0.diff
```

Create the two source archives in `../ubuntu-qemu-prototype/source-archives/`:

```sh
for spec in qemu:c3d48b7d1e89604920e5b81b91140c2ad39a1943 keycodemapdb:f5772a62ec52591ff6870b7e8ef32482371f22c6; do
  name=${spec%%:*}
  commit=${spec#*:}
  git init -q /tmp/$name
  git -C /tmp/$name fetch -q --depth 1 https://github.com/qemu/$name.git $commit
  git -C /tmp/$name archive --format=tar --prefix=$name-$commit/ FETCH_HEAD | gzip -n > ../source-archives/$name-$commit.tar.gz
done
```

Then build with Python 3.11 or newer first on `PATH`; QEMU's configure needs `tomllib`:

```sh
OMARCHY_DOWNLOAD_CACHE=$PWD/../source-archives ./macos/build-qemu-gpu-runtime.sh
```

If your git or gzip writes different bytes, the build reports a checksum mismatch. The commits are what matter: re-pin the two `*_sha256` values in the build script to your archives. `scripts/build-app.sh` expects this layout.
