"""Capture small helper output without buffering an unlimited pipe."""
import os
import selectors
import subprocess
import time


def capture(args, timeout, limit=65536):
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = {child.stdout: bytearray(), child.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout
    try:
        for stream in output:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(args, timeout)
            for key, _ in selector.select(.1):
                data = os.read(key.fd, 4096)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                if sum(map(len, output.values())) + len(data) > limit:
                    raise ValueError('Discovery output exceeds its size limit')
                output[key.fileobj].extend(data)
        code = child.wait(timeout=max(.1, deadline - time.monotonic()))
        return subprocess.CompletedProcess(args, code, output[child.stdout].decode('utf-8', errors='replace'),
                                           output[child.stderr].decode('utf-8', errors='replace'))
    finally:
        selector.close()
        if child.poll() is None:
            child.kill()
        child.wait()
        child.stdout.close()
        child.stderr.close()
