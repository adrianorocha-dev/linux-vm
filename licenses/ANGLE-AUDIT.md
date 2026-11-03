# ANGLE source and notice audit

The shipped bottle is `angle-1.0.16.arm64_sequoia.bottle.tar.gz`.
Its SHA-256 is `29fe2175b157a65f12879f9a12b5c8f94d0a76fafdf41ff009a2fdb4e9df525c`.
Its `angle/1.0.16/INSTALL_RECEIPT.json` records tap commit `97987d9531ea8feeaf0fcc126be2bd97ffdf6479`.
Its `.brew/angle.rb` builds [that tap archive](https://github.com/startergo/homebrew-angle/archive/97987d9531ea8feeaf0fcc126be2bd97ffdf6479.tar.gz), with SHA-256 `f1b6c6c047714a023c89412b736408e3e28d7b5beffc29d577fc69bf460b6e85`.
That download was verified.

The [v1.0.16 tag formula](https://github.com/startergo/homebrew-angle/blob/v1.0.16/Formula/angle.rb) instead names `archive/refs/tags/v1.0.16.tar.gz` and SHA-256 `34eca0a062bceff8049e1925ce696e86435c4d205c88883c6a04c71c6e89f35e`.
On 3 November 2026 that URL returned SHA-256 `3550935c401a004d40ec025fb646cfbe65b9a1858c81bb8ab24dbcfe8af27514`.
The alternate codeload URL returned the same bytes.
Those bytes are untrusted research evidence, not a replacement for the formula pin.
Source retention uses the verified formula embedded in the actual bottle.

The tag archive mismatch is a finding, not a release blocker.

## Revision recorded by the binary

The bottle's `commit.txt` contains only a newline.
The shipped library itself records `ANGLE 2.1.27632 git hash: bb9e1870521d`.
This command reads that evidence without changing the dependency tree:

```sh
strings -a ~/ccsandbox/linux-vm/.deps/try-omarchy/macos/.build/qemu-gpu-runtime/lib/libGLESv2.dylib | rg 'ANGLE 2.1.27632 git hash: bb9e1870521d'
```

The prefix resolves to [bb9e1870521db37d5030103d74a9d3c9163ef7cc](https://github.com/google/angle/commit/bb9e1870521db37d5030103d74a9d3c9163ef7cc), committed on 25 April 2026.
The manifest pins the source archive by that commit and SHA-256.
The input check also compares the version evidence against the installed library.

## Build graph and notice sources

The verified tap `build.sh` invokes `gn gen` with these arguments:

```text
angle_enable_vulkan=true angle_enable_metal=true angle_enable_gl=false
angle_enable_swiftshader=false angle_enable_wgpu=false angle_enable_null=false
angle_enable_abseil=false angle_build_all=false is_debug=false
angle_has_frame_capture=false use_siso=false use_system_xcode=true
use_custom_libcxx=false use_lld=false
```

The targets are `libEGL libGLESv2 libGLESv1_CM install_angle`.
The app ships only libEGL and libGLESv2.
This audit follows `BUILD.gn`, `src/libGLESv2.gni`, `src/compiler.gni`, `src/libANGLE/renderer/{metal,vulkan}/BUILD.gn`, `src/common/vulkan/BUILD.gn` and the backend shader sources at the pinned ANGLE commit.
Both entry libraries use the common implementation and translator.
The Metal backend uses ANGLE's own Metal translator.
The Vulkan backend uses the Vulkan headers, static loader, allocator and compression targets.
The image utilities use ASTC encoder, whose code is present in the binary.
The common library uses xxHash and Chromium base helpers.
The compiled Vulkan shader arrays include the ETC decoder and FidelityFX SPD code.
The Khronos EGL, GLES and WGL header notices are preserved in the source notice collections.

On macOS `angle_shared_libvulkan` defaults to false, so the loader is linked statically.
volk belongs to the shared-loader branch and is included conservatively.
Release defaults disable validation layers, API dump layers, overlay and OpenCL.
Those branches do not introduce an additional compiled dependency into this configuration.
SPIRV-Tools, glslang, SPIRV-Cross, Vulkan-Tools, ceval, the overlay font and libXNVCtrl notices are included conservatively.
Build tools, tests and Linux-only backends are not evidence of code compiled into these two libraries.
No separate MoltenVK library is shipped in the app runtime.

Each row below identifies the revision from which the notice was taken.
In-tree copies are read from the ANGLE archive, including their local modifications.
Where an in-tree README names an upstream revision, the table records it.
The manifest records both that revision and the ANGLE notice input.
External revisions are the ones ANGLE's pinned DEPS names.
They are notice reference revisions, not recovered bottle build revisions.

| Component | License | Notice revision | Graph evidence |
| --- | --- | --- | --- |
| BSD | BSD-3-Clause | `bb9e1870521db37d5030103d74a9d3c9163ef7cc` | BUILD.gn: libEGL and libGLESv2 |
| xxHash | BSD-2-Clause | `e626a72bc2321cd320e953a0ccf1584cad60f363` | BUILD.gn: angle_common_lib -> xxhash |
| volk | MIT | `9767549a8bba5454555764ee0f3319bc5d205da9` | src/common/vulkan/BUILD.gn: shared loader branch; macOS defaults to static loader; included conservatively |
| ceval | MIT | `1ed80ae78ba7bef1744b1ccdffc6c6802eeec8fa` | src/libGLESv2.gni: capture sources; frame capture disabled, included conservatively |
| libXNVCtrl | MIT | `ffa5183362ed4ace5b1cfd031a272f72e7d68c1b` | BUILD.gn: X11 only, excluded on macOS; included conservatively |
| ETC-decoder | MIT | `cbc9cc966d2b3cae8906d2d30e761904342b5aba` | Vulkan shaders: EtcToBc.comp includes third_party/etc_decoder |
| FidelityFX-SPD | MIT | `0e82a6f4f491aa18adde62edc3f5c4ed20d92627` | Vulkan shaders: GenerateMipmap.comp includes third_party/ffx_spd |
| overlay-font | Apache-2.0 | `bb9e1870521db37d5030103d74a9d3c9163ef7cc` | src/libGLESv2.gni: overlay font; included conservatively |
| ASTC-encoder | Apache-2.0 | `2319d9c4d4af53a7fc7c52985e264ce6e8a02a9b` | BUILD.gn: angle_image_util -> third_party/astc-encoder:astcenc; binary contains ASTC encoder code |
| glslang | LicenseRef-glslang | `5ed4003a18a10a9d1bd7e43aaf1664499abffa83` | External fetched by bottle; tests/validation candidates included conservatively |
| SPIRV-Headers | MIT | `ad9184e76a66b1001c29db9b0a3e87f646c64de0` | src/common/spirv and Vulkan shader translator includes |
| SPIRV-Tools | Apache-2.0 | `aee3d20c3f083465f566fd6075a81822c3c4ae90` | Vulkan OpenCL branch / validation candidates; included conservatively |
| SPIRV-Cross | Apache-2.0 | `b8fcf307f1f347089e3c46eb4451d27f32ebc8d3` | DEPS candidate; Metal translator is ANGLE code, included conservatively |
| Vulkan-Headers | Apache-2.0 OR MIT | `f6a6f7ab165cedbfa2a7d0c93fe27a2d01ce09c8` | src/common/vulkan:angle_vulkan_headers |
| Vulkan-Loader | Apache-2.0 | `15a84652b94e465e9a7b25eb507193929863bc2f` | src/common/vulkan:angle_vulkan_entry_points -> libvulkan (static or data dependency) |
| Vulkan-Tools | Apache-2.0 | `7c46da2b39036a80ce088576d5794bf39e667f56` | src/common/vulkan:angle_libvulkan -> VkICD_mock_icd data dependency; conservative |
| Vulkan-Utility-Libraries | Apache-2.0 | `e2f236b273bfcd9c665306fdd53451b923d659ab` | Vulkan loader transitive headers; conservative |
| VulkanMemoryAllocator | MIT | `cb0597213b0fcb999caa9ed08c2f88dc45eb7d50` | src/libANGLE/renderer/vulkan:angle_vk_mem_alloc_wrapper |
| zlib | Zlib AND BSD-3-Clause | `89921383f1f51331f48a2dc843403779770ea3a9` | BUILD.gn: angle_compression -> compression_utils_portable -> zlib |
| Chromium base helpers | BSD-3-Clause | `28b5bbb227d331c01e6ff9b2f8729732135aadc7` | src/common/base/README.chromium; angle_common and anglebase headers |
| Khronos EGL/GLES/KHR/WGL headers | MIT AND Apache-2.0 | `bb9e1870521db37d5030103d74a9d3c9163ef7cc` | include/ and src/third_party/khronos; WGL included conservatively |
| Bison generated parser skeleton | GPL-3.0-or-later WITH Bison-exception-2.2 | `bb9e1870521db37d5030103d74a9d3c9163ef7cc` | src/compiler/translator/glslang_tab_autogen.cpp and .h; larger-work exception permits distribution under chosen terms; no source obligation for ANGLE output |

`manifest.json` records every notice's exact archive member and SHA-256.
`license-notices.py --inputs` verifies those bytes against the pinned downloads.
It also verifies the external notice revisions against ANGLE's DEPS.
Source header collections preserve individual author notices in addition to the complete license texts.

## What the bottle did not record

The bottle build cloned Vulkan-Headers, SPIRV-Headers, SPIRV-Tools, glslang, Vulkan-Loader, Vulkan-Tools, Vulkan-Utility-Libraries and zlib at moving heads with `--depth=1`.
It selected ASTC encoder and Vulkan Memory Allocator from the DEPS on main on the build day.
Those revisions need not match the recovered ANGLE commit's DEPS.
The build also fetched moving Chromium build tools and other test dependencies.
Neither the fetched revisions nor the success of the local patch application were recorded.
The pinned tap source preserves the build recipe and candidate patch.
These limits remain findings in the source index.
They do not establish a missing source obligation for these permissive libraries.

## Release and source retention

ANGLE uses BSD-3-Clause.
The listed embedded libraries use BSD, MIT, Apache-2.0, Zlib or the permissive glslang composite terms.
The generated Bison parser has GPL-3.0-or-later with Bison-exception-2.2.
That exception permits this larger work under chosen terms, so it does not require distributing ANGLE's source.
Its license and the exception in the generated headers are retained in the notices.
No unexcepted GPL or LGPL library was found in this ANGLE configuration.
ANGLE therefore has no corresponding-source distribution obligation and does not block release.
The collector attempts to retain the pinned ANGLE source and reference dependencies as best effort.
An unavailable reference is recorded in `optional_failures` and does not make the copyleft source archive incomplete.
QEMU, GLib, libintl and libusb remain required, including their source, patches and build inputs.
