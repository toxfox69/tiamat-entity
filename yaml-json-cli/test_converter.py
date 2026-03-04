"""
Tests for yaml_json_converter.

Run with:  pytest test_converter.py -v
           pytest test_converter.py -v --cov=yaml_json_converter
"""

import json
import os
import sys
import textwrap
from io import StringIO
from pathlib import Path

import pytest
import yaml

# Ensure the local module is importable when running tests from this dir.
sys.path.insert(0, str(Path(__file__).parent))
from yaml_json_converter import (
    _detect_format,
    _json_serializable,
    _load_json,
    _load_yaml_docs,
    build_parser,
    json_to_yaml,
    main,
    yaml_to_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp(tmp_path):
    """Alias for tmp_path."""
    return tmp_path


# ---------------------------------------------------------------------------
# _load_yaml_docs
# ---------------------------------------------------------------------------

class TestLoadYamlDocs:
    def test_simple_dict(self):
        docs = _load_yaml_docs("key: value\n")
        assert docs == [{"key": "value"}]

    def test_nested_dict(self):
        docs = _load_yaml_docs("a:\n  b:\n    c: 1\n")
        assert docs == [{"a": {"b": {"c": 1}}}]

    def test_list_root(self):
        docs = _load_yaml_docs("- 1\n- 2\n- 3\n")
        assert docs == [[1, 2, 3]]

    def test_multi_document(self):
        text = "key: a\n---\nkey: b\n"
        docs = _load_yaml_docs(text)
        assert len(docs) == 2
        assert docs[0] == {"key": "a"}
        assert docs[1] == {"key": "b"}

    def test_empty_document_returns_empty_list(self):
        docs = _load_yaml_docs("")
        assert docs == []

    def test_malformed_yaml_raises_value_error(self):
        with pytest.raises(ValueError, match="Malformed YAML"):
            _load_yaml_docs("{bad yaml: [unclosed")

    def test_scalar_root(self):
        docs = _load_yaml_docs("42\n")
        assert docs == [42]


# ---------------------------------------------------------------------------
# _load_json
# ---------------------------------------------------------------------------

class TestLoadJson:
    def test_dict(self):
        data = _load_json('{"a": 1}')
        assert data == {"a": 1}

    def test_list(self):
        data = _load_json("[1, 2, 3]")
        assert data == [1, 2, 3]

    def test_nested(self):
        data = _load_json('{"a": {"b": {"c": true}}}')
        assert data["a"]["b"]["c"] is True

    def test_malformed_raises_value_error(self):
        with pytest.raises(ValueError, match="Malformed JSON"):
            _load_json("{bad json}")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            _load_json("")


# ---------------------------------------------------------------------------
# _json_serializable
# ---------------------------------------------------------------------------

class TestJsonSerializable:
    def test_plain_dict_unchanged(self):
        obj = {"a": 1, "b": "x"}
        assert _json_serializable(obj) == obj

    def test_nested_list(self):
        obj = [1, [2, 3], {"k": "v"}]
        assert _json_serializable(obj) == obj

    def test_datetime_to_isoformat(self):
        import datetime
        obj = {"ts": datetime.datetime(2024, 1, 15, 12, 0, 0)}
        result = _json_serializable(obj)
        assert result["ts"] == "2024-01-15T12:00:00"

    def test_date_to_isoformat(self):
        import datetime
        obj = {"d": datetime.date(2024, 6, 1)}
        result = _json_serializable(obj)
        assert result["d"] == "2024-06-01"

    def test_set_to_sorted_list(self):
        obj = {"tags": {3, 1, 2}}
        result = _json_serializable(obj)
        assert result["tags"] == [1, 2, 3]

    def test_bytes_to_base64(self):
        import base64
        obj = {"data": b"hello"}
        result = _json_serializable(obj)
        assert result["data"] == base64.b64encode(b"hello").decode()

    def test_dict_keys_coerced_to_str(self):
        obj = {1: "one", 2: "two"}
        result = _json_serializable(obj)
        assert "1" in result
        assert "2" in result


# ---------------------------------------------------------------------------
# yaml_to_json (function API)
# ---------------------------------------------------------------------------

class TestYamlToJson:
    def test_simple_yaml_to_json_file(self, tmp):
        src = tmp / "in.yaml"
        out = tmp / "out.json"
        src.write_text("name: Alice\nage: 30\n")
        data = yaml_to_json(src, out)
        assert data == {"name": "Alice", "age": 30}
        parsed = json.loads(out.read_text())
        assert parsed == {"name": "Alice", "age": 30}

    def test_nested_yaml(self, tmp):
        src = tmp / "nested.yaml"
        src.write_text("server:\n  host: localhost\n  port: 8080\n")
        data = yaml_to_json(src, text=None)
        assert data["server"]["port"] == 8080

    def test_yaml_list_root(self, tmp):
        src = tmp / "list.yaml"
        src.write_text("- a\n- b\n- c\n")
        data = yaml_to_json(src)
        assert data == ["a", "b", "c"]

    def test_yaml_with_nulls(self, tmp):
        src = tmp / "nulls.yaml"
        src.write_text("key: null\n")
        data = yaml_to_json(src)
        assert data["key"] is None

    def test_yaml_with_booleans(self, tmp):
        src = tmp / "bools.yaml"
        src.write_text("active: true\ndebug: false\n")
        data = yaml_to_json(src)
        assert data["active"] is True
        assert data["debug"] is False

    def test_yaml_with_numbers(self, tmp):
        src = tmp / "nums.yaml"
        src.write_text("count: 42\nrate: 3.14\n")
        data = yaml_to_json(src)
        assert data["count"] == 42
        assert abs(data["rate"] - 3.14) < 1e-9

    def test_multi_document_yaml(self, tmp):
        src = tmp / "multi.yaml"
        src.write_text("id: 1\n---\nid: 2\n")
        data = yaml_to_json(src)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["id"] == 2

    def test_deep_nesting(self, tmp):
        src = tmp / "deep.yaml"
        src.write_text("a:\n  b:\n    c:\n      d: 'leaf'\n")
        data = yaml_to_json(src)
        assert data["a"]["b"]["c"]["d"] == "leaf"

    def test_unicode(self, tmp):
        src = tmp / "unicode.yaml"
        src.write_text("greeting: こんにちは\n", encoding="utf-8")
        data = yaml_to_json(src, encoding="utf-8")
        assert data["greeting"] == "こんにちは"

    def test_yaml_anchors_and_aliases(self, tmp):
        src = tmp / "anchors.yaml"
        src.write_text("defaults: &defaults\n  color: red\nitem:\n  <<: *defaults\n  name: rose\n")
        data = yaml_to_json(src)
        assert data["item"]["color"] == "red"
        assert data["item"]["name"] == "rose"

    def test_file_not_found(self, tmp):
        with pytest.raises(FileNotFoundError, match="Input file not found"):
            yaml_to_json(tmp / "missing.yaml")

    def test_malformed_yaml(self, tmp):
        src = tmp / "bad.yaml"
        src.write_text("{bad: [unclosed\n")
        with pytest.raises(ValueError, match="Malformed YAML"):
            yaml_to_json(src)

    def test_empty_yaml_raises(self, tmp):
        src = tmp / "empty.yaml"
        src.write_text("")
        with pytest.raises(ValueError, match="empty"):
            yaml_to_json(src)

    def test_sort_keys(self, tmp):
        src = tmp / "sort.yaml"
        src.write_text("z: 1\na: 2\nm: 3\n")
        out = tmp / "sort.json"
        yaml_to_json(src, out, sort_keys=True)
        text = out.read_text()
        keys = [line.strip().split('"')[1] for line in text.splitlines() if ":" in line]
        assert keys == sorted(keys)

    def test_indent_option(self, tmp):
        src = tmp / "indent.yaml"
        src.write_text("a: 1\nb: 2\n")
        out = tmp / "indent.json"
        yaml_to_json(src, out, indent=4)
        lines = out.read_text().splitlines()
        # 4-space indent: lines like '    "a": 1'
        data_lines = [l for l in lines if l.startswith("    ")]
        assert len(data_lines) >= 2

    def test_text_kwarg(self):
        data = yaml_to_json(text="x: 42\n")
        assert data == {"x": 42}

    def test_neither_path_nor_text_raises(self):
        with pytest.raises(ValueError, match="Provide either"):
            yaml_to_json()


# ---------------------------------------------------------------------------
# json_to_yaml (function API)
# ---------------------------------------------------------------------------

class TestJsonToYaml:
    def test_simple_json_to_yaml_file(self, tmp):
        src = tmp / "in.json"
        out = tmp / "out.yaml"
        src.write_text('{"name": "Bob", "age": 25}')
        data = json_to_yaml(src, out)
        assert data == {"name": "Bob", "age": 25}
        loaded = yaml.safe_load(out.read_text())
        assert loaded == {"name": "Bob", "age": 25}

    def test_nested_json_to_yaml(self, tmp):
        src = tmp / "nested.json"
        src.write_text('{"db": {"host": "localhost", "port": 5432}}')
        data = json_to_yaml(src)
        assert data["db"]["port"] == 5432

    def test_json_list_to_yaml(self, tmp):
        src = tmp / "list.json"
        src.write_text('[1, 2, 3]')
        data = json_to_yaml(src)
        assert data == [1, 2, 3]

    def test_json_with_nulls(self, tmp):
        src = tmp / "nulls.json"
        src.write_text('{"key": null}')
        out = tmp / "nulls.yaml"
        json_to_yaml(src, out)
        loaded = yaml.safe_load(out.read_text())
        assert loaded["key"] is None

    def test_json_with_booleans(self, tmp):
        src = tmp / "bools.json"
        src.write_text('{"active": true, "debug": false}')
        out = tmp / "bools.yaml"
        json_to_yaml(src, out)
        loaded = yaml.safe_load(out.read_text())
        assert loaded["active"] is True
        assert loaded["debug"] is False

    def test_sort_keys(self, tmp):
        src = tmp / "sort.json"
        src.write_text('{"z": 1, "a": 2, "m": 3}')
        out = tmp / "sort.yaml"
        json_to_yaml(src, out, sort_keys=True)
        text = out.read_text()
        keys = [line.split(":")[0].strip() for line in text.splitlines() if ":" in line]
        assert keys == sorted(keys)

    def test_flow_style(self, tmp):
        src = tmp / "flow.json"
        src.write_text('{"a": [1, 2], "b": {"c": 3}}')
        out = tmp / "flow.yaml"
        json_to_yaml(src, out, default_flow_style=True)
        text = out.read_text()
        # Flow style puts everything on fewer lines
        assert len(text.splitlines()) < 6

    def test_unicode(self, tmp):
        src = tmp / "unicode.json"
        src.write_text('{"greeting": "こんにちは"}', encoding="utf-8")
        out = tmp / "unicode.yaml"
        json_to_yaml(src, out, encoding="utf-8")
        loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert loaded["greeting"] == "こんにちは"

    def test_deep_nesting(self, tmp):
        src = tmp / "deep.json"
        src.write_text('{"a":{"b":{"c":{"d":"leaf"}}}}')
        data = json_to_yaml(src)
        assert data["a"]["b"]["c"]["d"] == "leaf"

    def test_file_not_found(self, tmp):
        with pytest.raises(FileNotFoundError, match="Input file not found"):
            json_to_yaml(tmp / "missing.json")

    def test_malformed_json(self, tmp):
        src = tmp / "bad.json"
        src.write_text("{bad json}")
        with pytest.raises(ValueError, match="Malformed JSON"):
            json_to_yaml(src)

    def test_text_kwarg(self):
        data = json_to_yaml(text='{"x": 99}')
        assert data == {"x": 99}

    def test_neither_path_nor_text_raises(self):
        with pytest.raises(ValueError, match="Provide either"):
            json_to_yaml()


# ---------------------------------------------------------------------------
# _detect_format
# ---------------------------------------------------------------------------

class TestDetectFormat:
    def test_yaml_extension(self):
        assert _detect_format(Path("file.yaml"), None) == "yaml"

    def test_yml_extension(self):
        assert _detect_format(Path("file.yml"), None) == "yaml"

    def test_json_extension(self):
        assert _detect_format(Path("file.json"), None) == "json"

    def test_jsonl_extension(self):
        assert _detect_format(Path("file.jsonl"), None) == "json"

    def test_forced_yaml(self):
        assert _detect_format(Path("file.txt"), "yaml") == "yaml"

    def test_forced_json(self):
        assert _detect_format(Path("file.txt"), "json") == "json"

    def test_unknown_extension_raises(self):
        with pytest.raises(ValueError, match="Cannot detect format"):
            _detect_format(Path("file.txt"), None)


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_yaml_to_json_via_cli(self, tmp):
        src = tmp / "in.yaml"
        out = tmp / "out.json"
        src.write_text("hello: world\n")
        rc = main([str(src), "-o", str(out)])
        assert rc == 0
        assert json.loads(out.read_text()) == {"hello": "world"}

    def test_json_to_yaml_via_cli(self, tmp):
        src = tmp / "in.json"
        out = tmp / "out.yaml"
        src.write_text('{"hello": "world"}')
        rc = main([str(src), "-o", str(out)])
        assert rc == 0
        assert yaml.safe_load(out.read_text()) == {"hello": "world"}

    def test_missing_file_returns_1(self, tmp):
        rc = main([str(tmp / "missing.yaml"), "-o", "/dev/null"])
        assert rc == 1

    def test_malformed_yaml_returns_1(self, tmp):
        src = tmp / "bad.yaml"
        src.write_text("{bad: [unclosed\n")
        rc = main([str(src)])
        assert rc == 1

    def test_malformed_json_returns_1(self, tmp):
        src = tmp / "bad.json"
        src.write_text("{bad json}")
        rc = main([str(src)])
        assert rc == 1

    def test_unknown_extension_exits(self, tmp):
        src = tmp / "file.txt"
        src.write_text("hello")
        with pytest.raises(SystemExit):
            main([str(src)])

    def test_force_from_yaml(self, tmp):
        src = tmp / "data.txt"
        out = tmp / "data.json"
        src.write_text("k: v\n")
        rc = main([str(src), "--from", "yaml", "-o", str(out)])
        assert rc == 0
        assert json.loads(out.read_text()) == {"k": "v"}

    def test_force_from_json(self, tmp):
        src = tmp / "data.txt"
        out = tmp / "data.yaml"
        src.write_text('{"k": "v"}')
        rc = main([str(src), "--from", "json", "-o", str(out)])
        assert rc == 0
        assert yaml.safe_load(out.read_text()) == {"k": "v"}

    def test_sort_keys_flag(self, tmp):
        src = tmp / "s.yaml"
        out = tmp / "s.json"
        src.write_text("z: 3\na: 1\n")
        main([str(src), "--sort-keys", "-o", str(out)])
        text = out.read_text()
        idx_a = text.index('"a"')
        idx_z = text.index('"z"')
        assert idx_a < idx_z

    def test_indent_flag(self, tmp):
        src = tmp / "i.yaml"
        out = tmp / "i.json"
        src.write_text("a: 1\n")
        main([str(src), "--indent", "4", "-o", str(out)])
        lines = out.read_text().splitlines()
        content_lines = [l for l in lines if '"a"' in l]
        assert content_lines[0].startswith("    ")

    def test_flow_style_flag(self, tmp):
        src = tmp / "f.json"
        out = tmp / "f.yaml"
        src.write_text('{"a": [1, 2]}')
        main([str(src), "--flow-style", "-o", str(out)])
        text = out.read_text()
        assert len(text.splitlines()) <= 3

    def test_stdout_yaml_to_json(self, tmp, capsys):
        src = tmp / "stdout.yaml"
        src.write_text("x: 1\n")
        rc = main([str(src)])
        assert rc == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"x": 1}

    def test_stdout_json_to_yaml(self, tmp, capsys):
        src = tmp / "stdout.json"
        src.write_text('{"x": 1}')
        rc = main([str(src)])
        assert rc == 0
        captured = capsys.readouterr()
        assert yaml.safe_load(captured.out) == {"x": 1}

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "1.0.0" in captured.out

    def test_yaml_list_of_objects(self, tmp):
        src = tmp / "objs.yaml"
        out = tmp / "objs.json"
        src.write_text("- id: 1\n  name: Alice\n- id: 2\n  name: Bob\n")
        main([str(src), "-o", str(out)])
        data = json.loads(out.read_text())
        assert len(data) == 2
        assert data[0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_yaml_json_yaml_roundtrip(self, tmp):
        original_yaml = "server:\n  host: localhost\n  port: 8080\ndebug: false\n"
        yaml_in = tmp / "orig.yaml"
        json_mid = tmp / "mid.json"
        yaml_out = tmp / "final.yaml"
        yaml_in.write_text(original_yaml)
        yaml_to_json(yaml_in, json_mid)
        json_to_yaml(json_mid, yaml_out)
        orig = yaml.safe_load(original_yaml)
        final = yaml.safe_load(yaml_out.read_text())
        assert orig == final

    def test_json_yaml_json_roundtrip(self, tmp):
        original_json = '{"users": [{"id": 1, "active": true}, {"id": 2, "active": false}]}'
        json_in = tmp / "orig.json"
        yaml_mid = tmp / "mid.yaml"
        json_out = tmp / "final.json"
        json_in.write_text(original_json)
        json_to_yaml(json_in, yaml_mid)
        yaml_to_json(yaml_mid, json_out)
        orig = json.loads(original_json)
        final = json.loads(json_out.read_text())
        assert orig == final

    def test_complex_nested_roundtrip(self, tmp):
        data = {
            "project": {
                "name": "TIAMAT",
                "version": "1.0.0",
                "features": ["chat", "summarize", "generate"],
                "config": {
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "providers": ["anthropic", "groq", "cerebras"],
                },
            }
        }
        json_in = tmp / "complex.json"
        yaml_mid = tmp / "complex.yaml"
        json_out = tmp / "complex_out.json"
        json_in.write_text(json.dumps(data))
        json_to_yaml(json_in, yaml_mid)
        yaml_to_json(yaml_mid, json_out)
        assert json.loads(json_out.read_text()) == data
