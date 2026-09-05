"""Keep pyatv's storage format with bounded, no-follow I/O and atomic saves."""
from pathlib import Path
import json
from pyatv.storage.file_storage import FileStorage as BaseStorage
from safe_io import read_file, atomic_write


class FileStorage(BaseStorage):
    @staticmethod
    def default_storage(loop):
        return FileStorage(str(Path.home() / '.pyatv.conf'), loop)

    def _read_file(self):
        return read_file(self._filename, 65536)

    def _save_file(self, dumped):
        text = json.dumps(dumped) + '\n'
        if len(text.encode()) > 65536:
            raise ValueError('Pairing storage exceeds its size limit')
        atomic_write(self._filename, text)
