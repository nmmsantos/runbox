import socket
import subprocess
from pathlib import Path
from typing import Unpack

from support import BINARY, LABEL, DockerTest, InvocationOptions


class RuntimeTests(DockerTest):
    def run_script(
        self,
        code: str | None = None,
        *,
        expected: int = 0,
        timeout: float = 45,
        **kwargs: Unpack[InvocationOptions],
    ) -> subprocess.CompletedProcess[bytes]:
        kwargs["docker_args"] = [
            *kwargs.get("docker_args", ()),
            "-e",
            f"XDG_RUNTIME_DIR={self.runtime}",
        ]
        return super().run_script(code, expected=expected, timeout=timeout, **kwargs)

    def listen(self, path: Path) -> socket.socket:
        path.parent.mkdir(exist_ok=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
        listener.listen(4)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        return listener

    def test_host_runtime_sockets_keep_identical_paths(self):
        wayland = self.listen(self.runtime / "wayland-fixture")
        pulse = self.listen(self.runtime / "pulse" / "native")
        code = f"""import socket
assert os.environ['XDG_RUNTIME_DIR'] == {str(self.runtime)!r}
assert os.environ['WAYLAND_DISPLAY'] == 'wayland-fixture'
for path in ({str(self.runtime / "wayland-fixture")!r}, {str(self.runtime / "pulse/native")!r}):
    client = socket.socket(socket.AF_UNIX)
    client.connect(path)
    client.sendall(b'container-to-host')
    client.close()
print('connected')
"""
        result = self.run_script(
            code, environment={"WAYLAND_DISPLAY": "wayland-fixture"}
        )
        self.assertEqual(result.stdout, b"connected\n")
        for listener in (wayland, pulse):
            connection, _ = listener.accept()
            with connection:
                self.assertEqual(connection.recv(100), b"container-to-host")

    def test_wayland_selection_prefers_explicit_display_then_sorted_fallback(self):
        self.listen(self.runtime / "wayland-2")
        self.listen(self.runtime / "wayland-1")
        for value, expected in [("wayland-2", "wayland-2"), ("missing", "wayland-1")]:
            result = self.run_script(
                "print(os.environ['WAYLAND_DISPLAY'])",
                environment={"WAYLAND_DISPLAY": value},
            )
            self.assertEqual(result.stdout.decode().strip(), expected)

    def test_absolute_wayland_display(self):
        path = self.scripts / "custom-wayland"
        self.listen(path)
        result = self.run_script(
            f"print(os.environ['WAYLAND_DISPLAY']); assert Path({str(path)!r}).is_socket()",
            environment={"WAYLAND_DISPLAY": str(path)},
        )
        self.assertEqual(result.stdout.decode().strip(), str(path))

    def test_nested_runtime_socket_alignment(self):
        wayland = self.listen(self.runtime / "wayland-fixture")
        pulse = self.listen(self.runtime / "pulse" / "native")
        child = self.make_script(self.root / "child")
        child_code = f"""import socket
for path in ({str(self.runtime / "wayland-fixture")!r}, {str(self.runtime / "pulse/native")!r}):
    client = socket.socket(socket.AF_UNIX)
    client.connect(path)
    client.sendall(b'nested-to-host')
    client.close()
print('nested-runtime-ok')
"""
        command = [
            "sudo",
            "-E",
            str(BINARY),
            "run",
            "arch",
            "nested-runtime",
            str(child),
            "--label",
            LABEL,
            "-e",
            f"XDG_RUNTIME_DIR={self.runtime}",
            "--",
            "--exec",
            child_code,
        ]
        code = f"result = subprocess.run({command!r}, capture_output=True); assert result.returncode == 0, result.stderr; sys.stdout.buffer.write(result.stdout)"
        result = self.run_script(
            code,
            options=["--path", self.root],
            environment={"WAYLAND_DISPLAY": "wayland-fixture"},
        )
        self.assertEqual(result.stdout, b"nested-runtime-ok\n")
        for listener in (wayland, pulse):
            connection, _ = listener.accept()
            with connection:
                self.assertEqual(connection.recv(100), b"nested-to-host")

    def test_session_mounts_need_no_source_metadata(self):
        self.listen(self.runtime / "wayland-fixture")
        self.listen(self.runtime / "pulse" / "native")
        code = f"assert Path({str(self.runtime / 'wayland-fixture')!r}).is_socket(); assert Path({str(self.runtime / 'pulse/native')!r}).is_socket(); assert not any(key.endswith('_SOURCE') and key.startswith('RUNBOX_') for key in os.environ)"
        self.run_script(code, environment={"WAYLAND_DISPLAY": "wayland-fixture"})
