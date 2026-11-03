# ANGLE source audit

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

Both build scripts fetch ANGLE with `git fetch origin main` and `git checkout --force FETCH_HEAD`.
Neither sets `ANGLE_COMMIT` before writing it into `commit.txt`.
The bottle's `share/angle/commit.txt` contains only a newline.
The scripts also fetch moving revisions for Chromium build files, SPIRV-Tools, SPIRV-Headers, glslang, Vulkan-Headers, Vulkan-Loader and other dependencies.
ASTC encoder and VulkanMemoryAllocator commits come from ANGLE's moving main DEPS at build time.
They need not match the ANGLE checkout.
The patch application can fail and continue without patches.

The configuration enables Metal and Vulkan and disables OpenGL, SwiftShader, WebGPU, Abseil and Perfetto.
The target list is `libEGL libGLESv2 libGLESv1_CM install_angle`.
This identifies candidates for embedded code but does not establish the exact compiled third-party graph.
The bottle has no matching LICENSE or third-party collection.
A nearby ANGLE commit or a current LICENSE would not establish the shipped terms.

The remaining evidence needed is the exact ANGLE commit, every fetched dependency revision, whether the patches applied, and the generated GN/Ninja build graph or equivalent build logs.
With those, retain ANGLE's LICENSE and each compiled dependency's notices from its actual revision.
Until then ANGLE remains an enforced release blocker and complete source retention must fail closed.
