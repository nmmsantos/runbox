"""Test the shell helper and linuxdeploy wrapper without Docker or sudo."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from support import BINARY, CommandArgument


class LinuxdeployTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="runbox-linuxdeploy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scratch = self.root / "pre-run scratch with 'quotes'"
        self.scratch.mkdir()
        self.binary = Path(os.environ.get("RUNBOX_TEST_BINARY", BINARY)).resolve()
        self.base = self.root / "tools with 'quotes' and [glob]"
        self.installation = self.base / "linuxdeploy"
        self.bin = self.installation
        self.private = self.installation / "_linuxdeploy"
        self.wrapper = self.bin / "linuxdeploy"
        self.destination = self.root / "bundle"
        self.activation = self.install()

    def run_command(
        self,
        *args: CommandArgument,
        environment: Mapping[str, str] | None = None,
        success: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            args,
            env=dict(
                os.environ,
                **{
                    "PATH": str(self.binary.parent) + os.pathsep + os.environ["PATH"],
                    "TMPDIR": str(self.scratch),
                    **(environment or {}),
                },
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def install(self) -> str:
        return self.run_command(
            self.binary,
            "helper",
            "linuxdeploy",
            self.base,
            environment={"RUNBOX_SCRIPT": "test"},
        ).stdout

    def deploy(
        self,
        *args: CommandArgument,
        environment: Mapping[str, str] | None = None,
        success: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            self.wrapper,
            "--appdir",
            self.destination,
            *args,
            environment=environment,
            success=success,
        )

    def recorder(self, status: int = 0) -> None:
        script = self.private / "linuxdeploy"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, shutil, sys\n"
            "print(json.dumps({'args': sys.argv[1:], 'path': os.environ['PATH'], "
            "'libraries': os.environ.get('LD_LIBRARY_PATH'), "
            "'strip': shutil.which('strip'), 'dpkg-query': shutil.which('dpkg-query'), "
            "'patchelf': shutil.which('patchelf')}))\n"
            f"sys.exit({status})\n"
        )

    def fixture(self) -> Path:
        source = self.root / "source"
        source.mkdir()
        for name, code, flags in (
            (
                "leaf.so",
                "int leaf(void) { return 42; }",
                ["-shared", "-fPIC", "-Wl,-soname,leaf.so"],
            ),
            (
                "middle.so",
                "extern int leaf(void); int middle(void) { return leaf(); }",
                ["-shared", "-fPIC", "-Wl,-soname,middle.so", "-l:leaf.so"],
            ),
            (
                "app",
                "extern int middle(void); int main(void) { return middle() != 42; }",
                ["-l:middle.so"],
            ),
        ):
            code_file = source / (name + ".c")
            code_file.write_text(code)
            self.run_command(
                "cc",
                "-g",
                code_file,
                "-o",
                source / name,
                "-L" + str(source),
                "-Wl,-rpath,$ORIGIN",
                *flags,
            )
        return source

    def test_activation_and_reuse(self):
        self.assertTrue(all(not any(path.iterdir()) for path in self.scratch.iterdir()))
        self.assertEqual(
            self.installation.stat().st_mode & 0o777, self.base.stat().st_mode & 0o777
        )
        before = (self.bin / "patchelf").stat().st_mtime_ns
        self.assertEqual(self.install(), self.activation)
        self.assertEqual((self.bin / "patchelf").stat().st_mtime_ns, before)
        self.assertEqual(self.wrapper.readlink(), self.binary)
        self.assertEqual(
            {path.name for path in self.installation.iterdir()},
            {"linuxdeploy", "patchelf", "_linuxdeploy"},
        )
        self.assertEqual(
            {path.name for path in self.private.iterdir()},
            {"linuxdeploy", "strip", "dpkg-query"},
        )
        self.assertNotIn(str(self.scratch), self.activation)
        subprocess.run(["sh", "-n"], input=self.activation, text=True, check=True)
        result = self.run_command(
            "sh",
            "-eu",
            "-c",
            self.activation
            + self.activation
            + '\ncommand -v linuxdeploy\ncommand -v patchelf\nprintf "%s\\n" "$PATH"',
        )
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], [str(self.wrapper), str(self.bin / "patchelf")])
        self.assertEqual(lines[2].split(":").count(str(self.bin)), 1)
        self.assertNotIn(str(self.private), lines[2].split(":"))

    def test_help_and_removed_bundle_command(self):
        result = self.run_command(self.wrapper, "--help")
        for option in (
            "--library-path",
            "--remove-empty-dirs",
            "--plugin",
            "--desktop-file",
        ):
            self.assertIn(option, result.stdout + result.stderr)
        self.run_command(self.binary, "bundle", success=False)
        result = self.run_command(
            self.binary,
            "helper",
            "linuxdeploy",
            environment={"RUNBOX_SCRIPT": "test"},
            success=False,
        )
        self.assertIn("<base-dir>", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_help_is_forwarded_and_extra_help_is_last(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = self.run_command(self.wrapper, flag)
                self.assertIn("linuxdeploy -- create AppDir", result.stderr)
                self.assertLess(
                    result.stderr.index("--plugin"),
                    result.stderr.index("--library-path"),
                )
                self.assertTrue(
                    result.stderr.endswith(
                        "Accept multiple paths per option; the shell expands globs\n"
                    )
                )

    def test_printed_helper_skips_pre_run(self):
        result = self.run_command(self.binary, "helper", "-p", "linuxdeploy")
        self.assertIn("activate_path()", result.stdout)
        self.assertIn("INSTALL_DIR='/tmp/runbox-linuxdeploy-XXXXXX'", result.stdout)
        self.assertNotIn("# runbox pre-run-output", result.stdout)
        self.assertNotIn("# runbox include", result.stdout)
        self.assertTrue(all(not any(path.iterdir()) for path in self.scratch.iterdir()))
        script = self.root / "printed-helper.sh"
        script.write_text(result.stdout)
        self.run_command("sh", "-n", script)
        # Printing must also work when a hook could not create its scratch files.
        other = self.run_command(
            self.binary,
            "helper",
            "-p",
            "linuxdeploy",
            environment={"TMPDIR": str(self.root / "missing-directory")},
        )
        self.assertEqual(other.stdout, result.stdout)

    def test_existing_shell_helper_composition(self):
        base = self.root / "java tools"
        (base / "java-temurin-test").mkdir(parents=True)
        result = self.run_command(
            self.binary,
            "helper",
            "java",
            base,
            "test",
            environment={"RUNBOX_SCRIPT": "test"},
        )
        self.assertIn("export JAVA_HOME=", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertTrue(all(not any(path.iterdir()) for path in self.scratch.iterdir()))

    def test_hook_supplies_current_runbox_without_path_lookup(self):
        base = self.root / "without runbox on path"
        self.run_command(
            self.binary,
            "helper",
            "linuxdeploy",
            base,
            environment={"RUNBOX_SCRIPT": "test", "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual((base / "linuxdeploy/linuxdeploy").readlink(), self.binary)
        self.assertTrue(all(not any(path.iterdir()) for path in self.scratch.iterdir()))

    def test_helper_validation(self):
        self.run_command(
            self.binary,
            "helper",
            "linuxdeploy",
            environment={"RUNBOX_SCRIPT": "test"},
            success=False,
        )
        self.run_command(
            self.binary,
            "helper",
            "linuxdeploy",
            self.base,
            environment={"RUNBOX_SCRIPT": ""},
            success=False,
        )
        self.run_command(
            self.binary,
            "helper",
            "linuxdeploy",
            "",
            environment={"RUNBOX_SCRIPT": "test"},
            success=False,
        )

    def test_path_lookup_dispatch_and_private_shims(self):
        self.recorder()
        result = self.run_command(
            "sh", "-eu", "-c", self.activation + "\nlinuxdeploy --version"
        )
        recorded = json.loads(result.stdout)
        self.assertEqual(recorded["args"], ["--version"])
        for name in ("strip", "dpkg-query"):
            self.assertEqual(recorded[name], str(self.private / name))
        self.assertEqual(recorded["patchelf"], str(self.bin / "patchelf"))
        self.run_command(self.private / "strip", "anything")
        self.run_command(self.private / "dpkg-query", "anything", success=False)

    def test_multi_inputs_and_forwarded_options(self):
        self.recorder()
        result = self.run_command(
            self.wrapper,
            "--appdir=output",
            "-e",
            "one",
            "two with spaces",
            "--library=lib-one",
            "lib-two",
            "-lthird",
            "fourth",
            "--executable=app-three",
            "app-four",
            "-d",
            "desktop-file",
            "--plugin",
            "qt",
            "--output=appimage",
            "--exclude-library",
            "lib*.so",
            "--deploy-deps-only",
            "staged",
            "--",
            "-L",
            "literal",
        )
        self.assertEqual(
            json.loads(result.stdout)["args"],
            [
                "--appdir",
                "output",
                "-e",
                "one",
                "-e",
                "two with spaces",
                "-l",
                "lib-one",
                "lib-two",
                "-l",
                "third",
                "fourth",
                "-e",
                "app-three",
                "app-four",
                "-d",
                "desktop-file",
                "--plugin",
                "qt",
                "--output=appimage",
                "--exclude-library",
                "lib*.so",
                "--deploy-deps-only",
                "staged",
                "--",
            ],
        )

    def test_library_paths(self):
        self.recorder()
        result = self.run_command(
            self.wrapper,
            "-L",
            "relative",
            "-L/attached",
            "--library-path=/equal",
            "--library-path",
            "/separate",
            "--version",
            environment={"LD_LIBRARY_PATH": "/inherited:/other"},
        )
        recorded = json.loads(result.stdout)
        self.assertEqual(recorded["args"], ["--version"])
        self.assertEqual(
            recorded["libraries"].split(":"),
            [
                str(Path("relative").absolute()),
                "/attached",
                "/equal",
                "/separate",
                "/inherited",
                "/other",
            ],
        )
        result = self.run_command(
            self.wrapper, "--version", environment={"LD_LIBRARY_PATH": ":/keep"}
        )
        self.assertEqual(json.loads(result.stdout)["libraries"], ":/keep")

    def test_multiple_library_paths_per_option(self):
        self.recorder()
        result = self.run_command(
            self.wrapper,
            "-L",
            "first",
            "second with spaces",
            "--library-path",
            "third",
            "fourth",
            "--version",
            environment={"LD_LIBRARY_PATH": "/inherited"},
        )
        recorded = json.loads(result.stdout)
        self.assertEqual(recorded["args"], ["--version"])
        self.assertEqual(
            recorded["libraries"].split(":"),
            [
                str(Path(name).absolute())
                for name in ("first", "second with spaces", "third", "fourth")
            ]
            + ["/inherited"],
        )

    def test_separator_is_forwarded_while_options_are_rewritten(self):
        self.recorder()
        result = self.run_command(
            self.wrapper,
            "--",
            "-e",
            "first",
            "second",
            "--",
            "-L",
            "libraries",
            "--plugin",
            "qt",
            environment={"LD_LIBRARY_PATH": "/inherited"},
        )
        recorded = json.loads(result.stdout)
        self.assertEqual(
            recorded["args"],
            [
                "--",
                "-e",
                "first",
                "-e",
                "second",
                "--",
                "--plugin",
                "qt",
            ],
        )
        self.assertEqual(
            recorded["libraries"], str(Path("libraries").absolute()) + ":/inherited"
        )

    def test_shell_globs_and_literal_globs(self):
        self.recorder()
        source = self.root / "inputs"
        source.mkdir()
        for name in ("lib-one.so", "lib-two.so"):
            (source / name).touch()
        result = self.run_command(
            "bash", "-c", '"$1" -e "$2"/*.so', "test", self.wrapper, source
        )
        self.assertEqual(
            json.loads(result.stdout)["args"],
            ["-e", str(source / "lib-one.so"), "-e", str(source / "lib-two.so")],
        )
        result = self.run_command(self.wrapper, "-e", "literal*.so")
        self.assertEqual(json.loads(result.stdout)["args"], ["-e", "literal*.so"])

    def test_non_utf8_arguments(self):
        self.recorder()
        name = os.fsdecode(b"file-\xff")
        result = self.run_command(self.wrapper, "-e", name, "second")
        self.assertEqual(
            json.loads(result.stdout)["args"], ["-e", name, "-e", "second"]
        )

    def test_missing_arguments(self):
        self.recorder()
        for args in (("-L",), ("-L", "--version"), ("--library-path=",)):
            with self.subTest(args=args):
                result = self.run_command(self.wrapper, *args, success=False)
                self.assertEqual(result.stdout, "")

    def test_upstream_argument_errors(self):
        for args in (
            ("--appdir",),
            ("-e",),
            ("-l", "--version"),
            ("--remove-empty-dirs",),
        ):
            with self.subTest(args=args):
                self.run_command(self.wrapper, *args, success=False)

    def test_cleanup_preserves_data_and_symlinks(self):
        self.recorder()
        empty = self.destination / "arbitrary/nested/empty"
        empty.mkdir(parents=True)
        for name in ("doc", "icons", "applications", "pixmaps"):
            directory = self.destination / "usr/share" / name
            directory.mkdir(parents=True)
            (directory / "keep").write_text("data")
        external = self.root / "external/empty"
        external.mkdir(parents=True)
        (self.destination / "linked").symlink_to(
            external.parent, target_is_directory=True
        )
        self.deploy()
        self.assertTrue(empty.is_dir())
        self.deploy("--remove-empty-dirs")
        self.assertFalse((self.destination / "arbitrary").exists())
        self.assertTrue(external.is_dir())
        self.assertTrue((self.destination / "linked").is_symlink())
        for path in self.destination.glob("usr/share/*/keep"):
            self.assertEqual(path.read_text(), "data")
        self.assertEqual(len(list(self.destination.glob("usr/share/*/keep"))), 4)

    def test_cleanup_preserves_root(self):
        self.recorder()
        (self.destination / "empty/nested").mkdir(parents=True)
        self.deploy("--remove-empty-dirs")
        self.assertTrue(self.destination.is_dir())
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_failed_deployment_skips_cleanup_and_preserves_status(self):
        self.recorder(status=23)
        empty = self.destination / "empty"
        empty.mkdir(parents=True)
        result = self.deploy("--remove-empty-dirs", success=False)
        self.assertEqual(result.returncode, 23)
        self.assertTrue(empty.is_dir())

    def test_help_skips_cleanup(self):
        self.recorder()
        empty = self.destination / "empty"
        empty.mkdir(parents=True)
        self.deploy("--remove-empty-dirs", "--help")
        self.assertTrue(empty.is_dir())

    def test_real_relocation_and_no_stripping(self):
        source = self.fixture()
        original = (source / "app").read_bytes()
        second = source / "app-two"
        shutil.copy2(source / "app", second)
        self.deploy("-L", source, "-e", source / "app", second, "--remove-empty-dirs")
        self.assertEqual((source / "app").read_bytes(), original)
        self.assertIn(b".debug_info", (self.destination / "usr/bin/app").read_bytes())
        self.assertFalse((self.destination / "usr/share").exists())
        for name in ("middle.so", "leaf.so"):
            self.assertTrue((self.destination / "usr/lib" / name).is_file())
        shutil.rmtree(source)
        moved = self.root / "moved"
        self.destination.rename(moved)
        for name in ("app", "app-two"):
            self.run_command(
                moved / "usr/bin" / name, environment={"LD_LIBRARY_PATH": ""}
            )
        self.run_command(self.bin / "patchelf", "--print-rpath", moved / "usr/bin/app")

    def test_real_multiple_libraries(self):
        source = self.fixture()
        self.deploy("-l", source / "middle.so", source / "leaf.so")
        for name in ("middle.so", "leaf.so"):
            self.assertTrue((self.destination / "usr/lib" / name).is_file())

    def test_real_staged_files_and_exclusion(self):
        source = self.fixture()
        staged = self.destination / "usr/lib/example/bin"
        staged.mkdir(parents=True)
        shutil.copy2(source / "app", staged / "app")
        script = staged / "script"
        script.write_text("#!/bin/sh\nprintf works")
        script.chmod(0o755)
        self.deploy(
            "-L", source, "--deploy-deps-only", staged, "--exclude-library", "leaf.so"
        )
        self.assertFalse((self.destination / "usr/lib/leaf.so").exists())
        self.deploy("-L", source, "--deploy-deps-only", staged)
        shutil.rmtree(source)
        self.run_command(staged / "app", environment={"LD_LIBRARY_PATH": ""})
        self.assertEqual(self.run_command(script).stdout, "works")

    def test_real_multiple_dependency_inputs(self):
        source = self.fixture()
        staged = self.destination / "usr/lib/example/bin"
        staged.mkdir(parents=True)
        first, second = staged / "first", staged / "second"
        shutil.copy2(source / "app", first)
        shutil.copy2(source / "app", second)
        self.deploy("-L", source, "--deploy-deps-only", first, second)
        shutil.rmtree(source)
        moved = self.root / "moved"
        self.destination.rename(moved)
        for name in ("first", "second"):
            self.run_command(
                moved / "usr/lib/example/bin" / name,
                environment={"LD_LIBRARY_PATH": ""},
            )

    def test_real_missing_library_fails(self):
        source = self.fixture()
        (source / "leaf.so").unlink()
        self.deploy("-e", source / "app", success=False)
