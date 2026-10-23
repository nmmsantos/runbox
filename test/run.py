#!/usr/bin/env python3
"""Build, install, and exercise runbox on the host and inside real containers."""

import argparse
import atexit
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import BINARY, IMAGE, ROOT, SESSION, WORK, cleanup_containers, docker


def checked(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pattern", default="test_*.py", help="unittest discovery pattern"
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="use the already installed binary",
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    WORK.mkdir(exist_ok=True)
    checked("sudo", "-n", "true")
    checked("cargo", "fmt", "--check")
    checked("cargo", "clippy", "--", "-D", "warnings")
    if not args.no_build:
        checked("make", "dev")
        checked("sudo", "-n", "make", "install-dev")
    if not BINARY.is_file():
        raise SystemExit(f"{BINARY} is missing; run without --no-build")
    image = docker("image", "inspect", IMAGE, "--format", "{{.Id}}")
    if image.returncode:
        raise SystemExit(
            f"{IMAGE} must already be built; the suite does not replace your image"
        )
    for script in (ROOT / "helpers").glob("*.sh"):
        checked("sh", "-n", str(script))
    atexit.register(cleanup_containers)
    started = datetime.now(UTC)
    before = time.monotonic()
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "test"), pattern=args.pattern
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    cleanup_containers()
    remaining = (
        docker("ps", "-aq", "--filter", f"label=runbox.integration={SESSION}")
        .stdout.decode()
        .split()
    )
    summary: dict[str, object] = {
        "started_utc": started.isoformat(),
        "duration_seconds": round(time.monotonic() - before, 2),
        "tests_run": result.testsRun,
        "failures": [name.id() for name, _ in result.failures],
        "errors": [name.id() for name, _ in result.errors],
        "skipped": [(name.id(), reason) for name, reason in result.skipped],
        "expected_failures": [name.id() for name, _ in result.expectedFailures],
        "unexpected_successes": [name.id() for name in result.unexpectedSuccesses],
        "remaining_fixture_containers": remaining,
        "binary": str(BINARY),
        "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(),
        "image": IMAGE,
        "image_id": image.stdout.decode().strip(),
        "docker_version": docker("version", "--format", "{{.Server.Version}}")
        .stdout.decode()
        .strip(),
    }
    (WORK / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nMachine-readable results: {WORK / 'results.json'}", flush=True)
    return 0 if result.wasSuccessful() and not remaining else 1


if __name__ == "__main__":
    raise SystemExit(main())
