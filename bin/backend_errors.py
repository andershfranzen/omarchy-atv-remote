"""Stable UI error categories; never classify a network failure as bad pairing."""
import asyncio
from pyatv import exceptions


def error_response(error):
    if isinstance(error, (exceptions.AuthenticationError, exceptions.NoCredentialsError,
                          exceptions.InvalidCredentialsError)):
        state, message = 'pairing', 'Pairing needed'
    elif isinstance(error, (OSError, asyncio.TimeoutError, exceptions.ConnectionFailedError,
                            exceptions.ConnectionLostError, exceptions.OperationTimeoutError)):
        state, message = 'offline', 'Apple TV is offline or unreachable'
    elif isinstance(error, exceptions.NotSupportedError):
        state, message = 'unsupported', 'This feature is not available on this Apple TV'
    else:
        state, message = 'error', 'Apple TV connection failed'
    return {'ok': False, 'state': state, 'error': message}
