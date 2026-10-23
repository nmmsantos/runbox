#!/usr/bin/python3
"""Inspect paths and arguments from inside a real runbox container."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if len(sys.argv) > 1 and sys.argv[1] == "--exec":
    exec(sys.argv[2], dict(globals(), subprocess=subprocess))  # noqa: S102
    raise SystemExit(0)

print(
    json.dumps(
        {
            "arguments": sys.argv[1:],
            "script": str(Path(__file__).resolve()),
            "cwd": os.getcwd(),
            "marker": os.environ.get("RUNBOX_SCRIPT"),
            "binary": shutil.which("runbox"),
            "uid": os.getuid(),
            "runtime_dir": os.environ.get("XDG_RUNTIME_DIR"),
            "hostname": os.environ.get("HOSTNAME"),
            "path": os.environ.get("PATH"),
            "mounts": Path("/proc/self/mountinfo").read_text(),
        }
    )
)
