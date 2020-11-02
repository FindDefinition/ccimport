import contextlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ccimport import compat

@contextlib.contextmanager
def tempdir(delete=True):
    try:
        dirpath = tempfile.mkdtemp()
        dirpath = Path(dirpath)
        yield dirpath
    finally:
        if delete:
            shutil.rmtree(str(dirpath))
