import subprocess
from pathlib import Path

import ccimport
from ccimport import compat
from ccimport.utils import tempdir
import os 
import sys 

def test_cpp_build():
    source = ccimport.autoimport([Path(__file__).parent / "source.cc"],
                                 Path(__file__).parent / "source")
    assert source.sub(2, 1) == 1
    obj = source.TestClass(5)
    assert obj.add(3) == 8


def test_cpp_exec_build():
    with tempdir() as tempd:
        sources = [
            Path(__file__).parent / "executable.cc",
            Path(__file__).parent / "source.cc"
        ]
        p2s = {Path(__file__).parent / "some_pch.h": sources}
        pch_to_include = {Path(__file__).parent / "some_pch.h": "some_pch.h"}
        source = ccimport.ccimport(sources,
                                   tempd / "executable",
                                   includes=[Path(__file__).parent],
                                   shared=False,
                                   load_library=False,
                                   pch_to_sources=p2s,
                                   pch_to_include=pch_to_include,
                                   verbose=False,
                                   objects_folder="objects")

        output = subprocess.check_output([str(source)])
        assert output.decode("utf-8").strip() == "hello ccimport!"

def _test_gcc_crosscompile_build():
    # currently no CI/CD available, so disable this test.
    if compat.InWindows:
        return
    # aarch64-linux-gnu-g++
    with tempdir() as tempd:
        py_ver = (sys.version_info[0], sys.version_info[1])
        os.environ["SETUPTOOLS_EXT_SUFFIX"] = compat.get_extension_suffix_linux_custom(py_ver, "aarch64")

        sources = [
            Path(__file__).parent / "executable.cc",
            Path(__file__).parent / "source.cc"
        ]
        p2s = {Path(__file__).parent / "some_pch.h": sources}
        pch_to_include = {Path(__file__).parent / "some_pch.h": "some_pch.h"}
        source = ccimport.ccimport(sources,
                                   tempd / "executable",
                                   includes=[Path(__file__).parent],
                                   shared=True,
                                   load_library=False,
                                   pch_to_sources=p2s,
                                   pch_to_include=pch_to_include,
                                   verbose=True,
                                   objects_folder="objects")
        print(input("hold"), tempd)

        output = subprocess.check_output([str(source)])
        assert output.decode("utf-8").strip() == "hello ccimport!"


if __name__ == "__main__":
    _test_gcc_crosscompile_build()
