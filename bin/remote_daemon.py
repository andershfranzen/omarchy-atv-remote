#!/usr/bin/env python3
"""Persistent, serialized Apple TV connection exposed over a local socket."""

import asyncio
import json
import os
import signal
import resource
import sys
import time
import unicodedata
from pathlib import Path

import pyatv
from pyatv.interface import KeyboardListener, DeviceListener
from pyatv.const import Protocol
from pyatv.exceptions import NoCredentialsError
from backend_errors import error_response
from secure_storage import FileStorage
from safe_io import runtime_directory

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
connection_listener = None
command_lock = asyncio.Lock()
watchers = set()
clients = set()
focus_task = None
last_activity = time.monotonic()
stop = None


class FocusListener(KeyboardListener):
    def focusstate_update(self, _old_state, new_state):
        global focus_task
        if focus_task is None or focus_task.done():
            focus_task = asyncio.get_running_loop().create_task(broadcast_focus())


class ConnectionListener(DeviceListener):
    def __init__(self, device):
        self.device = device

    def connection_lost(self, exception):
        global atv
        if atv is self.device:
            atv = None
            self.device.close()

    def connection_closed(self):
        global atv
        if atv is self.device:
            atv = None


async def broadcast_focus(state=None):
    if atv is None:
        return
    message = (json.dumps({"keyboard": state or atv.keyboard.text_focus_state.name}) + "\n").encode()
    stale = []
    for writer in tuple(watchers):
        try:
            writer.write(message)
            await asyncio.wait_for(writer.drain(), 1)
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            stale.append(writer)
    for writer in stale:
        watchers.discard(writer)


async def connect():
    global atv, storage, focus_listener, connection_listener
    loop = asyncio.get_running_loop()
    storage = FileStorage.default_storage(loop)
    await storage.load()
    devices = await pyatv.scan(loop, hosts=[ADDRESS], timeout=3, storage=storage)
    if not devices:
        raise ConnectionError(f"Apple TV at {ADDRESS} was not found")
    companion = devices[0].get_service(Protocol.Companion)
    if companion is None or not companion.credentials:
        raise NoCredentialsError("Companion pairing is required")
    atv = await asyncio.wait_for(pyatv.connect(devices[0], loop, storage=storage), 6)
    # StateProducer retains listeners weakly, so the daemon must own this object.
    focus_listener = FocusListener()
    atv.keyboard.listener = focus_listener
    connection_listener = ConnectionListener(atv)
    atv.listener = connection_listener


def validate_command(command):
    if command in REMOTE_COMMANDS | POWER_COMMANDS | AUDIO_COMMANDS | {"keyboard_state", "power_state", "status", "reconnect", "text_backspace"}:
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
    if command == "status":
        return await read_status(atv)
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


def bounded_text(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("Metadata exceeds its limit")
    return value


async def read_status(device):
    result = {"state": "connected", "power": device.power.power_state.name, "playing": {}}
    try:
        playing = await asyncio.wait_for(device.metadata.playing(), 2)
        result["playing"] = {"title": bounded_text(playing.title), "artist": bounded_text(playing.artist),
                             "state": playing.device_state.name,
                             "series": bounded_text(playing.series_name),
                             "season": playing.season_number,
                             "episode": playing.episode_number,
                             "position": playing.position,
                             "duration": playing.total_time}
    except Exception:
        # Optional metadata neither blocks navigation nor fails a working remote.
        pass
    return result


async def run_command(command):
    global last_activity
    validate_command(command)
    if command == "status":
        async with command_lock:
            last_activity = time.monotonic()
            if atv is None:
                await connect()
            device = atv
        return await read_status(device)
    async with command_lock:
        last_activity = time.monotonic()
        if command == "reconnect":
            await close_connection()
            return {}
        if atv is None:
            await connect()
        try:
            return await invoke(command)
        except Exception:
            await close_connection()
            # Do not replay a command whose acknowledgement may have been lost.
            raise


async def handle(reader, writer):
    global last_activity
    watching = False
    if len(clients) >= 16:
        writer.close()
        return
    clients.add(writer)
    try:
        request = json.loads((await asyncio.wait_for(reader.readline(), 5)).decode())
        command = request.get("command")
        if command == "ping":
            writer.write(b'{"ok":true}\n')
            return
        if command == "keyboard_watch":
            await asyncio.wait_for(run_command("keyboard_state"), 12)
            watching = True
            if len(watchers) >= 4:
                raise ValueError("Too many keyboard subscribers")
            watchers.add(writer)
            last_activity = time.monotonic()
            await broadcast_focus()
            await reader.read(1)
            return
        if not isinstance(command, str):
            raise ValueError("A string command is required")
        result = await asyncio.wait_for(run_command(command), 12)
        writer.write((json.dumps({"ok": True, **result}) + "\n").encode())
    except Exception as error:
        if isinstance(error, asyncio.TimeoutError):
            await close_connection()
        writer.write((json.dumps(error_response(error)) + "\n").encode())
    finally:
        clients.discard(writer)
        if watching:
            watchers.discard(writer)
        try:
            await asyncio.wait_for(writer.drain(), 1)
        except (ConnectionError, asyncio.TimeoutError):
            pass
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1)
        except (ConnectionError, asyncio.TimeoutError):
            pass


async def close_connection():
    global atv, focus_listener
    if atv is not None:
        atv.close()
        atv = None
        focus_listener = None


async def idle_monitor():
    started = time.monotonic()
    owner = os.environ.get("ATV_OWNER_PID", "")
    owner_start = os.environ.get("ATV_OWNER_START", "")
    while not stop.is_set():
        await asyncio.sleep(2)
        try:
            current = Path(f"/proc/{int(owner)}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, ValueError, IndexError):
            current = ""
        if not owner_start or current != owner_start or time.monotonic() - started > 3600:
            stop.set()
        elif not watchers and time.monotonic() - last_activity >= IDLE_SECONDS:
            stop.set()
        elif watchers:
            await broadcast_focus()


async def main():
    global stop
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    if SOCKET.parent != runtime_directory():
        raise ValueError("Socket must be inside the private runtime directory")
    stop = asyncio.Event()
    server = None
    monitor = None
    try:
        server = await asyncio.start_unix_server(handle, path=SOCKET, limit=4096)
        os.chmod(SOCKET, 0o600)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        monitor = asyncio.create_task(idle_monitor())
        async with server:
            await stop.wait()
    finally:
        if monitor:
            monitor.cancel()
        for writer in tuple(clients):
            writer.close()
        await close_connection()
        if server:
            server.close()
            await server.wait_closed()
        SOCKET.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
