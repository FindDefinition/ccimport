import subprocess
from pathlib import Path

import ccimport
from ccimport.utils import tempdir


def test_cpp_build():
    source = ccimport.autoimport([Path(__file__).parent / "source.cc"],
                                 Path(__file__).parent / "source")
    assert source.sub(2, 1) == 1
    obj = source.TestClass(5)
    assert obj.add(3) == 8


def test_cpp_exec_build():
    with tempdir() as tempd:
        sources = [Path(__file__).parent / "executable.cc", Path(__file__).parent / "source.cc"]
        p2s = {Path(__file__).parent / "some_pch.h": sources}
        source = ccimport.ccimport(sources,
                                   tempd / "executable",
                                   shared=False,
                                   load_library=False,
                                   pch_to_sources=p2s)

        output = subprocess.check_output([str(source)])
        assert output.decode("utf-8").strip() == "hello ccimport!"

if __name__ == "__main__":
    test_cpp_exec_build()