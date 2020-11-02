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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

import pybind11
from ccimport import compat
from ccimport import loader
from ccimport.source_iter import CppSourceIterator
from ccimport.buildtools.writer import (build_simple_ninja,
                                             fill_build_flags)
from ccimport.utils import tempdir

_PYBIND_COMMON_INCLUDES = [
    "#include <pybind11/pybind11.h>",
    "#include <pybind11/stl.h>",
    "#include <pybind11/numpy.h>",
    # "#include <pybind11/eigen.h>",
]


def ccimport(source_paths: List[Union[str, Path]],
             out_path: Union[str, Path],
             includes: Optional[List[Union[str, Path]]] = None,
             libpaths: Optional[List[Union[str, Path]]] = None,
             libraries: Optional[List[str]] = None,
             compile_options: Optional[List[str]] = None,
             link_options: Optional[List[str]] = None,
             source_paths_for_hash: Optional[List[Union[str, Path]]] = None,
             std="c++14",
             build_ctype=False,
             disable_hash=True,
             load_library=True,
             additional_cflags: Optional[Dict[str, List[str]]] = None):
    source_paths = list(map(lambda p: Path(p).resolve(), source_paths))
    out_path = Path(out_path)
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
    if includes is None:
        includes = []
    if libpaths is None:
        libpaths = []
    if libraries is None:
        libraries = []
    if compile_options is None:
        compile_options = []
    if additional_cflags is None:
        additional_cflags = {}
    if link_options is None:
        link_options = []
    fill_build_flags(additional_cflags)
    additional_cflags["cl"].extend(["/std:{}".format(std), "/O2"])
    additional_cflags["g++"].extend(["-std={}".format(std), "-O3"])
    additional_cflags["clang++"].extend(["-std={}".format(std), "-O3"])
    additional_cflags["nvcc"].extend(["-std={}".format(std), "-O3"])
    if compat.InWindows:
        # in windows, we need to link against python library.
        if not build_ctype:
            py_version_str_p = f"{py_version[0]}.{py_version[1]}"
            pythonlib = compat.locate_libpython_2(py_version_str_p)
            assert isinstance(pythonlib, str)
            pythonlib = Path(pythonlib)
            libraries.append(pythonlib.stem)
            libpaths.append(pythonlib.parent)
    python_includes = compat.get_pybind11_includes()
    includes.extend(python_includes)

    target_filename = None
    lib_prefix = ""
    if not compat.InWindows and build_ctype:
        lib_prefix = "lib"
    if not build_ctype:
        lib_suffix = compat.get_extension_suffix()
        target_filename = lib_prefix + lib_name + lib_suffix
    else:
        if compat.InWindows:
            lib_suffix = ".dll"
        else:
            lib_suffix = ".so"
    build_dir = out_path.parent / "build"
    build_dir.mkdir(exist_ok=True)
    target_filename = build_simple_ninja(lib_name, build_dir, source_paths,
                                         includes, libraries, libpaths,
                                         compile_options, link_options,
                                         target_filename, additional_cflags)
    build_out_path = build_dir / target_filename
    out_path = out_path.parent / target_filename
    shutil.copy(build_out_path, out_path)
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
            return ctypes.cdll.LoadLibrary(extension_path)
        return loader.try_import_from_path(extension_path)
    return extension_path


def _parse_sources_get_pybind(lib_name, source_paths, source_contents,
                              export_keyword, export_init_keyword):
    classes = {}
    outside_methods = []
    path_has_export = []
    for path in source_paths:
        path = Path(path)
        source = source_contents[str(path)]
        siter = CppSourceIterator(source)
        all_func_defs = siter.find_function_prefix(export_keyword,
                                                   True,
                                                   True,
                                                   decl_only=True)
        all_cls_init_defs = siter.find_function_prefix(export_init_keyword,
                                                       True,
                                                       True,
                                                       decl_only=True)
        if all_func_defs or all_cls_init_defs:
            path_has_export.append(path)
        for init_def in all_cls_init_defs:
            func_id = init_def.local_id
            parts = func_id.split("::")
            ns_func_id = "::".join(parts[:-1])

            assert ns_func_id in siter.local_id_to_cdef, "init must inside a class"
            cdef = siter.local_id_to_cdef[ns_func_id]
            cls_local_id = cdef.local_id
            if cdef.is_template:
                cls_local_id += "<>"
            if cls_local_id not in classes:
                classes[cls_local_id] = {
                    "inits": [],
                    "methods": [],
                    "is_template": cdef.is_template
                }
            func_name = func_id.split("::")[-1]
            classes[cls_local_id]["inits"].append(cls_local_id + "::" +
                                                  func_name)
        for func_def in all_func_defs:
            func_id = func_def.local_id
            is_template = func_def.is_template

            parts = func_id.split("::")
            if len(parts) == 1:
                outside_methods.append((func_id, is_template))
                continue
            ns_func_id = "::".join(parts[:-1])
            if ns_func_id not in siter.local_id_to_cdef:
                outside_methods.append((func_id, is_template))
                continue
            cdef = siter.local_id_to_cdef[ns_func_id]
            cls_local_id = cdef.local_id
            if cdef.is_template:
                cls_local_id += "<>"
            if cls_local_id not in classes:
                classes[cls_local_id] = {
                    "inits": [],
                    "methods": [],
                    "is_template": cdef.is_template
                }
            func_name = func_id.split("::")[-1]
            classes[cls_local_id]["methods"].append(cls_local_id + "::" +
                                                    func_name)

        for v in classes.values():
            assert len(
                v["inits"]
            ) > 0, "your exported class must have at least one constructor"

    py_module_code_lines = [
        "PYBIND11_MODULE({}, m){{".format(lib_name),
        "  namespace py = pybind11;",
    ]
    for k, v in classes.items():
        class_lines = [
            "  py::class_<{}>(m, \"{}\")".format(
                k,
                k.replace("::", "_").replace("<>", "")),
        ]
        for init in v["inits"]:
            class_lines.append("    .def(py::init(&{}))".format(init))
        for method in v["methods"]:
            method_name = method.split("::")[-1]
            class_lines.append("    .def(\"{}\", &{})".format(
                method_name, method))
        class_lines[-1] += ";"
        py_module_code_lines.extend(class_lines)
    for k, is_template in outside_methods:
        if is_template:
            py_module_code_lines.append("  m.def(\"{}\", &{});".format(
                k.replace("::", "_"), k + "<>"))
        else:
            py_module_code_lines.append("  m.def(\"{}\", &{});".format(
                k.replace("::", "_"), k))
    py_module_code_lines += ["}"]
    return py_module_code_lines, path_has_export


def autoimport(sources: List[Union[str, Path]],
               out_path: Union[str, Path],
               includes: Optional[List[Union[str, Path]]] = None,
               libpaths: Optional[List[Union[str, Path]]] = None,
               libraries: Optional[List[str]] = None,
               export_keyword="CODEAI_EXPORT",
               export_init_keyword="CODEAI_EXPORT_INIT",
               compile_options: Optional[List[str]] = None,
               link_options: Optional[List[str]] = None,
               std="c++14",
               additional_cflags: Optional[Dict[str, List[str]]] = None):
    sources = list(map(lambda p: Path(p).resolve(), sources))
    if includes is None:
        includes = []
    if libpaths is None:
        libpaths = []
    if libraries is None:
        libraries = []
    if additional_cflags is None:
        additional_cflags = {}
    if link_options is None:
        link_options = []
    fill_build_flags(additional_cflags)
    for define in [export_keyword, export_init_keyword]:
        additional_cflags["cl"].append(f"/D{define}=")
        additional_cflags["g++"].append(f"-D{define}=")
        additional_cflags["clang++"].append(f"-D{define}=")
        additional_cflags["nvcc"].append(f"-D{define}=")
    source_contents = {}
    for path in sources:
        path = Path(path)
        with path.open("r") as f:
            source_contents[str(path)] = f.read()

    out_path = Path(out_path)
    lib_name = out_path.stem
    py_module_code_lines, path_has_export = _parse_sources_get_pybind(
        lib_name, sources, source_contents, export_keyword,
        export_init_keyword)
    final_source_lines = _PYBIND_COMMON_INCLUDES.copy()
    final_impl_sources = []
    for s in sources:
        if Path(s) in path_has_export:
            final_source_lines.append("#include \"{}\"".format(s))
        else:
            final_impl_sources.append(s)
    final_source_lines.extend(py_module_code_lines)
    with tempdir() as dirpath:
        path_to_write = Path(dirpath) / "main.cc"
        path_to_write = path_to_write.resolve()
        with path_to_write.open("w") as f:
            f.write("\n".join(final_source_lines))

        mod = ccimport([str(path_to_write), *final_impl_sources],
                       out_path,
                       includes,
                       libpaths,
                       libraries,
                       compile_options,
                       link_options,
                       std=std,
                       source_paths_for_hash=sources,
                       disable_hash=False,
                       additional_cflags=additional_cflags)
        return mod
