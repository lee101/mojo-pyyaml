from __future__ import annotations

import base64
import datetime
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from ._lib import quote
from .errors import RepresenterError
from .loader import resolve_scalar


class SafeDumper:
    pass


class Dumper(SafeDumper):
    pass


def _plain_string(value: str) -> bool:
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        return False
    if value[0] in "-?:,[]{}#&*!|>'\"%@`":
        return False
    if ": " in value or " #" in value or value.endswith(":"):
        return False
    return resolve_scalar(value) == value


class _Emitter:
    def __init__(
        self,
        *,
        default_style: str | None,
        default_flow_style: bool | None,
        canonical: bool,
        indent: int,
        width: int,
        allow_unicode: bool | None,
        sort_keys: bool,
    ):
        self.default_style = default_style
        self.flow = bool(default_flow_style) or canonical
        self.canonical = canonical
        self.indent = max(2, indent)
        self.width = width
        self.allow_unicode = allow_unicode is not False
        self.sort_keys = sort_keys
        self.active: set[int] = set()

    def scalar(self, value: Any, key: bool = False) -> str:
        if isinstance(value, str):
            if self.default_style == "'":
                return "'" + value.replace("'", "''") + "'"
            if not self.allow_unicode and any(ord(char) > 127 for char in value):
                return json.dumps(value, ensure_ascii=True)
            if self.default_style == '"' or not _plain_string(value):
                return quote(value)
            return value
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if math.isnan(value):
                return ".nan"
            if math.isinf(value):
                return ".inf" if value > 0 else "-.inf"
            text = repr(value)
            return text if any(c in text for c in ".eE") else text + ".0"
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
        if isinstance(value, bytes):
            return "!!binary " + quote(base64.b64encode(value).decode("ascii"))
        raise RepresenterError(f"cannot represent an object of type {type(value).__name__}")

    def is_collection(self, value: Any) -> bool:
        if isinstance(value, (str, bytes, bytearray)):
            return False
        return isinstance(value, Mapping) or (
            isinstance(value, Sequence)
        )

    def flow_value(self, value: Any) -> str:
        if not self.is_collection(value):
            return self.scalar(value)
        identity = id(value)
        if identity in self.active:
            raise RepresenterError("recursive objects are not supported")
        self.active.add(identity)
        try:
            if isinstance(value, Mapping):
                items = self.items(value)
                return "{" + ", ".join(
                    f"{self.flow_value(key)}: {self.flow_value(item)}"
                    for key, item in items
                ) + "}"
            return "[" + ", ".join(self.flow_value(item) for item in value) + "]"
        finally:
            self.active.remove(identity)

    def items(self, value: Mapping) -> list[tuple[Any, Any]]:
        items = list(value.items())
        if self.sort_keys:
            try:
                items.sort(key=lambda item: item[0])
            except TypeError:
                items.sort(key=lambda item: str(item[0]))
        return items

    def lines(self, value: Any, level: int = 0) -> list[str]:
        if self.flow:
            return [" " * level + self.flow_value(value)]
        if not self.is_collection(value):
            return [" " * level + self.scalar(value)]
        identity = id(value)
        if identity in self.active:
            raise RepresenterError("recursive objects are not supported")
        self.active.add(identity)
        try:
            if isinstance(value, Mapping):
                if not value:
                    return [" " * level + "{}"]
                result = []
                for key, item in self.items(value):
                    key_text = self.scalar(key, key=True)
                    item_is_collection = self.is_collection(item)
                    if item_is_collection and item:
                        result.append(" " * level + key_text + ":")
                        result.extend(self.lines(item, level + self.indent))
                    else:
                        result.append(
                            " " * level + key_text + ": " +
                            (self.flow_value(item) if item_is_collection else self.scalar(item))
                        )
                return result
            if not value:
                return [" " * level + "[]"]
            result = []
            for item in value:
                item_is_collection = self.is_collection(item)
                if item_is_collection and item:
                    result.append(" " * level + "-")
                    result.extend(self.lines(item, level + self.indent))
                else:
                    result.append(
                        " " * level + "- " +
                        (self.flow_value(item) if item_is_collection else self.scalar(item))
                    )
            return result
        finally:
            self.active.remove(identity)


def dump_documents(
    documents: list[Any],
    *,
    default_style: str | None = None,
    default_flow_style: bool | None = False,
    canonical: bool = False,
    indent: int = 2,
    width: int = 80,
    allow_unicode: bool | None = None,
    line_break: str | None = None,
    explicit_start: bool | None = None,
    explicit_end: bool | None = None,
    version: tuple[int, int] | None = None,
    tags: dict[str, str] | None = None,
    sort_keys: bool = True,
) -> str:
    emitter = _Emitter(
        default_style=default_style,
        default_flow_style=default_flow_style,
        canonical=canonical,
        indent=indent,
        width=width,
        allow_unicode=allow_unicode,
        sort_keys=sort_keys,
    )
    newline = line_break or "\n"
    output: list[str] = []
    many = len(documents) > 1
    for document in documents:
        if version:
            output.append(f"%YAML {version[0]}.{version[1]}")
        if tags:
            output.extend(f"%TAG {handle} {prefix}" for handle, prefix in tags.items())
        if explicit_start or many or version or tags:
            output.append("---")
        output.extend(emitter.lines(document))
        if explicit_end:
            output.append("...")
    return newline.join(output) + (newline if output else "")
