"""
Tests for csv_json_converter.

Run with:
    pytest test_converter.py -v
    pytest test_converter.py --cov=csv_json_converter --cov-report=term-missing
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from csv_json_converter import (
    csv_to_json,
    flatten_dict,
    infer_value,
    json_to_csv,
    main,
)


# ---------------------------------------------------------------------------
# infer_value
# ---------------------------------------------------------------------------

class TestInferValue(unittest.TestCase):
    def test_integer(self):
        self.assertEqual(infer_value("42"), 42)
        self.assertEqual(infer_value("-7"), -7)
        self.assertEqual(infer_value("0"), 0)

    def test_float(self):
        self.assertAlmostEqual(infer_value("3.14"), 3.14)
        self.assertAlmostEqual(infer_value("-0.5"), -0.5)

    def test_bool_true(self):
        self.assertIs(infer_value("true"), True)
        self.assertIs(infer_value("True"), True)
        self.assertIs(infer_value("TRUE"), True)

    def test_bool_false(self):
        self.assertIs(infer_value("false"), False)
        self.assertIs(infer_value("False"), False)

    def test_empty_is_none(self):
        self.assertIsNone(infer_value(""))

    def test_plain_string(self):
        self.assertEqual(infer_value("hello"), "hello")
        self.assertEqual(infer_value("  "), "  ")

    def test_numeric_string_with_spaces(self):
        # Python's int() strips leading/trailing whitespace, so " 42" → 42
        self.assertEqual(infer_value(" 42"), 42)


# ---------------------------------------------------------------------------
# flatten_dict
# ---------------------------------------------------------------------------

class TestFlattenDict(unittest.TestCase):
    def test_flat_dict_unchanged(self):
        d = {"a": 1, "b": "x"}
        self.assertEqual(flatten_dict(d), {"a": 1, "b": "x"})

    def test_one_level_nesting(self):
        d = {"user": {"name": "Alice", "age": 30}}
        self.assertEqual(flatten_dict(d), {"user.name": "Alice", "user.age": 30})

    def test_deep_nesting(self):
        d = {"a": {"b": {"c": {"d": 1}}}}
        self.assertEqual(flatten_dict(d), {"a.b.c.d": 1})

    def test_list_of_scalars(self):
        d = {"tags": ["x", "y", "z"]}
        self.assertEqual(flatten_dict(d), {"tags[0]": "x", "tags[1]": "y", "tags[2]": "z"})

    def test_list_of_dicts(self):
        d = {"items": [{"id": 1}, {"id": 2}]}
        self.assertEqual(flatten_dict(d), {"items[0].id": 1, "items[1].id": 2})

    def test_custom_separator(self):
        d = {"a": {"b": 1}}
        self.assertEqual(flatten_dict(d, sep="__"), {"a__b": 1})

    def test_empty_dict(self):
        self.assertEqual(flatten_dict({}), {})

    def test_mixed_nested(self):
        d = {"user": {"name": "Bob"}, "tags": ["a", "b"]}
        result = flatten_dict(d)
        self.assertEqual(result["user.name"], "Bob")
        self.assertEqual(result["tags[0]"], "a")
        self.assertEqual(result["tags[1]"], "b")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TmpDir:
    """Mixin: creates a temp dir per test."""
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def _path(self, name: str) -> str:
        return os.path.join(self._tmpdir, name)

    def _write(self, name: str, content: str) -> str:
        p = self._path(name)
        Path(p).write_text(content, encoding="utf-8")
        return p


# ---------------------------------------------------------------------------
# csv_to_json
# ---------------------------------------------------------------------------

class TestCsvToJson(TmpDir, unittest.TestCase):
    def test_basic_types(self):
        p = self._write("t.csv", "name,age,active,score\nAlice,30,true,9.5\n")
        rows = csv_to_json(p)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["name"], "Alice")
        self.assertEqual(r["age"], 30)
        self.assertIs(r["active"], True)
        self.assertAlmostEqual(r["score"], 9.5)

    def test_null_empty(self):
        p = self._write("t.csv", "name,age\nAlice,\n")
        rows = csv_to_json(p)
        self.assertIsNone(rows[0]["age"])

    def test_no_infer(self):
        p = self._write("t.csv", "name,age\nAlice,30\n")
        rows = csv_to_json(p, infer_types=False)
        self.assertEqual(rows[0]["age"], "30")

    def test_multiple_rows(self):
        p = self._write("t.csv", "x,y\n1,2\n3,4\n5,6\n")
        rows = csv_to_json(p)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]["x"], 5)

    def test_output_file(self):
        p = self._write("t.csv", "a,b\n1,2\n")
        out = self._path("out.json")
        csv_to_json(p, output_path=out)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data[0]["a"], 1)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            csv_to_json("/nonexistent/file.csv")

    def test_returns_list(self):
        p = self._write("t.csv", "x\n1\n2\n")
        result = csv_to_json(p)
        self.assertIsInstance(result, list)

    def test_stdout(self):
        """csv_to_json with no output_path returns rows and doesn't raise."""
        p = self._write("t.csv", "a\n1\n")
        rows = csv_to_json(p)          # prints to stdout — should not raise
        self.assertEqual(rows[0]["a"], 1)

    def test_indent_in_output(self):
        p = self._write("t.csv", "a\n1\n")
        out = self._path("out.json")
        csv_to_json(p, output_path=out, indent=4)
        text = Path(out).read_text()
        self.assertIn("    ", text)   # 4-space indent present


# ---------------------------------------------------------------------------
# json_to_csv
# ---------------------------------------------------------------------------

class TestJsonToCsv(TmpDir, unittest.TestCase):
    def _write_json(self, name: str, data) -> str:
        return self._write(name, json.dumps(data))

    def test_basic_list(self):
        p = self._write_json("t.json", [{"name": "Alice", "age": 30}])
        out = self._path("out.csv")
        json_to_csv(p, output_path=out)
        with open(out) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["name"], "Alice")
        self.assertEqual(rows[0]["age"], "30")

    def test_single_object(self):
        p = self._write_json("t.json", {"name": "Bob", "age": 25})
        out = self._path("out.csv")
        json_to_csv(p, output_path=out)
        with open(out) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Bob")

    def test_nested_flattening(self):
        data = [{"user": {"name": "Alice", "role": "admin"}, "active": True}]
        p = self._write_json("t.json", data)
        out = self._path("out.csv")
        json_to_csv(p, output_path=out)
        with open(out) as fh:
            rows = list(csv.DictReader(fh))
        self.assertIn("user.name", rows[0])
        self.assertEqual(rows[0]["user.name"], "Alice")
        self.assertEqual(rows[0]["user.role"], "admin")

    def test_list_values_flattened(self):
        data = [{"tags": ["a", "b"]}]
        p = self._write_json("t.json", data)
        out = self._path("out.csv")
        json_to_csv(p, output_path=out)
        with open(out) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["tags[0]"], "a")
        self.assertEqual(rows[0]["tags[1]"], "b")

    def test_custom_flatten_sep(self):
        data = [{"user": {"name": "Alice"}}]
        p = self._write_json("t.json", data)
        out = self._path("out.csv")
        json_to_csv(p, output_path=out, flatten_sep="__")
        with open(out) as fh:
            header = fh.readline().strip()
        self.assertIn("user__name", header)

    def test_missing_keys_filled_empty(self):
        """Rows with missing keys should produce empty cells."""
        data = [{"a": 1, "b": 2}, {"a": 3}]
        p = self._write_json("t.json", data)
        out = self._path("out.csv")
        json_to_csv(p, output_path=out)
        with open(out) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[1].get("b", ""), "")

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            json_to_csv("/nonexistent/file.json")

    def test_malformed_json(self):
        p = self._write("bad.json", "{invalid json}")
        with self.assertRaises(ValueError):
            json_to_csv(p)

    def test_empty_array(self):
        p = self._write_json("t.json", [])
        with self.assertRaises(ValueError):
            json_to_csv(p)

    def test_invalid_root_type(self):
        p = self._write_json("t.json", "just a string")
        with self.assertRaises(ValueError):
            json_to_csv(p)

    def test_returns_list(self):
        p = self._write_json("t.json", [{"x": 1}])
        out = self._path("out.csv")
        result = json_to_csv(p, output_path=out)
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------

class TestCLI(TmpDir, unittest.TestCase):
    def _write(self, name: str, content: str) -> str:
        p = os.path.join(self._tmpdir, name)
        Path(p).write_text(content, encoding="utf-8")
        return p

    def test_csv_to_json_via_cli(self):
        csv_path = self._write("t.csv", "a,b\n1,2\n")
        out = self._path("out.json")
        rc = main([csv_path, "-o", out])
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data[0]["a"], 1)

    def test_json_to_csv_via_cli(self):
        json_path = self._write("t.json", json.dumps([{"x": 10}]))
        out = self._path("out.csv")
        rc = main([json_path, "-o", out])
        self.assertEqual(rc, 0)
        with open(out) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["x"], "10")

    def test_missing_file_returns_1(self):
        rc = main(["/no/such/file.csv", "-o", "/tmp/x.json"])
        self.assertEqual(rc, 1)

    def test_no_infer_flag(self):
        csv_path = self._write("t.csv", "n\n42\n")
        out = self._path("out.json")
        main([csv_path, "-o", out, "--no-infer"])
        data = json.loads(Path(out).read_text())
        self.assertEqual(data[0]["n"], "42")  # stays string

    def test_from_flag_overrides_extension(self):
        # Write a CSV but name it .dat — use --from csv
        path = self._write("data.dat", "a,b\n1,2\n")
        out = self._path("out.json")
        rc = main([path, "-o", out, "--from", "csv"])
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data[0]["a"], 1)

    def test_flatten_sep_flag(self):
        json_path = self._write("t.json", json.dumps([{"a": {"b": 1}}]))
        out = self._path("out.csv")
        main([json_path, "-o", out, "--flatten-sep", "__"])
        with open(out) as fh:
            header = fh.readline().strip()
        self.assertIn("a__b", header)

    def test_indent_flag(self):
        csv_path = self._write("t.csv", "x\n1\n")
        out = self._path("out.json")
        main([csv_path, "-o", out, "--indent", "0"])
        text = Path(out).read_text()
        # indent=0 means no newlines between elements inside the array
        self.assertNotIn("  ", text)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip(TmpDir, unittest.TestCase):
    def test_csv_json_csv(self):
        """CSV → JSON → CSV should preserve scalar values."""
        original = "name,age\nAlice,30\nBob,25\n"
        csv1 = self._path("orig.csv")
        Path(csv1).write_text(original)

        json1 = self._path("mid.json")
        csv_to_json(csv1, output_path=json1)

        csv2 = self._path("final.csv")
        json_to_csv(json1, output_path=csv2)

        with open(csv1) as f1, open(csv2) as f2:
            r1 = list(csv.DictReader(f1))
            r2 = list(csv.DictReader(f2))

        self.assertEqual(len(r1), len(r2))
        for a, b in zip(r1, r2):
            self.assertEqual(a["name"], b["name"])
            self.assertEqual(a["age"], b["age"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
