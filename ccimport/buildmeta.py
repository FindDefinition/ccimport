import copy
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union
import enum
from ccimport import compat


def group_dict_by_split(data: Dict[str, List[str]], split: str = ","):
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


def _unique_list_keep_order(seq: list):
    if compat.Python3_7AndLater:
        # https://www.peterbe.com/plog/fastest-way-to-uniquify-a-list-in-python-3.6
        # only python 3.7 language std ensure the preserve-order dict
        return list(dict.fromkeys(seq))
    else:
        # https://stackoverflow.com/questions/480214/how-do-you-remove-duplicates-from-a-list-whilst-preserving-order
        seen = set()
        seen_add = seen.add
        return [x for x in seq if not (x in seen or seen_add(x))]


class CFlagsNode:

    def __init__(self, public_flags: Dict[str, List[str]],
                 private_flags: Dict[str, List[str]],
                 global_flags: Dict[str, List[str]]) -> None:
        self.public_flags = public_flags
        self.private_flags = private_flags
        self.global_flags = global_flags

    def copy(self):
        new_public_flags = {k: v.copy() for k, v in self.public_flags.items()}
        new_private_flags = {
            k: v.copy()
            for k, v in self.private_flags.items()
        }
        new_global_flags = {k: v.copy() for k, v in self.global_flags.items()}

        return CFlagsNode(new_public_flags, new_private_flags,
                          new_global_flags)


class IncludesNode:

    def __init__(self, public_incs: List[Union[str, Path]],
                 private_incs: List[Union[str, Path]],
                 global_incs: List[Union[str, Path]]) -> None:
        self.public_incs = public_incs
        self.private_incs = private_incs
        self.global_incs = global_incs

    def copy(self):
        return IncludesNode(self.public_incs.copy(), self.private_incs.copy(),
                            self.global_incs.copy())


def _merge_compiler_to_flags(this: Dict[str, List[str]],
                             other: Dict[str, List[str]]):
    all_cflag_keys = [*this.keys(), *other.keys()]
    res_cflags = OrderedDict()  # type: Dict[str, List[str]]
    for k in all_cflag_keys:
        k_in_this = k in this
        k_in_other = k in other
        if k_in_this and not k_in_other:
            res_cflags[k] = this[k]
        elif not k_in_this and k_in_other:
            res_cflags[k] = other[k]
        else:
            res_cflags[k] = _unique_list_keep_order(this[k] + other[k])
    return res_cflags


def _merge_type_to_cflags(this: CFlagsNode, other: CFlagsNode):
    public_flags = _merge_compiler_to_flags(this.public_flags,
                                            other.public_flags)
    private_flags = _merge_compiler_to_flags(this.private_flags,
                                             other.private_flags)
    global_flags = _merge_compiler_to_flags(this.global_flags,
                                            other.global_flags)

    return CFlagsNode(public_flags, private_flags, global_flags)


def _inherit_type_to_cflags(this: CFlagsNode, other: CFlagsNode):
    public_flags = _merge_compiler_to_flags(this.public_flags,
                                            other.public_flags)
    private_flags = this.private_flags
    return CFlagsNode(public_flags, private_flags, {})


def _merge_include_node(this: IncludesNode, other: IncludesNode):
    public_incs = this.public_incs + other.public_incs
    private_incs = this.private_incs + other.private_incs
    global_incs = this.global_incs + other.global_incs
    return IncludesNode(public_incs, private_incs, global_incs)


def _inherit_include_node(this: IncludesNode, other: IncludesNode):
    public_incs = this.public_incs + other.public_incs
    private_incs = this.private_incs
    global_incs = []

    return IncludesNode(public_incs, private_incs, global_incs)


class BuildMeta(object):
    # TODO add private flags
    def __init__(self,
                 includes: Optional[List[Union[str, Path]]] = None,
                 libpaths: Optional[List[Union[str, Path]]] = None,
                 libraries: Optional[List[str]] = None,
                 compiler_to_cflags: Optional[Dict[str, List[str]]] = None,
                 compiler_to_ldflags: Optional[Dict[str, List[str]]] = None,
                 cflags_node: Optional[CFlagsNode] = None,
                 include_node: Optional[IncludesNode] = None):
        if includes is None:
            includes = []
        if libpaths is None:
            libpaths = []
        if libraries is None:
            libraries = []
        if compiler_to_cflags is None:
            compiler_to_cflags = OrderedDict()
        if compiler_to_ldflags is None:
            compiler_to_ldflags = OrderedDict()

        # self.includes = includes
        self.libpaths = libpaths
        self.libraries = libraries
        # self.compiler_to_cflags = group_dict_by_split(compiler_to_cflags)
        self.compiler_to_ldflags = group_dict_by_split(compiler_to_ldflags)
        if cflags_node is None:
            cflags_node = CFlagsNode({}, {}, group_dict_by_split(compiler_to_cflags))
        else:
            cflags_node = _merge_type_to_cflags(
                CFlagsNode({}, {}, group_dict_by_split(compiler_to_cflags)),
                cflags_node)
        if include_node is None:
            include_node = IncludesNode([], [], includes)
        else:
            include_node = _merge_include_node(IncludesNode([], [], includes),
                                               include_node)

        self.cflags_node = cflags_node
        self.include_node = include_node

    def copy(self):
        new_ldflags = {
            k: v.copy()
            for k, v in self.compiler_to_ldflags.items()
        }
        return BuildMeta(None, self.libpaths.copy(), self.libraries.copy(),
                         None, new_ldflags, self.cflags_node.copy(),
                         self.include_node.copy())

    def __add__(self, other: "BuildMeta"):
        merged_cflags = _merge_type_to_cflags(self.cflags_node,
                                              other.cflags_node)
        # merged_cflags = _merge_compiler_to_flags(self.compiler_to_cflags,
        #                                          other.compiler_to_cflags)
        merged_ldflags = _merge_compiler_to_flags(self.compiler_to_ldflags,
                                                  other.compiler_to_ldflags)
        merged_inc_node = _merge_include_node(self.include_node,
                                              other.include_node)

        res = BuildMeta([], self.libpaths + other.libpaths,
                        _unique_list_keep_order(self.libraries +
                                                other.libraries), None,
                        merged_ldflags, merged_cflags, merged_inc_node)
        return res

    def __radd__(self, other: "BuildMeta"):
        return other.__add__(self)

    def __iadd__(self, other: "BuildMeta"):
        merged_cflags = _merge_type_to_cflags(self.cflags_node,
                                              other.cflags_node)
        # merged_cflags = _merge_compiler_to_flags(self.compiler_to_cflags,
        #                                          other.compiler_to_cflags)
        merged_ldflags = _merge_compiler_to_flags(self.compiler_to_ldflags,
                                                  other.compiler_to_ldflags)
        merged_inc_node = _merge_include_node(self.include_node,
                                              other.include_node)
        # self.includes += other.includes
        self.libpaths += other.libpaths
        self.libraries += other.libraries
        # self.compiler_to_cflags.update(merged_cflags)
        self.compiler_to_ldflags.update(merged_ldflags)
        self.cflags_node = merged_cflags
        self.include_node = merged_inc_node
        return self

    def add_cflags(self, compiler: str, *cflags: str):
        return self.add_global_cflags(compiler, *cflags)

    def add_global_cflags(self, compiler: str, *cflags: str):
        flags = self.cflags_node.global_flags
        for comp in compiler.split(","):
            comp = comp.strip()
            if comp not in flags:
                flags[comp] = []
            flags[comp].extend(cflags)

    def add_public_cflags(self, compiler: str, *cflags: str):
        flags = self.cflags_node.public_flags
        for comp in compiler.split(","):
            comp = comp.strip()
            if comp not in flags:
                flags[comp] = []
            flags[comp].extend(cflags)

    def add_private_cflags(self, compiler: str, *cflags: str):
        flags = self.cflags_node.private_flags
        for comp in compiler.split(","):
            comp = comp.strip()
            if comp not in flags:
                flags[comp] = []
            flags[comp].extend(cflags)

    def add_ldflags(self, linker: str, *ldflags: str):
        for link in linker.split(","):
            link = link.strip()
            if link not in self.compiler_to_ldflags:
                self.compiler_to_ldflags[link] = []
            self.compiler_to_ldflags[link].extend(ldflags)

    def add_includes(self, *incs: Union[str, Path]):
        self.add_global_includes(*incs)

    def add_private_includes(self, *incs: Union[str, Path]):
        self.include_node.private_incs.extend(incs)

    def add_public_includes(self, *incs: Union[str, Path]):
        self.include_node.public_incs.extend(incs)

    def add_global_includes(self, *incs: Union[str, Path]):
        self.include_node.global_incs.extend(incs)

    def add_libraries(self, *libs: str):
        self.libraries.extend(libs)

    def add_library_paths(self, *libpaths: Union[str, Path]):
        self.libpaths.extend(libpaths)

    def get_global_cflags(self):
        return self.cflags_node.global_flags

    def get_local_cflags(self):
        flags = _merge_compiler_to_flags(self.cflags_node.public_flags,
                                         self.cflags_node.private_flags)
        return flags

    def get_all_cflags(self):
        flags = _merge_compiler_to_flags(self.cflags_node.public_flags,
                                         self.cflags_node.private_flags)
        flags = _merge_compiler_to_flags(flags,
                                         self.cflags_node.global_flags)
        return flags

    def get_global_includes(self):
        return _unique_list_keep_order(self.include_node.global_incs)

    def get_local_includes(self):
        return _unique_list_keep_order(self.include_node.public_incs + self.include_node.private_incs)

    def inherit(self, other: "BuildMeta"):
        # inherit other's public flags while keep private flags
        # global and link flags will be removed because
        # we don't have meanful method to merge them.
        merged_cflags = _inherit_type_to_cflags(self.cflags_node,
                                                other.cflags_node)
        # merged_cflags = _merge_compiler_to_flags(self.compiler_to_cflags,
        #                                          other.compiler_to_cflags)
        merged_inc_node = _inherit_include_node(self.include_node,
                                                other.include_node)

        res = BuildMeta([], self.libpaths + other.libpaths,
                        _unique_list_keep_order(self.libraries +
                                                other.libraries), None, {},
                        merged_cflags, merged_inc_node)
        return res
