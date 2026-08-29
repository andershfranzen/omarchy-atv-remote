#!/usr/bin/env python3
"""Start the persistent backend if needed and send it one command."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


address, command, daemon = sys.argv[1:4]
runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/user-{os.getuid()}"))
socket_path = runtime / ("omarchy-appletv-" + hashlib.sha256(address.encode()).hexdigest()[:12] + ".sock")


def send():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(4)
        client.connect(str(socket_path))
        client.sendall((json.dumps({"command": command}) + "\n").encode())
        response = json.loads(client.makefile().readline())
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "Apple TV command failed"))


try:
    send()
except (FileNotFoundError, ConnectionRefusedError):
    socket_path.unlink(missing_ok=True)
    log_dir = Path.home() / ".local/state/omarchy/apple-tv-remote"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "backend.log", "ab", buffering=0)
    subprocess.Popen(
        [sys.executable, daemon, address, str(socket_path)],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            send()
            break
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(0.05)
    else:
        raise RuntimeError("Apple TV backend did not start")
