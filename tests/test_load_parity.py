from __future__ import annotations

import datetime
import math

import pytest
import yaml

import mojopyyaml


@pytest.mark.parametrize(
    "function_name", ["load", "safe_load", "full_load", "unsafe_load"]
)
def test_single_document_load_entry_points(function_name):
    function = getattr(mojopyyaml, function_name)
    assert function("answer: 42\n") == {"answer": 42}


@pytest.mark.parametrize(
    "function_name", ["load_all", "safe_load_all", "full_load_all", "unsafe_load_all"]
)
def test_multi_document_load_entry_points(function_name):
    function = getattr(mojopyyaml, function_name)
    assert list(function("--- 1\n--- 2\n")) == [1, 2]


@pytest.mark.parametrize(
    "source",
    [
        "null",
        "~",
        "true",
        "FALSE",
        "yes",
        "Off",
        "0",
        "-42",
        "0b101101",
        "0755",
        "0xCAFE",
        "1_000_000",
        "12:34:56",
        "3.14159",
        "-2.5e+4",
        ".inf",
        "-.Inf",
        "plain text",
        "'true'",
        '"line\\nfeed"',
        "2026-07-30",
        "2026-07-30 12:34:56Z",
    ],
)
def test_scalar_resolution_matches_pyyaml(source):
    got = mojopyyaml.safe_load(source)
    expected = yaml.safe_load(source)
    if isinstance(expected, float) and math.isnan(expected):
        assert math.isnan(got)
    else:
        assert got == expected
        assert type(got) is type(expected)


def test_nested_block_collections_match():
    source = """
application:
  name: example
  enabled: true
  ports:
    - 8080
    - 8443
  database:
    host: localhost
    credentials:
      user: admin
      password: "s3cr#t"
workers:
  - name: alpha
    concurrency: 4
  - name: beta
    concurrency: 8
empty_map: {}
empty_list: []
"""
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_indentless_sequence_matches():
    source = "items:\n- one\n- two\n"
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_flow_collections_match():
    source = """
point: {x: 1.5, y: -2, labels: [north, "x:y", 'it''s']}
matrix: [[1, 2], [3, 4]]
url: http://example.test:8080/a#fragment
"""
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_comments_only_start_after_separation():
    source = """
hash: abc#def
quoted: "abc # def"
value: 3 # actual comment
"""
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


@pytest.mark.parametrize(
    "source",
    [
        "value: |\n  one\n  two\n",
        "value: |-\n  one\n  two\n",
        "value: |+\n  one\n\n  two\n\n",
        "value: >\n  one\n  two\n",
        "value: >-\n  one\n\n  two\n",
        "value: |2\n    indented\n    text\n",
    ],
)
def test_block_scalar_chomping_matches(source):
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_anchors_aliases_and_merge_match():
    source = """
defaults: &defaults
  enabled: true
  retries: 3
service:
  <<: *defaults
  retries: 5
copy: *defaults
"""
    got = mojopyyaml.safe_load(source)
    expected = yaml.safe_load(source)
    assert got == expected
    assert got["copy"] is got["defaults"]


def test_merge_sequence_precedence_matches():
    source = """
a: &a {x: 1, y: 2}
b: &b {x: 9, z: 3}
combined:
  <<: [*a, *b]
"""
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_multiple_documents_match():
    source = """
%YAML 1.1
---
name: first
---
- second
- document
...
--- {third: true}
"""
    assert list(mojopyyaml.safe_load_all(source)) == list(yaml.safe_load_all(source))


def test_explicit_empty_documents_match():
    source = "---\n---\nvalue\n...\n---\n"
    assert list(mojopyyaml.safe_load_all(source)) == list(yaml.safe_load_all(source))


def test_explicit_tags_match():
    source = """
string: !!str 123
integer: !!int 0x20
float: !!float 2.5
boolean: !!bool YES
nothing: !!null null
date: !!timestamp 2020-02-03
"""
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_quoted_explicit_string_and_binary_tags_match():
    source = 'number: !!str "123"\npayload: !!binary "AAEC/w=="\n'
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_base_loader_keeps_scalars_as_strings():
    source = "a: true\nb: 12\nc: null\n"
    assert mojopyyaml.load(source, Loader=mojopyyaml.BaseLoader) == yaml.load(
        source, Loader=yaml.BaseLoader
    )


def test_unicode_and_all_yaml_double_quote_escapes():
    source = r'"snowman \u2603, tab\t, nul\0, next\N, nbsp\_, line\L"'
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)


def test_file_like_and_bytes_input(tmp_path):
    path = tmp_path / "input.yaml"
    path.write_text("answer: 42\n", encoding="utf-8")
    with path.open("rb") as stream:
        assert mojopyyaml.safe_load(stream) == {"answer": 42}
    assert mojopyyaml.safe_load(b"answer: 42\n") == {"answer": 42}


def test_date_and_datetime_types():
    result = mojopyyaml.safe_load("d: 2020-01-02\nt: 2020-01-02T03:04:05+02:00\n")
    assert result["d"] == datetime.date(2020, 1, 2)
    assert result["t"] == datetime.datetime(
        2020, 1, 2, 3, 4, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )


def test_invalid_alias_raises_yaml_error():
    with pytest.raises(mojopyyaml.YAMLError):
        mojopyyaml.safe_load("value: *missing\n")


def test_tab_indentation_is_rejected():
    with pytest.raises(mojopyyaml.ScannerError):
        mojopyyaml.safe_load("root:\n\tchild: value\n")


@pytest.mark.parametrize("indicator", ["-", "?", ":"])
def test_bare_indicators_are_rejected(indicator):
    with pytest.raises(mojopyyaml.ScannerError):
        mojopyyaml.safe_load(f"value: {indicator}\n")


@pytest.mark.parametrize("source", ["value: |\n", "value: |\n\n", "value: |\n  \n"])
def test_empty_literal_block_matches(source):
    assert mojopyyaml.safe_load(source) == yaml.safe_load(source)
