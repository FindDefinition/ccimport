from pathlib import Path 
from typing import List
import json 
import traceback

class GlobalConfig:
    def __init__(self, includes: List[str]):
        self.includes = includes

GLOBAL_CONFIG_PATH = Path.home() / ".ccimport_global.json"
GLOBAL_CONFIG = GlobalConfig([])
if GLOBAL_CONFIG_PATH.exists():
    try:
        with GLOBAL_CONFIG_PATH.open("r") as f:
            cfg = json.load(f)
        GLOBAL_CONFIG = GlobalConfig(cfg["includes"])
    except:
        traceback.print_exc()
