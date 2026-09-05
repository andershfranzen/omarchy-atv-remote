import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

BIN = Path(__file__).resolve().parents[1] / 'bin'
sys.path.insert(0, str(BIN))
from safe_io import read_file, open_file, atomic_write
from bounded_process import capture
import discovery


class LimitTests(unittest.TestCase):
    def test_symlink_reads_and_locks_do_not_follow_target(self):
        with tempfile.TemporaryDirectory() as temp:
            victim = Path(temp) / 'victim'
            victim.write_text('unchanged')
            link = Path(temp) / 'link'
            link.symlink_to(victim)
            for operation in (lambda: read_file(link), lambda: open_file(link, os.O_CREAT | os.O_RDWR)):
                with self.assertRaises(OSError):
                    operation()
            self.assertEqual(victim.read_text(), 'unchanged')

    def test_atomic_write_does_not_follow_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            victim = Path(temp) / 'victim'
            victim.write_text('unchanged')
            link = Path(temp) / 'link'
            link.symlink_to(victim)
            atomic_write(link, 'new')
            self.assertEqual(victim.read_text(), 'unchanged')
            self.assertEqual(read_file(link), 'new')
            self.assertEqual(link.stat().st_mode & 0o777, 0o600)

    def test_oversized_file_and_pipe_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'large'
            path.write_text('x' * 100)
            with self.assertRaises(ValueError):
                read_file(path, 10)
        with self.assertRaises(ValueError):
            capture([sys.executable, '-c', 'print("x" * 100000)'], timeout=2, limit=4096)
        with self.assertRaises(subprocess.TimeoutExpired):
            capture([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.1)

    def test_runner_limits_output_and_deadline(self):
        for timeout, code in [(1, 'import time; time.sleep(10)'), (3, 'print("x" * 100000)')]:
            result = subprocess.run([sys.executable, str(BIN / 'runner.py'), str(timeout), sys.executable, '-c', code],
                                    capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertLess(len(result.stdout), 65536)

    def test_untrusted_discovery_names_addresses_and_count_are_rejected(self):
        base = '=;eth0;IPv4;NAME;_airplay._tcp;local;host;ADDRESS;7000;"model=AppleTV14,1" "deviceid=aa:bb"'
        for line in (base.replace('NAME', 'x' * 100000).replace('ADDRESS', '10.0.0.5'),
                     base.replace('NAME', 'TV').replace('ADDRESS', 'not-an-ip')):
            with self.assertRaises(ValueError):
                discovery.parse_services(line)
        with self.assertRaises(ValueError):
            discovery.validate_devices([{}] * 33)


    def test_runner_kills_descendant_that_ignores_termination(self):
        with tempfile.TemporaryDirectory() as temp:
            pidfile = Path(temp) / 'pid'
            descendant = "import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(%r,'w').write(str(os.getpid())); time.sleep(30)" % str(pidfile)
            parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',%r])" % descendant
            result = subprocess.run([sys.executable, str(BIN / 'runner.py'), '1', sys.executable, '-c', parent], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            pid = int(pidfile.read_text())
            self.assert_process_stopped(pid)

    def assert_process_stopped(self, pid):
        for _ in range(50):
            try:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            except FileNotFoundError:
                return
            if state == 'Z':
                return
            time.sleep(.02)
        self.fail(f'Process {pid} survived supervisor cleanup')

    def test_daemon_supervisor_stops_when_component_owner_ends(self):
        with tempfile.TemporaryDirectory() as temp:
            pidfile = Path(temp) / 'pid'
            owner = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            child = "import os,time; open(%r,'w').write(str(os.getpid())); time.sleep(30)" % str(pidfile)
            supervisor = subprocess.Popen([sys.executable, str(BIN / 'runner.py'), 'daemon', sys.executable, '-c', child],
                                          env={**os.environ, 'ATV_COMPONENT_PID': str(owner.pid)}, stdout=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if pidfile.exists():
                        break
                    time.sleep(.02)
                self.assertTrue(pidfile.exists())
                owner.terminate()
                owner.wait(timeout=2)
                self.assertNotEqual(supervisor.wait(timeout=3), 0)
                self.assert_process_stopped(int(pidfile.read_text()))
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait()
                if supervisor.poll() is None:
                    supervisor.terminate()
                supervisor.wait(timeout=3)
