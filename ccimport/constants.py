# Copyright 2021 Yan Yan
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from typing import Dict 

CXX = os.getenv("CXX", None)
CUDACXX = os.getenv("CUDACXX", None)
HIPCXX = os.getenv("HIPCXX", None)

def get_compiler_map() -> Dict[str, str]:
    cmap = os.getenv("CCIMPORT_COMPILER_LINKER_MAP", None)
    if cmap is None:
        return {}
    cmap_items = cmap.split(",")
    res: Dict[str, str] = {}
    for item in cmap_items:
        item_map = item.strip().split(":")
        msg = "error format, use something like g++:aarch64-linux-gnu-g++"
        assert len(item_map) == 2, msg
        key = item_map[0].strip()
        val = item_map[1].strip()
        assert key, "key must not empty"
        assert val, "val must not empty"
        res[key] = val
    return res
    
