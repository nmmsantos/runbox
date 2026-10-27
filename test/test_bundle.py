"""Exercise bundling with a real executable and two levels of shared libraries."""

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

    def bundle(self, *options: CommandArgument, success: bool = True) -> str:
        result = subprocess.run(
            [
                self.binary,
                "bundle",
                str(self.destination),
                *options,
                "--",
                str(self.source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result.stderr

    def copied(self, source: Path) -> Path:
        return self.destination / str(source).lstrip("/")

    def test_relocation(self):
        app = self.source / "app"
        original = app.read_bytes()
        interpreter = self.checked("patchelf", "--print-interpreter", app)
        (self.source / "data").write_text("payload")
        (self.source / "alias").symlink_to("data")
        app.chmod(0o555)
        self.bundle()
        self.assertEqual(app.read_bytes(), original)
        self.assertEqual(
            self.checked("patchelf", "--print-interpreter", self.copied(app)),
            interpreter,
        )
        self.assertFalse(self.copied(Path(interpreter.strip())).exists())
        self.assertFalse(self.copied(Path(interpreter.strip()).resolve()).exists())
        self.assertFalse(list(self.destination.rglob(Path(interpreter.strip()).name)))
        shutil.rmtree(self.source)
        moved = self.root / "moved"
        self.destination.rename(moved)
        self.destination = moved
        self.checked(self.copied(app))
        self.assertEqual(self.copied(self.source / "alias").read_text(), "payload")
        self.assertEqual(self.copied(app).stat().st_mode & 0o777, 0o555)
        for line in self.checked("ldd", self.copied(app)).splitlines():
            if " => /" in line and interpreter.strip() not in line:
                self.assertIn(str(moved), line)

    def test_libm_does_not_copy_loader(self):
        self.compile(
            "math-app", "int main(void) { return 0; }", "-Wl,--no-as-needed", "-lm"
        )
        app = self.source / "math-app"
        interpreter = self.checked("patchelf", "--print-interpreter", app).strip()
        self.checked(self.binary, "bundle", self.destination, "--", app)
        self.assertTrue(list(self.destination.rglob("libm.so.6")))
        self.assertFalse(list(self.destination.rglob(Path(interpreter).name)))
        shutil.rmtree(self.source)
        self.checked(self.copied(app))

    def test_excluded_libraries_are_still_discovered(self):
        self.checked(
            self.binary,
            "bundle",
            self.destination,
            "--exclude",
            self.source / "middle.so",
            "--",
            self.source / "app",
        )
        self.assertFalse(self.copied(self.source / "middle.so").exists())
        self.assertTrue(self.copied(self.source / "leaf.so").exists())
        paths = self.checked(
            "patchelf", "--print-rpath", self.copied(self.source / "app")
        )
        self.assertNotIn("$ORIGIN", paths.strip().split(":"))

    def test_directory_symlink_paths_and_exclusions(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        for source in self.source.glob("*.c"):
            source.unlink()
        self.checked(self.binary, "bundle", self.destination, "--", alias)
        self.assertTrue(self.copied(alias / "app").exists())
        self.assertFalse(self.copied(self.source / "app").exists())
        self.checked(self.copied(alias / "app"))
        shutil.rmtree(self.destination)
        self.checked(
            self.binary, "bundle", self.destination, "--exclude", alias, "--", alias
        )
        self.assertFalse(self.copied(alias).exists())
        self.assertFalse(self.copied(self.source / "app").exists())

    def test_parent_after_directory_symlink(self):
        nested = self.source / "nested"
        nested.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(nested, target_is_directory=True)
        self.checked(
            self.binary, "bundle", self.destination, "--", alias / ".." / "app"
        )
        self.checked(self.copied(self.source / "app"))

    def test_missing_library_fails(self):
        (self.source / "leaf.so").unlink()
        message = self.bundle("--exclude", "*leaf.so", success=False)
        self.assertIn("unresolved dependencies", message)
        self.assertFalse(self.destination.exists())

    def test_conflicting_dependency_of_cached_library_fails(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        (self.source / "leaf.so").rename(first / "leaf.so")
        shutil.copy2(first / "leaf.so", second / "leaf.so")
        shutil.copy2(self.source / "app", second / "app")
        self.checked("patchelf", "--remove-rpath", self.source / "middle.so")
        for app, leaf_dir in ((self.source / "app", first), (second / "app", second)):
            self.checked(
                "patchelf",
                "--force-rpath",
                "--set-rpath",
                f"{self.source}:{leaf_dir}",
                app,
            )

        result = subprocess.run(
            [
                self.binary,
                "bundle",
                str(self.destination),
                "--",
                str(self.source / "app"),
                str(second / "app"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting library paths", result.stderr)
        self.assertIn(str(first / "leaf.so"), result.stderr)
        self.assertIn(str(second / "leaf.so"), result.stderr)
        self.assertFalse(self.destination.exists())

    def test_dry_run(self):
        source = self.source / "app"
        original = source.read_bytes()
        plan = self.checked(
            self.binary, "bundle", self.destination, "--dry-run", "--", self.source
        )
        self.assertIn(": Copy", plan)
        self.assertIn("Patch {", plan)
        self.assertIn("$ORIGIN", plan)
        self.assertIn(str(self.copied(source)), plan)
        self.assertFalse(self.destination.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_dry_run_missing_library_prints_no_plan(self):
        (self.source / "leaf.so").unlink()
        result = subprocess.run(
            [
                self.binary,
                "bundle",
                str(self.destination),
                "--dry-run",
                "--",
                str(self.source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.destination.exists())

    def test_library_path(self):
        libraries = self.root / "libraries"
        libraries.mkdir()
        for name in ("leaf.so", "middle.so"):
            (self.source / name).rename(libraries / name)
        self.bundle("--library-path", str(libraries))
        shutil.rmtree(libraries)
        self.checked(self.copied(self.source / "app"))

    def test_absolute_dependency(self):
        self.compile("absolute.so", "int value(void) { return 0; }", "-shared", "-fPIC")
        self.compile(
            "absolute-app",
            "extern int value(void); int main(void) { return value(); }",
            str(self.source / "absolute.so"),
        )
        self.bundle()
        shutil.rmtree(self.source)
        self.checked(self.copied(self.source / "absolute-app"))

    def test_direct_dependency_paths(self):
        self.compile(
            "leaf.so",
            "int leaf(void) { return 42; }",
            "-shared",
            "-fPIC",
            "-nostdlib",
            "-Wl,-soname,leaf.so",
        )
        self.compile(
            "middle.so",
            "extern int leaf(void); int middle(void) { return leaf(); }",
            "-shared",
            "-fPIC",
            "-nostdlib",
            "-Wl,-soname,middle.so",
            "-l:leaf.so",
        )
        app = self.source / "app"
        middle_dir = self.root / "middle"
        leaf_dir = self.root / "leaf"
        middle_dir.mkdir()
        leaf_dir.mkdir()
        middle = middle_dir / "middle.so"
        leaf = leaf_dir / "leaf.so"
        (self.source / "middle.so").rename(middle)
        (self.source / "leaf.so").rename(leaf_dir / "leaf.so.1")
        leaf.symlink_to("leaf.so.1")
        self.checked("patchelf", "--set-rpath", "$ORIGIN/../leaf", middle)
        self.checked("patchelf", "--remove-rpath", leaf)
        self.checked("patchelf", "--set-rpath", "$ORIGIN/../middle", app)

        self.checked(
            self.binary,
            "bundle",
            self.destination,
            "--",
            self.source / ".." / "source" / "app",
        )
        self.assertTrue(self.copied(leaf).exists())
        self.assertFalse(self.copied(leaf_dir / "leaf.so.1").exists())

        app_paths = (
            self.checked("patchelf", "--print-rpath", self.copied(app))
            .strip()
            .split(":")
        )
        self.assertIn("$ORIGIN/../middle", app_paths)
        self.assertNotIn("$ORIGIN/../leaf", app_paths)
        self.assertEqual(
            self.checked("patchelf", "--print-rpath", self.copied(middle)).strip(),
            "$ORIGIN/../leaf",
        )
        self.assertEqual(
            self.checked("patchelf", "--print-rpath", self.copied(leaf)).strip(), ""
        )

        shutil.rmtree(self.source)
        shutil.rmtree(middle_dir)
        shutil.rmtree(leaf_dir)
        self.checked(self.copied(app))

    def test_application(self):
        path = os.environ.get("RUNBOX_TEST_APPLICATION")
        if not path:
            self.skipTest(
                "set RUNBOX_TEST_APPLICATION to test an installed application"
            )
        source = Path(path).resolve()
        expected = self.checked(source, "--version")
        interpreter = self.checked("patchelf", "--print-interpreter", source)
        self.checked(self.binary, "bundle", self.destination, "--", source)
        copied = self.copied(source)
        self.assertEqual(self.checked(copied, "--version"), expected)
        self.assertEqual(
            self.checked("patchelf", "--print-interpreter", copied), interpreter
        )
        for line in self.checked("ldd", copied).splitlines():
            if " => /" in line and interpreter.strip() not in line:
                self.assertIn(str(self.destination), line)
