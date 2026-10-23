import io
import json
import select
import subprocess
import tarfile
import textwrap
import zipfile
from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict

from support import CommandArgument, DockerTest


class HelperResult(TypedDict):
    code: int
    stdout: str
    stderr: str


class HelperTests(DockerTest):
    def helper(
        self,
        name: str,
        *arguments: CommandArgument,
        environment: Mapping[str, str] | None = None,
    ) -> HelperResult:
        code = f"""environment = dict(os.environ, **{environment or {}!r})
result = subprocess.run(['runbox', 'helper', {name!r}, *{list(map(str, arguments))!r}], env=environment, capture_output=True)
print(json.dumps({{'code': result.returncode, 'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()}}))
"""
        return json.loads(self.run_script(code).stdout)

    def stub(self, name: str, body: str) -> dict[str, str]:
        directory = self.scripts / "stubs"
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_text("#!/usr/bin/python3\n" + textwrap.dedent(body))
        path.chmod(0o755)
        return {"PATH": f"{directory}:/usr/local/bin:/usr/bin:/bin"}

    def test_installer_usage_and_no_output_on_failure(self):
        for name in ("java", "javafx", "uv", "wine", "wine-mono"):
            with self.subTest(helper=name):
                result = self.helper(name)
                self.assertEqual(result["code"], 1)
                self.assertIn("usage:", result["stderr"])
                self.assertEqual(result["stdout"], "")

    def test_cached_installers_and_activation_without_runtimes_dir(self):
        for name in ("java", "javafx", "uv", "wine"):
            with self.subTest(helper=name):
                dest = self.scripts / f"{name} runtime"
                dest.mkdir()
                args: list[CommandArgument] = (
                    [dest, "kron4ek", "amd64", "fixture"]
                    if name == "wine"
                    else [dest, "fixture"]
                )
                result = self.helper(
                    name, *args, environment=self.stub("curl", "raise SystemExit(99)\n")
                )
                self.assertEqual(result["code"], 0, result)
                self.assertEqual(result["stderr"], "")
                activation = result["stdout"]
                expression = {
                    "java": "$JAVA_HOME",
                    "javafx": "$JAVAFX_HOME",
                    "uv": "${PATH%%:*}",
                    "wine": "${PATH%%:*}",
                }[name]
                script = activation + '\nprintf "%s\\n" "' + expression + '"\n'
                code = f"print(subprocess.check_output(['sh', '-c', {script!r}], text=True), end='')"
                expected = str(dest / "bin") if name == "wine" else str(dest)
                self.assertEqual(
                    self.run_script(code).stdout.decode().strip(), expected
                )

    def test_activation_handles_shell_metacharacters_in_destination(self):
        for name in ("java", "javafx", "uv", "wine"):
            with self.subTest(helper=name):
                dest = self.scripts / (name + ' "quoted" $HOME `literal` single\' *')
                dest.mkdir()
                args: list[CommandArgument] = (
                    [dest, "kron4ek", "amd64", "fixture"]
                    if name == "wine"
                    else [dest, "fixture"]
                )
                result = self.helper(name, *args)
                self.assertEqual(result["code"], 0, result)
                expression = {
                    "java": "$JAVA_HOME",
                    "javafx": "$JAVAFX_HOME",
                    "uv": "${PATH%%:*}",
                    "wine": "${PATH%%:*}",
                }[name]
                script = result["stdout"] + '\nprintf "%s\\n" "' + expression + '"\n'
                code = f"print(subprocess.check_output(['sh', '-c', {script!r}], text=True), end='')"
                expected = str(dest / "bin") if name == "wine" else str(dest)
                self.assertEqual(
                    self.run_script(code).stdout.decode().strip(), expected
                )

    def test_wine_init_stdout_stderr_and_large_capture(self):
        env = self.stub(
            "winetricks",
            """
            import sys
            sys.stdout.write('x' * 1048576)
            sys.stderr.write('diagnostic\\n')
        """,
        )
        env["WINEPREFIX"] = str(self.scripts / "absent-prefix")
        env["WINEARCH"] = "win64"
        result = self.helper("wine-init", environment=env)
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["stdout"], "x" * 1048576)
        self.assertEqual(result["stderr"], "diagnostic\n")

    def test_wine_init_discards_failed_stdout_and_preserves_status(self):
        env = self.stub(
            "winetricks",
            """
            import sys
            print('partial output')
            print('diagnostic', file=sys.stderr)
            sys.exit(37)
        """,
        )
        env["WINEPREFIX"] = str(self.scripts / "absent-prefix")
        env["WINEARCH"] = "win64"
        result = self.helper("wine-init", environment=env)
        self.assertEqual(result, {"code": 37, "stdout": "", "stderr": "diagnostic\n"})

    def test_helper_signal_exit_status(self):
        env = self.stub(
            "winetricks",
            """
            import os, signal
            os.kill(os.getpid(), signal.SIGTERM)
        """,
        )
        env["WINEPREFIX"] = str(self.scripts / "absent-prefix")
        env["WINEARCH"] = "win64"
        result = self.helper("wine-init", environment=env)
        self.assertEqual(result["code"], 143, result)
        self.assertFalse(result["stdout"])

    def test_helper_stderr_streams_before_completion(self):
        env = self.stub(
            "winetricks",
            """
            import pathlib, sys, time
            print('progress-visible', file=sys.stderr, flush=True)
            while not pathlib.Path('gate').exists():
                time.sleep(0.05)
            print('completed')
        """,
        )
        env["WINEPREFIX"] = str(self.scripts / "absent-prefix")
        env["WINEARCH"] = "win64"
        code = f"subprocess.run(['runbox', 'helper', 'wine-init'], env=dict(os.environ, **{env!r}), check=True)"
        process = subprocess.Popen(
            self.invocation(arguments=["--exec", code]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        assert process.stderr is not None
        ready, _, _ = select.select([process.stderr], [], [], 30)
        self.assertTrue(ready, "stderr was not streamed")
        self.assertEqual(process.stderr.readline(), b"progress-visible\n")
        self.assertIsNone(process.poll())
        (self.scripts / "gate").touch()
        stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout, b"completed\n")

    def test_gamescope_arguments_preserve_quoting(self):
        data = self.scripts / "data"
        arguments = [
            "--option",
            "two words",
            "",
            "quote'arg",
            "$HOME",
            "$(touch SHOULD_NOT_EXIST)",
        ]
        result = self.helper("gamescope", data, *arguments)
        self.assertEqual(result["code"], 0, result)
        wrapper = data / "bin" / "gs"
        self.assertTrue(wrapper.stat().st_mode & 0o111)
        stub_dir = self.scripts / "stubs"
        self.stub("chown", "pass\n")
        self.stub(
            "setpriv",
            """
            import os, sys
            args = sys.argv[1:]
            position = args.index('gamescope')
            os.execvp('gamescope', ['gamescope', *args[position + 1:]])
        """,
        )
        self.stub(
            "gamescope",
            """
            import json, sys
            print(json.dumps(sys.argv[1:]))
        """,
        )
        env = {
            "GAMESCOPE_SESSION": "1",
            "MY_USER": "nuno",
            "SEATD_SOCK": "/fixture/socket",
            "PATH": f"{stub_dir}:/usr/bin:/bin",
        }
        code = f"result = subprocess.check_output([{str(wrapper)!r}, 'app argument'], env=dict(os.environ, **{env!r}), text=True); print(result, end='')"
        received = json.loads(self.run_script(code).stdout)
        self.assertEqual(
            received, ["--backend", "drm", *arguments, "--", "app argument"]
        )
        self.assertFalse((self.scripts / "SHOULD_NOT_EXIST").exists())

    def test_wine_mono_cached_and_invalid_arch(self):
        prefix = self.scripts / "prefix"
        (prefix / "drive_c/windows/mono").mkdir(parents=True)
        for arch in ("win32", "win64"):
            result = self.helper(
                "wine-mono",
                "9.4.0",
                environment={"WINEPREFIX": str(prefix), "WINEARCH": arch},
            )
            self.assertEqual(result, {"code": 0, "stdout": "", "stderr": ""})
        result = self.helper(
            "wine-mono",
            "9.4.0",
            environment={"WINEPREFIX": str(prefix), "WINEARCH": "unknown"},
        )
        self.assertEqual(result["code"], 1)
        self.assertIn("unknown WINEARCH", result["stderr"])

    def test_uv_real_download_install_activate_and_reuse(self):
        dest = self.scripts / "uv installed"
        result = self.helper("uv", dest, "0.9.7")
        self.assertEqual(result["code"], 0, result)
        self.assertTrue((dest / "uv").is_file())
        script = result["stdout"] + "\nexec uv --version\n"
        code = f"print(subprocess.check_output(['sh', '-c', {script!r}], text=True), end='')"
        self.assertEqual(self.run_script(code).stdout, b"uv 0.9.7\n")
        second = self.helper(
            "uv", dest, "0.9.7", environment=self.stub("curl", "raise SystemExit(99)\n")
        )
        self.assertEqual(second["code"], 0, second)
        self.assertEqual(second["stdout"], result["stdout"])

    def test_fresh_installers_unpack_validate_and_activate_local_payloads(self):
        archives = self.scripts / "archives"
        archives.mkdir()

        def tar_payload(
            filename: str,
            mode: Literal["w:gz", "w:xz"],
            prefix: str,
            executables: Sequence[str],
        ) -> str:
            path = archives / filename
            with tarfile.open(path, mode) as archive:
                for directory in (prefix, prefix + "/bin"):
                    entry = tarfile.TarInfo(directory)
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    archive.addfile(entry)
                for name in executables:
                    data = b'#!/bin/sh\nprintf "%s\\n" fixture-executable\n'
                    entry = tarfile.TarInfo(prefix + "/bin/" + name)
                    entry.mode = 0o755
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
            return str(path)

        java = tar_payload("java.tar.gz", "w:gz", "jdk-fixture", ("java", "javac"))
        wine = tar_payload("wine.tar.xz", "w:xz", "wine-fixture", ("wine",))
        proton = tar_payload("proton.tar.gz", "w:gz", "release/files", ("wine",))
        javafx = archives / "javafx.zip"
        with zipfile.ZipFile(javafx, "w") as archive:
            archive.writestr(
                "javafx-sdk-fixture/lib/javafx.controls.jar", b"fixture jar"
            )
        payloads = {"java": java, "wine": wine, "proton": proton, "javafx": str(javafx)}
        env = self.stub(
            "curl",
            f"""
            import pathlib, sys
            payloads = {payloads!r}
            url = next(arg for arg in sys.argv[1:] if arg.startswith('https://'))
            if 'winetricks' in url:
                data = b'#!/bin/sh\\nexit 0\\n'
            elif 'adoptium.net' in url:
                data = pathlib.Path(payloads['java']).read_bytes()
            elif 'openjfx' in url:
                data = pathlib.Path(payloads['javafx']).read_bytes()
            elif 'Kron4ek' in url:
                data = pathlib.Path(payloads['wine']).read_bytes()
            elif 'proton-ge-custom' in url:
                data = pathlib.Path(payloads['proton']).read_bytes()
            else:
                raise AssertionError(url)
            if '-o' in sys.argv:
                pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(data)
            else:
                sys.stdout.buffer.write(data)
        """,
        )
        cases = [
            ("java", ["fixture"], "bin/java"),
            ("javafx", ["fixture"], "lib/javafx.controls.jar"),
            ("wine", ["kron4ek", "amd64", "fixture"], "bin/wine"),
            ("wine", ["proton-ge", "amd64", "fixture"], "bin/wine"),
        ]
        for index, (name, args, required) in enumerate(cases):
            with self.subTest(helper=name, arguments=args):
                dest = self.scripts / f"installed-{index}"
                result = self.helper(name, dest, *args, environment=env)
                self.assertEqual(result["code"], 0, result)
                self.assertTrue((dest / required).is_file())
                self.assertIn(str(dest), result["stdout"])
                if name == "wine":
                    self.assertTrue((dest / "bin/winetricks").stat().st_mode & 0o111)

    def test_failed_download_never_emits_activation(self):
        env = self.stub(
            "curl",
            "import sys; print('fixture download failed', file=sys.stderr); sys.exit(22)\n",
        )
        for name in ("java", "javafx", "uv", "wine"):
            with self.subTest(helper=name):
                dest = self.scripts / ("failed-" + name)
                args: list[CommandArgument] = (
                    [dest, "kron4ek", "amd64", "fixture"]
                    if name == "wine"
                    else [dest, "fixture"]
                )
                result = self.helper(name, *args, environment=env)
                self.assertNotEqual(result["code"], 0, result)
                self.assertEqual(result["stdout"], "")
                self.assertIn("fixture download failed", result["stderr"])
                self.assertFalse(dest.exists())

    def test_wine_mono_fresh_install_uses_x86_and_removes_msi(self):
        env = self.stub(
            "curl",
            """
            import pathlib, sys
            url = next(arg for arg in sys.argv[1:] if arg.startswith('https://'))
            assert url.endswith('/wine-mono-9.4.0-x86.msi'), url
            pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(b'fixture MSI')
        """,
        )
        self.stub(
            "wine",
            """
            import os, pathlib, sys
            assert sys.argv[1:] == ['msiexec', '/i', 'C:\\\\mono.msi', '/q'], sys.argv
            prefix = pathlib.Path(os.environ['WINEPREFIX'])
            assert (prefix / 'drive_c/mono.msi').read_bytes() == b'fixture MSI'
            (prefix / 'drive_c/windows/mono').mkdir(parents=True)
        """,
        )
        for arch in ("win32", "win64"):
            prefix = self.scripts / ("prefix-" + arch)
            (prefix / "drive_c").mkdir(parents=True)
            result = self.helper(
                "wine-mono",
                "9.4.0",
                environment=dict(env, WINEARCH=arch, WINEPREFIX=str(prefix)),
            )
            self.assertEqual(result["code"], 0, result)
            self.assertTrue((prefix / "drive_c/windows/mono").is_dir())
            self.assertFalse((prefix / "drive_c/mono.msi").exists())
