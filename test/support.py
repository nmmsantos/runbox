"""Shared setup for real Docker tests; no third-party Python dependencies."""

import json
import os
import pwd
import shutil
import subprocess
import tempfile
import unittest
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypedDict, Unpack

CommandArgument = str | os.PathLike[str]


class InvocationOptions(TypedDict, total=False):
    script: CommandArgument | None
    options: Sequence[CommandArgument]
    docker_args: Sequence[CommandArgument]
    arguments: Sequence[CommandArgument]
    environment: Mapping[str, str | None] | None
    separator: bool
    name: str


class ProbeInfo(TypedDict):
    arguments: list[str]
    script: str
    cwd: str
    marker: str | None
    binary: str | None
    uid: int
    runtime_dir: str | None
    hostname: str | None
    path: str | None
    mounts: str


ROOT = Path(__file__).resolve().parents[1]
BINARY = Path("/usr/local/bin/runbox")
USER_UID = int(os.environ.get("SUDO_UID", os.getuid()))
IMAGE = f"runbox-arch-{USER_UID}:local"
WORK = ROOT / "test" / ".work"
SESSION = os.environ.setdefault("RUNBOX_TEST_SESSION", uuid.uuid4().hex[:12])
LABEL = f"runbox.integration={SESSION}"
PROBE = ROOT / "test" / "fixtures" / "probe.py"


def docker(*arguments: CommandArgument) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", *map(str, arguments)], capture_output=True, check=False
    )


def cleanup_containers() -> None:
    result = docker("ps", "-aq", "--filter", f"label={LABEL}")
    ids = result.stdout.decode().split()
    if ids:
        docker("rm", "-f", *ids)


class DockerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(os.umask, os.umask(0o002))
        WORK.mkdir(exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix=self._testMethodName[:18] + "-", dir=WORK)
        )
        # share fixture writes with the container user when the suite runs as root
        if os.geteuid() == 0:
            os.chown(self.root, -1, pwd.getpwuid(USER_UID).pw_gid)
            self.root.chmod(0o2770)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        self.script = self.scripts / "probe.py"
        shutil.copyfile(PROBE, self.script)
        self.script.chmod(0o755)
        self.runtime = self.root / "host-runtime"
        self.runtime.mkdir()
        self.addCleanup(self.cleanup)

    def cleanup(self) -> None:
        cleanup_containers()
        try:
            shutil.rmtree(self.root)
        except PermissionError:
            subprocess.run(
                [
                    "chown",
                    "-R",
                    f"{os.getuid()}:{os.getgid()}",
                    str(self.root),
                ],
                check=True,
            )
            shutil.rmtree(self.root)

    def invocation(
        self,
        *,
        script: CommandArgument | None = None,
        options: Sequence[CommandArgument] = (),
        docker_args: Sequence[CommandArgument] = (),
        arguments: Sequence[CommandArgument] = (),
        environment: Mapping[str, str | None] | None = None,
        separator: bool = True,
        name: str = "test",
    ) -> list[str]:
        settings: dict[str, str | None] = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "SUDO_UID": str(USER_UID),
            "XDG_RUNTIME_DIR": str(self.runtime),
        }
        settings.update(environment or {})
        command = ["env", "-i"]
        command += [
            f"{key}={value}" for key, value in settings.items() if value is not None
        ]
        command += [
            str(BINARY),
            "run",
            "arch",
            name,
            str(script or self.script),
            *map(str, options),
        ]
        command += ["--label", LABEL, *map(str, docker_args)]
        if separator:
            command += [
                "--",
                *(
                    os.fspath(argument)
                    if isinstance(argument, os.PathLike)
                    else argument
                    for argument in arguments
                ),
            ]
        return command

    def run_script(
        self,
        code: str | None = None,
        *,
        expected: int = 0,
        timeout: float = 45,
        **kwargs: Unpack[InvocationOptions],
    ) -> subprocess.CompletedProcess[bytes]:
        if code is not None:
            kwargs["arguments"] = ["--exec", code, *kwargs.get("arguments", ())]
        result = subprocess.run(
            self.invocation(**kwargs), capture_output=True, timeout=timeout, check=False
        )
        self.assertEqual(
            result.returncode,
            expected,
            result.stderr.decode(errors="replace")
            + "\n"
            + result.stdout.decode(errors="replace"),
        )
        return result

    def info(self, **kwargs: Unpack[InvocationOptions]) -> ProbeInfo:
        return json.loads(self.run_script(**kwargs).stdout)

    def make_script(self, directory: Path, name: str = "probe.py") -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        shutil.copyfile(PROBE, path)
        path.chmod(0o755)
        return path
