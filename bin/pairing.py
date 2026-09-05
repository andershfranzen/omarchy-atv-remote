"""Interactive pairing: JSON events on stdout, PIN/password responses on stdin."""
import asyncio
import ipaddress
import json
import signal
import sys

import pyatv
from pyatv.const import Protocol, PairingRequirement, OperatingSystem
from secure_storage import FileStorage
from discovery import remember_devices


def emit(event, **values):
    print(json.dumps({'event': event, **values}), flush=True)


async def answer(reader, event, message):
    emit(event, message=message)
    line = await asyncio.wait_for(reader.readline(), 120)
    if not line:
        raise asyncio.CancelledError()
    response = json.loads(line)
    return str(response.get('value', ''))


async def pair_device(address, reader):
    address = str(ipaddress.IPv4Address(address))
    loop = asyncio.get_running_loop()
    storage = FileStorage.default_storage(loop)
    await storage.load()
    emit('progress', message='Connecting to Apple TV…')
    devices = await pyatv.scan(loop, hosts=[address], timeout=4, storage=storage)
    if not devices:
        raise ConnectionError('Apple TV is offline or unreachable.')
    device = devices[0]
    if device.device_info.operating_system != OperatingSystem.TvOS:
        raise ValueError('This address does not belong to an Apple TV.')
    airplay = device.get_service(Protocol.AirPlay)
    companion = device.get_service(Protocol.Companion)
    if companion is None:
        raise ValueError('This Apple TV does not advertise remote pairing.')
    for protocol in (Protocol.Companion, Protocol.AirPlay):
        service = device.get_service(protocol)
        if service is None:
            continue
        if service.pairing in (PairingRequirement.Disabled, PairingRequirement.Unsupported):
            if protocol == Protocol.Companion:
                raise ValueError('Remote pairing is disabled on this Apple TV.')
            continue
        if service.pairing == PairingRequirement.NotNeeded:
            continue
        if service.requires_password:
            service.password = await answer(reader, 'password', 'Enter the Apple TV AirPlay password.')
        emit('progress', message=f'Starting {protocol.name} pairing…')
        handler = await pyatv.pair(device, protocol, loop, storage=storage)
        try:
            await asyncio.wait_for(handler.begin(), 15)
            if handler.device_provides_pin:
                pin = await answer(reader, 'pin', f'Enter the PIN shown on your TV ({protocol.name}).')
                if not pin.isascii() or not pin.isdigit() or len(pin) != 4:
                    raise ValueError('Enter the four-digit PIN shown on your TV.')
                handler.pin(pin)
            else:
                raise ValueError('This pairing method is not supported in the panel.')
            emit('progress', message=f'Verifying {protocol.name} PIN…')
            await asyncio.wait_for(handler.finish(), 15)
            if not handler.has_paired:
                raise ValueError('The PIN was not accepted. Try pairing again.')
            await storage.save()
        finally:
            await handler.close()
    identifier = airplay.identifier.upper() if airplay and airplay.identifier else device.identifier
    remember_devices([{'identifier': identifier, 'address': address}])
    emit('done', message='Paired. Your remote is ready.', identifier=identifier)


async def main():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=1024)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await asyncio.wait_for(pair_device(sys.argv[1], reader), 300)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        emit('error', message='Pairing timed out. Try again when the TV is ready.')
        return 1
    except Exception as error:
        # Do not emit credentials or third-party exception payloads.
        message = str(error) if isinstance(error, (ValueError, ConnectionError)) else 'Pairing failed. Check the PIN and try again.'
        emit('error', message=message)
        return 1
    finally:
        transport.close()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
