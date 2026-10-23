import json
import os
import subprocess
import time

from support import BINARY, IMAGE, LABEL, DockerTest, docker


class ContainerTests(DockerTest):
    def test_installed_binary_paths_and_environment(self):
        info = self.info()
        self.assertEqual(info["cwd"], str(self.scripts))
        self.assertEqual(info["script"], str(self.script))
        self.assertEqual(info["marker"], str(self.script))
        self.assertEqual(info["binary"], str(BINARY))
        self.assertEqual(info["uid"], 1000)
        self.assertEqual(info["runtime_dir"], "/run/user/1000")
        self.assertIn(" /usr/local/bin/runbox ro,", info["mounts"])
        image_env = json.loads(
            docker("image", "inspect", IMAGE, "--format", "{{json .Config.Env}}").stdout
        )
        self.assertEqual(
            info["path"],
            next(item[5:] for item in image_env if item.startswith("PATH=")),
        )
        result = self.run_script(
            "print(subprocess.check_output(['runbox', '--version'], text=True).strip())"
        )
        self.assertIn(b"runbox 1.0.0", result.stdout)

    def test_script_arguments_are_unchanged(self):
        arguments = [
            "",
            "two words",
            "-h",
            "--help",
            "--path",
            "--rebuild",
            "--",
            "$HOME",
            "$(touch unwanted)",
            "single'quote",
            'double"quote',
            "*.sh",
            "line\nbreak",
            "café",
        ]
        self.assertEqual(self.info(arguments=arguments)["arguments"], arguments)
        self.assertFalse((self.scripts / "unwanted").exists())

    def test_docker_arguments_and_script_separator(self):
        info = self.info(
            docker_args=["--env", "FIXTURE_VALUE=two words"],
            arguments=["--env", "literal"],
        )
        self.assertEqual(info["arguments"], ["--env", "literal"])
        result = self.run_script(
            "print(os.environ['FIXTURE_VALUE'])",
            docker_args=["--env", "FIXTURE_VALUE=two words"],
        )
        self.assertEqual(result.stdout, b"two words\n")

    def test_no_separator_means_no_script_arguments(self):
        info = self.info(separator=False, docker_args=["--env", "FIXTURE_VALUE=works"])
        self.assertEqual(info["arguments"], [])

    def test_canonical_script_symlink(self):
        symlink = self.root / "alias.py"
        symlink.symlink_to(self.script)
        info = self.info(script=symlink)
        self.assertEqual(info["script"], str(self.script))
        self.assertEqual(info["marker"], str(self.script))
        self.assertEqual(info["cwd"], str(self.scripts))

    def test_script_directory_is_writable(self):
        self.run_script("Path('from-container').write_text('aligned')")
        self.assertEqual((self.scripts / "from-container").read_text(), "aligned")

    def test_binary_is_readonly(self):
        result = self.run_script(
            """try:
    with open('/usr/local/bin/runbox', 'ab') as file:
        file.write(b'bad')
except OSError as error:
    print(error.errno)
else:
    raise AssertionError('binary writable')
""",
            docker_args=["--user", "0"],
        )
        self.assertEqual(result.stdout.strip(), b"30")

    def test_repeated_paths_readwrite_and_readonly(self):
        writable = self.root / "writable"
        writable.mkdir()
        readonly = self.root / "readonly"
        readonly.mkdir()
        (readonly / "input").write_text("read-only input")
        another = self.root / "another"
        another.mkdir()
        code = """writable, readonly, another = map(Path, sys.argv[3:])
(writable / 'output').write_text('written')
(another / 'output').write_text('also written')
assert (readonly / 'input').read_text() == 'read-only input'
try:
    (readonly / 'output').write_text('bad')
except OSError as error:
    assert error.errno == 30, error
else:
    raise AssertionError('read-only mount accepted a write')
print('ok')
"""
        result = self.run_script(
            code,
            options=["--path", writable, "--path", another, "--ro-path", readonly],
            arguments=[writable, readonly, another],
            docker_args=["--user", "0"],
        )
        self.assertEqual(result.stdout, b"ok\n")
        self.assertEqual((writable / "output").read_text(), "written")
        self.assertFalse((readonly / "output").exists())

    def test_nested_mount_order_and_readonly_subdirectory(self):
        parent = self.root / "tree"
        child = parent / "readonly"
        child.mkdir(parents=True)
        code = """parent, child = map(Path, sys.argv[3:])
(parent / 'writable').touch()
assert os.statvfs(parent).f_flag & os.ST_RDONLY == 0
assert os.statvfs(child).f_flag & os.ST_RDONLY
print('ok')
"""
        self.assertEqual(
            self.run_script(
                code,
                options=["--ro-path", child, "--path", parent],
                arguments=[parent, child],
            ).stdout,
            b"ok\n",
        )

    def test_bind_file_and_symlink_deduplication(self):
        file = self.root / "file"
        file.write_text("same file")
        link = self.root / "link"
        link.symlink_to(file)
        code = "print(Path(sys.argv[3]).read_text())"
        result = self.run_script(
            code, options=["--ro-path", file, "--ro-path", link], arguments=[file]
        )
        self.assertEqual(result.stdout, b"same file\n")

    def test_paths_with_spaces_commas_quotes_unicode_and_newlines(self):
        for name in ("two words", "a,b", 'a"b', "a'b", "café", "line\nbreak"):
            with self.subTest(name=name):
                path = self.root / name
                path.mkdir()
                result = self.run_script(
                    "print(Path(sys.argv[3]).is_dir())",
                    options=["--ro-path", path],
                    arguments=[path],
                )
                self.assertEqual(result.stdout, b"True\n")

    def test_script_path_with_commas_and_quotes(self):
        script = self.make_script(self.root / 'script dir,"quoted', "script name.py")
        info = self.info(script=script, arguments=["literal"])
        self.assertEqual(info["cwd"], str(script.parent))
        self.assertEqual(info["marker"], str(script))
        self.assertEqual(info["arguments"], ["literal"])

    def test_mount_conflict_and_missing_source(self):
        result = self.run_script(
            options=["--path", self.root, "--ro-path", self.root], expected=1
        )
        self.assertIn(b"conflicting mount permissions", result.stderr)
        result = self.run_script(options=["--path", self.root / "missing"], expected=1)
        self.assertIn(b"resolve bind mount path", result.stderr)

    def test_docker_name_override_is_rejected(self):
        for args in (["--name", "override"], ["--name=override"]):
            result = self.run_script(docker_args=args, expected=1)
            self.assertIn(b"use the mandatory CONTAINER_NAME", result.stderr)
        self.assertEqual(
            self.info(arguments=["--name", "literal"])["arguments"],
            ["--name", "literal"],
        )

    def test_script_exit_code_and_stderr(self):
        result = self.run_script(
            "print('stdout'); print('stderr', file=sys.stderr); sys.exit(23)",
            expected=23,
        )
        self.assertEqual(result.stdout, b"stdout\n")
        self.assertEqual(result.stderr, b"stderr\n")

    def test_parallel_instances_have_unique_names_and_remove_themselves(self):
        ready = self.scripts / "ready"
        gate = self.scripts / "gate"
        ready.mkdir()
        code = """import time
(Path('ready') / str(os.getpid())).touch()
while not Path('gate').exists():
    time.sleep(0.05)
print('finished')
"""
        processes = [
            subprocess.Popen(
                self.invocation(arguments=["--exec", code], name="parallel"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        self.addCleanup(lambda: [p.kill() for p in processes if p.poll() is None])
        names: list[str] = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            names = (
                docker("ps", "--filter", f"label={LABEL}", "--format", "{{.Names}}")
                .stdout.decode()
                .split()
            )
            if len(names) == 2 and all(p.poll() is None for p in processes):
                break
            time.sleep(0.1)
        self.assertEqual(len(names), 2, names)
        self.assertEqual(len(set(names)), 2)
        for name in names:
            self.assertRegex(name, r"^runbox-parallel-[a-z0-9]{6}$")
        gate.touch()
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout, b"finished\n")
        self.assertFalse(
            docker("ps", "-aq", "--filter", f"label={LABEL}").stdout.strip()
        )

    def test_stop_one_instance_preserves_another_and_exit_status(self):
        code = """import signal, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(42))
Path(sys.argv[3]).touch()
while not Path('finish').exists():
    time.sleep(0.05)
print('finished')
"""
        processes = [
            subprocess.Popen(
                self.invocation(
                    arguments=["--exec", code, f"ready-{i}"], name=f"signal-{i}"
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for i in range(2)
        ]
        self.addCleanup(lambda: [p.kill() for p in processes if p.poll() is None])
        deadline = time.monotonic() + 30
        while (
            not all((self.scripts / f"ready-{i}").exists() for i in range(2))
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        self.assertTrue(all((self.scripts / f"ready-{i}").exists() for i in range(2)))
        names = (
            docker("ps", "--filter", f"label={LABEL}", "--format", "{{.Names}}")
            .stdout.decode()
            .split()
        )
        target = next(name for name in names if name.startswith("runbox-signal-0-"))
        stopped = docker("stop", "--timeout", "5", target)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        stdout, stderr = processes[0].communicate(timeout=20)
        self.assertEqual(processes[0].returncode, 42, stderr)
        self.assertIsNone(processes[1].poll())
        (self.scripts / "finish").touch()
        stdout, stderr = processes[1].communicate(timeout=20)
        self.assertEqual(processes[1].returncode, 0, stderr)
        self.assertEqual(stdout, b"finished\n")

    def test_script_reentry_guard_from_host(self):
        script = self.scripts / "reentry.sh"
        script.write_text(
            """#!/bin/sh
set -eu
ME="$(readlink -f "$0")"
if [ "${RUNBOX_SCRIPT:-}" != "$ME" ]; then
    exec runbox run arch reentry "$ME" --label """
            + repr(LABEL)
            + """ -- "$@"
fi
printf '%s\\n' "$RUNBOX_SCRIPT" "$@"
"""
        )
        script.chmod(0o755)
        command = [
            "sudo",
            "-n",
            "env",
            "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            f"SUDO_UID={os.environ.get('SUDO_UID', os.getuid())}",
            f"XDG_RUNTIME_DIR={self.runtime}",
            str(script),
            "two words",
            "",
        ]
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (str(script) + "\ntwo words\n\n").encode())
