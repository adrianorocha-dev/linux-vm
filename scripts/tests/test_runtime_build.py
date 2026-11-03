"""Runtime input integrity and checkout safety without compiling QEMU."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PINS = dict(re.findall(r"^(\w+)=([\w.]+)$", (ROOT / "runtime/source-pins.sh").read_text(), re.M))


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git(directory, *args):
    return run("git", "-C", str(directory), *args).stdout.strip()


class PatchedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.source = Path(cls.scratch.name) / "try-omarchy"
        reference = ROOT / ".deps/try-omarchy"
        if reference.is_dir():
            run("git", "clone", "--quiet", "--no-hardlinks", str(reference), str(cls.source))
        else:
            run("git", "clone", "--quiet", "--depth=1", "--branch", PINS["try_omarchy_tag"],
                "https://github.com/omacom/try-omarchy.git", str(cls.source))
        git(cls.source, "checkout", "--quiet", "--detach", PINS["try_omarchy_commit"])
        cls.diff = ROOT / "runtime/try-omarchy-v1.3.0.diff"
        git(cls.source, "apply", "--check", str(cls.diff))
        git(cls.source, "apply", str(cls.diff))

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_diff_applies_to_pinned_tag_and_pins_agree(self):
        self.assertEqual(git(self.source, "rev-parse", "v1.3.0^{commit}"), PINS["try_omarchy_commit"])
        builder = (self.source / "macos/build-qemu-gpu-runtime.sh").read_text()
        for key in ("qemu_commit", "keycodemap_commit"):
            self.assertRegex(builder, rf"(?m)^{key}={PINS[key]}$")
            self.assertNotRegex(builder, rf"(?m)^{key.removesuffix('_commit')}_sha256=")
        for script in ("build-app.sh", "build-runtime.sh"):
            self.assertIn('source "$root/runtime/source-pins.sh"', (ROOT / "scripts" / script).read_text())
        self.assertIn('pinned_git_source_archive "$qemu_url" "$qemu_commit"', builder)
        self.assertIn('pinned_git_source_archive "$keycodemap_url" "$keycodemap_commit"', builder)
        self.assertIn('pinned_git_source_archive https://github.com/qemu/qemu.git "$qemu_commit"',
                      (ROOT / "scripts/build-app.sh").read_text())
        git(self.source, "apply", "--check", "--reverse", str(self.diff))

    def test_git_objects_replace_untrusted_archives_and_work_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            upstream = work / "upstream"
            upstream.mkdir()
            git(upstream, "init", "--quiet")
            (upstream / "payload").write_text("pinned source\n")
            git(upstream, "add", ".")
            git(upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "fixture")
            commit = git(upstream, "rev-parse", "HEAD")
            archive = work / "source.tar.gz"
            archive.write_text("untrusted cache entry")
            helper = self.source / "macos/pinned-git-source.sh"
            command = ['bash', '-euo', 'pipefail', '-c',
                       'source "$1"; pinned_git_source_archive "$2" "$3" source "$4" "$5"',
                       'test', str(helper), str(upstream), commit, str(archive), str(work / "cache")]
            run(*command)
            self.assertEqual(run("tar", "-xOf", str(archive), "source/payload").stdout, "pinned source\n")
            shutil.rmtree(upstream)
            archive.write_text("another corrupt archive")
            run(*command)
            self.assertEqual(run("tar", "-xOf", str(archive), "source/payload").stdout, "pinned source\n")
            repository = work / "cache/git/source.git"
            blob = git(repository, "rev-parse", f"{commit}:payload")
            object_path = repository / "objects" / blob[:2] / blob[2:]
            object_path.chmod(0o644)
            object_path.write_bytes(b"corrupt object")
            self.assertNotEqual(run(*command, check=False).returncode, 0)


@unittest.skipUnless(shutil.which("xcrun") and Path("/opt/homebrew/bin/python3.14").exists(),
                     "bootstrap integration needs macOS build prerequisites")
class CheckoutSafetyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        (self.root / "scripts").mkdir()
        (self.root / "runtime").mkdir()
        shutil.copy(ROOT / "scripts/build-runtime.sh", self.root / "scripts")
        self.source = self.root / ".deps/try-omarchy"
        (self.source / "macos").mkdir(parents=True)
        (self.source / ".gitignore").write_text("macos/.build/\n")
        (self.source / "message").write_text("before\n")
        builder = self.source / "macos/build-qemu-gpu-runtime.sh"
        builder.write_text('''#!/bin/bash
set -euo pipefail
[[ ${FIXTURE_BUILD_SUCCESS:-} == 1 ]] || exit 23
qemu="$(dirname "$0")/.build/qemu-gpu-runtime/bin/qemu-system-aarch64"
mkdir -p "$(dirname "$qemu")"
cp /usr/bin/true "$qemu"
codesign --force --sign - --entitlements "$FIXTURE_ENTITLEMENTS" "$qemu"
''')
        builder.chmod(0o755)
        git(self.source, "init", "--quiet")
        git(self.source, "add", ".")
        git(self.source, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "fixture")
        commit = git(self.source, "rev-parse", "HEAD")
        git(self.source, "tag", "v1.3.0")
        (self.root / "runtime/source-pins.sh").write_text(f"try_omarchy_tag=v1.3.0\ntry_omarchy_commit={commit}\n")
        (self.source / "message").write_text("patched\n")
        (self.source / "new-file").write_text("new\n")
        git(self.source, "add", ".")
        diff = git(self.source, "diff", "--cached") + "\n"
        (self.root / "runtime/try-omarchy-v1.3.0.diff").write_text(diff)
        git(self.source, "reset", "--hard", "--quiet")
        self.env = dict(os.environ, LINUXVM_PYTHON="/opt/homebrew/bin/python3.14")

    def bootstrap(self):
        return run("bash", str(self.root / "scripts/build-runtime.sh"), env=self.env, check=False)

    def test_pristine_and_exact_patch_rerun_reach_builder(self):
        for _ in range(2):
            result = self.bootstrap()
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual((self.source / "message").read_text(), "patched\n")
        (self.source / "new-file").write_text("user edit\n")
        result = self.bootstrap()
        self.assertIn("unexpected changes", result.stderr)
        self.assertEqual((self.source / "new-file").read_text(), "user edit\n")

    def test_untracked_staged_and_unexpected_head_are_preserved(self):
        (self.source / "user-file").write_text("keep me\n")
        self.assertIn("unexpected changes", self.bootstrap().stderr)
        git(self.source, "add", "user-file")
        self.assertIn("staged changes", self.bootstrap().stderr)
        git(self.source, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "user change")
        self.assertIn("existing checkout was left alone", self.bootstrap().stderr)
        self.assertEqual((self.source / "user-file").read_text(), "keep me\n")

    def test_invalid_python_fails_before_checkout_changes(self):
        self.env["LINUXVM_PYTHON"] = "/no/such/python"
        self.assertIn("LINUXVM_PYTHON is not executable", self.bootstrap().stderr)
        self.assertEqual((self.source / "message").read_text(), "before\n")

    def test_signed_runtime_entitlement_check(self):
        import plistlib
        entitlements = self.root / "entitlements.plist"
        self.env.update(FIXTURE_BUILD_SUCCESS="1", FIXTURE_ENTITLEMENTS=str(entitlements))
        for enabled in (True, False):
            entitlements.write_bytes(plistlib.dumps({"com.apple.security.hypervisor": enabled}))
            result = self.bootstrap()
            if enabled:
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                self.assertIn("lost its hypervisor entitlement", result.stderr)
