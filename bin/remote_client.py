#!/usr/bin/env python3
"""Start the versioned backend if needed and send it one command."""

import fcntl
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
daemon_hash = hashlib.sha256(Path(daemon).read_bytes()).hexdigest()[:10]
address_hash = hashlib.sha256(address.encode()).hexdigest()[:12]
socket_path = runtime / f"omarchy-appletv-{address_hash}-{daemon_hash}.sock"
lock_path = runtime / f"omarchy-appletv-{address_hash}.lock"
RETRYABLE = (FileNotFoundError, ConnectionRefusedError, ConnectionResetError, BrokenPipeError, socket.timeout)


def send(request_command, watch=False, emit=True):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(None if watch else 5)
        client.connect(str(socket_path))
        client.sendall((json.dumps({"command": request_command}) + "\n").encode())
        stream = client.makefile()
        if watch:
            for line in stream:
                print(line, end="", flush=True)
            return
        line = stream.readline()
        if not line:
            raise ConnectionResetError("Apple TV backend closed without a response")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "Apple TV command failed"))
        if emit:
            print(json.dumps(response), flush=True)


def rotate_log(path):
    if path.exists() and path.stat().st_size > 1_000_000:
        previous = path.with_suffix(".log.1")
        previous.unlink(missing_ok=True)
        path.replace(previous)


def ensure_backend():
    runtime.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            send("keyboard_state", emit=False)
            return
        except RETRYABLE:
            socket_path.unlink(missing_ok=True)
        log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy/apple-tv-remote"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "backend.log"
        rotate_log(log_path)
        with log_path.open("ab", buffering=0) as log:
            subprocess.Popen(
                [sys.executable, daemon, address, str(socket_path)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            try:
                send("keyboard_state", emit=False)
                return
            except RETRYABLE:
                time.sleep(0.05)
        raise RuntimeError("Apple TV backend did not start; check backend.log")


try:
    send(command, watch=command == "keyboard_watch")
except RETRYABLE:
    ensure_backend()
    send(command, watch=command == "keyboard_watch")
