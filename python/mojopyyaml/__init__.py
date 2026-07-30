"""A standalone YAML parser and emitter accelerated by Mojo lexical kernels."""

from __future__ import annotations

from typing import Any

from .dumper import Dumper, SafeDumper, dump_documents
from .errors import (
    ComposerError,
    ConstructorError,
    EmitterError,
    MarkedYAMLError,
    ParserError,
    RepresenterError,
    ScannerError,
    SerializerError,
    YAMLError,
)
from .loader import (
    BaseLoader,
    FullLoader,
    Loader,
    ReaderError,
    SafeLoader,
    UnsafeLoader,
    parse_documents,
)


__version__ = "0.1.0"


def _read(stream: Any) -> bytes:
    value = stream.read() if hasattr(stream, "read") else stream
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TypeError("stream must be str, bytes, or a file-like object")


def load(stream, Loader=Loader):
    documents = parse_documents(_read(stream), Loader)
    if len(documents) > 1:
        raise ComposerError("expected a single document in the stream")
    return documents[0] if documents else None


def load_all(stream, Loader=Loader):
    yield from parse_documents(_read(stream), Loader)


def safe_load(stream):
    return load(stream, Loader=SafeLoader)


def safe_load_all(stream):
    return load_all(stream, Loader=SafeLoader)


def full_load(stream):
    return load(stream, Loader=FullLoader)


def full_load_all(stream):
    return load_all(stream, Loader=FullLoader)


def unsafe_load(stream):
    return load(stream, Loader=UnsafeLoader)


def unsafe_load_all(stream):
    return load_all(stream, Loader=UnsafeLoader)


def dump_all(
    documents,
    stream=None,
    Dumper=Dumper,
    default_style=None,
    default_flow_style=False,
    canonical=None,
    indent=None,
    width=None,
    allow_unicode=None,
    line_break=None,
    encoding=None,
    explicit_start=None,
    explicit_end=None,
    version=None,
    tags=None,
    sort_keys=True,
):
    del Dumper
    text = dump_documents(
        list(documents),
        default_style=default_style,
        default_flow_style=default_flow_style,
        canonical=bool(canonical),
        indent=indent or 2,
        width=width or 80,
        allow_unicode=allow_unicode,
        line_break=line_break,
        explicit_start=explicit_start,
        explicit_end=explicit_end,
        version=version,
        tags=tags,
        sort_keys=sort_keys,
    )
    result = text.encode(encoding) if encoding else text
    if stream is None:
        return result
    stream.write(result)
    return None


def dump(data, stream=None, Dumper=Dumper, **kwds):
    return dump_all([data], stream, Dumper=Dumper, **kwds)


def safe_dump_all(documents, stream=None, **kwds):
    return dump_all(documents, stream, Dumper=SafeDumper, **kwds)


def safe_dump(data, stream=None, **kwds):
    return dump_all([data], stream, Dumper=SafeDumper, **kwds)


serialize_all = dump_all


__all__ = [
    "BaseLoader", "ComposerError", "ConstructorError", "Dumper", "EmitterError",
    "FullLoader", "Loader", "MarkedYAMLError", "ParserError", "ReaderError", "RepresenterError",
    "SafeDumper", "SafeLoader", "ScannerError", "SerializerError", "UnsafeLoader",
    "YAMLError", "dump", "dump_all", "full_load", "full_load_all", "load",
    "load_all", "safe_dump", "safe_dump_all", "safe_load", "safe_load_all",
    "unsafe_load", "unsafe_load_all",
]
