import json

from support import BINARY, LABEL, DockerTest


class NestedTests(DockerTest):
    def test_nested_binary_and_paths_align_with_host(self):
        child = self.make_script(self.root / "child scripts")
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "input").write_text("host input")
        code = f"""child = {str(child)!r}
shared = {str(shared)!r}
args = ['sudo', '-E', 'runbox', 'run', 'arch', 'nested', child, '--path', shared, '--label', {LABEL!r}, '--', 'two words', '']
result = subprocess.run(args, capture_output=True, text=True)
assert result.returncode == 0, result.stderr
info = json.loads(result.stdout)
assert info['binary'] == '/usr/local/bin/runbox', info
assert info['marker'] == child, info
assert info['cwd'] == str(Path(child).parent), info
assert info['arguments'] == ['two words', ''], info
print(json.dumps(info))
"""
        info = json.loads(self.run_script(code, options=["--path", self.root]).stdout)
        self.assertEqual(info["script"], str(child))

    def test_nested_child_writes_host_files_and_runs_helpers(self):
        child = self.make_script(self.root / "child")
        shared = self.root / "shared"
        shared.mkdir()
        dest = shared / "uv runtime"
        installed = dest / "uv-fixture"
        installed.mkdir(parents=True)
        child_code = f"""assert Path({str(shared / "input")!r}).read_text() == 'host'
Path({str(shared / "output")!r}).write_text('child')
result = subprocess.run(['runbox', 'helper', 'uv', {str(dest)!r}, 'fixture'], capture_output=True, text=True)
assert result.returncode == 0, result.stderr
assert {str(installed)!r} in result.stdout
print('nested-helper-ok')
"""
        (shared / "input").write_text("host")
        command = [
            "sudo",
            "-E",
            str(BINARY),
            "run",
            "arch",
            "nested-helper",
            str(child),
            "--path",
            str(shared),
            "--label",
            LABEL,
            "--",
            "--exec",
            child_code,
        ]
        code = f"result = subprocess.run({command!r}, capture_output=True); assert result.returncode == 0, result.stderr; sys.stdout.buffer.write(result.stdout)"
        self.assertEqual(
            self.run_script(code, options=["--path", self.root]).stdout,
            b"nested-helper-ok\n",
        )
        self.assertEqual((shared / "output").read_text(), "child")

    def test_parent_mount_is_not_implicitly_inherited(self):
        child = self.make_script(self.root / "child")
        secret = self.root / "parent-only"
        secret.mkdir()
        (secret / "secret").write_text("private to parent")
        child_code = (
            f"assert not Path({str(secret / 'secret')!r}).exists(); print('isolated')"
        )
        command = [
            "sudo",
            "-E",
            str(BINARY),
            "run",
            "arch",
            "isolated",
            str(child),
            "--label",
            LABEL,
            "--",
            "--exec",
            child_code,
        ]
        code = f"assert Path({str(secret / 'secret')!r}).exists(); result = subprocess.run({command!r}, capture_output=True); assert result.returncode == 0, result.stderr; sys.stdout.buffer.write(result.stdout)"
        self.assertEqual(
            self.run_script(code, options=["--path", self.root]).stdout, b"isolated\n"
        )

    def test_sudo_helper_preserves_marker_when_requested(self):
        dest = self.scripts / "cached"
        installed = dest / "uv-fixture"
        installed.mkdir(parents=True)
        code = f"result = subprocess.run(['sudo', '-E', 'runbox', 'helper', 'uv', {str(dest)!r}, 'fixture'], capture_output=True); assert result.returncode == 0, result.stderr; sys.stdout.buffer.write(result.stdout)"
        self.assertIn(str(installed).encode(), self.run_script(code).stdout)
