# ccimport

[![Build Status](https://github.com/FindDefinition/ccimport/workflows/build/badge.svg)](https://github.com/FindDefinition/ccimport/actions?query=workflow%3Abuild)

a tiny package for fast python c++ binding build.

support python 3.5, 3.7-3.9.

## Usage

### Limitations in Code

* Function/class with template parameter aren't supported. If you really need to use template, you need to provide all parameters with a default value. The generated code will use ```func<>``` to bind your code.

### Single File Extension

* Add ```CODEAI_EXPORT``` before your function declaration name. For class, write a static factory member that return a unique_ptr, then add ```CODEAI_EXPORT_INIT``` before it.

* use ```ccimport.autoimport``` to build extension.

### Multiple File Extension

* Add ```CODEAI_EXPORT``` and/or ```CODEAI_EXPORT_INIT``` in header files.

* Implement functions and classes in source files.

* use ```ccimport.autoimport``` to build extension. you need to add all header files with ```CODEAI_EXPORT``` to ```sources``` parameter.

### Library without pybind

* Use ccimport.ccimport instead.

## API

* ccimport.autoimport

```Python
def autoimport(sources: List[Union[str, Path]], # list of source path, may include headers with 'CODEAI_EXPORT'
               out_path: Union[str, Path], # output path. the name of output file must be a name 
                                           # without platform library prefix and suffix such as `lib-`, '.so'.
               includes: Optional[List[Union[str, Path]]] = None, # include paths
               libpaths: Optional[List[Union[str, Path]]] = None, # library paths
               libraries: Optional[List[str]] = None, # libraries. the name of library must be a name 
                                           # without platform library prefix and suffix such as `lib-`, '.so'.
               export_kw="CODEAI_EXPORT", # use the macro to mark a exported function.
               export_init_kw="CODEAI_EXPORT_INIT", # use the macro to mark a static class factory member.
               compile_options: Optional[List[str]] = None, # compile options.
               link_options: Optional[List[str]] = None, # link options.
               std="c++14", # c++ standard.
               additional_cflags: Optional[Dict[str, List[str]]] = None): # compiler to compile options
    pass
```

* ccimport.ccimport

```Python
def ccimport(source_paths: List[Union[str, Path]],
             out_path: Union[str, Path],
             includes: Optional[List[Union[str, Path]]] = None,
             libpaths: Optional[List[Union[str, Path]]] = None,
             libraries: Optional[List[str]] = None,
             compile_options: Optional[List[str]] = None,
             link_options: Optional[List[str]] = None,
             source_paths_for_hash: Optional[List[Union[str, Path]]] = None, # if provided, the content of source files will be used
                                                                             # for change detection.
             std="c++14",
             build_ctype=False, # if True, a standard shared library will be built. otherwise a pybind library will be built
             disable_hash=True, # if True, source-content based change detection will be used.
             load_library=True, # if True, the library will be loaded by python or ctypes.CDLL
             additional_cflags: Optional[Dict[str, List[str]]] = None):
    pass
```