import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

BIN = Path(__file__).resolve().parents[1] / 'bin'
sys.path.insert(0, str(BIN))
try:
    import pyatv
    from pyatv import exceptions
    from pyatv.const import Protocol, PairingRequirement, OperatingSystem
    from backend_errors import error_response
    import pairing
    with patch.object(sys, 'argv', ['remote_daemon.py', '10.0.0.5', '/tmp/atv-test-unused.sock']):
        spec = importlib.util.spec_from_file_location('daemon_test', BIN / 'remote_daemon.py')
        daemon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daemon)
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'pyatv required for backend integration tests')
class ErrorTests(unittest.TestCase):
    def test_network_failure_is_not_pairing_failure(self):
        for error in (TimeoutError(), ConnectionError(), exceptions.ConnectionFailedError()):
            self.assertEqual(error_response(error)['state'], 'offline')
        for error in (exceptions.AuthenticationError(), exceptions.NoCredentialsError()):
            self.assertEqual(error_response(error)['state'], 'pairing')
        self.assertEqual(error_response(ValueError())['state'], 'error')


@unittest.skipUnless(AVAILABLE, 'pyatv required for backend integration tests')
class PairingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = types.SimpleNamespace(load=AsyncMock(), save=AsyncMock())
        self.service = types.SimpleNamespace(identifier='aa:bb', credentials=None,
                    pairing=PairingRequirement.Mandatory, requires_password=False)
        self.device = types.SimpleNamespace(device_info=types.SimpleNamespace(operating_system=OperatingSystem.TvOS),
                    get_service=lambda _: self.service, identifier='AA:BB')
        self.handler = types.SimpleNamespace(begin=AsyncMock(), finish=AsyncMock(), close=AsyncMock(),
                    pin=Mock(), has_paired=True, device_provides_pin=True)
        self.events = []
        self.patches = [patch.object(pairing.FileStorage, 'default_storage', return_value=self.storage),
                        patch.object(pairing.pyatv, 'scan', AsyncMock(return_value=[self.device])),
                        patch.object(pairing.pyatv, 'pair', AsyncMock(return_value=self.handler)),
                        patch.object(pairing, 'remember_devices'),
                        patch.object(pairing, 'emit', side_effect=lambda event, **kw: self.events.append((event, kw)))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_pairs_both_protocols_and_saves_before_reporting_success(self):
        reader = types.SimpleNamespace(readline=AsyncMock(return_value=b'{"value":"1234"}\n'))
        await pairing.pair_device('10.0.0.5', reader)
        self.assertEqual(self.storage.save.await_count, 2)
        self.assertEqual(self.handler.close.await_count, 2)
        self.assertEqual(self.events[-1][0], 'done')
        self.assertEqual(self.events[-1][1]['identifier'], 'AA:BB')
        self.assertEqual([call.args[1] for call in pairing.pyatv.pair.await_args_list], [Protocol.Companion, Protocol.AirPlay])

    async def test_invalid_pin_does_not_save_and_closes_session(self):
        reader = types.SimpleNamespace(readline=AsyncMock(return_value=b'{"value":"wrong"}\n'))
        with self.assertRaises(ValueError):
            await pairing.pair_device('10.0.0.5', reader)
        self.storage.save.assert_not_awaited()
        self.handler.close.assert_awaited_once()
        self.assertNotIn('done', [event for event, _ in self.events])

    async def test_cancel_closes_session_without_saving(self):
        reader = types.SimpleNamespace(readline=AsyncMock(return_value=b''))
        with self.assertRaises(asyncio.CancelledError):
            await pairing.pair_device('10.0.0.5', reader)
        self.storage.save.assert_not_awaited()
        self.handler.close.assert_awaited_once()

    async def test_metadata_failure_keeps_remote_connected(self):
        fake = types.SimpleNamespace(power=types.SimpleNamespace(power_state=types.SimpleNamespace(name='On')),
                    metadata=types.SimpleNamespace(playing=AsyncMock(side_effect=exceptions.NotSupportedError())))
        with patch.object(daemon, 'atv', fake):
            result = await daemon.invoke('status')
        self.assertEqual(result['state'], 'connected')
        self.assertEqual(result['playing'], {})

    async def test_failed_navigation_is_not_replayed(self):
        with patch.object(daemon, 'atv', object()), patch.object(daemon, 'command_lock', asyncio.Lock()), \
             patch.object(daemon, 'invoke', AsyncMock(side_effect=ConnectionError())) as invoke, \
             patch.object(daemon, 'close_connection', AsyncMock()):
            with self.assertRaises(ConnectionError):
                await daemon.run_command('select')
            invoke.assert_awaited_once()

    async def test_slow_metadata_does_not_block_navigation(self):
        started = asyncio.Event()
        finish = asyncio.Event()
        async def slow_metadata(_):
            started.set()
            await finish.wait()
            return {}
        with patch.object(daemon, 'atv', object()), patch.object(daemon, 'command_lock', asyncio.Lock()), \
             patch.object(daemon, 'read_status', side_effect=slow_metadata), \
             patch.object(daemon, 'invoke', AsyncMock(return_value={})) as invoke:
            status_task = asyncio.create_task(daemon.run_command('status'))
            try:
                await asyncio.wait_for(started.wait(), .5)
                await asyncio.wait_for(daemon.run_command('down'), .5)
                invoke.assert_awaited_once_with('down')
            finally:
                finish.set()
                await status_task
