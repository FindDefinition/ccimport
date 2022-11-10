# ccimport

[![Build Status](https://github.com/FindDefinition/ccimport/workflows/build/badge.svg)](https://github.com/FindDefinition/ccimport/actions?query=workflow%3Abuild)

a tiny package for fast python c++ binding build.

ccimport 0.2.x support python 3.5.
ccimport >= 0.3 support python 3.6-3.10.

## Usage

```Python
build_meta = ccimport.BuildMeta()
build_meta.add_global_includes(...)
build_meta.add_global_cflags(...)
build_meta.add_ldflags(...)

lib = ccimport([path1, path2], out_path, build_meta)
```

## Usage in setup.py 

see [example](example/setup)