"""Bound process groups, output, resource usage, and the lifetime of UI helpers."""
import ctypes
import os
import resource
import selectors
import signal
import subprocess
import sys
import time


def main():
    detached = sys.argv[1] == "daemon"
    timeout = 3600 if detached else int(sys.argv[1])
    parent = os.getppid()
    owner = int(os.environ.get('ATV_COMPONENT_PID', '0')) or (int(os.environ.get('ATV_OWNER_PID', str(parent))) if detached else parent)
    os.environ['PATH'] = '/usr/bin:/bin'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['ATV_OWNER_PID'] = str(owner)
    try:
        os.environ['ATV_OWNER_START'] = open(f'/proc/{owner}/stat').read().rsplit(')', 1)[1].split()[19]
    except OSError:
        return 1
    child = None
    def stop(*_):
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        raise SystemExit(1)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not detached:
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
    if not detached and os.getppid() != parent:
        return 1
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    try:
        child = subprocess.Popen(sys.argv[2:], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, preexec_fn=limits)
        selector = selectors.DefaultSelector()
        buffers = {}
        for stream in (child.stdout, child.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
            buffers[stream] = b''
        deadline = time.monotonic() + timeout
        total = 0
        while selector.get_map():
            try:
                current_owner = open(f'/proc/{owner}/stat').read().rsplit(')', 1)[1].split()[19]
            except OSError:
                current_owner = ''
            if current_owner != os.environ['ATV_OWNER_START']:
                raise TimeoutError('Owner process ended')
            if time.monotonic() > deadline:
                raise TimeoutError('Helper deadline exceeded')
            for key, _ in selector.select(.2):
                data = os.read(key.fd, 4096)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                total += len(data)
                buffers[key.fileobj] += data
                if total > 65536 or len(buffers[key.fileobj]) > 32768:
                    raise ValueError('Helper output limit exceeded')
                while b'\n' in buffers[key.fileobj]:
                    line, buffers[key.fileobj] = buffers[key.fileobj].split(b'\n', 1)
                    destination = sys.stdout.buffer if key.fileobj is child.stdout else sys.stderr.buffer
                    destination.write(line + b'\n')
                    destination.flush()
        return child.wait(timeout=max(.1, deadline - time.monotonic()))
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        print('{"ok":false,"state":"error","event":"error","message":"Apple TV helper exceeded its limits or could not start.","error":"Apple TV helper exceeded its limits or could not start."}', flush=True)
        return 1
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Escalate for the entire group even if its direct child exited.
            time.sleep(.2)
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


if __name__ == '__main__':
    sys.exit(main())
