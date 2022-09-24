import io
import locale
import os
import platform
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from ninja.ninja_syntax import Writer
from ccimport import compat
from ccimport.constants import get_compiler_map, CXX, CUDACXX, HIPCXX
from ccimport.buildmeta import BuildMeta

LOCALE_TO_MSVC_DEP_PREFIX = {
    "en": "Note: including file:",
    "zh": "注意: 包含文件:",
    "en_US": "Note: including file:",
    "zh_CN": "注意: 包含文件:",
}

DEFAULT_MSVC_DEP_PREFIX = LOCALE_TO_MSVC_DEP_PREFIX["en"]

_LOC = locale.getdefaultlocale()[0]
if _LOC is not None:
    if _LOC in LOCALE_TO_MSVC_DEP_PREFIX:
        DEFAULT_MSVC_DEP_PREFIX = LOCALE_TO_MSVC_DEP_PREFIX[_LOC]
    else:
        _LOC_SPLIT = _LOC.split("_")
        if _LOC_SPLIT[0] in LOCALE_TO_MSVC_DEP_PREFIX:
            DEFAULT_MSVC_DEP_PREFIX = LOCALE_TO_MSVC_DEP_PREFIX[_LOC_SPLIT[0]]

ALL_SUPPORTED_COMPILER = set(['cl', 'nvcc', 'g++', 'clang++', "em++"])
ALL_SUPPORTED_LINKER = set(['cl', 'nvcc', 'g++', 'clang++', "em++"])

ALL_SUPPORTED_CPU_COMPILER = set(['cl', 'g++', 'clang++', "em++"])
ALL_SUPPORTED_CUDA_COMPILER = set(['nvcc'])
ALL_SUPPORTED_HIP_COMPILER = set(['hipcc'])

_ALL_OVERRIDE_FLAGS = (set(["/MT", "/MD", "/LD", "/MTd", "/MDd", "/LDd"]), )

ALL_SUPPORTED_PCH_COMPILER = set(['g++', 'clang++', 'cl'])
PCH_COMPILER_NEED_SOURCE = set(['cl'])

COMPILER_TO_PCH_SUFFIX = {
    "clang++": ".pch",
    "cl": ".pch",
    "g++": ".gch",
}


def _get_include_flags_by_compiler(compiler: str, includes: List[Union[Path,
                                                                       str]]):
    if compiler == "cl":
        return " ".join(["/I \"{}\"".format(str(i)) for i in includes])
    else:
        return " ".join(["-I \"{}\"".format(str(i)) for i in includes])


def _make_unique_name(unique_set, name, max_count=10000):
    if name not in unique_set:
        unique_set.add(name)
        return name
    for i in range(max_count):
        new_name = name + "_{}".format(i)
        if new_name not in unique_set:
            unique_set.add(new_name)
            return new_name
    raise ValueError("max count reached")


class UniqueNamePool:

    def __init__(self, max_count=10000):
        self.max_count = max_count
        self.unique_set = set()

    def __call__(self, name):
        return _make_unique_name(self.unique_set, name, self.max_count)


def _list_none(val):
    if val is None:
        return []
    return val


_ALL_COMPILER_PLATFORM = {
    "Linux": set(["g++", 'clang++', 'nvcc', 'hipcc', "em++"]),
    "Darwin": set(["clang++", "em++"]),
    "Windows": set(["cl", 'clang++', 'nvcc', 'hipcc', "em++"]),
}


def _filter_unsupported_compiler(compilers: List[str]):
    all_supported = _ALL_COMPILER_PLATFORM[platform.system()]
    supported = []
    for c in compilers:
        if c.strip() in all_supported:
            supported.append(c)
    return supported


def _override_flags(major_flags, minor_flags):
    """if a flag exists in _ALL_OVERRIDE_FLAGS, the one
    in major flag will override the one in minor.
    """
    flag_to_override = set([])
    for override_flags in _ALL_OVERRIDE_FLAGS:
        for flag in major_flags:
            if flag in override_flags:
                for flag2 in minor_flags:
                    if flag2 in override_flags:
                        flag_to_override.add(flag2)
    new_flags = []
    for flag2 in minor_flags:
        if flag2 not in flag_to_override:
            new_flags.append(flag2)
    return new_flags


def _unify_path(path: Union[str, Path]):
    path = Path(path)
    if path.exists():
        return path.resolve()
    return path

class BaseWritter(Writer):

    def __init__(self,
                 suffix_to_compiler: Dict[str, str],
                 build_dir: Union[Path, str],
                 global_build_meta: BuildMeta,
                 compiler_to_path: Optional[Dict[str, str]] = None,
                 linker_to_path: Optional[Dict[str, str]] = None,
                 out_root: Optional[Union[Path, str]] = None,
                 msvc_stub_dir: str = "msvc_stub",
                 objects_folder: Optional[Union[str, Path]] = None,
                 width=78,
                 use_rspfile_for_windows: bool = True):
        # TODO check available compilers by subprocess.
        self._sstream = io.StringIO()
        super().__init__(self._sstream, width)
        if out_root is None:
            self.out_root: Optional[Path] = None
        else:
            self.out_root: Optional[Path] = Path(out_root).resolve()

        self._build_dir = Path(build_dir).resolve()
        self._msvc_stub_dir = self._build_dir / msvc_stub_dir
        self._suffix_to_compiler_var = {}
        self._suffix_to_rule = {}
        self.global_build_meta = global_build_meta
        self._compiler_var_to_compiler = {}
        self._compiler_to_compiler_var = {}
        self._compiler_linker_map = get_compiler_map()
        self.use_rspfile_for_windows = use_rspfile_for_windows
        if compiler_to_path is None:
            self.compiler_to_path = {}
        else:
            self.compiler_to_path = compiler_to_path
        if linker_to_path is None:
            self.linker_to_path = {}
        else:
            self.linker_to_path = linker_to_path
        if compat.InLinux:
            # CXX only valid in linux
            if CXX is not None:
                # if cxx available, we force all map to
                for compiler in ALL_SUPPORTED_CPU_COMPILER:
                    self.compiler_to_path[compiler] = CXX
                    self.linker_to_path[compiler] = CXX
            if CUDACXX is not None:
                for compiler in ALL_SUPPORTED_CUDA_COMPILER:
                    self.compiler_to_path[compiler] = CUDACXX
                    self.linker_to_path[compiler] = CUDACXX
            if HIPCXX is not None:
                for compiler in ALL_SUPPORTED_HIP_COMPILER:
                    self.compiler_to_path[compiler] = HIPCXX
                    self.linker_to_path[compiler] = HIPCXX

        self.objects_folder = None if objects_folder is None else Path(
            objects_folder)
        if self.objects_folder is not None:
            assert not self.objects_folder.is_absolute(
            ), "objects_folder must be relative"
        suf_to_c_items = list(suffix_to_compiler.items())
        suf_to_c_items.sort(key=lambda x: x[0])
        for suffix, compiler in suf_to_c_items:
            compilers = compiler.split(",")
            compiler = _filter_unsupported_compiler(compilers)[0]
            suffix_ = suffix.replace(".", "_")
            compiler_name = 'compiler_' + suffix_
            if compiler in self.compiler_to_path:
                self.variable(compiler_name, self.compiler_to_path[compiler])
            else:
                self.variable(compiler_name, self.get_mapped_cc_ld(compiler))

            self._suffix_to_compiler_var[suffix] = compiler_name
            self._compiler_var_to_compiler[compiler_name] = compiler
            self._compiler_to_compiler_var[compiler] = compiler_name

        self.variable(
            "msvc_deps_prefix",
            os.getenv("CCIMPORT_MSVC_DEPS_PREFIX", "Note: including file:"))

    @property
    def content(self) -> str:
        return self._sstream.getvalue()

    def get_mapped_cc_ld(self, name: str):
        if name in self._compiler_linker_map:
            return self._compiler_linker_map[name]
        return name

    def gcc_build_setup(self,
                        name,
                        compiler,
                        compiler_var,
                        meta: BuildMeta,
                        pch: bool = False,
                        use_pch: bool = False):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        includes = _get_include_flags_by_compiler(compiler,
                                                  meta.get_global_includes())
        cflags = meta.get_global_cflags().get(compiler, [])
        if pch:
            cflags.append("-x")
            cflags.append("c++-header")

        cflags = " ".join(cflags)

        rule_name = name + "_cxx_{}".format(compiler_var)
        desc = "[GCC][c++]$out"
        if pch:
            rule_name += "_pch"
            desc = "[GCC][c++/pch]$out"
        if use_pch:
            rule_name += "_with_pch"
        compile_stmt = "${} -MMD -MT $out -MF $out.d {} $includes {} $cflags -c $in -o $out"
        if use_pch:
            compile_stmt = "${} -MMD -MT $out -MF $out.d {} $includes {} $cflags -include $pch -c $in -o $out"
        # if pch:
        #     compile_stmt = "${} {} {} -c $in -o $out {}"
        self.rule(rule_name,
                  compile_stmt.format(compiler_var, includes, cflags),
                  description=desc,
                  depfile="$out.d",
                  deps="gcc")

        self.newline()
        return rule_name

    def emcc_build_setup(self,
                        name,
                        compiler,
                        compiler_var,
                        meta: BuildMeta,
                        pch: bool = False,
                        use_pch: bool = False):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        includes = _get_include_flags_by_compiler(compiler,
                                                  meta.get_global_includes())
        cflags = meta.get_global_cflags().get(compiler, [])
        assert not pch, "emcc don't support pch"
        if pch:
            cflags.append("-x")
            cflags.append("c++-header")

        cflags = " ".join(cflags)

        rule_name = name + "_cxx_{}".format(compiler_var)
        desc = "[EMCC][c++]$out"
        if pch:
            rule_name += "_pch"
            desc = "[EMCC][c++/pch]$out"
        if use_pch:
            rule_name += "_with_pch"
        compile_stmt = "${} -MMD -MT $out -MF $out.d {} $includes {} $cflags -c $in -o $out"
        if use_pch:
            compile_stmt = "${} -MMD -MT $out -MF $out.d {} $includes {} $cflags -include $pch -c $in -o $out"
        # if pch:
        #     compile_stmt = "${} {} {} -c $in -o $out {}"
        self.rule(rule_name,
                  compile_stmt.format(compiler_var, includes, cflags),
                  description=desc,
                  depfile="$out.d",
                  deps="gcc")

        self.newline()
        return rule_name

    def gcc_link_setup(self, name, linker, linker_name, meta: BuildMeta, rspfile: str = ""):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        ldflags = " ".join(meta.compiler_to_ldflags.get(linker, []))
        libs = meta.libraries
        lib_flags = []
        for l in libs:
            splits = l.split("::")
            lib_flag = "-l" + str(splits[-1])
            if len(splits) == 2:
                prefix = splits[0]
                if prefix == "file":
                    lib_flag = "-l:" + splits[-1]
                elif prefix == "raw":
                    lib_flag = splits[-1]
                else:
                    raise NotImplementedError(
                        "unsupported lib prefix. supported: file/raw::your_flag"
                    )
            lib_flags.append(lib_flag)
        libs_str = " ".join(lib_flags)
        libpaths_str = " ".join(
            ["-L \"{}\"".format(str(l)) for l in meta.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        desc = "[GCC][Link]$out"
        if rspfile != "":
            self.rule(rule_name,
                    f"${linker_name} @${rspfile} {libs_str} {libpaths_str} {ldflags} -o $out",
                    description=desc,
                    rspfile=f"${rspfile}",
                    rspfile_content="$in")
        else:
            self.rule(rule_name,
                    "${} $in {} {} {} -o $out".format(linker_name, libs_str,
                                                        libpaths_str, ldflags),
                    description=desc)

        self.newline()
        return rule_name

    def emcc_link_setup(self, name, linker, linker_name, meta: BuildMeta, rspfile: str = ""):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        ldflags = " ".join(meta.compiler_to_ldflags.get(linker, []))
        libs = meta.libraries
        lib_flags = []
        for l in libs:
            splits = l.split("::")
            lib_flag = "-l" + str(splits[-1])
            if len(splits) == 2:
                prefix = splits[0]
                if prefix == "file":
                    lib_flag = "-l:" + splits[-1]
                elif prefix == "raw":
                    lib_flag = splits[-1]
                else:
                    raise NotImplementedError(
                        "unsupported lib prefix. supported: file/raw::your_flag"
                    )
            lib_flags.append(lib_flag)
        libs_str = " ".join(lib_flags)
        libpaths_str = " ".join(
            ["-L \"{}\"".format(str(l)) for l in meta.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        desc = "[EMCC][Link]$out"
        if rspfile != "":
            self.rule(rule_name,
                    f"${linker_name} @${rspfile} {libs_str} {libpaths_str} {ldflags} -o $out",
                    description=desc,
                    rspfile=f"${rspfile}",
                    rspfile_content="$in")
        else:
            self.rule(rule_name,
                    "${} $in {} {} {} -o $out".format(linker_name, libs_str,
                                                        libpaths_str, ldflags),
                    description=desc)

        self.newline()
        return rule_name

    def msvc_build_setup(self,
                         name,
                         compiler,
                         compiler_var,
                         meta: BuildMeta,
                         pch: bool = False,
                         use_pch: bool = False):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        includes = _get_include_flags_by_compiler(compiler,
                                                  meta.get_global_includes())
        cflags = meta.get_global_cflags().get(compiler, [])
        cflags = " ".join(cflags)
        rule_name = name + "_cxx_{}".format(compiler_var)
        if pch:
            rule_name += "_pch"
        if use_pch:
            rule_name += "_with_pch"
        compile_stmt = "${} {} {} /nologo /showIncludes $cflags $includes -c $in /Fo$out"
        desc = "[MSVC][c++]$out"
        if pch:
            compile_stmt = "${} {} {} /nologo /showIncludes $cflags $includes -c /Yc$pch /Fp$pchobj $in /Fo$out"
            desc = "[MSVC][c++/pch]$pchobj|$out"
        if use_pch:
            compile_stmt = "${} {} {} /nologo /showIncludes $cflags $includes -c /Yu$pch /Fp$pchobj $in /Fo$out"
        self.rule(rule_name,
                  compile_stmt.format(compiler_var, includes, cflags),
                  deps="msvc",
                  description=desc)

        self.newline()
        return rule_name

    def msvc_link_setup(self, name, linker, linker_name, meta: BuildMeta, rspfile: str = ""):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        ldflags = " ".join(meta.compiler_to_ldflags.get(linker, []))
        libs_str = " ".join([str(l) + ".lib" for l in meta.libraries])
        libpaths_str = " ".join(
            ["/LIBPATH:\"{}\"".format(str(l)) for l in meta.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        desc = "[MSVC][Link]$out"
        if rspfile != "":
            self.rule(rule_name,
                    (f"${linker_name} /link /nologo @${rspfile} "
                    f"{libs_str} {libpaths_str} {ldflags} /out:$out"),
                    description=desc,
                    rspfile=f"${rspfile}",
                    rspfile_content="$in_newline")
        else:
            self.rule(rule_name,
                    "${} /link /nologo $in {} {} {} /out:$out".format(
                        linker_name, libs_str, libpaths_str, ldflags),
                    description=desc)
        self.newline()
        return rule_name

    def nvcc_build_setup(self,
                         name,
                         compiler,
                         compiler_var,
                         meta: BuildMeta,
                         pch: bool = False,
                         use_pch: bool = False):
        assert not pch and not use_pch, "nvcc don't support pch"
        global_meta = self.global_build_meta
        meta = global_meta + meta
        includes = _get_include_flags_by_compiler(compiler,
                                                  meta.get_global_includes())
        cflags = meta.get_global_cflags().get(compiler, [])
        if "-keep" in cflags or "--keep" in cflags:
            cflags.append("--keep-dir $builddir")
        cflags = " ".join(cflags)
        rule_name = name + "_cuda_{}".format(compiler_var)
        MMD = "-MD" if compat.InWindows else "-MMD"
        desc = "[NVCC][c++]$out"
        self.rule(
            rule_name,
            "${} {} -MT $out -MF $out.d {} $includes {} $cflags -c $in -o $out"
            .format(compiler_var, MMD, includes, cflags),
            description=desc,
            depfile="$out.d",
            deps="gcc")
        self.newline()
        return rule_name

    def nvcc_link_setup(self, name, linker, linker_name, meta: BuildMeta, rspfile: str = ""):
        global_meta = self.global_build_meta
        meta = global_meta + meta
        ldflags = " ".join(meta.compiler_to_ldflags.get(linker, []))
        libs = meta.libraries
        libs_str = " ".join(
            ["-l \"{}\"".format(str(l)) for l in meta.libraries])
        libpaths_str = " ".join(
            ["-L \"{}\"".format(str(l)) for l in meta.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        desc = "[NVCC][Link]$out"
        if rspfile != "":
            self.rule(rule_name,
                    f"${linker_name} @${rspfile} {libs_str} {libpaths_str} {ldflags} -o $out",
                    description=desc,
                    rspfile=f"${rspfile}",
                    rspfile_content="$in")
        else:
            self.rule(rule_name,
                    "${} $in {} {} {} -o $out".format(linker_name, libs_str,
                                                        libpaths_str, ldflags),
                    description=desc)            
        self.newline()
        return rule_name

    def create_linker_rule(self, linker, target_name, meta: BuildMeta, rspfile: str):
        link_name = "{}_{}".format(linker, target_name)
        linker_path = None
        if linker in self.linker_to_path:
            linker_path = self.linker_to_path[linker]
        if linker == "g++":
            # ++ can't be used in name
            link_name = "gplusplus_{}".format(target_name)
            self.variable(
                link_name,
                self.get_mapped_cc_ld("g++")
                if linker_path is None else linker_path)
            return self.gcc_link_setup(target_name, linker, link_name, meta, rspfile)
        if linker == "em++":
            # ++ can't be used in name
            link_name = "emplusplus_{}".format(target_name)
            self.variable(
                link_name,
                self.get_mapped_cc_ld("em++")
                if linker_path is None else linker_path)
            return self.emcc_link_setup(target_name, linker, link_name, meta, rspfile)

        elif linker == "clang++":
            link_name = "clang_{}".format(target_name)
            self.variable(
                link_name,
                self.get_mapped_cc_ld("clang++")
                if linker_path is None else linker_path)
            return self.gcc_link_setup(target_name, linker, link_name, meta, rspfile)
        elif linker == "cl":
            self.variable(
                link_name,
                self.get_mapped_cc_ld("link")
                if linker_path is None else linker_path)
            return self.msvc_link_setup(target_name, linker, link_name, meta, rspfile)
        elif linker == "nvcc":
            self.variable(
                link_name,
                self.get_mapped_cc_ld("nvcc")
                if linker_path is None else linker_path)
            return self.nvcc_link_setup(target_name, linker, link_name, meta, rspfile)
        else:
            raise NotImplementedError

    def create_build_rule(self,
                          compiler_name,
                          target_name,
                          meta: BuildMeta,
                          pch: bool = False,
                          use_pch: bool = False):
        compiler = self._compiler_var_to_compiler[compiler_name]
        if compiler == "g++" or compiler == "clang++":
            # self.variable(compiler_name, "g++")
            return self.gcc_build_setup(target_name, compiler, compiler_name,
                                        meta, pch, use_pch)
        elif compiler == "em++" or compiler == "emcc":
            # self.variable(compiler_name, "cl")
            return self.emcc_build_setup(target_name, compiler, compiler_name,
                                         meta, pch, use_pch)
                                        
        elif compiler == "cl":
            # self.variable(compiler_name, "cl")
            return self.msvc_build_setup(target_name, compiler, compiler_name,
                                         meta, pch, use_pch)
        elif compiler == "nvcc":
            # self.variable(compiler_name, "nvcc")
            return self.nvcc_build_setup(target_name, compiler, compiler_name,
                                         meta, pch, use_pch)
        else:
            raise NotImplementedError

    def create_pch_rule(self, compiler_name, target_name, meta: BuildMeta):
        compiler = self._compiler_var_to_compiler[compiler_name]
        if compiler == "g++":
            # self.variable(compiler_name, "g++")
            return self.gcc_build_setup(target_name, compiler, compiler_name,
                                        meta)
        elif compiler == "clang++":
            # self.variable(compiler_name, "cl")
            return self.msvc_build_setup(target_name, compiler, compiler_name,
                                         meta)
        else:
            raise NotImplementedError

    def add_target(self,
                   target_name: str,
                   build_meta: BuildMeta,
                   linker,
                   sources: List[Union[Path, str]],
                   target_filename: str,
                   shared=False,
                   pch_to_sources: Optional[Dict[Union[str, Path],
                                                 List[Union[str,
                                                            Path]]]] = None,
                   pch_to_include: Optional[Dict[Union[str, Path],
                                                 str]] = None,
                   source_meta: Optional[Dict[str, BuildMeta]] = None):
        source_paths = [_unify_path(p) for p in sources]
        if source_meta is None:
            source_meta = {}
        source_meta_unified = {
            _unify_path(p): v
            for p, v in source_meta.items()
        }
        if pch_to_include is not None:
            pch_to_include = {
                _unify_path(p): v
                for p, v in pch_to_include.items()
            }
        if pch_to_sources is None:
            pch_to_sources = {}
        unified_pch_to_sources = {}  # type: Dict[Path, List[Path]]
        for k, v in pch_to_sources.items():
            k_u = _unify_path(k)
            if k_u not in unified_pch_to_sources:
                unified_pch_to_sources[k_u] = []
            unified_pch_to_sources[k_u].extend(_unify_path(p) for p in v)
        compiler_to_rule = {}  # type: Dict[str, str]
        compiler_to_pch_rule = {}  # type: Dict[str, str]

        pch_rule_name = ""
        path_to_pch_obj = {}
        path_to_pch = {}
        path_to_pch_stub_obj = {}

        self.newline()
        # determine PCH compiler
        pch_compiler = ""
        for pch_sources in unified_pch_to_sources.values():
            pch_compiler_determined = False
            for p in pch_sources:
                suffix = p.suffix
                compiler_var = self._suffix_to_compiler_var[suffix]
                compiler = self._compiler_var_to_compiler[compiler_var]
                if compiler in ALL_SUPPORTED_PCH_COMPILER:
                    pch_compiler = compiler
                    pch_compiler_determined = True
                    break
            if pch_compiler_determined:
                break
        name_pool = UniqueNamePool()
        if pch_compiler:
            pch_compiler_name = self._compiler_to_compiler_var[pch_compiler]
            pch_rule_name = self.create_build_rule(pch_compiler_name,
                                                   target_name,
                                                   build_meta,
                                                   pch=True)
            for pch_path, sources_use_pch in unified_pch_to_sources.items():
                assert pch_path.exists()
                pch_valid_count = 0
                valid_source_use_pch = []  # type: List[Path]
                for source_path in sources_use_pch:
                    assert source_path.exists()
                    suffix = source_path.suffix
                    compiler_var = self._suffix_to_compiler_var[suffix]
                    compiler = self._compiler_var_to_compiler[compiler_var]
                    if compiler == pch_compiler:
                        pch_valid_count += 1
                        valid_source_use_pch.append(source_path)
                if pch_valid_count > 1:
                    pch_obj_path = str(
                        self._create_output_path(
                            pch_path,
                            name_pool,
                            suffix=COMPILER_TO_PCH_SUFFIX[pch_compiler]))
                    stub_obj_file = None
                    # compile pch here
                    cflags = ""
                    incs = ""
                    if pch_path in source_meta_unified:
                        meta = source_meta_unified[pch_path]
                        cflags = " ".join(meta.get_local_cflags().get(
                            pch_compiler, []))
                        incs = _get_include_flags_by_compiler(
                            pch_compiler, meta.get_local_includes())

                    if pch_compiler == "cl":
                        assert pch_to_include is not None
                        # create a stub file for this include
                        stub_file = self._create_msvc_stub_path(
                            pch_path, name_pool)
                        write_stub = True
                        stub_content = "#include <{}>".format(
                            pch_to_include[pch_path])
                        if stub_file.exists():
                            with stub_file.open("r") as f:
                                data = f.read().strip()
                            write_stub = data != stub_content.strip()
                        if write_stub:
                            with stub_file.open("w") as f:
                                f.write(stub_content)
                        stub_obj_file = str(stub_file.parent /
                                            (stub_file.name + ".o"))
                        self.build(stub_obj_file,
                                   pch_rule_name,
                                   str(stub_file),
                                   variables={
                                       "pch": pch_to_include[pch_path],
                                       'pchobj': pch_obj_path,
                                       "cflags": cflags,
                                       "includes": incs,
                                   })
                    else:
                        self.build(pch_obj_path,
                                   pch_rule_name,
                                   str(pch_path),
                                   variables={
                                       "cflags": cflags,
                                       "includes": incs,
                                   })
                    for source_path in sources_use_pch:
                        assert source_path.exists()
                        suffix = source_path.suffix
                        compiler_var = self._suffix_to_compiler_var[suffix]
                        compiler = self._compiler_var_to_compiler[compiler_var]
                        if compiler == pch_compiler:
                            path_to_pch_obj[source_path] = str(pch_obj_path)
                            path_to_pch[source_path] = str(pch_path)
                            if pch_compiler == "cl":
                                path_to_pch_stub_obj[
                                    source_path] = stub_obj_file
        path_to_rule = {}
        path_to_compiler = {}

        for p in source_paths:
            suffix = p.suffix
            compiler_var = self._suffix_to_compiler_var[suffix]
            compiler = self._compiler_var_to_compiler[compiler_var]
            if p in path_to_pch_obj and compiler == pch_compiler:
                # compile pch rule
                if compiler in compiler_to_pch_rule:
                    rule_name = compiler_to_pch_rule[compiler]
                else:
                    compiler = self._compiler_var_to_compiler[compiler_var]
                    rule_name = self.create_build_rule(compiler_var,
                                                       target_name,
                                                       build_meta,
                                                       use_pch=True)
                    compiler_to_pch_rule[compiler] = rule_name
            else:
                if compiler in compiler_to_rule:
                    rule_name = compiler_to_rule[compiler]
                else:
                    compiler = self._compiler_var_to_compiler[compiler_var]
                    rule_name = self.create_build_rule(compiler_var,
                                                       target_name, build_meta)
                    compiler_to_rule[compiler] = rule_name
            path_to_rule[p] = rule_name
            path_to_compiler[p] = compiler
        # for k, v in compiler_to_option.items():
        # we will modify build_meta, so copy it.
        build_meta = build_meta.copy()
        linker_flags = build_meta.compiler_to_ldflags.get(linker, [])
        if shared:
            if linker not in ["emcc", "em++"]:
                if not compat.InWindows:
                    build_meta.add_ldflags(linker, "-shared")
                    linker_flags.append("-shared")
                else:

                    build_meta.add_ldflags(linker, "/dll")

                    linker_flags.append("/dll")
            # else:
                # build_meta.add_ldflags(linker, "-sSIDE_MODULE")
                # linker_flags.append("-sSIDE_MODULE")

        if (Path(target_filename).is_absolute()):
            target_path = Path(target_filename)
        else:
            target_path = self._build_dir / target_filename
        # rspfile = Path(target_filename).stem + ".rsp"
        rspfile = "out.rsp"
        link_rule = self.create_linker_rule(linker, target_name, build_meta, rspfile)
        self.newline()
        obj_files = []
        stub_obj_files = set()
        # print(source_meta_unified)
        for p in source_paths:
            assert p.exists()
            obj_path = str(self._create_output_path(p, name_pool))
            obj_files.append(obj_path)
            rule = path_to_rule[p]
            compiler = path_to_compiler[p]
            cflags = ""
            incs = ""
            if p in source_meta_unified:
                meta = source_meta_unified[p]
                cflags = " ".join(meta.get_local_cflags().get(compiler, []))
                incs = _get_include_flags_by_compiler(
                    compiler, meta.get_local_includes())
            # print(p in source_meta_unified, compiler)
            if p in path_to_pch_obj:
                pch_obj = path_to_pch_obj[p]
                pch_path = path_to_pch[p]
                if pch_compiler == "cl":
                    stub = path_to_pch_stub_obj[p]
                    stub_obj_files.add(stub)
                    self.build(obj_path,
                               rule,
                               str(p),
                               variables={
                                   "pch": pch_to_include[Path(pch_path)],
                                   "pchobj": pch_obj,
                                   "builddir": str(p.parent),
                                   "cflags": cflags,
                                   "includes": incs,
                               },
                               implicit=[stub])
                else:
                    self.build(obj_path,
                               rule,
                               str(p),
                               variables={
                                   "pch": pch_path,
                                   "builddir": str(p.parent),
                                   "cflags": cflags,
                                   "includes": incs,
                               },
                               implicit=[pch_obj])

            else:
                self.build(obj_path,
                           rule,
                           str(p),
                           variables={
                               "builddir": str(p.parent),
                               "cflags": cflags,
                               "includes": incs,
                           })
        # breakpoint()
        self.newline()
        stub_obj_files_list = list(stub_obj_files)
        stub_obj_files_list.sort()
        self.build(str(target_path), link_rule,
                   obj_files + stub_obj_files_list)
        self.build(target_name, "phony", str(target_path))
        self.default(target_name)

    def _create_output_path(self,
                            p: Path,
                            name_pool: UniqueNamePool,
                            suffix: str = ".o"):
        if self.objects_folder is not None:
            source_out_parent = self._build_dir / self.objects_folder
        else:
            source_out_parent = self._build_dir
            if self.out_root is not None:
                out_root = self.out_root
                try:
                    relative = p.parent.relative_to(out_root)
                    source_out_parent = self._build_dir / relative
                except ValueError:
                    source_out_parent = self._build_dir
        source_out_parent.mkdir(exist_ok=True, parents=True, mode=0o755)
        obj_path_no_suffix = (source_out_parent / (p.name))
        obj_path_no_suffix = Path(name_pool(str(obj_path_no_suffix)))
        obj_path = obj_path_no_suffix.parent / (obj_path_no_suffix.name +
                                                suffix)
        assert obj_path.parent.exists()

        if self.objects_folder is not None:
            # cwd is build_dir, so we just use relative path to avoid
            # 'command too long' in windows.
            return obj_path.relative_to(self._build_dir)
        return obj_path

    def _create_msvc_stub_path(self,
                               p: Path,
                               name_pool: UniqueNamePool,
                               suffix: str = ".cc"):
        source_out_parent = self._msvc_stub_dir
        if self.out_root is not None:
            out_root = self.out_root
            try:
                relative = p.parent.relative_to(out_root)
                source_out_parent = self._msvc_stub_dir / relative
            except ValueError:
                source_out_parent = self._msvc_stub_dir
        source_out_parent.mkdir(exist_ok=True, parents=True, mode=0o755)
        obj_path_no_suffix = (source_out_parent / (p.name))
        obj_path_no_suffix = Path(name_pool(str(obj_path_no_suffix)))
        obj_path = obj_path_no_suffix.parent / (obj_path_no_suffix.name +
                                                suffix)
        assert obj_path.parent.exists()
        return obj_path

    def add_shared_target(self, target_name: str, build_meta: BuildMeta,
                          linker, sources: List[Union[Path, str]],
                          target_filename: str):
        return self.add_target(target_name, build_meta, linker, sources,
                               target_filename, True)


def _default_suffix_to_compiler():
    if compat.InWindows:
        return {
            ".cc": "cl",
            ".cpp": "cl",
            ".cxx": "cl",
            ".cu": "nvcc",
        }
    else:
        return {
            ".cc": "g++",
            ".cpp": "g++",
            ".cxx": "g++",
            ".cu": "nvcc",
            ".hip": "hipcc",
        }


COMMON_NVCC_FLAGS = [
    # '-D__CUDA_NO_HALF_OPERATORS__', '-D__CUDA_NO_HALF_CONVERSIONS__',
    # '-D__CUDA_NO_HALF2_OPERATORS__',
    '-Xcompiler=\"-fPIC\"',
    '-Xcompiler=\'-O3\''
]

COMMON_NVCC_FLAGS_WINDOWS = ['-Xcompiler=\"/O2\"']

COMMON_MSVC_FLAGS = [
    '/MD', '/wd4819', '/wd4251', '/wd4244', '/wd4267', '/wd4275', '/wd4018',
    '/wd4190', '/EHsc', '/Zc:__cplusplus'
]

COMMON_HIPCC_FLAGS = [
    '-fPIC',
    '-D__HIP_PLATFORM_HCC__=1',
    '-DCUDA_HAS_FP16=1',
    '-D__HIP_NO_HALF_OPERATORS__=1',
    '-D__HIP_NO_HALF_CONVERSIONS__=1',
]


def default_build_meta():
    if compat.InWindows:
        nvcc_flags = COMMON_NVCC_FLAGS_WINDOWS.copy()
    else:
        nvcc_flags = COMMON_NVCC_FLAGS.copy()

    if compat.InWindows:
        nvcc_flags.extend("-Xcompiler=\"{}\"".format(c)
                          for c in COMMON_MSVC_FLAGS)
    meta = BuildMeta()
    meta.add_cflags("cl", *COMMON_MSVC_FLAGS)
    meta.add_cflags("nvcc", *nvcc_flags)
    meta.add_cflags("clang++", "-fPIC")
    meta.add_cflags("g++", "-fPIC")
    # TODO em++ need fPIC?
    meta.add_cflags("em++", "-fPIC")
    return meta


def _default_linker():
    if compat.InWindows:
        return "cl"
    else:
        return "g++"


def _default_target_filename(target, shared=True):
    # if Path(target).suffix
    if shared:
        if compat.InWindows:
            return target + ".dll"
        else:
            return "lib" + target + ".so"
    else:
        if compat.InWindows:
            return target + ".exe"
        else:
            return target


def fill_build_flags(
        build_flags: Optional[Dict[str, List[str]]]) -> Dict[str, List[str]]:
    """fill compile/link compiler-to-list flags with all compiler.
    """
    if build_flags is None:
        build_flags = {}
    for comp in ALL_SUPPORTED_COMPILER:
        if comp not in build_flags:
            build_flags[comp] = []
    return build_flags


def fill_link_flags(
        link_flags: Optional[Dict[str, List[str]]]) -> Dict[str, List[str]]:
    """fill compile/link compiler-to-list flags with all compiler.
    """
    if link_flags is None:
        link_flags = {}
    for comp in ALL_SUPPORTED_LINKER:
        if comp not in link_flags:
            link_flags[comp] = []
    return link_flags


def group_dict_by_split(data: Dict[str, List[Any]], split: str = ","):
    """convert {gcc,clang++: [xxx], clang++: [yyy]}
    to {gcc: [xxx], clang++: [xxx, yyy]}
    """
    new_data = OrderedDict()  # type: Dict[str, List[Any]]
    for k, v in data.items():
        ks = k.split(split)
        for k_ in ks:
            k_ = k_.strip()
            if k_ not in new_data:
                new_data[k_] = []
            new_data[k_].extend(v)
    return new_data


def create_simple_ninja(
        target,
        build_dir,
        sources,
        build_meta: BuildMeta,
        target_filename=None,
        suffix_to_compiler=None,
        out_root: Optional[Union[Path, str]] = None,
        shared=False,
        pch_to_sources: Optional[Dict[Union[str, Path],
                                      List[Union[str, Path]]]] = None,
        pch_to_include: Optional[Dict[Union[str, Path], str]] = None,
        objects_folder: Optional[Union[str, Path]] = None,
        compiler_to_path: Optional[Dict[str, str]] = None,
        linker_to_path: Optional[Dict[str, str]] = None,
        source_meta: Optional[Dict[str, BuildMeta]] = None,
        linker: Optional[str] = None):
    default_suffix_to_compiler = _default_suffix_to_compiler()
    suffix_to_compiler_ = default_suffix_to_compiler
    if suffix_to_compiler is not None:
        suffix_to_compiler_.update(suffix_to_compiler)
    if linker is None:
        linker = _default_linker()
    build_meta = build_meta + default_build_meta()
    if target_filename is None:
        target_filename = _default_target_filename(target, shared)
    else:
        path = Path(target_filename)
        if path.suffix == "":
            # add default suffix
            target_filename = str(path.parent /
                                  _default_target_filename(path.stem, shared))

    writer = BaseWritter(suffix_to_compiler_,
                         build_dir,
                         build_meta,
                         compiler_to_path,
                         linker_to_path,
                         out_root,
                         objects_folder=objects_folder)
    writer.add_target(target, build_meta, linker, sources, target_filename,
                      shared, pch_to_sources, pch_to_include, source_meta)
    return writer.content, target_filename


def build_simple_ninja(
        target,
        build_dir,
        sources,
        build_meta: BuildMeta,
        target_filename=None,
        suffix_to_compiler=None,
        out_root: Optional[Union[Path, str]] = None,
        verbose=False,
        shared=True,
        pch_to_sources: Optional[Dict[Union[str, Path],
                                      List[Union[str, Path]]]] = None,
        pch_to_include: Optional[Dict[Union[str, Path], str]] = None,
        objects_folder: Optional[Union[str, Path]] = None,
        compiler_to_path: Optional[Dict[str, str]] = None,
        linker_to_path: Optional[Dict[str, str]] = None,
        source_meta: Optional[Dict[str, BuildMeta]] = None,
        linker: Optional[str] = None):
    ninja_content, target_filename = create_simple_ninja(
        target, build_dir, sources, build_meta, target_filename,
        suffix_to_compiler, out_root, shared, pch_to_sources, pch_to_include,
        objects_folder, compiler_to_path, linker_to_path, source_meta, linker)
    build_dir = Path(build_dir).resolve()
    content = ""
    if (build_dir / "build.ninja").exists():
        with (build_dir / "build.ninja").open("r") as f:
            content = f.read()
    if content != ninja_content:
        with (build_dir / "build.ninja").open("w") as f:
            f.write(ninja_content)
    # TODO: check_call don't raise, this is a problem
    cmds = ["ninja"]
    if verbose:
        cmds.append("-v")
    if compat.Python3_7AndLater:
        proc = subprocess.Popen(cmds,
                                cwd=str(build_dir),
                                stdout=subprocess.PIPE,
                                text=True)
    else:
        proc = subprocess.Popen(cmds,
                                cwd=str(build_dir),
                                stdout=subprocess.PIPE,
                                universal_newlines=True)
    output = ''
    while True:
        chunk_or_line = proc.stdout.readline()
        if not chunk_or_line:
            break
        output += chunk_or_line
        # print(chunk_or_line.encode("utf-8"))
        if not "ninja: no work to do" in chunk_or_line:
            print(chunk_or_line, end='')
    proc.wait()
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, cmds)

    no_work_to_do = False
    if "ninja: no work to do" in output:
        no_work_to_do = True
    return target_filename, no_work_to_do


def run_simple_ninja(target,
                     build_dir,
                     sources,
                     build_meta: BuildMeta,
                     target_filename=None,
                     source_meta: Optional[Dict[str, BuildMeta]] = None):
    ninja_content, target_filename = create_simple_ninja(
        target,
        build_dir,
        sources,
        build_meta,
        target_filename,
        shared=False,
        source_meta=source_meta)
    build_dir = Path(build_dir)
    content = ""
    if (build_dir / "build.ninja").exists():
        with (build_dir / "build.ninja").open("r") as f:
            content = f.read()
    if content != ninja_content:
        with (build_dir / "build.ninja").open("w") as f:
            f.write(ninja_content)
    # TODO: check_call don't raise, this is a problem
    subprocess.check_call(["ninja", "-v"], cwd=str(build_dir))
    subprocess.check_call([str(build_dir / target_filename)],
                          cwd=str(build_dir))
    return target_filename
