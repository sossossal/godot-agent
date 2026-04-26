from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, Iterable, List, Optional, Tuple


IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CLASS_RE = re.compile(r"^\s*class_name\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+extends\s+([A-Za-z_][A-Za-z0-9_]*))?")
EXTENDS_RE = re.compile(r"^\s*extends\s+([A-Za-z_][A-Za-z0-9_\.]*)")
SIGNAL_RE = re.compile(r"^\s*signal\s+([A-Za-z_][A-Za-z0-9_]*)(?:\(([^)]*)\))?")
FUNC_RE = re.compile(r"^\s*(?:static\s+)?func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?:?")
VAR_DECL_RE = re.compile(r"^\s*(?:@[\w\.]+\s*)*(?:var|const)\s+([A-Za-z_][A-Za-z0-9_]*)")
FOR_DECL_RE = re.compile(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
STRING_FUNC_RE = re.compile(
    r'(?P<prefix>(?:call|call_deferred|rpc|rpc_id|has_method)\(\s*["\'])(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<suffix>["\'])'
)
CALLABLE_RE = re.compile(
    r'(?P<prefix>Callable\([^,\n]+,\s*["\'])(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<suffix>["\'])'
)
STRING_SIGNAL_RE = re.compile(
    r'(?P<prefix>(?:emit_signal|connect|disconnect|is_connected)\(\s*["\'])(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<suffix>["\'])'
)


@dataclass
class GDScriptSymbol:
    name: str
    symbol_type: str
    line: int
    column: int
    base: Optional[str] = None
    args: List[str] = field(default_factory=list)
    signature: Optional[str] = None


@dataclass
class GDScriptReference:
    name: str
    symbol_type: Optional[str]
    line: int
    column: int
    offset: int
    end_offset: int
    context: str
    scope: Optional[str] = None


@dataclass
class GDScriptFunction:
    name: str
    line: int
    indent: int
    args: List[str] = field(default_factory=list)
    body_start: int = 0
    body_end: int = 0
    locals: set[str] = field(default_factory=set)
    signature: Optional[str] = None


@dataclass
class GDScriptAST:
    path: str = ""
    symbols: List[GDScriptSymbol] = field(default_factory=list)
    references: List[GDScriptReference] = field(default_factory=list)
    functions: List[GDScriptFunction] = field(default_factory=list)
    classes: Dict[str, Dict[str, object]] = field(default_factory=dict)
    signals: Dict[str, Dict[str, object]] = field(default_factory=dict)
    methods: Dict[str, Dict[str, object]] = field(default_factory=dict)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _strip_comment(line: str) -> str:
    in_string: Optional[str] = None
    escaped = False
    for index, char in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char in {'"', "'"}:
            in_string = char
            continue
        if char == "#":
            return line[:index]
    return line


def _mask_non_code(line: str) -> str:
    chars = list(line)
    in_string: Optional[str] = None
    escaped = False
    for index, char in enumerate(chars):
        if in_string:
            chars[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char in {'"', "'"}:
            chars[index] = " "
            in_string = char
            continue
        if char == "#":
            for comment_index in range(index, len(chars)):
                chars[comment_index] = " "
            break
    return "".join(chars)


def _split_args(arg_string: Optional[str]) -> List[str]:
    if not arg_string:
        return []
    results: List[str] = []
    for raw_arg in arg_string.split(","):
        item = raw_arg.strip()
        if not item:
            continue
        name = item.split("=", 1)[0].strip()
        name = name.split(":", 1)[0].strip()
        if name.startswith("&"):
            name = name[1:]
        if IDENTIFIER_RE.fullmatch(name):
            results.append(name)
    return results


def _line_offsets(lines: List[str]) -> List[int]:
    offsets: List[int] = []
    current = 0
    for line in lines:
        offsets.append(current)
        current += len(line) + 1
    return offsets


def _next_identifier(tokens: List[re.Match[str]], index: int) -> Optional[str]:
    for token_index in range(index + 1, len(tokens)):
        value = tokens[token_index].group(0)
        if IDENTIFIER_RE.fullmatch(value):
            return value
    return None


class GDScriptAstParser:
    def parse(self, content: str, path: str = "") -> GDScriptAST:
        lines = content.splitlines()
        offsets = _line_offsets(lines)
        ast = GDScriptAST(path=path)
        current_function: Optional[GDScriptFunction] = None

        for line_no, raw_line in enumerate(lines, start=1):
            code_line = _strip_comment(raw_line)
            stripped = code_line.strip()
            indent = _indent_of(raw_line)

            if current_function and stripped and indent <= current_function.indent:
                current_function.body_end = line_no - 1
                current_function = None

            class_match = CLASS_RE.match(code_line)
            if class_match:
                symbol = GDScriptSymbol(
                    name=class_match.group(1),
                    symbol_type="类",
                    line=line_no,
                    column=class_match.start(1) + 1,
                    base=class_match.group(2),
                )
                ast.symbols.append(symbol)
                ast.classes[symbol.name] = {
                    "path": f"res://{path}" if path else "",
                    "base": symbol.base,
                    "line": line_no,
                    "signals": [],
                    "methods": [],
                }

            signal_match = SIGNAL_RE.match(code_line)
            if signal_match:
                signal_symbol = GDScriptSymbol(
                    name=signal_match.group(1),
                    symbol_type="信号",
                    line=line_no,
                    column=signal_match.start(1) + 1,
                    args=_split_args(signal_match.group(2)),
                    signature=f"{signal_match.group(1)}({signal_match.group(2) or ''})",
                )
                ast.symbols.append(signal_symbol)
                ast.signals[signal_symbol.name] = {
                    "line": line_no,
                    "signature": signal_symbol.signature,
                }
                if ast.classes:
                    list(ast.classes.values())[-1]["signals"].append(signal_symbol.name)

            func_match = FUNC_RE.match(code_line)
            if func_match:
                signature = func_match.group(1) + f"({func_match.group(2) or ''})"
                if func_match.group(3):
                    signature += f" -> {func_match.group(3).strip()}"
                function = GDScriptFunction(
                    name=func_match.group(1),
                    line=line_no,
                    indent=indent,
                    args=_split_args(func_match.group(2)),
                    body_start=line_no + 1,
                    body_end=len(lines),
                    signature=signature,
                )
                function.locals.update(function.args)
                ast.functions.append(function)
                current_function = function
                func_symbol = GDScriptSymbol(
                    name=function.name,
                    symbol_type="函数",
                    line=line_no,
                    column=func_match.start(1) + 1,
                    args=list(function.args),
                    signature=signature,
                )
                ast.symbols.append(func_symbol)
                ast.methods[function.name] = {
                    "line": line_no,
                    "signature": signature,
                    "args": list(function.args),
                }
                if ast.classes:
                    list(ast.classes.values())[-1]["methods"].append({
                        "name": function.name,
                        "args": ", ".join(function.args),
                        "line": line_no,
                    })

        if current_function:
            current_function.body_end = len(lines)

        for function in ast.functions:
            for line_no in range(function.body_start, function.body_end + 1):
                if line_no < 1 or line_no > len(lines):
                    continue
                code_line = _strip_comment(lines[line_no - 1])
                var_match = VAR_DECL_RE.match(code_line)
                if var_match:
                    function.locals.add(var_match.group(1))
                for_match = FOR_DECL_RE.match(code_line)
                if for_match:
                    function.locals.add(for_match.group(1))

        function_by_line: Dict[int, GDScriptFunction] = {}
        for function in ast.functions:
            for line_no in range(function.line, function.body_end + 1):
                function_by_line[line_no] = function

        for line_no, raw_line in enumerate(lines, start=1):
            code_line = _strip_comment(raw_line)
            masked_line = _mask_non_code(raw_line)
            base_offset = offsets[line_no - 1]
            current_function = function_by_line.get(line_no)
            local_symbols = current_function.locals if current_function else set()
            scope_name = current_function.name if current_function else None

            for regex, symbol_type, context in (
                (STRING_FUNC_RE, "函数", "string_call"),
                (CALLABLE_RE, "函数", "callable"),
                (STRING_SIGNAL_RE, "信号", "string_signal"),
            ):
                for match in regex.finditer(code_line):
                    start = match.start("name")
                    end = match.end("name")
                    ast.references.append(
                        GDScriptReference(
                            name=match.group("name"),
                            symbol_type=symbol_type,
                            line=line_no,
                            column=start + 1,
                            offset=base_offset + start,
                            end_offset=base_offset + end,
                            context=context,
                            scope=scope_name,
                        )
                    )

            tokens = list(IDENTIFIER_RE.finditer(masked_line))
            for token_index, token in enumerate(tokens):
                name = token.group(0)
                start = token.start()
                end = token.end()
                prev_token = tokens[token_index - 1].group(0) if token_index > 0 else None
                prev_end = tokens[token_index - 1].end() if token_index > 0 else -1
                next_token = tokens[token_index + 1].group(0) if token_index + 1 < len(tokens) else None
                raw_prefix = masked_line[max(0, start - 12):start]
                raw_suffix = masked_line[end:min(len(masked_line), end + 12)]
                char_before = masked_line[start - 1] if start > 0 else ""
                char_after = masked_line[end] if end < len(masked_line) else ""

                if CLASS_RE.match(code_line) and CLASS_RE.match(code_line).group(1) == name:
                    continue
                if SIGNAL_RE.match(code_line) and SIGNAL_RE.match(code_line).group(1) == name:
                    continue
                if FUNC_RE.match(code_line) and FUNC_RE.match(code_line).group(1) == name:
                    continue
                if VAR_DECL_RE.match(code_line) and VAR_DECL_RE.match(code_line).group(1) == name:
                    continue
                if FOR_DECL_RE.match(code_line) and FOR_DECL_RE.match(code_line).group(1) == name:
                    continue
                if current_function and name in current_function.args and line_no == current_function.line:
                    continue

                context = "identifier"
                symbol_type: Optional[str] = None

                if line_no == 1 or EXTENDS_RE.match(code_line):
                    extends_match = EXTENDS_RE.match(code_line)
                    if extends_match and extends_match.group(1).split(".")[-1] == name:
                        context = "extends"
                        symbol_type = "类"
                elif char_before == ".":
                    receiver_is_self = masked_line[:start].rstrip().endswith("self.")
                    if receiver_is_self:
                        context = "self_member"
                        symbol_type = "函数"
                    else:
                        continue
                elif char_after == "(":
                    context = "call"
                    symbol_type = "函数"
                    if name in local_symbols:
                        continue
                elif char_after == ".":
                    context = "member"
                    var_next_identifier = _next_identifier(tokens, token_index)
                    if var_next_identifier in {"connect", "disconnect", "emit"}:
                        symbol_type = "信号"
                    elif var_next_identifier == "new":
                        context = "constructor"
                        symbol_type = "类"
                    elif name in local_symbols:
                        continue
                elif re.search(rf":\s*{re.escape(name)}\b", code_line):
                    context = "type_hint"
                    symbol_type = "类"
                elif re.search(rf"\bis\s+{re.escape(name)}\b", code_line):
                    context = "type_check"
                    symbol_type = "类"
                elif re.search(rf"\bas\s+{re.escape(name)}\b", code_line):
                    context = "cast"
                    symbol_type = "类"
                elif re.search(rf"\b{re.escape(name)}\s*\.\s*new\s*\(", code_line):
                    context = "constructor"
                    symbol_type = "类"
                elif name in local_symbols:
                    continue

                ast.references.append(
                    GDScriptReference(
                        name=name,
                        symbol_type=symbol_type,
                        line=line_no,
                        column=start + 1,
                        offset=base_offset + start,
                        end_offset=base_offset + end,
                        context=context,
                        scope=scope_name,
                    )
                )

        return ast


class GDScriptRefactorEngine:
    def __init__(self):
        self.parser = GDScriptAstParser()

    def rename_symbol(
        self,
        content: str,
        symbol_type: str,
        old_name: str,
        new_name: str,
    ) -> Tuple[str, List[Dict[str, object]]]:
        ast = self.parser.parse(content)
        edits: Dict[Tuple[int, int], Dict[str, object]] = {}
        updated_content = content

        def add_edit(start: int, end: int, line: int, context: str):
            if (start, end) in edits:
                return
            edits[(start, end)] = {
                "start": start,
                "end": end,
                "line": line,
                "context": context,
            }

        for symbol in ast.symbols:
            if symbol.name != old_name or symbol.symbol_type != symbol_type:
                continue
            line_start = content.splitlines(keepends=True)
            # Convert line/column to offsets lazily.
        lines = content.splitlines()
        offsets = _line_offsets(lines)

        for symbol in ast.symbols:
            if symbol.name != old_name or symbol.symbol_type != symbol_type:
                continue
            start = offsets[symbol.line - 1] + symbol.column - 1
            end = start + len(old_name)
            add_edit(start, end, symbol.line, "declaration")

        allowed_contexts = {
            "类": {"extends", "type_hint", "type_check", "cast", "constructor", "identifier"},
            "函数": {"call", "self_member", "string_call", "callable"},
            "信号": {"member", "string_signal"},
        }.get(symbol_type, {"identifier"})

        for reference in ast.references:
            if reference.name != old_name:
                continue
            if reference.symbol_type and reference.symbol_type != symbol_type:
                continue
            if reference.context not in allowed_contexts:
                continue
            if symbol_type == "类" and reference.context == "identifier":
                if not old_name[:1].isupper():
                    continue
            add_edit(reference.offset, reference.end_offset, reference.line, reference.context)

        if not edits:
            return content, []

        ordered = sorted(edits.values(), key=lambda item: item["start"], reverse=True)
        for edit in ordered:
            updated_content = (
                updated_content[: edit["start"]]
                + new_name
                + updated_content[edit["end"] :]
            )

        applied = [
            {
                "line": edit["line"],
                "context": edit["context"],
                "old_name": old_name,
                "new_name": new_name,
            }
            for edit in sorted(edits.values(), key=lambda item: (item["line"], item["start"]))
        ]
        return updated_content, applied
