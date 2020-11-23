import contextlib
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional, Dict, Any, Hashable

class HashableRegistry:
    def __init__(self, allow_duplicate=False):
        self.global_dict = {}  # type: Dict[Hashable, Any]
        self.allow_duplicate = allow_duplicate

    def register(self, func=None, key: Optional[Hashable] = None):
        def wrapper(func):
            key_ = key
            if key is None:
                key_ = func.__name__
            if not self.allow_duplicate and key_ in self.global_dict:
                raise KeyError("key {} already exists".format(key_))
            self.global_dict[key_] = func
        if func is None:
            return wrapper
        else:
            return wrapper(func)

    def __contains__(self, key: Hashable):
        return key in self.global_dict

    def __getitem__(self, key: Hashable):
        return self.global_dict[key]


@contextlib.contextmanager
def tempdir(delete=True):
    try:
        dirpath = tempfile.mkdtemp()
        dirpath = Path(dirpath)
        yield dirpath
    finally:
        if delete:
            shutil.rmtree(str(dirpath))
