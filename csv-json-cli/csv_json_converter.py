#!/usr/bin/env python3
"""
csv-json-cli: Convert CSV ↔ JSON from the command line.

Supports:
  - CSV → JSON with automatic type inference (int, float, bool, null)
  - JSON → CSV with recursive nested-dict flattening
  - stdin/stdout pipelines
  - configurable indent, separator, encoding
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def infer_value(val: str) -> Any:
    """Coerce a CSV string to the most specific Python scalar."""
    if val == "":
        return None
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def flatten_dict(d: Dict, parent_key: str = "", sep: str = ".") -> Dict:
    """
    Recursively flatten a nested dict.

    >>> flatten_dict({"a": {"b": 1}, "c": [2, 3]})
    {'a.b': 1, 'c[0]': 2, 'c[1]': 3}
    """
    items: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{parent_key}{sep}{k}" if parent_key else str(k)
        if isinstance(v, dict):
            items.update(flatten_dict(v, key, sep))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                list_key = f"{key}[{i}]"
                if isinstance(item, dict):
                    items.update(flatten_dict(item, list_key, sep))
                else:
                    items[list_key] = item
        else:
            items[key] = v
    return items


def _ordered_fieldnames(rows: List[Dict]) -> List[str]:
    """Return fieldnames in insertion order, deduplicated."""
    seen: set = set()
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    return fieldnames


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------

def csv_to_json(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    indent: int = 2,
    infer_types: bool = True,
    encoding: str = "utf-8",
) -> List[Dict]:
    """
    Read a CSV file and return (and optionally write) JSON.

    Parameters
    ----------
    input_path  : path to input CSV file
    output_path : path to output JSON file, or None for stdout
    indent      : JSON indent level
    infer_types : cast numeric/bool/null strings to native Python types
    encoding    : file encoding

    Returns
    -------
    List[Dict] — parsed rows

    Raises
    ------
    FileNotFoundError  — input file missing
    ValueError         — malformed CSV
    """
    input_path = Path(input_path)

    try:
        with input_path.open(newline="", encoding=encoding) as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no header row.")
            rows: List[Dict] = []
            lineno = 2
            for lineno, row in enumerate(reader, start=2):
                if infer_types:
                    rows.append({k: infer_value(v) for k, v in row.items()})
                else:
                    rows.append(dict(row))
    except FileNotFoundError:
        raise FileNotFoundError(f"Input file not found: {input_path}")
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV near line {lineno}: {exc}") from exc

    output = json.dumps(rows, indent=indent, ensure_ascii=False)

    if output_path:
        Path(output_path).write_text(output, encoding=encoding)
    else:
        print(output)

    return rows


def json_to_csv(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    flatten_sep: str = ".",
    encoding: str = "utf-8",
) -> List[Dict]:
    """
    Read a JSON file (array of objects or single object) and write CSV.

    Nested objects and arrays are flattened using *flatten_sep* as the
    key separator.  E.g. ``{"user": {"name": "Alice"}}`` →
    column ``user.name``.

    Parameters
    ----------
    input_path  : path to input JSON file
    output_path : path to output CSV file, or None for stdout
    flatten_sep : separator string for flattened keys
    encoding    : file encoding

    Returns
    -------
    List[Dict] — flattened rows (string values, as written to CSV)

    Raises
    ------
    FileNotFoundError  — input file missing
    ValueError         — malformed JSON or unsupported structure
    """
    input_path = Path(input_path)

    try:
        with input_path.open(encoding=encoding) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise FileNotFoundError(f"Input file not found: {input_path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON: {exc}") from exc

    # Normalise: single object → one-item list
    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        raise ValueError(
            "JSON root must be an array of objects or a single object, "
            f"got {type(data).__name__}."
        )

    if not data:
        raise ValueError("JSON array is empty — nothing to convert.")

    flat_rows: List[Dict] = []
    for item in data:
        if isinstance(item, dict):
            flat_rows.append(flatten_dict(item, sep=flatten_sep))
        else:
            # scalar/array row — wrap in a 'value' column
            flat_rows.append({"value": item})

    fieldnames = _ordered_fieldnames(flat_rows)

    def _write(writer_target):
        writer = csv.DictWriter(
            writer_target,
            fieldnames=fieldnames,
            extrasaction="ignore",
            restval="",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(flat_rows)

    if output_path:
        with Path(output_path).open("w", newline="", encoding=encoding) as fh:
            _write(fh)
    else:
        _write(sys.stdout)

    return flat_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _detect_format(path: Path, forced: Optional[str]) -> str:
    if forced:
        return forced
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in (".json", ".jsonl"):
        return "json"
    raise ValueError(
        f"Cannot detect format from extension '{suffix}'. "
        "Use --from csv|json to force it."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csv-json-cli",
        description="Convert CSV ↔ JSON bidirectionally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  csv-json-cli data.csv                         CSV  → JSON  (stdout)
  csv-json-cli data.csv -o out.json             CSV  → JSON  (file)
  csv-json-cli data.json -o out.csv             JSON → CSV   (file)
  csv-json-cli data.json                        JSON → CSV   (stdout)
  csv-json-cli data.csv --no-infer              Keep all CSV values as strings
  csv-json-cli nested.json --flatten-sep __     Use __ as nesting separator
  csv-json-cli data.csv --indent 4 -o out.json  Pretty-print with 4-space indent
  cat data.csv | csv-json-cli /dev/stdin --from csv
""",
    )

    parser.add_argument("input", metavar="INPUT", help="Input file (.csv or .json)")
    parser.add_argument(
        "-o", "--output", metavar="OUTPUT", default=None,
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "--from", dest="from_format", choices=["csv", "json"], metavar="FORMAT",
        help="Force input format: csv or json.",
    )
    parser.add_argument(
        "--indent", type=int, default=2, metavar="N",
        help="JSON indent width (default: 2).",
    )
    parser.add_argument(
        "--no-infer", action="store_true",
        help="Disable type inference; keep all CSV values as strings.",
    )
    parser.add_argument(
        "--flatten-sep", default=".", metavar="SEP",
        help="Separator for flattened nested JSON keys (default: '.').",
    )
    parser.add_argument(
        "--encoding", default="utf-8", metavar="ENC",
        help="File encoding (default: utf-8).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)

    try:
        fmt = _detect_format(input_path, args.from_format)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        if fmt == "csv":
            csv_to_json(
                input_path,
                output_path=args.output,
                indent=args.indent,
                infer_types=not args.no_infer,
                encoding=args.encoding,
            )
        else:
            json_to_csv(
                input_path,
                output_path=args.output,
                flatten_sep=args.flatten_sep,
                encoding=args.encoding,
            )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
