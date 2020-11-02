from pathlib import Path
import os 

def read_env(key, default):
    if key in os.environ:
        return os.environ[key]
    return default


CODEAI_SAVE_ROOT = read_env("CODEAI_SAVE_ROOT", str(Path.home() / ".codeai"))
