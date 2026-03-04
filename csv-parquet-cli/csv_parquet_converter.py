#!/usr/bin/env python3
"""
csv-parquet: Convert CSV files to Apache Parquet format.

Supports snappy/gzip compression, type inference, and metadata reporting.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

__version__ = "1.0.0"

COMPRESSIONS = {"snappy", "gzip", "none"}


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def csv_to_parquet(
    input_path: Path,
    output_path: Path,
    compression: Optional[str] = "snappy",
    encoding: str = "utf-8",
) -> dict:
    """
    Convert a CSV file to Apache Parquet.

    Parameters
    ----------
    input_path  : path to source CSV file
    output_path : path for output .parquet file
    compression : 'snappy', 'gzip', or None (no compression)
    encoding    : CSV character encoding (default utf-8)

    Returns
    -------
    dict with rows, columns, schema, file sizes, and compression ratio

    Raises
    ------
    FileNotFoundError — input file missing
    ValueError        — malformed or empty CSV
    IOError           — write failure
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    input_size = input_path.stat().st_size
    if input_size == 0:
        raise ValueError("Input CSV file is empty.")

    try:
        table = pa_csv.read_csv(
            input_path,
            read_options=pa_csv.ReadOptions(encoding=encoding),
            convert_options=pa_csv.ConvertOptions(
                null_values=["", "NA", "N/A", "null", "NULL", "None"],
                true_values=["true", "True", "TRUE", "yes", "Yes", "1"],
                false_values=["false", "False", "FALSE", "no", "No", "0"],
            ),
        )
    except pa.ArrowInvalid as exc:
        raise ValueError(f"Malformed CSV: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to read CSV: {exc}") from exc

    if table.num_rows == 0:
        raise ValueError("CSV file contains no data rows (header only).")

    try:
        pq.write_table(table, output_path, compression=compression)
    except Exception as exc:
        raise IOError(f"Failed to write Parquet: {exc}") from exc

    output_size = output_path.stat().st_size
    ratio = round(input_size / output_size, 2) if output_size > 0 else None

    return {
        "rows": table.num_rows,
        "columns": table.num_columns,
        "column_names": table.column_names,
        "schema": {f.name: str(f.type) for f in table.schema},
        "compression": compression or "none",
        "input_file": str(input_path),
        "output_file": str(output_path),
        "input_size_bytes": input_size,
        "output_size_bytes": output_size,
        "compression_ratio": ratio,
    }


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def _print_meta(meta: dict) -> None:
    print(f"Converted: {meta['input_file']} → {meta['output_file']}")
    print(f"  Rows:        {meta['rows']:,}")
    print(f"  Columns:     {meta['columns']}")
    print(f"  Compression: {meta['compression']}")
    print(f"  Input size:  {_fmt_bytes(meta['input_size_bytes'])}")
    print(f"  Output size: {_fmt_bytes(meta['output_size_bytes'])}")
    print(f"  Ratio:       {meta['compression_ratio']}x smaller")
    print(f"  Schema:")
    for col, dtype in meta["schema"].items():
        print(f"    {col}: {dtype}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="csv-parquet",
        description="Convert CSV files to Apache Parquet format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  csv-parquet data.csv                    Convert using snappy (default)
  csv-parquet data.csv -o output.parquet  Specify output path
  csv-parquet data.csv --compression gzip Use gzip compression
  csv-parquet data.csv --compression none No compression
  csv-parquet data.csv --json             Output metadata as JSON
  csv-parquet data.csv --encoding latin-1 Non-UTF-8 input
""",
    )
    p.add_argument("input", metavar="INPUT", help="Input CSV file path")
    p.add_argument("-o", "--output", metavar="OUTPUT", default=None,
                   help="Output .parquet file (default: INPUT.parquet)")
    p.add_argument("--compression", choices=["snappy", "gzip", "none"],
                   default="snappy", help="Compression codec (default: snappy)")
    p.add_argument("--encoding", default="utf-8", metavar="ENC",
                   help="CSV file encoding (default: utf-8)")
    p.add_argument("--json", action="store_true", dest="json_output",
                   help="Print metadata as JSON")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(".parquet")
    compression = None if args.compression == "none" else args.compression

    try:
        meta = csv_to_parquet(input_path, output_path,
                               compression=compression, encoding=args.encoding)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (ValueError, IOError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    if args.json_output:
        print(json.dumps(meta, indent=2))
    else:
        _print_meta(meta)

    return 0


if __name__ == "__main__":
    sys.exit(main())
