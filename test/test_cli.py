import os
import subprocess
from collections.abc import Mapping

from support import BINARY, CommandArgument, DockerTest


class CliTests(DockerTest):
    def cli(
        self,
        *arguments: CommandArgument,
        environment: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        env = dict(os.environ)
        env.pop("RUNBOX_SCRIPT", None)
        env.update(environment or {})
        return subprocess.run(
            [str(BINARY), *map(str, arguments)],
            env=env,
            capture_output=True,
            check=False,
        )

    def test_help_and_version(self):
        cases: list[tuple[CommandArgument, ...]] = [
            ("--help",),
            ("build", "--help"),
            ("help", "build"),
            ("run", "--help"),
            ("helper", "--help"),
            ("help", "run"),
            ("help", "helper"),
            ("--version",),
        ]
        for args in cases:
            with self.subTest(arguments=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout)
                self.assertFalse(result.stderr)
        help_text = self.cli("run", "--help").stdout
        self.assertNotIn(b"--rebuild", help_text)
        for term in (
            b"IMAGE_NAME",
            b"CONTAINER_NAME",
            b"DOCKER_ARGUMENTS",
            b"SCRIPT_ARGUMENTS",
            b"--path",
            b"repeatable",
        ):
            self.assertIn(term, help_text)

    def test_unknown_image_and_helper(self):
        cases: list[tuple[CommandArgument, ...]] = [
            ("build", "unknown"),
            ("run", "unknown", "test", self.script),
            ("helper", "unknown"),
        ]
        for args in cases:
            result = self.cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"possible values", result.stderr)

    def test_helper_requires_nonempty_marker(self):
        cases: list[tuple[str, ...]] = [(), ("--", "--help")]
        for value in (None, ""):
            env = {} if value is None else {"RUNBOX_SCRIPT": value}
            for arguments in cases:
                result = self.cli("helper", "java", *arguments, environment=env)
                self.assertEqual(result.returncode, 1)
                self.assertIn(b"helpers must run inside", result.stderr)
                self.assertFalse(result.stdout)

    def test_missing_or_nonexecutable_script(self):
        result = self.cli("run", "arch", "test", self.root / "missing")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"resolve script", result.stderr)
        self.script.chmod(0o644)
        result = self.cli("run", "arch", "test", self.script)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"script is not executable", result.stderr)

    def test_missing_path_value(self):
        for option in ("--path", "--ro-path"):
            result = self.cli("run", "arch", "test", self.script, option)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"a value is required", result.stderr)

    def test_literal_helper_help_is_forwarded(self):
        result = self.cli(
            "helper", "java", "--", "--help", environment={"RUNBOX_SCRIPT": "1"}
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"usage: java <destination> <version>", result.stderr)
        self.assertFalse(result.stdout)
