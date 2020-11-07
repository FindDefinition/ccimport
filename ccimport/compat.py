import os
import platform
import re
import subprocess
import sys
import sysconfig
from enum import Enum

Python3 = (sys.version_info[0] == 3)
Python4 = (sys.version_info[0] == 4)
Python3AndLater = (sys.version_info[0] >= 3)
Python3Later = (sys.version_info[0] > 3)
Python35 = Python3 and sys.version_info[1] == 5
Python3_10AndLater = Python3Later or (Python3 and sys.version_info[1] >= 10)
Python3_9AndLater = Python3Later or (Python3 and sys.version_info[1] >= 9)
Python3_8AndLater = Python3Later or (Python3 and sys.version_info[1] >= 8)
Python3_7AndLater = Python3Later or (Python3 and sys.version_info[1] >= 7)
Python3_6AndLater = Python3Later or (Python3 and sys.version_info[1] >= 6)
Python3_5AndLater = Python3Later or (Python3 and sys.version_info[1] >= 5)
PyPy3 = platform.python_implementation().lower() == "pypy"
assert Python3_5AndLater, "only support python >= 3.5"

VALID_PYTHON_MODULE_NAME_PATTERN = re.compile(r"[a-zA-Z_][0-9a-zA-Z_]*")


class OSType(Enum):
    Win10 = "Win10"
    MacOS = "MacOS"
    Linux = "Linux"
    Unknown = "Unknown"


OS = OSType.Unknown

InWindows = False
if os.name == 'nt':
    InWindows = True
    OS = OSType.Win10

InLinux = False
if platform.system() == "Linux":
    InLinux = True
    OS = OSType.Linux

InMacOS = False
if platform.system() == "Darwin":
    InMacOS = True
    OS = OSType.MacOS


def get_os_name():
    return os.name


string_classes = (str, bytes)
int_classes = int


def get_python_version():
    return sys.version_info


def get_extension_suffix():
    ext_suffix = sysconfig.get_config_var('EXT_SUFFIX')
    if ext_suffix is None:
        ext_suffix = sysconfig.get_config_var('SO')
    assert ext_suffix is not None
    return ext_suffix


def get_python_includes():
    return [sysconfig.get_path('include'), sysconfig.get_path('platinclude')]


def get_pybind11_includes():
    import pybind11
    return [pybind11.get_include(), *get_python_includes()]


def _compiler_preprocessor_verbose(compiler, extraflags):
    """Capture the compiler preprocessor stage in verbose mode
    copied from https://github.com/AndrewWalker/ccsyspath/blob/master/ccsyspath/paths.py
    """
    lines = []
    with open(os.devnull, 'r') as devnull:
        cmd = [compiler, '-E']
        cmd += extraflags
        cmd += ['-', '-v']
        p = subprocess.Popen(cmd,
                             stdin=devnull,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        p.wait()
        p.stdout.close()
        lines = p.stderr.read()
        lines = lines.decode('utf-8')
        lines = lines.splitlines()
    return lines


def get_system_include_paths(compiler, cpp=True):
    # copied from https://github.com/AndrewWalker/ccsyspath/blob/master/ccsyspath/paths.py
    extraflags = []
    if cpp:
        extraflags = '-x c++'.split()
    lines = _compiler_preprocessor_verbose(compiler, extraflags)
    lines = [line.strip() for line in lines]

    start = lines.index('#include <...> search starts here:')
    end = lines.index('End of search list.')

    lines = lines[start + 1:end]
    paths = []
    for line in lines:
        line = line.replace('(framework directory)', '')
        line = line.strip()
        paths.append(line)
    return paths


def locate_libpython_2(python_version: str):
    """Get path to the python library associated with the current python
    interpreter."""
    # https://stackoverflow.com/questions/47423246/get-pythons-lib-path
    import itertools
    from distutils import sysconfig

    # determine direct path to libpython
    python_library = sysconfig.get_config_var('LIBRARY')

    # if static (or nonexistent), try to find a suitable dynamic libpython
    if (python_library is None
            or os.path.splitext(python_library)[1][-2:] == '.a'):

        candidate_lib_prefixes = ['', 'lib']

        candidate_extensions = ['.lib', '.so', '.a']
        if sysconfig.get_config_var('WITH_DYLD'):
            candidate_extensions.insert(0, '.dylib')

        candidate_versions = [python_version]
        if python_version:
            candidate_versions.append('')
            candidate_versions.insert(0,
                                      "".join(python_version.split(".")[:2]))

        abiflags = getattr(sys, 'abiflags', '')
        candidate_abiflags = [abiflags]
        if abiflags:
            candidate_abiflags.append('')

        # Ensure the value injected by virtualenv is
        # returned on windows.
        # Because calling `sysconfig.get_config_var('multiarchsubdir')`
        # returns an empty string on Linux, `du_sysconfig` is only used to
        # get the value of `LIBDIR`.
        libdir = sysconfig.get_config_var('LIBDIR')
        if sysconfig.get_config_var('MULTIARCH'):
            masd = sysconfig.get_config_var('multiarchsubdir')
            if masd:
                if masd.startswith(os.sep):
                    masd = masd[len(os.sep):]
                libdir = os.path.join(libdir, masd)

        if libdir is None:
            libdir = os.path.abspath(
                os.path.join(sysconfig.get_config_var('LIBDEST'), "..",
                             "libs"))

        candidates = (os.path.join(libdir, ''.join(
            (pre, 'python', ver, abi, ext)))
                      for (pre, ext, ver, abi) in itertools.product(
                          candidate_lib_prefixes, candidate_extensions,
                          candidate_versions, candidate_abiflags))

        for candidate in candidates:
            if os.path.exists(candidate):
                # we found a (likely alternate) libpython
                python_library = candidate
                break

    # TODO(opadron): what happens if we don't find a libpython?

    return python_library
