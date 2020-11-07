import contextlib
import shutil
import tempfile
from pathlib import Path


@contextlib.contextmanager
def tempdir(delete=True):
    try:
        dirpath = tempfile.mkdtemp()
        dirpath = Path(dirpath)
        yield dirpath
    finally:
        if delete:
            shutil.rmtree(str(dirpath))
