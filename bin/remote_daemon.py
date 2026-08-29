#!/usr/bin/env python3
"""Persistent, serialized Apple TV connection exposed over a local socket."""

import asyncio
import json
import os
import signal
import sys
import time
import unicodedata
from pathlib import Path

import pyatv
from pyatv.interface import KeyboardListener
from pyatv.storage.file_storage import FileStorage

ADDRESS = sys.argv[1]
SOCKET = Path(sys.argv[2])
IDLE_SECONDS = 600
MAX_TEXT_LENGTH = 256
REMOTE_COMMANDS = {"down", "home", "home_hold", "left", "menu", "pause", "play", "play_pause", "right", "select", "up"}
POWER_COMMANDS = {"turn_off", "turn_on"}
AUDIO_COMMANDS = {"volume_down", "volume_up"}
atv = None
storage = None
focus_listener = None
command_lock = asyncio.Lock()
watchers = set()
last_activity = time.monotonic()
stop = None


class FocusListener(KeyboardListener):
    def focusstate_update(self, _old_state, new_state):
        asyncio.get_running_loop().create_task(broadcast_focus(new_state.name))


async def broadcast_focus(state=None):
    if atv is None:
        return
    message = (json.dumps({"keyboard": state or atv.keyboard.text_focus_state.name}) + "\n").encode()
    stale = []
    for writer in tuple(watchers):
        try:
            writer.write(message)
            await writer.drain()
        except (ConnectionError, RuntimeError):
            stale.append(writer)
    for writer in stale:
        watchers.discard(writer)


async def connect():
    global atv, storage, focus_listener
    loop = asyncio.get_running_loop()
    storage = FileStorage.default_storage(loop)
    await storage.load()
    devices = await pyatv.scan(loop, hosts=[ADDRESS], timeout=3, storage=storage)
    if not devices:
        raise RuntimeError(f"Apple TV at {ADDRESS} was not found")
    atv = await pyatv.connect(devices[0], loop, storage=storage)
    # StateProducer retains listeners weakly, so the daemon must own this object.
    focus_listener = FocusListener()
    atv.keyboard.listener = focus_listener


def validate_command(command):
    if command in REMOTE_COMMANDS | POWER_COMMANDS | AUDIO_COMMANDS | {"keyboard_state", "power_state", "text_backspace"}:
        return
    if command.startswith("text_append:"):
        text = command.removeprefix("text_append:")
        if not text or len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Text input must contain between 1 and 256 characters")
        return
    raise ValueError(f"Unsupported Apple TV command: {command}")


async def invoke(command):
    validate_command(command)
    if command == "keyboard_state":
        state = atv.keyboard.text_focus_state.name
        if state == "Unknown":
            try:
                await atv.keyboard.text_get()
                state = atv.keyboard.text_focus_state.name
            except Exception:
                pass
        return {"keyboard": state}
    if command == "power_state":
        return {"power": atv.power.power_state.name}
    if command.startswith("text_append:"):
        await atv.keyboard.text_append(command.removeprefix("text_append:"))
        return {}
    if command == "text_backspace":
        current = await atv.keyboard.text_get()
        if current:
            cut = len(current)
            while cut > 0 and unicodedata.combining(current[cut - 1]):
                cut -= 1
            if cut > 0:
                cut -= 1
            updated = current[:cut]
            await atv.keyboard.text_set(updated)
        return {}
    owner = atv.power if command in POWER_COMMANDS else atv.audio if command in AUDIO_COMMANDS else atv.remote_control
    await getattr(owner, command)()
    return {}


async def run_command(command):
    global last_activity
    validate_command(command)
    async with command_lock:
        last_activity = time.monotonic()
        try:
            return await invoke(command)
        except Exception:
            await close_connection()
            await connect()
            await broadcast_focus()
            return await invoke(command)


async def handle(reader, writer):
    global last_activity
    watching = False
    try:
        request = json.loads((await asyncio.wait_for(reader.readline(), 5)).decode())
        command = request.get("command")
        if command == "keyboard_watch":
            watching = True
            watchers.add(writer)
            last_activity = time.monotonic()
            await broadcast_focus()
            await reader.read()
            return
        if not isinstance(command, str):
            raise ValueError("A string command is required")
        result = await run_command(command)
        writer.write((json.dumps({"ok": True, **result}) + "\n").encode())
    except Exception as error:
        writer.write((json.dumps({"ok": False, "error": str(error)}) + "\n").encode())
    finally:
        if watching:
            watchers.discard(writer)
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()
        await writer.wait_closed()


async def close_connection():
    global atv, focus_listener
    if atv is not None:
        atv.close()
        atv = None
        focus_listener = None


async def idle_monitor():
    while not stop.is_set():
        await asyncio.sleep(30)
        if not watchers and time.monotonic() - last_activity >= IDLE_SECONDS:
            stop.set()


async def main():
    global stop
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    await connect()
    server = await asyncio.start_unix_server(handle, path=SOCKET)
    os.chmod(SOCKET, 0o600)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    monitor = asyncio.create_task(idle_monitor())
    async with server:
        await stop.wait()
    monitor.cancel()
    await close_connection()
    SOCKET.unlink(missing_ok=True)


asyncio.run(main())
