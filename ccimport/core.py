"""a small library to replace cppimport.
when use in windows, you need to run ccimport/autoimport in vs developer prompt.
example config in microsoft terminal:

{
    "name" : "Developer Command Prompt for VS 2019",
    "commandline" : "powershell.exe -noe -c \"&{Import-Module \"\"\"C:/Program Files (x86)/Microsoft Visual Studio/2019/Community/Common7/Tools/Microsoft.VisualStudio.DevShell.dll\"\"\"; Enter-VsDevShell 4bd12d00 -DevCmdArguments '-arch=x64 -no_logo'}\"",
    "startingDirectory" : "%USERPROFILE%"
}

"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

import pybind11

from ccimport import compat, loader
from ccimport.buildmeta import BuildMeta
from ccimport.buildtools.writer import (DEFAULT_MSVC_DEP_PREFIX,
                                        build_simple_ninja, fill_build_flags)
from ccimport.global_cfg import GLOBAL_CONFIG
from ccimport.source_iter import CppSourceIterator
from ccimport.utils import tempdir

_PYBIND_COMMON_INCLUDES = [
    "#include <pybind11/pybind11.h>",
    "#include <pybind11/stl.h>",
    "#include <pybind11/numpy.h>",
    # "#include <pybind11/eigen.h>",
]


def get_full_file_name(name, build_ctype, shared=True):
    if not shared:
        if compat.InWindows:
            return name + ".exe"
        else:
            return name
    lib_prefix = ""
    if not compat.InWindows and build_ctype:
        lib_prefix = "lib"
    if not build_ctype:
        lib_suffix = compat.get_extension_suffix()
    else:
        if compat.InWindows:
            lib_suffix = ".dll"
        else:
            lib_suffix = ".so"
    return lib_prefix + name + lib_suffix


def ccimport(source_paths: List[Union[str, Path]],
             out_path: Union[str, Path],
             build_meta: BuildMeta,
             source_paths_for_hash: Optional[List[Union[str, Path]]] = None,
             std: Optional[str] = "c++14",
             build_ctype=False,
             disable_hash=True,
             load_library=True,
             shared=True,
             msvc_deps_prefix=DEFAULT_MSVC_DEP_PREFIX,
             out_root: Optional[Union[str, Path]] = None,
             build_dir: Optional[Union[str, Path]] = None,
             pch_to_sources: Optional[Dict[Union[str, Path],
                                           List[Union[str, Path]]]] = None,
             pch_to_include: Optional[Dict[Union[str, Path], str]] = None,
             suffix_to_compiler: Optional[Dict[str, str]] = None,
             objects_folder: Optional[Union[str, Path]] = None,
             compiler_to_path: Optional[Dict[str, str]] = None,
             linker_to_path: Optional[Dict[str, str]] = None,
             source_meta: Optional[Dict[str, BuildMeta]] = None,
             linker: Optional[str] = None,
             verbose=False,
             manual_target_name: Optional[str] = ""):
    if not shared:
        assert load_library is False, "executable can't be loaded to python"
    source_paths = list(map(lambda p: Path(p).resolve(), source_paths))
    out_path = (Path(out_path).parent.resolve() / Path(out_path).stem)
    if source_paths_for_hash is None:
        source_paths_for_hash = source_paths
    source_str_paths = list(map(lambda p: str(p), source_paths_for_hash))
    source_contents = {}
    for path in source_paths_for_hash:
        path = Path(path)
        with path.open("r") as f:
            source_contents[str(path)] = f.read()
    py_version = sys.version_info[:2]
    py_version_str = "{}_{}".format(*py_version)
    fake_out_as_hash = out_path.parent / (
        out_path.stem + "_hash_{}.fake.out".format(py_version_str))
    if not disable_hash and fake_out_as_hash.exists():
        # check if need to rebuilt
        with fake_out_as_hash.open("r") as f:
            hash_data = json.load(f)
        source_paths_for_hash_prev = set(hash_data["sources"])
        source_contents_saved = hash_data["source_contents"]
        extension_path = hash_data["extension_path"]
        # py_version_cache = hash_data["python_version"]
        if source_paths_for_hash_prev == set(source_str_paths):
            no_change = True
            for p in source_paths_for_hash_prev:
                content = source_contents_saved[p]
                content_expected = source_contents[p]
                if content != content_expected:
                    no_change = False
                    break
            if no_change:
                if load_library:
                    if build_ctype:
                        return ctypes.cdll.LoadLibrary(str(extension_path))
                    return loader.try_import_from_path(extension_path)
                return extension_path
    lib_name = out_path.stem
    if std is not None:
        build_meta.add_global_cflags("cl", "/std:{}".format(std), "/O2")
        build_meta.add_global_cflags("g++,clang++,nvcc", "-std={}".format(std), "-O3")
        build_meta.add_global_cflags("em++", "-std={}".format(std), "-O3")
    if compat.InWindows:
        # in windows, we need to link against python library.
        if not build_ctype:
            py_version_str_p = "{}.{}".format(py_version[0], py_version[1])
            pythonlib = compat.locate_libpython_2(py_version_str_p)
            assert isinstance(pythonlib, str)
            pythonlib = Path(pythonlib)
            build_meta.add_libraries(pythonlib.stem)
            build_meta.add_library_paths(pythonlib.parent)
            # libraries.append(pythonlib.stem)
            # libpaths.append(pythonlib.parent)
    python_includes = compat.get_pybind11_includes()
    build_meta.add_global_includes(*python_includes, *GLOBAL_CONFIG.includes)
    # includes.extend(python_includes)
    # includes.extend(GLOBAL_CONFIG.includes)
    if not manual_target_name:
        target_filename = get_full_file_name(lib_name, build_ctype, shared)
    else:
        target_filename = manual_target_name
    if build_dir is not None:
        build_dir = Path(build_dir)
    else:
        build_dir = out_path.parent / "build"
    build_dir.mkdir(exist_ok=True, parents=True, mode=0o755)
    if "CCIMPORT_MSVC_DEPS_PREFIX" not in os.environ:
        os.environ["CCIMPORT_MSVC_DEPS_PREFIX"] = msvc_deps_prefix
    # print(build_meta.libraries)
    # breakpoint()

    try:
        target_filename, no_work = build_simple_ninja(
            lib_name,
            build_dir,
            source_paths,
            build_meta,
            target_filename,
            out_root=out_root,
            suffix_to_compiler=suffix_to_compiler,
            shared=shared,
            verbose=verbose,
            pch_to_sources=pch_to_sources,
            pch_to_include=pch_to_include,
            objects_folder=objects_folder,
            compiler_to_path=compiler_to_path,
            linker_to_path=linker_to_path,
            source_meta=source_meta,
            linker=linker)
    finally:
        os.environ.pop("CCIMPORT_MSVC_DEPS_PREFIX")
    build_out_path = build_dir / target_filename
    out_path = out_path.parent / target_filename
    if not no_work:
        shutil.copy(str(build_out_path), str(out_path))
        if compat.InWindows and build_ctype:
            win_lib_file = build_out_path.parent / (build_out_path.stem +
                                                    ".lib")
            if win_lib_file.exists():
                shutil.copy(str(win_lib_file),
                            str(out_path.parent / win_lib_file.name))

    extension_path = str(out_path)
    if not disable_hash:
        with fake_out_as_hash.open("w") as f:
            d = {
                "sources": source_str_paths,
                "source_contents": source_contents,
                "extension_path": extension_path,
                "python_version": py_version,
            }
            json.dump(d, f)
    if load_library:
        if build_ctype:
            # user must load library by your self.
            return extension_path
        return loader.try_import_from_path(extension_path)
    return extension_path
