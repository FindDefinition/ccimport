import contextlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ccimport import compat
from ccimport.constants import CODEAI_SAVE_ROOT


@contextlib.contextmanager
def tempdir(delete=True):
    if compat.InWindows:
        save_root = Path(CODEAI_SAVE_ROOT) / "codeai_tempdir"
        save_root.mkdir(exist_ok=True, parents=True)
        dirpath = save_root / os.urandom(24).hex()
        dirpath.mkdir()
        yield dirpath
        if delete:
            shutil.rmtree(dirpath)
    else:
        try:
            dirpath = tempfile.mkdtemp()
            dirpath = Path(dirpath)
            yield dirpath
        finally:
            if delete:
                shutil.rmtree(str(dirpath))
