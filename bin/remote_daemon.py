#!/usr/bin/env python3
"""Persistent Apple TV connection exposed through a local Unix socket."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pyatv
from pyatv.storage.file_storage import FileStorage


ADDRESS = sys.argv[1]
SOCKET = Path(sys.argv[2])
atv = None
storage = None


async def connect():
    global atv, storage
    loop = asyncio.get_running_loop()
    storage = FileStorage.default_storage(loop)
    await storage.load()
    devices = await pyatv.scan(loop, hosts=[ADDRESS], timeout=3, storage=storage)
    if not devices:
        raise RuntimeError(f"Apple TV at {ADDRESS} was not found")
    atv = await pyatv.connect(devices[0], loop, storage=storage)


async def invoke(command):
    global atv
    if command == "keyboard_state":
        state = atv.keyboard.text_focus_state.name
        if state == "Unknown":
            try:
                await atv.keyboard.text_get()
                state = atv.keyboard.text_focus_state.name
            except Exception:
                pass
        return {"keyboard": state}
    if command.startswith("text_append:"):
        await atv.keyboard.text_append(command[len("text_append:"):])
        return {}
    if command == "text_backspace":
        current = await atv.keyboard.text_get()
        if current:
            await atv.keyboard.text_set(current[:-1])
        return {}
    targets = {
        "turn_on": "power",
        "turn_off": "power",
        "volume_up": "audio",
        "volume_down": "audio",
    }
    owner = getattr(atv, targets.get(command, "remote_control"))
    method = getattr(owner, command)
    await method()
    return {}


async def handle(reader, writer):
    try:
        request = json.loads((await reader.readline()).decode())
        command = str(request["command"])
        try:
            result = await invoke(command)
        except Exception:
            # The Apple TV can sever an idle Companion session. Reconnect once
            # and replay the key instead of making the first press feel lost.
            await close_connection()
            await connect()
            result = await invoke(command)
        writer.write((json.dumps({"ok": True, **result}) + "\n").encode())
    except Exception as error:
        writer.write((json.dumps({"ok": False, "error": str(error)}) + "\n").encode())
    finally:
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def close_connection():
    global atv
    if atv is not None:
        atv.close()
        atv = None


async def main():
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET.exists():
        SOCKET.unlink()
    await connect()
    server = await asyncio.start_unix_server(handle, path=SOCKET)
    os.chmod(SOCKET, 0o600)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()
    await close_connection()
    SOCKET.unlink(missing_ok=True)


asyncio.run(main())
