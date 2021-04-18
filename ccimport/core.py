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
import os 
import pybind11
from ccimport import compat, loader
from ccimport.buildtools.writer import build_simple_ninja, fill_build_flags
from ccimport.source_iter import CppSourceIterator
from ccimport.utils import tempdir
from ccimport.global_cfg import GLOBAL_CONFIG
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
             additional_cflags: Optional[Dict[str, List[str]]] = None,
             additional_lflags: Optional[Dict[str, List[str]]] = None,
             shared=True,
             msvc_deps_prefix="Note: including file:",
             verbose=False):
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
            py_version_str_p = "{}.{}".format(py_version[0], py_version[1])
            pythonlib = compat.locate_libpython_2(py_version_str_p)
            assert isinstance(pythonlib, str)
            pythonlib = Path(pythonlib)
            libraries.append(pythonlib.stem)
            libpaths.append(pythonlib.parent)
    python_includes = compat.get_pybind11_includes()
    includes.extend(python_includes)
    includes.extend(GLOBAL_CONFIG.includes)
    target_filename = get_full_file_name(lib_name, build_ctype, shared)

    build_dir = out_path.parent / "build"
    build_dir.mkdir(exist_ok=True)
    if "CCIMPORT_MSVC_DEPS_PREFIX" not in os.environ:
        os.environ["CCIMPORT_MSVC_DEPS_PREFIX"] = msvc_deps_prefix
    try:
        target_filename, no_work = build_simple_ninja(lib_name, build_dir, source_paths,
                                            includes, libraries, libpaths,
                                            compile_options, link_options,
                                            target_filename, additional_cflags, 
                                            additional_lflags,
                                            shared=shared, verbose=verbose)
    finally:
        os.environ.pop("CCIMPORT_MSVC_DEPS_PREFIX")
    build_out_path = build_dir / target_filename
    out_path = out_path.parent / target_filename
    if not no_work:
        shutil.copy(str(build_out_path), str(out_path))
        if compat.InWindows and build_ctype:
            win_lib_file = build_out_path.parent / (build_out_path.stem + ".lib")
            if win_lib_file.exists():
                shutil.copy(str(win_lib_file), str(out_path.parent / win_lib_file.name))

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
                              export_kw, export_init_kw, export_init_shared_kw, export_prop_kw):
    classes = {}
    outside_methods = []
    path_has_export = []
    for path in source_paths:
        path = Path(path)
        source = source_contents[str(path)]
        siter = CppSourceIterator(source)
        all_func_defs = siter.find_function_prefix(export_kw,
                                                   True,
                                                   True,
                                                   decl_only=True)
        all_cls_init_defs = siter.find_function_prefix(export_init_kw,
                                                       True,
                                                       True,
                                                       decl_only=True)
        all_cls_init_defs = [(d, False) for d in all_cls_init_defs]
        all_cls_shared_init_defs = siter.find_function_prefix(export_init_shared_kw,
                                                       True,
                                                       True,
                                                       decl_only=True)
        all_cls_shared_init_defs = [(d, True) for d in all_cls_shared_init_defs]
        all_cls_init_defs += all_cls_shared_init_defs
        all_marked_props = siter.find_marked_identifier(export_prop_kw)
        if all_func_defs or all_cls_init_defs:
            path_has_export.append(path)
        for init_def, is_shared in all_cls_init_defs:
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
                    "public_props": [],
                    "is_template": cdef.is_template,
                    "is_shared": is_shared,
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
            assert cls_local_id in classes
            func_name = func_id.split("::")[-1]
            classes[cls_local_id]["methods"].append(cls_local_id + "::" +
                                                    func_name)
        for name, ns in all_marked_props:
            if ns not in siter.local_id_to_cdef:
                print("ignore invalid prop", name, ns)
                continue
            cdef = siter.local_id_to_cdef[ns]
            cls_local_id = cdef.local_id
            if cdef.is_template:
                cls_local_id += "<>"
            assert cls_local_id in classes
            classes[cls_local_id]["public_props"].append(name)

        for v in classes.values():
            assert len(
                v["inits"]
            ) > 0, "your exported class must have at least one constructor"

    py_module_code_lines = [
        "PYBIND11_MODULE({}, m){{".format(lib_name),
        "  namespace py = pybind11;",
    ]
    for k, v in classes.items():
        is_shared = v["is_shared"]
        if is_shared:
            class_lines = [
                "  py::class_<{}, std::shared_ptr<{}>>(m, \"{}\")".format(
                    k, k,
                    k.replace("::", "_").replace("<>", "")),
            ]
        else:
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
        for prop in v["public_props"]: # .def_readwrite("name", &Pet::name);
            class_lines.append("    .def_readwrite(\"{}\", &{}::{})".format(
                prop, k, prop))

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
               export_kw="CODEAI_EXPORT",
               export_init_kw="CODEAI_EXPORT_INIT",
               export_prop_kw="CODEAI_EXPORT_PROP", 
               export_init_shared_kw="CODEAI_EXPORT_SHARED_INIT", 
               compile_options: Optional[List[str]] = None,
               link_options: Optional[List[str]] = None,
               std="c++14",
               disable_hash=False,
               load_library=True,
               additional_cflags: Optional[Dict[str, List[str]]] = None,
               verbose=False):
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
    for define in [export_kw, export_init_kw, export_prop_kw, export_init_shared_kw]:
        additional_cflags["cl"].append("/D{}=".format(define))
        additional_cflags["g++"].append("-D{}=".format(define))
        additional_cflags["clang++"].append("-D{}=".format(define))
        additional_cflags["nvcc"].append("-D{}=".format(define))
    source_contents = {}
    for path in sources:
        path = Path(path)
        with path.open("r") as f:
            source_contents[str(path)] = f.read()

    out_path = Path(out_path)
    lib_name = out_path.stem
    py_module_code_lines, path_has_export = _parse_sources_get_pybind(
        lib_name, sources, source_contents, export_kw,
        export_init_kw, export_init_shared_kw, export_prop_kw)
    final_source_lines = _PYBIND_COMMON_INCLUDES.copy()
    final_impl_sources = []
    for s in sources:
        if Path(s) in path_has_export:
            final_source_lines.append("#include \"{}\"".format(s))
        else:
            final_impl_sources.append(s)
    final_source_lines.extend(py_module_code_lines)
    with tempdir() as dirpath:
        path_to_write = Path(dirpath).resolve() / "main.cc"
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
                       disable_hash=disable_hash,
                       load_library=load_library,
                       additional_cflags=additional_cflags,
                       verbose=verbose)
        return mod
