from __future__ import annotations

import numpy as np
import pytest
import yaml

import mojopyyaml
from mojopyyaml._lib import lib, quote, scan_lines


def test_scan_lines_empty_input_avoids_null_pointer_ffi():
    records = scan_lines(b"")
    assert records.dtype == np.int64
    assert records.tolist() == [[0], [0], [0], [0]]


def test_native_kernels_reject_null_pointers_and_short_capacity():
    native = lib()
    assert native.mpy_scan_lines(0, 0, 0, 0, 0, 0, 1) == -1
    assert native.mpy_quoted_size(0, 0) == -1

    source = np.frombuffer(b"x" * 256, dtype=np.uint8)
    destination = np.empty(2, dtype=np.uint8)
    assert native.mpy_quote(
        source.ctypes.data, source.size, destination.ctypes.data, destination.size
    ) == -1


@pytest.mark.parametrize("indent", [0, 1, 31, 32, 33, 63, 64, 65])
def test_scan_lines_simd_blocks_and_scalar_tails(indent):
    first = (b" " * indent) + b"value \t\n"
    data = first + b"next"
    records = scan_lines(data)

    assert records.dtype == np.int64
    assert records.shape == (4, 2)
    assert records[:, 0].tolist() == [
        0,
        indent + 7,
        indent,
        indent + 5,
    ]
    assert records[:, 1].tolist() == [
        len(first),
        len(data),
        0,
        len(data),
    ]


def test_scan_lines_crlf_and_trailing_empty_line():
    data = b"  first \t\r\nsecond\r\n"
    assert scan_lines(data).T.tolist() == [
        [0, 9, 2, 7],
        [11, 17, 0, 17],
        [19, 19, 0, 19],
    ]


@pytest.mark.parametrize("size", [255, 256])
def test_quote_small_and_bulk_paths_match(size):
    value = ('"\\\b\t\n\f\r\x01snowman-\N{SNOWMAN}' * 20)[:size]
    encoded = quote(value)
    assert yaml.safe_load(encoded) == value
    assert mojopyyaml.safe_load(encoded) == value
