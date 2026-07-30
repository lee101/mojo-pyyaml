from __future__ import annotations

import datetime as _datetime
import base64
import math
import re
from dataclasses import dataclass, field
from typing import Any

from ._lib import scan_lines
from .errors import ComposerError, ConstructorError, ParserError, ScannerError


_BOOL = {
    "yes": True, "no": False, "true": True, "false": False,
    "on": True, "off": False,
}
_NULL = {"", "~", "null"}
_INT = re.compile(
    r"^[-+]?(?:0b[0-1_]+|0x[0-9a-fA-F_]+|0o[0-7_]+|0[0-7_]+|"
    r"[0-9][0-9_]*|[0-9][0-9_]*(?::[0-5]?[0-9])+)$"
)
_FLOAT = re.compile(
    r"^[-+]?(?:"
    r"(?:[0-9][0-9_]*)?\.[0-9_]+(?:[eE][-+]?[0-9]+)?|"
    r"[0-9][0-9_]*\.(?:[eE][-+]?[0-9]+)?|"
    r"[0-9][0-9_]*(?:[eE][-+]?[0-9]+)|"
    r"\.(?:inf|Inf|INF|nan|NaN|NAN)|"
    r"[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]+"
    r")$"
)
_DATE = re.compile(r"^\d{4}-\d\d?-\d\d?$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d\d?-\d\d?[Tt \t]+\d\d?:\d\d:\d\d"
    r"(?:\.\d*)?(?:[ \t]*(?:Z|[-+]\d\d?(?::\d\d)?))?$"
)
_ANCHOR = re.compile(r"^&([^\s,\[\]{}]+)(?:\s+(.*))?$", re.S)
_TAG = re.compile(r"^(!![A-Za-z]+|![^\s]+)(?:\s+(.*))?$", re.S)


class BaseLoader:
    resolve_scalars = False


class SafeLoader:
    resolve_scalars = True


class FullLoader(SafeLoader):
    pass


class Loader(FullLoader):
    pass


class UnsafeLoader(FullLoader):
    pass


@dataclass
class _Line:
    number: int
    indent: int
    raw: str
    text: str = field(init=False)
    blank: bool = field(init=False)

    def __post_init__(self) -> None:
        content = self.raw[self.indent:]
        stripped = content.lstrip()
        self.text = _strip_comment(content).rstrip()
        self.blank = not stripped or stripped.startswith("#")


@dataclass
class _PendingAnchor:
    name: str


def _strip_comment(text: str) -> str:
    if "#" not in text:
        return text
    single = False
    double = False
    escaped = False
    for i, char in enumerate(text):
        if double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                double = False
        elif single:
            if char == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    continue
                single = False
        elif char == '"':
            double = True
        elif char == "'":
            single = True
        elif char == "#" and (i == 0 or text[i - 1].isspace()):
            return text[:i]
    return text


def _mapping_split(text: str) -> tuple[str, str] | None:
    single = double = escaped = False
    depth = 0
    for i, char in enumerate(text):
        if double:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                double = False
            continue
        if single:
            if char == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    continue
                single = False
            continue
        if char == '"':
            double = True
        elif char == "'":
            single = True
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
        elif char == ":" and depth == 0 and (
            i + 1 == len(text) or text[i + 1].isspace()
        ):
            return text[:i].rstrip(), text[i + 1:].lstrip()
    return None


def _decode_double(text: str) -> str:
    escapes = {
        "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t",
        "n": "\n", "v": "\v", "f": "\f", "r": "\r", "e": "\x1b",
        " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85",
        "_": "\xa0", "L": "\u2028", "P": "\u2029",
    }
    if "\\" not in text:
        return text[1:-1]
    result: list[str] = []
    i = 1
    stop = len(text) - 1
    while i < stop:
        slash = text.find("\\", i, stop)
        if slash < 0:
            result.append(text[i:stop])
            break
        result.append(text[i:slash])
        i = slash + 1
        if i >= stop:
            raise ScannerError("unterminated escape in double-quoted scalar")
        code = text[i]
        if code in escapes:
            result.append(escapes[code])
            i += 1
        elif code in "xXuU":
            digits = {"x": 2, "X": 2, "u": 4, "U": 8}[code]
            value = text[i + 1:i + 1 + digits]
            if len(value) != digits:
                raise ScannerError("short hexadecimal escape")
            try:
                result.append(chr(int(value, 16)))
            except (ValueError, OverflowError) as exc:
                raise ScannerError("invalid hexadecimal escape") from exc
            i += digits + 1
        elif code in "\r\n":
            i += 1
            if code == "\r" and i < len(text) - 1 and text[i] == "\n":
                i += 1
            while i < len(text) - 1 and text[i] in " \t":
                i += 1
        else:
            raise ScannerError(f"unknown escape character {code!r}")
    return "".join(result)


def _quote_end(text: str, quote: str) -> int | None:
    i = text.find(quote)
    while i >= 0:
        if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
            i = text.find(quote, i + 2)
            continue
        if quote == '"':
            backslashes = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2:
                i = text.find(quote, i + 1)
                continue
        return i
    return None


def _quoted_complete(text: str) -> bool:
    return len(text) > 1 and _quote_end(text[1:], text[0]) is not None


def _fold_lines(pieces: list[str]) -> str:
    if not pieces:
        return ""
    result = [pieces[0]]
    previous = pieces[0]
    for piece in pieces[1:]:
        if not piece:
            result.append("\n")
        elif previous and not previous[-1].isspace() and not piece[0].isspace():
            result.append(" ")
        result.append(piece)
        previous = piece
    return "".join(result)


def _fold_quoted_lines(pieces: list[str], double: bool) -> str:
    if not double:
        return _fold_lines(pieces)
    result = [pieces[0]] if pieces else []
    previous = pieces[0] if pieces else ""
    for piece in pieces[1:]:
        if previous.endswith("\\"):
            result.append("\n")
        elif not piece:
            result.append("\n")
        elif previous and not previous[-1].isspace() and not piece[0].isspace():
            result.append(" ")
        result.append(piece)
        previous = piece
    return "".join(result)


def _timestamp(value: str) -> _datetime.date | _datetime.datetime:
    if _DATE.match(value):
        return _datetime.date.fromisoformat(value)
    normalized = re.sub(r"[ \t]+", "T", value.strip(), count=1)
    normalized = re.sub(r"[ \t]+", "", normalized)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    match = re.search(r"([-+])(\d{1,2})$", normalized)
    if match:
        normalized += ":00"
    return _datetime.datetime.fromisoformat(normalized)


def resolve_scalar(value: str, enabled: bool = True) -> Any:
    if not enabled:
        return value
    lower = value.lower()
    if lower in _NULL:
        return None
    if lower in _BOOL:
        return _BOOL[lower]
    compact = value.replace("_", "")
    if _INT.match(value):
        sign = -1 if compact.startswith("-") else 1
        unsigned = compact.lstrip("+-")
        if ":" in unsigned:
            total = 0
            for component in unsigned.split(":"):
                total = total * 60 + int(component)
            return sign * total
        if unsigned.startswith(("0b", "0B")):
            return sign * int(unsigned[2:], 2)
        if unsigned.startswith(("0x", "0X")):
            return sign * int(unsigned[2:], 16)
        if unsigned.startswith(("0o", "0O")):
            return sign * int(unsigned[2:], 8)
        if len(unsigned) > 1 and unsigned.startswith("0"):
            return sign * int(unsigned, 8)
        return int(compact, 10)
    if _FLOAT.match(value):
        if ":" in compact:
            sign = -1.0 if compact.startswith("-") else 1.0
            parts = compact.lstrip("+-").split(":")
            total = 0.0
            for component in parts:
                total = total * 60.0 + float(component)
            return sign * total
        special = compact.lower().lstrip("+-")
        if special == ".inf":
            return -math.inf if compact.startswith("-") else math.inf
        if special == ".nan":
            return math.nan
        return float(compact)
    if _DATE.match(value) or _TIMESTAMP.match(value):
        try:
            return _timestamp(value)
        except ValueError:
            pass
    return value


class _FlowParser:
    def __init__(self, owner: "_Parser", text: str):
        self.owner = owner
        self.text = text
        self.pos = 0

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def parse(self) -> Any:
        self.skip()
        value = self.value()
        self.skip()
        if self.pos != len(self.text):
            raise ParserError(f"unexpected flow content: {self.text[self.pos:]!r}")
        return value

    def value(self, key: bool = False) -> Any:
        self.skip()
        if self.pos >= len(self.text):
            return None
        char = self.text[self.pos]
        if char == "[":
            return self.sequence()
        if char == "{":
            return self.mapping()
        if char in "'\"":
            return self.quoted()
        start = self.pos
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char in ",]}":
                break
            if key and char == ":":
                break
            if char == "#" and (
                self.pos == start or self.text[self.pos - 1].isspace()
            ):
                break
            self.pos += 1
        return self.owner.inline(self.text[start:self.pos].strip())

    def quoted(self) -> str:
        quote = self.text[self.pos]
        start = self.pos
        self.pos += 1
        while self.pos < len(self.text):
            if quote == '"' and self.text[self.pos] == "\\":
                self.pos += 2
                continue
            if self.text[self.pos] == quote:
                if quote == "'" and self.pos + 1 < len(self.text) and \
                        self.text[self.pos + 1] == "'":
                    self.pos += 2
                    continue
                self.pos += 1
                token = self.text[start:self.pos]
                return token[1:-1].replace("''", "'") if quote == "'" else _decode_double(token)
            self.pos += 1
        raise ScannerError("unterminated quoted scalar")

    def sequence(self) -> list[Any]:
        self.pos += 1
        values = []
        while True:
            self.skip()
            if self.pos < len(self.text) and self.text[self.pos] == "]":
                self.pos += 1
                return values
            values.append(self.value())
            self.skip()
            if self.pos >= len(self.text):
                raise ParserError("unterminated flow sequence")
            if self.text[self.pos] == ",":
                self.pos += 1
            elif self.text[self.pos] == "]":
                self.pos += 1
                return values
            else:
                raise ParserError("expected ',' or ']' in flow sequence")

    def mapping(self) -> dict[Any, Any]:
        self.pos += 1
        result = {}
        while True:
            self.skip()
            if self.pos < len(self.text) and self.text[self.pos] == "}":
                self.pos += 1
                return result
            key = self.value(key=True)
            self.skip()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                raise ParserError("expected ':' in flow mapping")
            self.pos += 1
            value = self.value()
            self.owner.assign(result, key, value)
            self.skip()
            if self.pos >= len(self.text):
                raise ParserError("unterminated flow mapping")
            if self.text[self.pos] == ",":
                self.pos += 1
            elif self.text[self.pos] == "}":
                self.pos += 1
                return result
            else:
                raise ParserError("expected ',' or '}' in flow mapping")


class _Parser:
    def __init__(self, lines: list[_Line], resolve: bool):
        self.lines = lines
        self.resolve = resolve
        self.anchors: dict[str, Any] = {}

    def significant(self, index: int, stop: int) -> int:
        while index < stop and (
            self.lines[index].blank or self.lines[index].text.startswith("%")
        ):
            index += 1
        return index

    def assign(self, mapping: dict[Any, Any], key: Any, value: Any) -> None:
        if key == "<<":
            sources = value if isinstance(value, list) else [value]
            for source in sources:
                if not isinstance(source, dict):
                    raise ConstructorError("merge value must be a mapping or list of mappings")
                for merged_key, merged_value in source.items():
                    mapping.setdefault(merged_key, merged_value)
            return
        try:
            mapping[key] = value
        except TypeError as exc:
            raise ConstructorError("found unhashable mapping key") from exc

    def inline(self, text: str) -> Any:
        text = text.strip()
        if text in {"-", "?", ":"}:
            raise ScannerError(f"invalid bare indicator {text!r}")
        anchor_match = _ANCHOR.match(text)
        if anchor_match:
            name, rest = anchor_match.groups()
            if rest is None:
                return _PendingAnchor(name)
            value = self.inline(rest)
            self.anchors[name] = value
            return value
        if text.startswith("*"):
            name = text[1:].strip()
            if name not in self.anchors:
                raise ComposerError(f"found undefined alias {name!r}")
            return self.anchors[name]
        tag = None
        tag_match = _TAG.match(text)
        if tag_match:
            tag, text = tag_match.groups()
            text = text or ""
            if tag.startswith("!") and not tag.startswith("!!"):
                raise ConstructorError(f"unsupported YAML tag {tag!r}")
        if text.startswith("[") or text.startswith("{"):
            value = _FlowParser(self, text).parse()
        elif len(text) >= 2 and text[0] == text[-1] == "'":
            value = text[1:-1].replace("''", "'")
        elif len(text) >= 2 and text[0] == text[-1] == '"':
            value = _decode_double(text)
        else:
            value = resolve_scalar(text, self.resolve)
        if tag:
            return self.tagged(tag, value, text)
        return value

    def tagged(self, tag: str, value: Any, source: str) -> Any:
        if tag == "!!str":
            return value if isinstance(value, str) else source
        if tag == "!!null":
            return None
        if tag == "!!bool":
            lower = source.lower()
            if lower not in _BOOL:
                raise ConstructorError(f"invalid boolean {source!r}")
            return _BOOL[lower]
        if tag == "!!int":
            resolved = resolve_scalar(source)
            if not isinstance(resolved, int) or isinstance(resolved, bool):
                raise ConstructorError(f"invalid integer {source!r}")
            return resolved
        if tag == "!!float":
            resolved = resolve_scalar(source)
            if isinstance(resolved, (int, float)) and not isinstance(resolved, bool):
                return float(resolved)
            raise ConstructorError(f"invalid float {source!r}")
        if tag == "!!timestamp":
            return _timestamp(source)
        if tag == "!!binary":
            encoded = value if isinstance(value, str) else source
            try:
                return base64.b64decode("".join(encoded.split()), validate=True)
            except ValueError as exc:
                raise ConstructorError("invalid base64 data in binary scalar") from exc
        if tag in {"!!seq", "!!map"}:
            return value
        raise ConstructorError(f"unsupported YAML tag {tag!r}")

    def block_scalar(self, index: int, stop: int, parent_indent: int, header: str) -> tuple[str, int]:
        style = header[0]
        modifiers = header[1:].strip()
        chomp = "+" if "+" in modifiers else "-" if "-" in modifiers else ""
        explicit = next((int(c) for c in modifiers if c.isdigit()), None)
        end = index
        while end < stop:
            line = self.lines[end]
            if not line.blank and line.indent <= parent_indent:
                break
            end += 1
        content = self.lines[index:end]
        nonblank = [line.indent for line in content if not line.blank]
        content_indent = parent_indent + explicit if explicit else (
            min(nonblank) if nonblank else parent_indent + 1
        )
        pieces = [
            "" if line.blank else line.raw[min(content_indent, len(line.raw)):]
            for line in content
        ]
        if style == "|":
            value = "\n".join(pieces)
        else:
            value = _fold_lines(pieces)
        if chomp == "-":
            value = value.rstrip("\n")
        elif chomp == "+":
            pass
        else:
            value = value.rstrip("\n") + "\n" if value.strip("\n") else ""
        return value, end

    def nested_value(
        self, index: int, stop: int, parent_indent: int, source: str
    ) -> tuple[Any, int]:
        if source.startswith(("|", ">")):
            return self.block_scalar(index + 1, stop, parent_indent, source)
        if source.startswith(("'", '"')) and not _quoted_complete(source):
            return self.multiline_quoted(index, stop, source)
        value = self.inline(source)
        if isinstance(value, _PendingAnchor):
            nxt = self.significant(index + 1, stop)
            if nxt < stop and self.lines[nxt].indent > parent_indent:
                nested, nxt = self.block(nxt, stop, self.lines[nxt].indent)
            else:
                nested, nxt = None, index + 1
            self.anchors[value.name] = nested
            return nested, nxt
        return value, index + 1

    def multiline_quoted(
        self, index: int, stop: int, source: str
    ) -> tuple[str, int]:
        quote_char = source[0]
        pieces = [source[1:]]
        index += 1
        while index < stop:
            piece = self.lines[index].raw.lstrip()
            closing = _quote_end(piece, quote_char)
            if closing is not None:
                final_piece = piece[:closing]
                if final_piece:
                    pieces.append(final_piece)
                folded = _fold_quoted_lines(pieces, quote_char == '"')
                if quote_char == "'":
                    return folded.replace("''", "'"), index + 1
                return _decode_double('"' + folded + '"'), index + 1
            pieces.append(piece)
            index += 1
        raise ScannerError("unterminated quoted scalar")

    def mapping(self, index: int, stop: int, indent: int) -> tuple[dict[Any, Any], int]:
        result: dict[Any, Any] = {}
        while True:
            index = self.significant(index, stop)
            if index >= stop or self.lines[index].indent != indent:
                break
            split = _mapping_split(self.lines[index].text)
            if split is None:
                break
            key_source, value_source = split
            key = self.inline(key_source)
            if isinstance(key, _PendingAnchor):
                raise ConstructorError("an anchor cannot stand in for a mapping key")
            if value_source:
                value, index = self.nested_value(
                    index, stop, indent, value_source
                )
            else:
                nxt = self.significant(index + 1, stop)
                indentless_sequence = (
                    nxt < stop and self.lines[nxt].indent == indent and
                    (self.lines[nxt].text == "-" or self.lines[nxt].text.startswith("- "))
                )
                if nxt < stop and (
                    self.lines[nxt].indent > indent or indentless_sequence
                ):
                    value, index = self.block(nxt, stop, self.lines[nxt].indent)
                else:
                    value, index = None, index + 1
            self.assign(result, key, value)
        return result, index

    def compact_mapping(
        self, index: int, stop: int, sequence_indent: int, source: str
    ) -> tuple[dict[Any, Any], int]:
        split = _mapping_split(source)
        if split is None:
            raise ParserError("expected compact mapping")
        result: dict[Any, Any] = {}
        key_source, value_source = split
        key = self.inline(key_source)
        if value_source:
            value, nxt = self.nested_value(index, stop, sequence_indent, value_source)
        else:
            nxt = self.significant(index + 1, stop)
            if nxt < stop and self.lines[nxt].indent > sequence_indent:
                value, nxt = self.block(nxt, stop, self.lines[nxt].indent)
            else:
                value, nxt = None, index + 1
        self.assign(result, key, value)
        continuation = self.significant(nxt, stop)
        if continuation < stop and self.lines[continuation].indent > sequence_indent:
            continuation_indent = self.lines[continuation].indent
            extra, continuation = self.mapping(
                continuation, stop, continuation_indent
            )
            for extra_key, extra_value in extra.items():
                self.assign(result, extra_key, extra_value)
        return result, continuation

    def sequence(self, index: int, stop: int, indent: int) -> tuple[list[Any], int]:
        result = []
        while True:
            index = self.significant(index, stop)
            if index >= stop or self.lines[index].indent != indent:
                break
            text = self.lines[index].text
            if not (text == "-" or text.startswith("- ")):
                break
            source = text[1:].lstrip()
            if not source:
                nxt = self.significant(index + 1, stop)
                if nxt < stop and self.lines[nxt].indent > indent:
                    value, index = self.block(nxt, stop, self.lines[nxt].indent)
                else:
                    value, index = None, index + 1
            elif source.startswith(("|", ">")):
                value, index = self.block_scalar(index + 1, stop, indent, source)
            elif _mapping_split(source):
                value, index = self.compact_mapping(index, stop, indent, source)
            else:
                value, index = self.nested_value(index, stop, indent, source)
            result.append(value)
        return result, index

    def block(self, index: int, stop: int, indent: int) -> tuple[Any, int]:
        index = self.significant(index, stop)
        if index >= stop:
            return None, index
        line = self.lines[index]
        if line.indent < indent:
            return None, index
        text = line.text
        if text == "-" or text.startswith("- "):
            return self.sequence(index, stop, line.indent)
        if _mapping_split(text):
            return self.mapping(index, stop, line.indent)
        if text.startswith(("|", ">")):
            return self.block_scalar(index + 1, stop, line.indent, text)
        if text.startswith(("'", '"')) and not _quoted_complete(text):
            return self.multiline_quoted(index, stop, text)
        return self.inline(text), index + 1


def _lines(data: bytes) -> list[_Line]:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReaderError("YAML input is not valid UTF-8") from exc
    starts, ends, indents, _ = scan_lines(data)
    result = []
    for number, (start, end, indent) in enumerate(
        zip(starts, ends, indents), 1
    ):
        raw = data[start:end].decode("utf-8")
        if raw.startswith("\t"):
            raise ScannerError(f"tab indentation is not allowed at line {number}")
        result.append(_Line(number, indent, raw))
    return result


class ReaderError(ScannerError):
    pass


def parse_documents(data: bytes, loader: type = SafeLoader) -> list[Any]:
    lines = _lines(data)
    ranges: list[tuple[int, int, str | None]] = []
    start = 0
    inline_start = None
    explicit_document = False
    i = 0
    while i < len(lines):
        text = lines[i].text
        if lines[i].indent == 0 and (text == "---" or text.startswith("--- ")):
            has_content = any(
                not line.blank and not line.text.startswith("%")
                for line in lines[start:i]
            )
            if explicit_document or inline_start is not None or has_content:
                ranges.append((start, i, inline_start))
            start = i + 1
            inline_start = text[3:].strip() or None
            explicit_document = True
        elif lines[i].indent == 0 and (text == "..." or text.startswith("... ")):
            ranges.append((start, i, inline_start))
            start = i + 1
            inline_start = None
            explicit_document = False
        i += 1
    has_content = any(
        not line.blank and not line.text.startswith("%") for line in lines[start:]
    )
    if explicit_document or inline_start is not None or has_content:
        ranges.append((start, len(lines), inline_start))
    if not ranges:
        return []

    documents = []
    for start, stop, inline in ranges:
        parser = _Parser(lines, getattr(loader, "resolve_scalars", True))
        if inline is not None:
            value = parser.inline(inline)
        else:
            first = parser.significant(start, stop)
            value, consumed = parser.block(
                first, stop, lines[first].indent if first < stop else 0
            )
            leftover = parser.significant(consumed, stop)
            if leftover < stop:
                raise ParserError(
                    f"unexpected content at line {lines[leftover].number}"
                )
        documents.append(value)
    return documents
