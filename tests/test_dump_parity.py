from __future__ import annotations

import datetime
import io

import pytest
import yaml

import mojopyyaml


@pytest.mark.parametrize("function_name", ["dump", "safe_dump"])
def test_single_document_dump_entry_points(function_name):
    function = getattr(mojopyyaml, function_name)
    assert yaml.safe_load(function({"answer": 42})) == {"answer": 42}


@pytest.mark.parametrize("function_name", ["dump_all", "safe_dump_all"])
def test_multi_document_dump_entry_points(function_name):
    function = getattr(mojopyyaml, function_name)
    assert list(yaml.safe_load_all(function([1, 2]))) == [1, 2]


CASES = [
    None,
    True,
    42,
    -2.5,
    "plain",
    "true",
    "with: punctuation # that needs quoting",
    "unicode \N{SNOWMAN}",
    "line one\nline two\n",
    [1, "two", False, None],
    {"z": 1, "a": [1, 2], "nested": {"enabled": True}},
    datetime.date(2025, 12, 31),
    datetime.datetime(2025, 12, 31, 23, 59, 58),
]


@pytest.mark.parametrize("value", CASES)
def test_safe_dump_roundtrips_through_both_implementations(value):
    ours = mojopyyaml.safe_dump(value)
    upstream = yaml.safe_dump(value)
    assert yaml.safe_load(ours) == value
    assert mojopyyaml.safe_load(upstream) == value


def test_loads_pyyaml_wrapped_double_quoted_scalar():
    value = ("The quick brown fox jumps over the lazy dog. " * 1000) + "\n"
    assert mojopyyaml.safe_load(yaml.safe_dump(value)) == value


def test_sort_keys_matches_upstream_order():
    value = {"z": 1, "a": 2, "m": 3}
    assert list(mojopyyaml.safe_load(mojopyyaml.safe_dump(value)).keys()) == ["a", "m", "z"]
    unsorted = mojopyyaml.safe_dump(value, sort_keys=False)
    assert list(mojopyyaml.safe_load(unsorted).keys()) == ["z", "a", "m"]


def test_flow_style_roundtrip():
    value = {"a": [1, 2], "b": {"c": True}}
    text = mojopyyaml.safe_dump(value, default_flow_style=True)
    assert text.startswith("{")
    assert yaml.safe_load(text) == value


def test_custom_indentation_roundtrip():
    text = mojopyyaml.safe_dump({"outer": {"inner": [1, 2]}}, indent=4)
    assert "\n    inner:\n" in text
    assert yaml.safe_load(text) == {"outer": {"inner": [1, 2]}}


def test_explicit_markers_version_and_line_break():
    text = mojopyyaml.safe_dump(
        {"a": 1},
        explicit_start=True,
        explicit_end=True,
        version=(1, 1),
        line_break="\r\n",
    )
    assert text.startswith("%YAML 1.1\r\n---\r\n")
    assert text.endswith("...\r\n")
    assert yaml.safe_load(text) == {"a": 1}


def test_allow_unicode_false_uses_ascii_escapes():
    text = mojopyyaml.safe_dump({"value": "snowman \N{SNOWMAN}"}, allow_unicode=False)
    assert text.isascii()
    assert yaml.safe_load(text) == {"value": "snowman \N{SNOWMAN}"}


def test_bytes_roundtrip_as_yaml_binary():
    value = {"payload": bytes(range(32))}
    text = mojopyyaml.safe_dump(value)
    assert yaml.safe_load(text) == value
    assert mojopyyaml.safe_load(text) == value


def test_dump_all_and_load_all():
    documents = [{"a": 1}, [2, 3], None]
    text = mojopyyaml.safe_dump_all(documents)
    assert list(yaml.safe_load_all(text)) == documents
    assert list(mojopyyaml.safe_load_all(text)) == documents


def test_text_and_binary_stream_output():
    text_stream = io.StringIO()
    assert mojopyyaml.safe_dump({"a": 1}, text_stream) is None
    assert yaml.safe_load(text_stream.getvalue()) == {"a": 1}

    byte_stream = io.BytesIO()
    assert mojopyyaml.safe_dump({"a": 1}, byte_stream, encoding="utf-8") is None
    assert yaml.safe_load(byte_stream.getvalue()) == {"a": 1}


def test_unsupported_object_raises_representer_error():
    with pytest.raises(mojopyyaml.RepresenterError):
        mojopyyaml.safe_dump(object())


@pytest.mark.parametrize("flow", [False, True])
def test_recursive_object_raises_representer_error(flow):
    value = []
    value.append(value)
    with pytest.raises(mojopyyaml.RepresenterError):
        mojopyyaml.safe_dump(value, default_flow_style=flow)
