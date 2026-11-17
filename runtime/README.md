# QEMU runtime

The app bundles Try Omarchy's patched QEMU runtime with our changes on top. `try-omarchy-v1.3.0.diff` applies to Try Omarchy at tag `v1.3.0` (commit `13d63df8da2947f833c04025ff5ade187d39ba81`, MIT):

- **`macos/patches/qemu-cocoa-touch-scroll-scale.patch`:** scales the touch-scroll contacts' travel. The scale is read from `TRYOMARCHY_TOUCH_SCROLL_SCALE_FILE` at every landing, so it can be tuned while a VM runs.
- **`macos/patches/qemu-cocoa-touch-scroll-direction.patch`:** the touch-scroll contacts follow the fingers. AppKit's deltas already include the Mac's natural scrolling (`isDirectionInvertedFromDevice`), and Try Omarchy's contacts moved in that direction for a guest with natural scrolling off. GNOME applies its own natural scrolling, so its touchpad setting worked backwards. The patch undoes the Mac's inversion, and the guest's setting picks the direction. The wheel path keeps the Mac's direction.
- **`macos/patches/qemu-slirp-host-loopback.patch`:** adds `host-loopback=on|off` to `-netdev user`. With `off`, libslirp's `disable_host_loopback` stops the guest from reaching the Mac's loopback interface through `10.0.2.2`; `libslirp-local-network.patch` also refuses destinations the guest addresses to the Mac directly (`127.0.0.0/8`, `0.0.0.0/8`, `::1`, `::` and their IPv4-mapped forms), which upstream lets through. The app uses it for VMs that may not reach services on the Mac.
- **`macos/patches/qemu-slirp-local-network.patch`** and **`macos/patches/libslirp-local-network.patch`:** add `local-network=on|off` to `-netdev user`. With `off`, libslirp refuses guest connections and packets (TCP, UDP, and ICMP echo through both its ping sockets and its UDP fallback) to private, shared, link-local, multicast and reserved addresses, and to the subnets of the Mac's interfaces, which it re-reads every two seconds. DNS through `10.0.2.3` and the host address keep their own rules. QEMU refuses `local-network=off` when built against a libslirp without the patch. `test/local-network-test.c` covers the address rules.
- **`macos/Sources/OmarchyVMHelper/main.swift`:** the clipboard and audio bridges' startup log lines say "the VM" instead of "Omarchy".
- **`macos/Sources/OmarchyVMHelper/NativeClipboardBridge.swift`:** the clipboard bridge doesn't send Mac copies marked private (`org.nspasteboard.ConcealedType` or `TransientType`), as password managers mark passwords.
- **`macos/patches/virgl-core-instance-id.patch`:** virglrenderer no longer writes `#extension GL_ARB_draw_instanced : require` into shaders for GLSL 1.40 and later, where `gl_InstanceID` is built in. macOS's GLSL 4.10 compiler rejected the directive, so any guest shader reading `gl_InstanceID` failed on the Mac and its draws were lost.
- **`macos/build-qemu-gpu-runtime.sh`:**
  - applies those six patches;
  - builds QEMU 11.1.3 (`005c61c0ef6f6ae615283440b4bb7be51b2c6ddd`) instead of 11.1.1, for the fixes to CVE-2026-93834 (9p shared folders) and CVE-2026-17588 (xHCI);
  - fetches QEMU and keycodemapdb from their GitHub mirrors at pinned commits. It verifies the Git objects and creates fresh archives from them. Other downloads keep their SHA-256 pins.

## Building

Run this from the repository root on an Apple Silicon Mac with macOS 15 or newer:

```sh
scripts/build-runtime.sh
```

Install Xcode command line tools (`xcode-select --install`), pkg-config (`brew install pkgconf`), and Python 3.11 or newer with working venvs (`brew install python@3.14`). The script prefers `/opt/homebrew/bin/python3.14`. Set `LINUXVM_PYTHON` to use another Python. It tests venv creation before building because uv-managed Python can fail there.

The script clones Try Omarchy at the pinned commit and applies our diff. It accepts an existing pristine checkout or the exact patched checkout. It refuses unexpected changes.

The build verifies every source input. QEMU and keycodemapdb use Git commit integrity, so local git and gzip versions do not change the pins. Their cached archives are recreated from verified Git objects before use. The app build uses the same check for its firmware source.

Inputs and output stay in git-ignored `.deps/`. Downloads and Git objects are reused from `.deps/source-archives/`. Set `OMARCHY_DOWNLOAD_CACHE` to use another cache for both build scripts. Set `OMARCHY_RUNTIME_BUILD_JOBS` to limit compiler jobs.

The runtime is written to `.deps/try-omarchy/macos/.build/qemu-gpu-runtime`, where `scripts/build-app.sh` expects it. The script checks QEMU's signature and hypervisor entitlement after building. It is safe to run again.
