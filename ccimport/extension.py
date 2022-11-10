import abc
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union

from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext

import ccimport
from ccimport import compat


class ExtCallback(abc.ABC):
    @abc.abstractmethod
    def __call__(self, ext: "CCImportExtension",
                 extdir: Path, target_path: Path):
        pass


class CCImportExtension(Extension):
    def __init__(self,
                 name,
                 sources: List[Union[str, Path]],
                 out_path: Union[str, Path],
                 build_meta: ccimport.BuildMeta,
                 std="c++14",
                 build_ctype=False,
                 additional_cflags: Optional[Dict[str, List[str]]] = None,
                 shared=True,
                 verbose=False,
                 extcallback: Optional[ExtCallback] = None,
                 sourcedir='',
                 library_dirs=[]):
        Extension.__init__(self, name, sources=[], library_dirs=library_dirs)
        self.sourcedir = os.path.abspath(sourcedir)
        self._ccimp_sources = sources
        self._ccimp_out_relative_path = out_path
        self._ccimp_build_meta = build_meta
        self._ccimp_std = std
        self._ccimp_additional_cflags = additional_cflags
        self._ccimp_build_ctype = build_ctype
        self._ccimp_verbose = verbose
        self._ccimp_shared = shared
        self._ccimp_callback = extcallback


class CCImportBuild(build_ext):
    def run(self):
        # override build_ext.run to avoid copy
        for ext in self.extensions:
            self.build_extension(ext)

    def build_extension(self, ext):
        if not isinstance(ext, CCImportExtension):
            return super().build_extension(ext)
        extdir = os.path.abspath(
            os.path.dirname(self.get_ext_fullpath(ext.name)))
        extdir = Path(extdir)
        out_path = extdir / ext._ccimp_out_relative_path
        if out_path.exists():
            shutil.rmtree(out_path)
        if not os.path.exists(self.build_temp):
            Path(self.build_temp).mkdir(exist_ok=True,
                                        parents=True,
                                        mode=0o755)
        build_out_path = Path.cwd() / Path(self.build_temp) / ext._ccimp_out_relative_path
        build_out_path.parent.mkdir(exist_ok=True, parents=True, mode=0o755)
        out_path.parent.mkdir(exist_ok=True, parents=True, mode=0o755)
        libpaths = []
        lib_path = ccimport.ccimport(
            source_paths=ext._ccimp_sources,
            out_path=build_out_path,
            build_meta=ext._ccimp_build_meta,
            std=ext._ccimp_std,
            disable_hash=True,
            load_library=False,
            build_ctype=ext._ccimp_build_ctype,
            verbose=ext._ccimp_verbose,
            shared=ext._ccimp_shared,
        )
        lib_path = Path(lib_path)
        out_lib_path = out_path.parent / lib_path.name
        shutil.copy(str(lib_path), str(out_lib_path))
        if compat.InWindows:
            lib_path = Path(lib_path)
            win_lib_path = lib_path.parent / (lib_path.stem + ".lib")
            if win_lib_path.exists():
                shutil.copy(str(win_lib_path),
                            str(out_lib_path.parent / win_lib_path.name))
        if ext._ccimp_callback is not None:
            ext._ccimp_callback(ext, extdir, out_lib_path)
