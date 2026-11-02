# Milestone 0 notes — Ubuntu on Try Omarchy's runtime

Date: 2026-11-01. Host: M1 Pro, macOS 27.2, built-in display 1512×982 points at 2× and 120 Hz.


This is the record of the Milestone 0 runs. The prototype's scripts and VM were retired after Milestone 1. The runtime source now lives in `.deps/try-omarchy` and `.deps/source-archives` ([runtime/README.md](../runtime/README.md)). `scripts/guest-diagnostics.sh` and `scripts/ssh-vm.sh` replace the prototype's diagnostics and SSH helpers.

## Setup

- Runtime: the QEMU 11.1.1 binary, libraries and edk2 firmware bundled in the installed **Try Omarchy 1.2.0** (`/Applications/Try Omarchy.app`, not 1.3.0). The scroll and pinch code is the same in both versions.
- Guest: the official Ubuntu 26.04.1 arm64 cloud image (sha256 `8eb876c2…da24`), configured by `seed/user-data` on first boot. It has GNOME Shell 50.1 / Mutter 50.1 on Wayland, kernel 7.0.0-42, and libinput 1.31.1.
- Launch: `run-ubuntu-prototype.sh`, which uses Try Omarchy's device set (virtio-gpu-gl, keyboard, tablet, `virtio-pinch-pci`) and Cocoa `gl=on` display options. It omits Try Omarchy's host bridges, so there is no shared clipboard, audio routing, shared folders or guest settings channel. It runs windowed (`full-screen=off`) with `show-cursor=on`. The display is `-display cocoa,gl=on,show-cursor=on,zoom-to-fit=on,full-screen=off,full-grab=off`.
- Guest touchpad settings follow Try Omarchy's Hyprland config: the libinput quirk `ModelLenovoX1Gen6Touchpad=1`, plus tap-to-click, disable-while-typing and natural-scroll all off. They are installed as GNOME defaults, so Settings can still change them.
- Neither UTM VM was touched. The UTM bundle is protected by macOS app-data protection anyway.
- Shell access: `./ssh-guest.sh <command>`. `guest-diagnostics.sh` collects the objective checks.

## Objective results

| Question | Result |
|---|---|
| VirGL rendering | Mutter uses KMS atomic and created a GBM renderer on virtio_gpu. QEMU's virglrenderer reports Apple OpenGL 4.1 (Metal) on the M1 Pro. |
| Host refresh in EDID | **Yes.** The preferred DTD is 800×600 at **119.998 Hz**, with a range limit of 50–125 Hz. Mutter runs that mode as current and preferred. No `video=` argument is needed. |
| Scale via EDID | The EDID carries 90 × 70 mm, which is Try Omarchy's 2× encoding at 110 DPI. **Mutter ignores it and picks scale 1.0**, so the encoding doesn't transfer to GNOME at this size. Needs a retest at a full-size window. |
| Initial size | The QEMU window was 316×269 points, below the patch's 800×600-pixel minimum, so the guest got 800×600 and zoom-to-fit scaled it down. |
| Hardware cursor plane | **Yes.** The kernel atomic state shows Mutter's KMS thread setting a 64×64 ARGB framebuffer on the cursor plane (plane 35). Guest cursor shapes therefore reach QEMU separately from the screen image. `drm_info` hides that plane because it doesn't set the hotspot client cap. |
| Touchpad detected | `QEMU Virtio Pinch Touchpad` has capabilities `pointer gesture`, two-finger scrolling, and the quirk applied. Tap-to-click is disabled. |

## First hands-on session

The user tested the VM and reported that it "ran super well", then shut the guest down from inside (1405 s uptime).

The QEMU log shows one VirGL problem to follow up. A guest GL context named "Renderer" had a shader rejected four times, because it requests `GL_ARB_draw_instanced` and Apple's GLSL 4.10 compiler doesn't support that extension. The draw calls that used the shader were dropped. The context was probably a browser compositor (Firefox WebRender or Chromium); the user did not notice anything missing.

## User results (first session)

1. **Scrolling** works, but it doesn't feel exactly like Try Omarchy. This may be Firefox compared with Omarchy's Chromium; it needs a same-browser comparison.
2. **Gestures:** scrolling, pinch zoom and swipe navigation all worked.
3. **Full screen** behaved well, but the guest extended under the MacBook notch and the notch hid GNOME's clock. The run used non-immersive full screen with the notch patch's default (cover the camera strip).
4. **Cursor:** the guest's shapes appeared (I-beam, resize). The macOS arrow was drawn on top of them. The guest cursor sometimes lagged behind the arrow, and sometimes the two were misaligned, especially near the top edge where the menu bar and notch are.

### Interpretation

- Shapes: Mutter's cursor plane feeds `dpy_cursor_define`, and Cocoa's `cursorLayer` draws the image at the position the guest reports (`dpy_mouse_set`). The arrow was there too because `show-cursor=on` keeps the host cursor visible. The lag is the guest round trip, which is inherent to positioning the layer from the guest.
- Top edge: in non-immersive full screen, macOS shows its menu bar over the window when the pointer reaches the top. The pointer then leaves the view, so the guest stops receiving positions. The notch strip may also shift the mapping there (not verified).
- Fix to test next: `PROTO_SHOW_CURSOR=off` (now the default), immersive full screen and `TRYOMARCHY_NOTCH=0` (also defaults now). These should remove the double cursor and the notch problems, but not the lag. Removing the lag needs a frontend patch that turns the guest image and hotspot into an `NSCursor`.

## Second session

Launched with the new defaults: `show-cursor=off`, `immersive=on`, `TRYOMARCHY_NOTCH=0`. The user said the VM "feels much, much better now".

Measured over SSH in full screen: the EDID preferred mode was 3024×1900 at 35 × 22 cm. Mutter chose **3024×1900 at 120.001 Hz, scale 2.0** (it also supports 1.0 and 1.33), with no manual configuration. That is the built-in panel minus the 64-pixel camera strip.

User follow-up: **no cursor delay** ("it's perfect"). Scrolling in Chromium still feels like "too much force" compared with macOS.

Cause: Try Omarchy's touch-scroll patch moves the contacts 0.12 mm per macOS point (times a gain of 0.35–1.0 depending on speed) and leaves speed to the guest. Omarchy sets Hyprland's `touchpad.scroll_factor` to 0.4 (Try Omarchy `docs/trackpad-scrolling.md`). GNOME 50 has no touchpad scroll-factor key; the schema was checked in the guest, and `speed` affects only pointer motion. So GNOME scrolls about 2.5 times as far for the same gesture. Fix: scale on the host (0.12 → about 0.048 mm per point), preferably as a runtime setting. This needs a runtime built from source.

## Patched runtime with adjustable scroll travel (2 November)

- Source: Try Omarchy v1.3.0 (`13d63df`) in `try-omarchy-src/`, built with its own `macos/build-qemu-gpu-runtime.sh` into `try-omarchy-src/macos/.build/qemu-gpu-runtime/`. The build ad-hoc signs the binary and targets macOS 15.
- One added patch, `macos/patches/qemu-cocoa-touch-scroll-scale.patch`, applied right after `qemu-cocoa-touch-scroll.patch`. It multiplies the contacts' travel by a scale that is read from `TRYOMARCHY_TOUCH_SCROLL_SCALE_FILE` at every landing. The 1.6 mm pre-roll that starts libinput's scroll is not scaled. Values are clamped to 0.05–4.
- Build changes in our copy only:
  - gitlab.com archives are behind a Cloudflare challenge. QEMU and keycodemapdb were therefore fetched from their GitHub mirrors at the pinned commits (the commit hashes were verified), packed with `git archive`, and their tarball checksums re-pinned. Upstream's checksums are kept in comments.
  - QEMU's configure needs Python ≥ 3.11 with working venvs. `build-tools/python3` points at Homebrew Python 3.14. The uv-managed 3.12 broke venv creation.
  - Downloads are cached in `source-archives/`.
- `run-ubuntu-prototype.sh` uses the built runtime when it exists (`PROTO_RUNTIME=app` switches back). It writes `vm/scroll-scale`, defaulting to 0.4 to match Omarchy's Hyprland factor. `./set-scroll-scale <n>` changes it while the VM runs.

User result at scale 0.4: scrolling "feels much closer. not perfect, but good enough for now." Further tuning is deferred.

## Still to test (needs the user at the Mac)

- Does Mutter follow window resizes, zoom and fullscreen? That is, does a new EDID become a new mode, and does the scale change?
- Trackpad feel compared with Try Omarchy: scrolling in Files, Settings, Text Editor, Firefox, Chromium and Ptyxis.
- Pinch zoom in Firefox, Chromium, Loupe and Papers. Two-finger back/forward swipe in the browsers.
- Cursor: does the guest's I-beam or resize shape appear, or only the macOS arrow? Is there a second, lagging cursor?
