from __future__ import annotations

import ctypes
import json
import os
import subprocess

import numpy as np


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "dist", "libmojo-pyyaml.so")
I = ctypes.c_int64
MAX_ABI_LENGTH = (1 << 63) - 1

_library: ctypes.CDLL | None = None


def build() -> str:
    sources = [
        os.path.join(path, name)
        for path, _, names in os.walk(os.path.join(ROOT, "src"))
        for name in names
        if name.endswith(".mojo")
    ]
    if os.path.exists(LIB) and os.path.getmtime(LIB) >= max(map(os.path.getmtime, sources)):
        return LIB
    subprocess.run(["bash", os.path.join(ROOT, "build", "build.sh")], check=True)
    return LIB


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        _library = ctypes.CDLL(build())
        _library.mpy_scan_lines.argtypes = [I, I, I, I, I, I, I]
        _library.mpy_scan_lines.restype = I
        _library.mpy_quoted_size.argtypes = [I, I]
        _library.mpy_quoted_size.restype = I
        _library.mpy_quote.argtypes = [I, I, I, I]
        _library.mpy_quote.restype = I
    return _library


def scan_lines(data: bytes) -> np.ndarray:
    if not isinstance(data, bytes):
        raise TypeError("scan_lines requires bytes")
    if not data:
        return np.zeros((4, 1), dtype=np.int64)
    if len(data) > MAX_ABI_LENGTH:
        raise OverflowError("input is too large for the native ABI")
    count = data.count(b"\n") + 1
    source = np.frombuffer(data, dtype=np.uint8)
    arrays = np.empty((4, count), dtype=np.int64, order="C")
    got = lib().mpy_scan_lines(
        source.ctypes.data,
        len(data),
        *(values.ctypes.data for values in arrays),
        count,
    )
    if got < 1 or got > count:
        raise RuntimeError("native line scanner returned an invalid line count")
    return arrays[:, :got]


def quote(text: str) -> str:
    if len(text) < 256:
        return json.dumps(text, ensure_ascii=False)
    data = text.encode("utf-8")
    if len(data) > MAX_ABI_LENGTH:
        raise OverflowError("encoded string is too large for the native ABI")
    source = np.frombuffer(data, dtype=np.uint8)
    size = int(lib().mpy_quoted_size(source.ctypes.data, len(data)))
    if size < 2 or size > MAX_ABI_LENGTH:
        raise RuntimeError("native quoting size calculation failed")
    dest = np.empty(size, dtype=np.uint8)
    written = int(
        lib().mpy_quote(source.ctypes.data, len(data), dest.ctypes.data, size)
    )
    if written != size:
        raise RuntimeError("native quoting kernel returned an invalid byte count")
    return dest[:written].tobytes().decode("utf-8")
