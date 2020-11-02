import ccimport
from pathlib import Path 


def test_cpp_build():
    source = ccimport.autoimport([Path(__file__).parent / "source.cc"],
                                Path(__file__).parent / "source")
    assert source.sub(2, 1) == 1
    obj = source.TestClass(5)
    assert obj.add(3) == 8