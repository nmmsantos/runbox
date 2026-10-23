"""Check expensive/failing build branches without replacing the user's image."""

import json
import os
import subprocess
import sys
from pathlib import Path

from support import BINARY, IMAGE, CommandArgument, DockerTest


class BuildCommandTests(DockerTest):
    def setUp(self) -> None:
        super().setUp()
        self.log = self.root / "docker.jsonl"
        self.docker = self.root / "docker"
        self.docker.write_text(
            "#!"
            + sys.executable
            + "\n"
            + """import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['image', 'inspect']:
    sys.exit(int(os.environ.get('FIXTURE_INSPECT_CODE', '0')))
if args[0] == 'build':
    pathlib.Path(os.environ['FIXTURE_DOCKERFILE']).write_text(sys.stdin.read())
    sys.exit(int(os.environ.get('FIXTURE_BUILD_CODE', '0')))
if args[0] == 'run':
    sys.exit(int(os.environ.get('FIXTURE_RUN_CODE', '0')))
"""
        )
        self.docker.chmod(0o755)

    def invoke(
        self,
        *options: CommandArgument,
        action: str = "run",
        expected: int = 0,
        **settings: str | None,
    ) -> subprocess.CompletedProcess[bytes]:
        env: dict[str, str | None] = dict(
            os.environ,
            PATH=f"{self.root}:/usr/local/bin:/usr/bin:/bin",
            RUNBOX_SCRIPT="fixture",
            XDG_RUNTIME_DIR=str(self.runtime),
            FIXTURE_LOG=str(self.log),
            FIXTURE_DOCKERFILE=str(self.root / "Dockerfile"),
        )
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("SUDO_UID", None)
        env.update(settings)
        environment = {key: value for key, value in env.items() if value is not None}
        arguments = [str(BINARY), action, "arch"]
        if action == "run":
            arguments += ["fixture", str(self.script)]
        result = subprocess.run(
            [*arguments, *options],
            env=environment,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        self.calls: list[list[str]] = [
            json.loads(line) for line in self.log.read_text().splitlines()
        ]
        return result

    def assert_build(
        self, uid: int | None = None, runtime: str | Path | None = None
    ) -> None:
        build = next(call for call in self.calls if call[0] == "build")
        for argument in ("--no-cache", "--pull", "--progress", "--network"):
            self.assertIn(argument, build)
        resolved_uid = os.getuid() if uid is None else uid
        self.assertEqual(
            build[build.index("-t") + 1], f"runbox-arch-{resolved_uid}:local"
        )
        run = next((call for call in self.calls if call[0] == "run"), None)
        if run is not None:
            self.assertIn(f"runbox-arch-{resolved_uid}:local", run)
        self.assertEqual(build[-1], "-")
        self.assertEqual(
            (self.root / "Dockerfile").read_bytes(),
            (Path(__file__).parents[1] / "images/arch/Dockerfile").read_bytes(),
        )
        self.assertIn("--build-arg", build)
        self.assertIn(f"my_uid={os.getuid() if uid is None else uid}", build)
        self.assertIn(
            f"xdg_runtime_dir={self.runtime if runtime is None else runtime}", build
        )

    def test_existing_image_reused_without_build(self):
        self.invoke()
        self.assertFalse(any(call[0] == "build" for call in self.calls))
        self.assertTrue(any(call[0] == "run" and IMAGE in call for call in self.calls))

    def test_missing_image_builds_embedded_dockerfile(self):
        self.invoke(FIXTURE_INSPECT_CODE="1")
        self.assert_build()

    def test_build_command_builds_without_inspection_or_container(self):
        self.invoke(action="build")
        self.assert_build()
        self.assertFalse(any(call[:2] == ["image", "inspect"] for call in self.calls))
        self.assertFalse(any(call[0] == "run" for call in self.calls))

    def test_failed_build_prevents_run(self):
        result = self.invoke(
            FIXTURE_INSPECT_CODE="1", FIXTURE_BUILD_CODE="17", expected=1
        )
        self.assertIn(b"image build failed", result.stderr)
        self.assertFalse(any(call[0] == "run" for call in self.calls))

    def test_docker_run_exit_status_preserved(self):
        self.invoke(FIXTURE_RUN_CODE="29", expected=29)

    def test_sudo_uid_selects_build_account(self):
        self.invoke(action="build", SUDO_UID="0")
        self.assert_build(uid=0)
        build = next(call for call in self.calls if call[0] == "build")
        self.assertIn("my_user=root", build)
        self.assertIn("my_gid=0", build)

    def test_runtime_fallback_uses_resolved_uid(self):
        self.invoke(action="build", SUDO_UID="0", XDG_RUNTIME_DIR=None)
        self.assert_build(uid=0, runtime="/run/user/0")

    def test_runtime_path_preserves_non_utf8_bytes(self):
        runtime = os.fsdecode(os.fsencode(self.runtime) + b"/runtime-\xff")
        self.invoke(action="build", XDG_RUNTIME_DIR=runtime)
        self.assert_build(runtime=runtime)

    def test_invalid_sudo_uid_fails_before_docker(self):
        for value in ("", "invalid", "-1", "4294967296"):
            env = dict(os.environ, SUDO_UID=value)
            result = subprocess.run(
                [str(BINARY), "run", "arch", "fixture", str(self.script)],
                env=env,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"SUDO_UID must be a valid UID", result.stderr)
            self.assertFalse(self.log.exists())

    def test_explicit_failed_build_returns_error(self):
        result = self.invoke(action="build", FIXTURE_BUILD_CODE="17", expected=1)
        self.assertIn(b"image build failed", result.stderr)
        self.assertFalse(any(call[0] == "run" for call in self.calls))
