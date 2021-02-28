"""small library to find classes/functions (need macro).
libclang is too huge for simple c++ analysis.
"""
import bisect
import re
from bisect import bisect_left, bisect_right
# from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple

CPP_SIMPLE_TOKEN = r"""
# group 1 is comments, dont care group2
(\/\/.*|\/\*[\s\S]*?\*\/) # comments
|(?:u8?|U|L)?'(?:\\(?:['\"?\\abfnrtv]|[0-7]{1,3}|x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})|[^'\\\r\n])+' # 'xxx'
|(?:u8?|U|L)?\"(?:\\(?:['\"?\\abfnrtv]|[0-7]{1,3}|x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})|[^\"\\\r\n])*\"|(?:u8?|U|L)?R\"([^ ()\\\t\x0B\r\n]*)\([\s\S]*?\)\2\"
|([a-zA-Z_][0-9a-zA-Z_]*) # identifier
"""

CPP_SIMPLE_TOKEN_RE = re.compile(CPP_SIMPLE_TOKEN, re.VERBOSE)


class TokenType(Enum):
    String = 0
    Comment = 1
    Identifier = 2


def cpp_simple_tokenize(source):
    matches = CPP_SIMPLE_TOKEN_RE.finditer(source)
    for match in matches:
        group0 = match.group(0)
        group1 = match.group(1)  # comments
        group3 = match.group(3)  # comments

        # group2 = match.group(2)
        if group1 is not None:
            yield (TokenType.Comment, match.start(1), match.end(1), group1)
        elif group3 is not None:
            yield (TokenType.Identifier, match.start(3), match.end(3), group3)
        else:
            yield (TokenType.String, match.start(0), match.end(0), group0)


def find_list_str_prefix(data: List[str], prefix: str, full_match=False):
    hi = len(data)
    if not hi:
        return
    left = bisect_left(data, prefix, 0, hi)
    if left == hi:
        return
    for i in range(left, len(data)):
        string = data[i]
        if full_match:
            should_break = string != prefix
        else:
            should_break = not string.startswith(prefix)
        if should_break:
            break
        yield i


class IdentifierMeta:
    def __init__(self, name: str, start: int, end: int):
        self.name = name 
        self.start = start 
        self.end = end 

class ClassDef:
    def __init__(self, name: str, keyword_pos: int, body_start: int,
        body_end: int, local_id: str = "", is_template: bool = False):
        self.name = name 
        self.keyword_pos = keyword_pos 
        self.body_start = body_start 
        self.body_end = body_end 
        self.local_id = local_id 
        self.is_template = is_template 

class FunctionDef:
    def __init__(self, name: str, identifier_pos: int, param_start: int,
        param_end: int, body_start: int,
        body_end: int, local_id: str = "", is_template: bool = False):
        self.name = name 
        self.identifier_pos = identifier_pos 
        self.param_start = param_start 
        self.param_end = param_end 
        self.body_start = body_start 
        self.body_end = body_end 
        self.local_id = local_id 
        self.is_template = is_template 


class CppSourceIterator(object):
    # TODO try to handle '<' and '>'
    # TODO use regex to write a c++ tokenize library
    AllSymbols = set([";", ":", "<", ">", "{", "}", "[", "]", "(", ")", "|"])

    def __init__(self, source):
        # if len(source) == 0:
        #     raise ValueError("dont support empty source")
        self.source = source
        self.tokens = list(cpp_simple_tokenize(source))
        self.identifier_metas = []  # type: List[IdentifierMeta]
        self.ignore_ranges = []
        self.ignore_starts = []
        for token, start, end, name in self.tokens:
            if token == TokenType.Identifier:
                self.identifier_metas.append(IdentifierMeta(name, start, end))
            elif token == TokenType.Comment or token == TokenType.String:
                self.ignore_ranges.append((start, end))
                self.ignore_starts.append(start)
        self.identifier_metas.sort(key=lambda x: x.name)
        self.identifiers = [x.name for x in self.identifier_metas]
        self.identifier_start_to_meta = {
            x.start: x
            for x in self.identifier_metas
        }
        self.identifier_metas_start_sorted = self.identifier_metas.copy()
        self.identifier_metas_start_sorted.sort(key=lambda x: x.start)
        self.identifier_starts = [
            x.start for x in self.identifier_metas_start_sorted
        ]

        self.pos = 0

        self.bracket_state = {
            "(": 0,
            "[": 0,
            "{": 0,
        }
        self._bracket_inc = {
            "(": ("(", 1),
            "[": ("[", 1),
            "{": ("{", 1),
            ")": ("(", -1),
            "]": ("[", -1),
            "}": ("{", -1),
        }
        self._skip_chars = set([' ', '\t', '\r', '\n'])
        self.length = len(self.source)
        self.bracket_pairs, self._symbol_to_poses = self._init_bracket_analysis(
        )
        self.bracket_pairs.sort(key=lambda x: x[1])
        self._start_to_bracket_pair = {x[1]: x for x in self.bracket_pairs}
        self._class_defs = list(
            self.find_all_class_def())  # type: List[ClassDef]

        self._namespace_ranges = self.get_namespace_ranges(self._class_defs)
        self._namespace_ranges.sort(key=lambda x: x[1])

        self.local_id_to_cdef = self._update_class_def_namespace()

    def find_symbols_in_range(self, sym, start, end=None):
        if sym not in self._symbol_to_poses:
            raise KeyError(
                "unknown sym {}. available: {}".format(sym, list(self._symbol_to_poses.keys()))
            )
        poses = self._symbol_to_poses[sym]
        hi = len(poses)
        start_idx = bisect_left(poses, start, 0, hi)
        if end is not None:
            end_idx = bisect_left(poses, end, 0, hi)
        else:
            end_idx = None
        return poses[start_idx:end_idx]

    def _update_class_def_namespace(self):
        local_id_to_cdef = {}  # type: Dict[str, ClassDef]
        for cdef in self._class_defs:
            namespaces = []
            for ns, ns_start, ns_end in self._namespace_ranges:
                if cdef.body_start > ns_start and cdef.body_end < ns_end:
                    namespaces.append(ns)
            namespaces.append(cdef.name)
            local_id = "::".join(namespaces)
            cdef.local_id = local_id
            local_id_to_cdef[local_id] = cdef
        return local_id_to_cdef

    def find_all_class_def(self):
        """
        1. find class keyword
        2. try to find next '{' or ';'. if '{', it's a class def, else is a declare.
        3. find prev 'template' or '}' or ';' to determine if is a class template
        """
        class_metas = list(
            self.find_identifier_prefix("class", full_match=True))
        struct_metas = list(
            self.find_identifier_prefix("struct", full_match=True))
        inherit_kw = set(["private", "public", "protected"])
        for meta in class_metas + struct_metas:
            self.reset_bracket_count().move(meta.end)
            # find '{'
            next_curly = self.find_symbols_in_range("{", meta.end)
            if not next_curly:
                continue
            next_curly = next_curly[0]
            next_semicolon = self.find_symbols_in_range(";", meta.end)
            if not next_semicolon:
                continue
            next_semicolon = next_semicolon[0]
            if next_semicolon < next_curly:
                # it's class declare
                continue
            next_curly_end = self._start_to_bracket_pair[next_curly][-1]
            # determine is class template
            prev_semicolon = self.find_symbols_in_range(";", 0, meta.start - 1)
            prev_curly_end = self.find_symbols_in_range("}", 0, meta.start - 1)
            is_template = False
            if prev_semicolon or prev_curly_end:
                # find 'template' between prev_semicolon and prev_curly_end
                pos1 = -1
                pos2 = -1
                if prev_semicolon:
                    pos1 = prev_semicolon[-1]
                if prev_curly_end:
                    pos2 = prev_curly_end[-1]
                pos = max(pos1, pos2)
                for iden_meta in self.find_identifier_range(
                        pos, meta.start - 1):
                    if iden_meta.name == "template":
                        is_template = True
                        break
            # handle [:[public|protected|private]] other_class
            idens = list(self.find_identifier_range(meta.end, next_curly))
            if not idens:
                continue
            if len(idens) >= 3 and idens[-2].name in inherit_kw:
                name = idens[-3].name
            else:
                name = idens[-1].name
            # now we have a class def. we yield class keyword, class name
            # (last identifier between class and '{') and bracket range.
            yield ClassDef(name,
                           meta.start,
                           next_curly,
                           next_curly_end,
                           is_template=is_template)

    def _init_bracket_analysis(self):
        # TODO decrease influence of unbalanced brackets (exists when using macro)
        self.pos = 0
        bracket_stack = {k: [] for k in self.bracket_state.keys()}
        N = len(self.source)
        self.skip_string_comment()
        end_brackets = {
            ')': '(',
            ']': '[',
            '}': '{',
        }
        pairs = []
        symbol_to_poses = {k: [] for k in self.AllSymbols}
        while self.pos < N:
            val = self.source[self.pos]
            if val in self._skip_chars:
                self.pos += 1
                continue
            if val in symbol_to_poses:
                symbol_to_poses[val].append(self.pos)
            if val in self.bracket_state:
                bracket_stack[val].append((val, self.pos))
            elif val in end_brackets:
                end_bracket = end_brackets[val]
                if not bracket_stack[end_bracket]:
                    raise ValueError(
                        "unbalanced bracket '{}'({}) in your source.".format(val, self.pos)
                    )
                start_val, start = bracket_stack[end_bracket].pop()
                pairs.append((start_val, start, self.pos))
            self.pos += 1
            self.skip_string_comment()
        for k, v in bracket_stack.items():
            assert len(v) == 0, "unbalanced bracket {} in your source.".format(k)
        return pairs, symbol_to_poses

    def get_namespace_ranges(self, class_defs: List[ClassDef]):
        state = self.state()
        res = []
        for meta in self.find_identifier_prefix("namespace", full_match=True):
            self.reset_bracket_count().move(meta.end)
            # find namespace name
            iden_meta = self.next_identifier()
            if iden_meta is None:
                continue
            ns_name = iden_meta.name
            self.move(iden_meta.end)
            pair = self.next_curly()
            if pair is None:
                continue
            if pair[0] not in self._start_to_bracket_pair:
                continue
            end_curly = self._start_to_bracket_pair[pair[0]][2]
            # we change state in this function, so yield is dangerous
            res.append((ns_name, pair[0], end_curly))
        for cdef in class_defs:
            res.append((cdef.name, cdef.body_start, cdef.body_end))

        self.restore_state(state)
        return res

    def __repr__(self):
        return "SourceIter[{},'('={}, '{{'={}]".format(self.pos,
                                                       self.bracket_state["("],
                                                       self.bracket_state["{"])

    def move(self, pos: int):
        self.pos = pos
        return self

    def reset_bracket_count(self):
        for k in self.bracket_state.keys():
            self.bracket_state[k] = 0
        return self

    def state(self):
        return (self.pos, self.bracket_state.copy())

    def restore_state(self, state):
        self.pos = state[0]
        self.bracket_state = state[1]

    def find_identifier_prefix(self, prefix: str, full_match=False):
        for i in find_list_str_prefix(self.identifiers, prefix, full_match):
            meta = self.identifier_metas[i]
            yield meta

    def find_function_prefix(self,
                             prefix: str,
                             find_after=False,
                             full_match=False,
                             decl_only=False):
        # return: (func_id, param_pair, body_pair)
        state = self.state()
        res = []  # type: List[FunctionDef]
        func_attr_kw = set(["const", "override", "final"])

        for meta in self.find_identifier_prefix(prefix, full_match=full_match):
            self.reset_bracket_count().move(meta.end)
            if find_after:
                meta = self.next_identifier()
                if meta is None:
                    continue
                self.reset_bracket_count().move(meta.end)
            round_pair = self.next_round()
            if not round_pair:
                continue

            prev_semicolon = self.find_symbols_in_range(";", 0, meta.start - 1)
            prev_curly_end = self.find_symbols_in_range("}", 0, meta.start - 1)
            is_template = False
            if prev_semicolon or prev_curly_end:
                # find 'template' between prev_semicolon and prev_curly_end
                pos1 = -1
                pos2 = -1
                if prev_semicolon:
                    pos1 = prev_semicolon[-1]
                if prev_curly_end:
                    pos2 = prev_curly_end[-1]
                pos = max(pos1, pos2)
                for iden_meta in self.find_identifier_range(
                        pos, meta.start - 1):
                    if iden_meta.name == "template":
                        is_template = True
                        break

            # generate local func id (ns::ns::func) TODO support class/struct
            namespaces = []
            for ns, ns_start, ns_end in self._namespace_ranges:
                if meta.start > ns_start and meta.end < ns_end:
                    namespaces.append(ns)
            namespaces.append(meta.name)
            func_id = "::".join(namespaces)
            iden = self.next_identifier()
            if iden is not None:
                if iden not in func_attr_kw:
                    continue 
            curly_pair = self.next_curly()
            if not curly_pair:
                if decl_only:
                    next_semi = self.next_semicolon()
                    if next_semi is not None:
                        func_meta = FunctionDef(meta.name, meta.start,
                                                round_pair[0], round_pair[1],
                                                -1, -1, func_id, is_template)
                        res.append(func_meta)

                continue

            func_meta = FunctionDef(meta.name, meta.start, round_pair[0],
                                    round_pair[1], curly_pair[0],
                                    curly_pair[1], func_id, is_template)
            res.append(func_meta)
        self.restore_state(state)
        return res

    def find_marked_identifier(self, mark: str):
        state = self.state()
        res = []  # type: List[Tuple[str,str]]
        for meta in self.find_identifier_prefix(mark, full_match=True):
            self.reset_bracket_count().move(meta.end)
            meta = self.next_identifier()
            if meta is None:
                continue
            namespaces = []
            for ns, ns_start, ns_end in self._namespace_ranges:
                if meta.start > ns_start and meta.start < ns_end:
                    namespaces.append(ns)

            res.append((meta.name, "::".join(namespaces)))
        self.restore_state(state)
        return res

    def inc_bracket(self):
        val = self.source[self.pos]
        if val not in self._bracket_inc:
            return
        bracket_trans = self._bracket_inc[self.source[self.pos]]
        self.bracket_state[bracket_trans[0]] += bracket_trans[1]
        return val

    def skip_string_comment(self):
        hi = len(self.ignore_starts)
        if hi == 0:
            return
        left = bisect_left(self.ignore_starts, self.pos, 0, hi) - 1
        if left < 0:
            return
        assert left != hi
        ignore_range = self.ignore_ranges[left]
        if self.pos < ignore_range[1]:
            self.pos = ignore_range[1]

    def next_bracket(self, bracket):
        self.skip_string_comment()
        while self.pos < self.length:
            val = self.source[self.pos]
            if val in self._skip_chars:
                self.pos += 1
                continue
            if self.source[self.pos] != bracket:
                return None
            start = self.pos
            end = self._start_to_bracket_pair[self.pos][2]
            self.pos = end + 1
            return (start, end)
        return None

    def next_curly(self):
        return self.next_bracket("{")

    def next_round(self):
        return self.next_bracket("(")

    def next_identifier(self):
        self.skip_string_comment()
        while self.pos < self.length:
            val = self.source[self.pos]
            if val in self._skip_chars:
                self.pos += 1
                continue
            if self.pos in self.identifier_start_to_meta:
                meta = self.identifier_start_to_meta[self.pos]
                self.pos = meta.end
                return meta
            else:
                return None

    def next_semicolon(self):
        self.skip_string_comment()
        while self.pos < self.length:
            val = self.source[self.pos]
            if val in self._skip_chars:
                self.pos += 1
                continue
            if val == ";":
                return self.pos
            else:
                return None

    def skip_identifier(self):
        iden_meta = self.next_identifier()
        if iden_meta is None:
            return
        self.pos = iden_meta.end

    def find_identifier_range(self, start: int, end: int):
        assert end > start
        hi = len(self.identifiers)
        if not hi:
            return
        left = bisect_left(self.identifier_starts, start, 0, hi)
        if left == hi:
            return
        for i in range(left, len(self.identifiers)):
            meta = self.identifier_metas_start_sorted[i]
            if meta.start >= start and meta.end <= end:
                yield meta
            else:
                break


if __name__ == "__main__":
    source = """
    std::cout << L"hello" << " world";
    std::cout << "He said: \"bananas\"" << "...";
    std::cout << ("");
    std::cout << "\x12\23\x34";
    "" // empty string
    '"' // character literal

    // this is "a string literal" in a comment
    /* this is
    "also inside"
    //a comment */

    // and this /*
    "is not in a comment"
    // */

    """
    it = CppSourceIterator(source)
    print(it.bracket_pairs)