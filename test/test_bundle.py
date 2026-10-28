"""Exercise linuxdeploy bundling with real executables and shared libraries."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import BINARY, CommandArgument


class BundleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="runbox-bundle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.destination = self.root / "bundle"
        self.binary = str(BINARY)
        self.compile(
            "leaf.so",
            "int leaf(void) { return 42; }",
            "-shared",
            "-fPIC",
            "-Wl,-soname,leaf.so",
        )
        self.compile(
            "middle.so",
            "extern int leaf(void); int middle(void) { return leaf(); }",
            "-shared",
            "-fPIC",
            "-Wl,-soname,middle.so",
            "-l:leaf.so",
        )
        self.compile(
            "app",
            "extern int middle(void); int main(void) { return middle() != 42; }",
            "-l:middle.so",
        )

    def checked(self, *args: CommandArgument) -> str:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def compile(self, name: str, code: str, *flags: str) -> None:
        source = self.source / (name + ".c")
        source.write_text(code)
        self.checked(
            "cc",
            source,
            "-o",
            self.source / name,
            "-L" + str(self.source),
            "-Wl,-rpath,$ORIGIN",
            *flags,
        )

    def bundle(self, *options: CommandArgument, success: bool = True):
        result = subprocess.run(
            [self.binary, "bundle", str(self.destination), *map(str, options)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_relocation(self):
        original = (self.source / "app").read_bytes()
        self.bundle("-e", self.source / "app")
        self.assertEqual((self.source / "app").read_bytes(), original)
        self.assertTrue((self.destination / "usr/lib/leaf.so").is_file())
        self.assertTrue((self.destination / "usr/lib/middle.so").is_file())
        self.assertFalse((self.destination / "usr/share").exists())
        shutil.rmtree(self.source)
        moved = self.root / "moved"
        self.destination.rename(moved)
        self.checked(moved / "usr/bin/app")

    def test_library_as_executable(self):
        self.compile("plugin.so", "int plugin(void) { return 42; }", "-shared", "-fPIC")
        self.bundle("-e", self.source / "app", self.source / "plugin.so")
        self.assertTrue((self.destination / "usr/bin/plugin.so").is_file())
        self.assertFalse((self.destination / "usr/lib/plugin.so").exists())
        self.checked(self.destination / "usr/bin/app")

    def test_library_only(self):
        self.bundle("-l", self.source / "middle.so")
        self.assertTrue((self.destination / "usr/lib/middle.so").is_file())
        self.assertTrue((self.destination / "usr/lib/leaf.so").is_file())
        self.assertFalse((self.destination / "usr/share").exists())

    def test_non_elf_executables(self):
        script = self.source / "script"
        script.write_text("#!/bin/sh\nprintf 'works'\n")
        script.chmod(0o755)
        empty = self.source / "empty"
        empty.touch()
        for inputs in ((script, empty), (script, empty, self.source / "app")):
            with self.subTest(inputs=inputs):
                self.bundle("-e", *inputs)
                copied = self.destination / "usr/bin/script"
                self.assertEqual(copied.read_bytes(), script.read_bytes())
                self.assertEqual(copied.stat().st_mode & 0o777, 0o755)
                self.assertEqual(self.checked(copied), "works")
                self.assertEqual((self.destination / "usr/bin/empty").read_bytes(), b"")
                shutil.rmtree(self.destination)

    def test_file_globs(self):
        nested = self.source / "nested"
        nested.mkdir()
        (self.source / "app").rename(nested / "app")
        (self.source / "app.c").unlink()
        (nested / "deeper").mkdir()
        (nested / "deeper/not-an-elf").write_text("must not be deployed")
        self.bundle(
            "--library-path", self.source,
            "-e", nested / "*",
            "-l", self.source / "*.so",
        )
        self.checked(self.destination / "usr/bin/app")
        self.assertFalse((self.destination / "usr/bin/not-an-elf").exists())

    def test_glob_matching_files_and_directories(self):
        nested = self.source / "nested"
        nested.mkdir()
        (self.source / "app").rename(nested / "app")
        for source in self.source.glob("*.c"):
            source.unlink()
        self.bundle("--library-path", self.source, "-e", self.source / "*")
        for name in ("middle.so", "leaf.so"):
            self.assertTrue((self.destination / "usr/bin" / name).is_file())
        self.assertFalse((self.destination / "usr/bin/app").exists())

    def test_library_path(self):
        libraries = self.root / "libraries"
        libraries.mkdir()
        for name in ("leaf.so", "middle.so"):
            (self.source / name).rename(libraries / name)
        self.bundle("--library-path", libraries, "-e", self.source / "app")
        shutil.rmtree(libraries)
        self.checked(self.destination / "usr/bin/app")

    def test_excluded_library(self):
        self.bundle("--exclude-library", "leaf.so", "-e", self.source / "app")
        self.assertFalse((self.destination / "usr/lib/leaf.so").exists())
        self.assertTrue((self.destination / "usr/lib/middle.so").exists())

    def test_missing_library_fails(self):
        (self.source / "leaf.so").unlink()
        self.bundle("-e", self.source / "app", success=False)

    def test_invalid_inputs(self):
        self.bundle(success=False)
        self.bundle("-e", self.source / "missing*", success=False)
        empty = self.root / "empty"
        empty.mkdir()
        self.bundle("-e", empty, success=False)
        self.assertFalse(self.destination.exists())

    def test_nonempty_destination(self):
        self.destination.mkdir()
        marker = self.destination / "keep"
        marker.write_text("keep")
        self.bundle("-e", self.source / "app", success=False)
        self.assertEqual(marker.read_text(), "keep")

    def test_application(self):
        path = os.environ.get("RUNBOX_TEST_APPLICATION")
        if not path:
            self.skipTest("set RUNBOX_TEST_APPLICATION to test an installed application")
        source = Path(path).resolve()
        expected = self.checked(source, "--version")
        self.bundle("-e", source)
        self.assertEqual(
            self.checked(self.destination / "usr/bin" / source.name, "--version"),
            expected,
        )
