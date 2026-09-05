"""Owned directories, no-follow bounded reads, and exclusive atomic writes."""
import os
from pathlib import Path
import secrets
import stat


def directory(path, private=True):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('An absolute, normalized directory is required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in (0, os.getuid()) or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise PermissionError('Unsafe directory ownership or permissions')
        info = os.fstat(fd)
        if info.st_uid != os.getuid():
            raise PermissionError('Directory is not owned by this user')
        if private:
            os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_file(path, flags=os.O_RDONLY):
    path = Path(path)
    parent = directory(path.parent, private=False)
    try:
        fd = os.open(path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            os.close(fd)
            raise PermissionError('Unsafe file ownership, type, or permissions')
        return fd
    finally:
        os.close(parent)


def read_file(path, limit=65536):
    with os.fdopen(open_file(path), 'rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File exceeds its size limit')
    return data.decode('utf-8')


def atomic_write(path, text):
    path = Path(path)
    parent = directory(path.parent, private=False)
    temporary = '.' + path.name + '.' + secrets.token_hex(12)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def runtime_directory():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'omarchy-appletv'
    os.close(directory(path))
    return path
