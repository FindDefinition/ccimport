import io
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union
import os 
from ninja.ninja_syntax import Writer
from collections import OrderedDict
from ccimport import compat

ALL_SUPPORTED_COMPILER = set(['cl', 'nvcc', 'g++', 'clang++'])
ALL_SUPPORTED_LINKER = set(['cl', 'nvcc', 'g++', 'clang++'])

_ALL_OVERRIDE_FLAGS = (set(["/MT", "/MD", "/LD", "/MTd", "/MDd", "/LDd"]), )

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
    "Linux": set(["g++", 'clang++', 'nvcc', 'hipcc']),
    "Darwin": set(["clang++"]),
    "Windows": set(["cl", 'clang++', 'nvcc', 'hipcc']),
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


class BuildOptions:
    def __init__(self,
                 includes: Optional[List[Union[Path, str]]] = None,
                 cflags: Optional[List[str]] = None,
                 post_cflags: Optional[List[str]] = None):
        self.includes = _list_none(includes)
        self.cflags = _list_none(cflags)
        self.post_cflags = _list_none(post_cflags)

    def copy(self):
        return BuildOptions(self.includes.copy(), self.cflags.copy(),
                            self.post_cflags.copy())


    def merge(self, opt: "BuildOptions"):
        res = self.copy()
        res.includes.extend(opt.includes)
        res.cflags.extend(_override_flags(res.cflags, opt.cflags))
        res.post_cflags.extend(
            _override_flags(res.post_cflags, opt.post_cflags))
        return res


class LinkOptions:
    def __init__(self,
                 libpaths: Optional[List[Union[Path, str]]] = None,
                 libs: Optional[List[str]] = None,
                 ldflags: Optional[List[str]] = None):
        self.libpaths = _list_none(libpaths)
        self.libs = _list_none(libs)
        self.ldflags = _list_none(ldflags)

    def copy(self):
        return LinkOptions(self.libpaths.copy(), self.libs.copy(),
                           self.ldflags.copy())

    def merge(self, opt: "LinkOptions"):
        res = self.copy()
        res.libpaths.extend(opt.libpaths)
        res.libs.extend(opt.libs)
        res.ldflags.extend(opt.ldflags)
        return res


class BaseWritter(Writer):
    def __init__(self,
                 suffix_to_compiler: Dict[str, str],
                 build_dir: Union[Path, str],
                 compiler_build_opts: Dict[str, BuildOptions],
                 compiler_link_opts: Dict[str, LinkOptions],
                 compiler_to_path: Dict[str, str],
                 linker_to_path: Dict[str, str],
                 width=78):
        # TODO check available compilers by subprocess.
        self._sstream = io.StringIO()
        super().__init__(self._sstream, width)

        self._build_dir = Path(build_dir).resolve()
        self._suffix_to_cl = {}
        self._suffix_to_rule = {}
        self.compiler_build_opts = compiler_build_opts
        self.compiler_link_opts = compiler_link_opts
        self._compiler_var_to_name = {}
        self.compiler_to_path = compiler_to_path
        self.linker_to_path = linker_to_path
        suf_to_c_items = list(suffix_to_compiler.items())
        suf_to_c_items.sort(key=lambda x: x[0])
        for suffix, compiler in suf_to_c_items:
            compilers = compiler.split(",")
            compiler = _filter_unsupported_compiler(compilers)[0]
            suffix_ = suffix.replace(".", "_")
            compiler_name = 'compiler_' + suffix_
            if compiler in compiler_to_path:
                self.variable(compiler_name, compiler_to_path[compiler])
            else:
                self.variable(compiler_name, compiler)

            self._suffix_to_cl[suffix] = compiler_name
            self._compiler_var_to_name[compiler_name] = compiler
        self.variable("msvc_deps_prefix",  os.getenv("CCIMPORT_MSVC_DEPS_PREFIX", "Note: including file:"))

    @property
    def content(self) -> str:
        return self._sstream.getvalue()

    def gcc_build_setup(self, name, compiler, compiler_var,
                        opts: BuildOptions):
        global_build_opts = self.compiler_build_opts.get(
            compiler, BuildOptions())
        opts = opts.merge(global_build_opts)
        includes = " ".join(["-I \"{}\"".format(str(i)) for i in opts.includes])
        cflags = opts.cflags
        post_cflags = opts.post_cflags
        cflags = " ".join(cflags)
        post_cflags = " ".join(post_cflags)
        rule_name = name + "_cxx_{}".format(compiler_var)
        self.rule(
            rule_name,
            "${} -MMD -MT $out -MF $out.d {} {} -c $in -o $out {}".format(compiler_var, includes, cflags, post_cflags),
            description="compile $out",
            depfile="$out.d",
            deps="gcc")
        self.newline()
        return rule_name

    def gcc_link_setup(self, name, linker, linker_name, opts: LinkOptions):
        global_build_opts = self.compiler_link_opts.get(
            linker, LinkOptions())
        opts = opts.merge(global_build_opts)
        ldflags = " ".join(opts.ldflags)
        libs = opts.libs
        lib_flags = []
        for l in libs:
            splits = l.split("::")
            lib_flag = "-l" + str(splits[-1])
            if len(splits) == 2:
                prefix = splits[0]
                if prefix == "path":
                    lib_flag = splits[-1]
                elif prefix == "file":
                    lib_flag = "-l:" + splits[-1]
                else:
                    raise NotImplementedError("unsupported lib prefix. supported: static and path")
            lib_flags.append(lib_flag)
        libs_str = " ".join(lib_flags)
        libpaths_str = " ".join(["-L \"{}\"".format(str(l)) for l in opts.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        self.rule(
            rule_name,
            "${} $in {} {} {} -o $out".format(linker_name, libs_str, libpaths_str, ldflags),
            description="link $out")
        self.newline()
        return rule_name

    def msvc_build_setup(self, name, compiler, compiler_var,
                         opts: BuildOptions):
        global_build_opts = self.compiler_build_opts.get(
            compiler, BuildOptions())
        opts = opts.merge(global_build_opts)
        includes = " ".join(
            ["/I \"{}\"".format(str(i)) for i in opts.includes])
        cflags = opts.cflags
        post_cflags = opts.post_cflags
        cflags = " ".join(cflags)
        post_cflags = " ".join(post_cflags)
        rule_name = name + "_cxx_{}".format(compiler_var)
        self.rule(
            rule_name,
            "${} {} {} /showIncludes -c $in /Fo$out {}".format(compiler_var, includes, cflags, post_cflags),
            deps="msvc"
        )
        self.newline()
        return rule_name

    def msvc_link_setup(self, name, linker, linker_name, opts: LinkOptions):
        global_build_opts = self.compiler_link_opts.get(
            linker, LinkOptions())
        opts = opts.merge(global_build_opts)
        ldflags = " ".join(opts.ldflags)
        libs_str = " ".join([str(l) + ".lib" for l in opts.libs])
        libpaths_str = " ".join(
            ["/LIBPATH:\"{}\"".format(str(l)) for l in opts.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        self.rule(
            rule_name,
            "${} /link /nologo $in {} {} {} /out:$out".format(linker_name, libs_str, libpaths_str, ldflags),
            description="link msvc $out")
        self.newline()
        return rule_name

    def nvcc_build_setup(self, name, compiler, compiler_var,
                         opts: BuildOptions):
        global_build_opts = self.compiler_build_opts.get(
            compiler, BuildOptions())
        opts = opts.merge(global_build_opts)
        includes = " ".join(["-I \"{}\"".format(str(i)) for i in opts.includes])
        cflags = opts.cflags
        post_cflags = opts.post_cflags
        cflags = " ".join(cflags)
        post_cflags = " ".join(post_cflags)
        rule_name = name + "_cuda_{}".format(compiler_var)
        MMD = "-MD" if compat.InWindows else "-MMD"
        self.rule(
            rule_name,
            "${} {} -MT $out -MF $out.d {} {} -c $in -o $out {}".format(compiler_var, MMD, includes, cflags, post_cflags),
            description="nvcc cxx $out",
            depfile="$out.d",
            deps="gcc")
        self.newline()
        return rule_name

    def nvcc_link_setup(self, name, linker, linker_name, opts: LinkOptions):
        global_build_opts = self.compiler_link_opts.get(
            linker, LinkOptions())
        opts = opts.merge(global_build_opts)
        ldflags = " ".join(opts.ldflags)
        libs_str = " ".join(["-l \"{}\"".format(str(l)) for l in opts.libs])
        libpaths_str = " ".join(["-L \"{}\"".format(str(l)) for l in opts.libpaths])
        rule_name = name + "_ld_{}".format(linker_name)
        libpaths_str = " ".join(["-L \"{}\"".format(str(l)) for l in opts.libpaths])
        self.rule(
            rule_name,
            "${} $in {} {} {} -o $out".format(linker_name, libs_str, libpaths_str, ldflags),
            description="link $out")
        self.newline()
        return rule_name

    def create_linker_rule(self, linker, target_name, link_opts: LinkOptions):
        link_name = "{}_{}".format(linker, target_name)
        linker_path = None
        if linker in self.linker_to_path:
            linker_path = self.linker_to_path[linker]
        if linker == "g++":
            # ++ can't be used in name
            link_name = "gplusplus_{}".format(target_name)
            self.variable(link_name,
                          'g++' if linker_path is None else linker_path)
            return self.gcc_link_setup(target_name, linker, link_name,
                                       link_opts)
        elif linker == "clang++":
            link_name = "clang_{}".format(target_name)
            self.variable(link_name,
                          "clang++" if linker_path is None else linker_path)
            return self.gcc_link_setup(target_name, linker, link_name,
                                       link_opts)
        elif linker == "cl":
            self.variable(link_name,
                          "link" if linker_path is None else linker_path)
            return self.msvc_link_setup(target_name, linker, link_name,
                                        link_opts)
        elif linker == "nvcc":
            self.variable(link_name,
                          "nvcc" if linker_path is None else linker_path)
            return self.nvcc_link_setup(target_name, linker, link_name,
                                        link_opts)
        else:
            raise NotImplementedError

    def create_build_rule(self, compiler_name, target_name,
                          opts: BuildOptions):
        compiler = self._compiler_var_to_name[compiler_name]
        if compiler == "g++" or compiler == "clang++":
            # self.variable(compiler_name, "g++")
            return self.gcc_build_setup(target_name, compiler, compiler_name,
                                        opts)
        elif compiler == "cl":
            # self.variable(compiler_name, "cl")
            return self.msvc_build_setup(target_name, compiler, compiler_name,
                                         opts)
        elif compiler == "nvcc":
            # self.variable(compiler_name, "nvcc")
            return self.nvcc_build_setup(target_name, compiler, compiler_name,
                                         opts)
        else:
            raise NotImplementedError

    def add_target(self,
                   target_name: str,
                   compiler_to_option: Dict[str, BuildOptions],
                   linker,
                   link_opts: LinkOptions,
                   sources: List[Union[Path, str]],
                   target_filename: str,
                   shared=False):
        source_paths = [Path(p) for p in sources]
        path_to_rule = {}
        compiler_to_rule = {}
        self.newline()
        for p in source_paths:
            suffix = p.suffix
            compiler_var = self._suffix_to_cl[suffix]
            compiler = self._compiler_var_to_name[compiler_var]
            if compiler in compiler_to_rule:
                rule_name = compiler_to_rule[compiler]
            else:
                compiler = self._compiler_var_to_name[compiler_var]
                rule_name = self.create_build_rule(
                    compiler_var, target_name, compiler_to_option[compiler])
                compiler_to_rule[compiler] = rule_name
            path_to_rule[p] = rule_name
        # for k, v in compiler_to_option.items():
        link_opts = link_opts.copy()
        if shared:
            if not compat.InWindows:
                link_opts.ldflags.append("-shared")
            else:
                link_opts.ldflags.append("/dll")
        link_rule = self.create_linker_rule(linker, target_name, link_opts)
        self.newline()
        if (Path(target_filename).is_absolute()):
            target_path = Path(target_filename)
        else:
            target_path = self._build_dir / target_filename
        obj_files = []
        name_pool = UniqueNamePool()
        for p in source_paths:
            assert p.exists()
            suffix = ".o"
            file_name = name_pool(p.name)
            obj = (self._build_dir / (file_name + suffix))
            assert obj.parent.exists()
            obj = str(obj)
            obj_files.append(obj)
            rule = path_to_rule[p]
            self.build(obj, rule, str(p))
        self.newline()
        self.build(str(target_path), link_rule, obj_files)
        self.build(target_name, "phony", str(target_path))
        self.default(target_name)

    def add_shared_target(self, target_name: str,
                          compiler_to_option: Dict[str, BuildOptions], linker,
                          link_opts: LinkOptions,
                          sources: List[Union[Path, str]],
                          target_filename: str):
        return self.add_target(target_name, compiler_to_option, linker,
                               link_opts, sources, target_filename, True)


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
    '-D__CUDA_NO_HALF_OPERATORS__', '-D__CUDA_NO_HALF_CONVERSIONS__',
    '-D__CUDA_NO_HALF2_OPERATORS__', '--expt-relaxed-constexpr',
    '-Xcompiler=\"-fPIC\"', '-Xcompiler=\'-O3\''
]

COMMON_NVCC_FLAGS_WINDOWS = [
    '--expt-relaxed-constexpr', '-Xcompiler=\"/O2\"'
]


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


def _default_build_options():
    if compat.InWindows:
        nvcc_flags = COMMON_NVCC_FLAGS_WINDOWS.copy()
    else:
        nvcc_flags = COMMON_NVCC_FLAGS.copy()

    if compat.InWindows:
        nvcc_flags.extend("-Xcompiler=\"{}\"".format(c)
                          for c in COMMON_MSVC_FLAGS)
    return {
        "cl": BuildOptions([], COMMON_MSVC_FLAGS.copy()),
        "nvcc": BuildOptions([], nvcc_flags),
        "clang++": BuildOptions([], ["-fPIC"]),
        "g++": BuildOptions([], ["-fPIC"]),
    }


def _default_link_options():
    return {
        "cl": LinkOptions([], [], []),
        "nvcc": LinkOptions(),
        "clang++": LinkOptions(),
        "g++": LinkOptions(),
    }


def _default_linker():
    if compat.InWindows:
        return "cl"
    else:
        return "g++"


def _default_target_filename(target, shared=True):
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


def fill_build_flags(build_flags: Optional[Dict[str, List[str]]]
                     ) -> Dict[str, List[str]]:
    """fill compile/link compiler-to-list flags with all compiler.
    """
    if build_flags is None:
        build_flags = {}
    for comp in ALL_SUPPORTED_COMPILER:
        if comp not in build_flags:
            build_flags[comp] = []
    return build_flags


def fill_link_flags(link_flags: Optional[Dict[str, List[str]]]
                    ) -> Dict[str, List[str]]:
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
    new_data = OrderedDict() # type: Dict[str, List[Any]]
    for k, v in data.items():
        ks = k.split(split)
        for k_ in ks:
            k_ = k_.strip()
            if k_ not in new_data:
                new_data[k_] = []
            new_data[k_].extend(v)
    return new_data


def create_simple_ninja(target,
                        build_dir,
                        sources,
                        includes=None,
                        libs=None,
                        libpaths=None,
                        compile_opts=None,
                        link_opts=None,
                        target_filename=None,
                        additional_cflags=None,
                        additional_lflags=None,
                        suffix_to_compiler=None,
                        shared=False):
    default_suffix_to_compiler = _default_suffix_to_compiler()
    suffix_to_compiler_ = default_suffix_to_compiler
    if suffix_to_compiler is not None:
        suffix_to_compiler_.update(suffix_to_compiler)
    linker = _default_linker()
    build_options = _default_build_options()
    link_options = _default_link_options()
    if target_filename is None:
        target_filename = _default_target_filename(target, shared)
    else:
        path = Path(target_filename)
        if path.suffix == "":
            # add default suffix
            target_filename = str(path.parent /
                                  _default_target_filename(path.stem, shared))
    writer = BaseWritter(suffix_to_compiler_, build_dir, build_options,
                         link_options, OrderedDict(), OrderedDict())
    target_build_opt = BuildOptions(includes, compile_opts)
    target_build_options = OrderedDict()
    additional_cflags = fill_build_flags(additional_cflags)
    additional_lflags = fill_link_flags(additional_lflags)
    additional_cflags = group_dict_by_split(additional_cflags)
    additional_lflags = group_dict_by_split(additional_lflags)
    for k, v in build_options.items():
        target_build_options[k] = target_build_opt.copy()
        if k in additional_cflags:
            target_build_options[k].cflags.extend(additional_cflags[k])
    link_opts = LinkOptions(libpaths, libs, link_opts)
    link_opts.ldflags.extend(additional_lflags[linker])
    writer.add_target(target, target_build_options, linker, link_opts, sources,
                      target_filename, shared)
    return writer.content, target_filename

def build_simple_ninja(target,
                       build_dir,
                       sources,
                       includes=None,
                       libs=None,
                       libpaths=None,
                       compile_opts=None,
                       link_opts=None,
                       target_filename=None,
                       additional_cflags=None,
                       additional_lflags=None,
                       suffix_to_compiler=None,
                       verbose=False,
                       shared=True):
    ninja_content, target_filename = create_simple_ninja(
        target, build_dir, sources, includes, libs, libpaths, compile_opts,
        link_opts, target_filename, additional_cflags, additional_lflags,
        suffix_to_compiler, shared)
    build_dir = Path(build_dir).resolve()
    with (build_dir / "build.ninja").open("w") as f:
        f.write(ninja_content)
    # TODO: check_call don't raise, this is a problem
    cmds = ["ninja"]
    if verbose:
        cmds.append("-v")
    if compat.Python3_7AndLater:
        proc = subprocess.Popen(cmds, cwd=str(build_dir),
                                stdout=subprocess.PIPE,
                                text=True)
    else:
        proc = subprocess.Popen(cmds, cwd=str(build_dir),
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
                     includes=None,
                     libs=None,
                     libpaths=None,
                     compile_opts=None,
                     link_opts=None,
                     target_filename=None,
                     additional_cflags=None):
    ninja_content, target_filename = create_simple_ninja(
        target, build_dir, sources, includes, libs, libpaths, compile_opts,
        link_opts, target_filename, additional_cflags, False)
    build_dir = Path(build_dir)
    with (build_dir / "build.ninja").open("w") as f:
        f.write(ninja_content)
    # TODO: check_call don't raise, this is a problem
    subprocess.check_call(["ninja", "-v"], cwd=str(build_dir))
    subprocess.check_call([str(build_dir / target_filename)],
                          cwd=str(build_dir))
    return target_filename
