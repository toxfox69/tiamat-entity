#!/usr/bin/env python3
"""
yaml-json-cli: Convert YAML ↔ JSON from the command line.

Supports:
  - YAML → JSON with full nested-structure preservation
  - JSON → YAML with configurable output style
  - Multi-document YAML (---) → JSON array
  - stdin/stdout pipelines
  - configurable indent, flow-style, sort-keys, encoding
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit(
        "Error: PyYAML is not installed. Run: pip install pyyaml"
    )

__version__ = "1.0.0"
__author__ = "ENERGENAI LLC"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _load_yaml_docs(text: str, source: str = "<input>") -> List[Any]:
    """
    Parse all YAML documents in *text* and return them as a list.

    A single-document YAML returns a one-item list.
    Multi-document YAML (separated by ``---``) returns multiple items.

    Raises
    ------
    ValueError  — on any YAML parse error
    """
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in {source}: {exc}") from exc

    # yaml.safe_load_all yields None for empty documents; filter them.
    docs = [d for d in docs if d is not None]
    return docs


def _load_json(text: str, source: str = "<input>") -> Any:
    """
    Parse JSON text and return the Python object.

    Raises
    ------
    ValueError  — on any JSON parse error
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {source}: {exc}") from exc


def _json_serializable(obj: Any) -> Any:
    """
    Recursively coerce YAML-specific types to JSON-safe equivalents.

    - datetime → ISO-8601 string
    - date     → ISO-8601 string
    - set      → sorted list
    - bytes    → base64 string (rare in YAML 1.1)
    """
    import datetime, base64

    if isinstance(obj, dict):
        return {str(k): _json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_serializable(v) for v in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(_json_serializable(v) for v in obj)
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return obj


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------

def yaml_to_json(
    input_path: Union[str, Path, None] = None,
    output_path: Optional[Union[str, Path]] = None,
    *,
    indent: int = 2,
    sort_keys: bool = False,
    encoding: str = "utf-8",
    text: Optional[str] = None,
) -> Any:
    """
    Convert a YAML file (or string) to JSON.

    Parameters
    ----------
    input_path  : path to input YAML file, or None when *text* is given
    output_path : path to output JSON file, or None for stdout
    indent      : JSON indent width (default 2)
    sort_keys   : sort JSON object keys alphabetically
    encoding    : file encoding
    text        : raw YAML string (overrides input_path)

    Returns
    -------
    Parsed Python object (dict, list, or scalar)

    Raises
    ------
    FileNotFoundError  — input file missing
    ValueError         — malformed YAML
    """
    if text is not None:
        source = "<string>"
        raw = text
    elif input_path is not None:
        input_path = Path(input_path)
        source = str(input_path)
        try:
            raw = input_path.read_text(encoding=encoding)
        except FileNotFoundError:
            raise FileNotFoundError(f"Input file not found: {input_path}")
    else:
        raise ValueError("Provide either input_path or text.")

    docs = _load_yaml_docs(raw, source)

    if len(docs) == 0:
        raise ValueError(f"YAML document in {source} is empty.")

    # Single document → unwrap; multi-document → keep as array
    data = docs[0] if len(docs) == 1 else docs
    data = _json_serializable(data)

    result = json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False)

    if output_path:
        Path(output_path).write_text(result, encoding=encoding)
    else:
        print(result)

    return data


def json_to_yaml(
    input_path: Union[str, Path, None] = None,
    output_path: Optional[Union[str, Path]] = None,
    *,
    sort_keys: bool = False,
    default_flow_style: bool = False,
    encoding: str = "utf-8",
    text: Optional[str] = None,
) -> Any:
    """
    Convert a JSON file (or string) to YAML.

    Parameters
    ----------
    input_path          : path to input JSON file, or None when *text* is given
    output_path         : path to output YAML file, or None for stdout
    sort_keys           : sort YAML mapping keys alphabetically
    default_flow_style  : if True, emit YAML in compact flow style
    encoding            : file encoding
    text                : raw JSON string (overrides input_path)

    Returns
    -------
    Parsed Python object

    Raises
    ------
    FileNotFoundError  — input file missing
    ValueError         — malformed JSON
    """
    if text is not None:
        source = "<string>"
        raw = text
    elif input_path is not None:
        input_path = Path(input_path)
        source = str(input_path)
        try:
            raw = input_path.read_text(encoding=encoding)
        except FileNotFoundError:
            raise FileNotFoundError(f"Input file not found: {input_path}")
    else:
        raise ValueError("Provide either input_path or text.")

    data = _load_json(raw, source)

    result = yaml.dump(
        data,
        default_flow_style=default_flow_style,
        sort_keys=sort_keys,
        allow_unicode=True,
    )

    if output_path:
        Path(output_path).write_text(result, encoding=encoding)
    else:
        sys.stdout.write(result)

    return data


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

_YAML_EXTENSIONS = {".yaml", ".yml"}
_JSON_EXTENSIONS = {".json", ".jsonl"}


def _detect_format(path: Path, forced: Optional[str]) -> str:
    if forced:
        return forced
    suffix = path.suffix.lower()
    if suffix in _YAML_EXTENSIONS:
        return "yaml"
    if suffix in _JSON_EXTENSIONS:
        return "json"
    raise ValueError(
        f"Cannot detect format from extension '{suffix}'. "
        "Use --from yaml|json to force it."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yaml-json-cli",
        description="Convert YAML ↔ JSON bidirectionally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  yaml-json-cli config.yaml                        YAML  → JSON  (stdout)
  yaml-json-cli config.yaml -o config.json         YAML  → JSON  (file)
  yaml-json-cli data.json -o data.yaml             JSON  → YAML  (file)
  yaml-json-cli data.json                          JSON  → YAML  (stdout)
  yaml-json-cli data.json --sort-keys              Sort keys in output
  yaml-json-cli data.json --flow-style             Compact YAML flow style
  yaml-json-cli data.yaml --indent 4               4-space JSON indent
  yaml-json-cli multi.yaml -o out.json             Multi-doc YAML → JSON array
  cat config.yaml | yaml-json-cli /dev/stdin --from yaml
""",
    )

    parser.add_argument(
        "input", metavar="INPUT",
        help="Input file (.yaml, .yml, or .json). Use /dev/stdin for piped input.",
    )
    parser.add_argument(
        "-o", "--output", metavar="OUTPUT", default=None,
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "--from", dest="from_format", choices=["yaml", "json"], metavar="FORMAT",
        help="Force input format: yaml or json.",
    )
    parser.add_argument(
        "--indent", type=int, default=2, metavar="N",
        help="JSON indent width when writing JSON output (default: 2).",
    )
    parser.add_argument(
        "--sort-keys", action="store_true",
        help="Sort mapping keys in output.",
    )
    parser.add_argument(
        "--flow-style", action="store_true",
        help="Emit YAML in compact flow style (JSON-like). Only applies to YAML output.",
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
        return 2  # unreachable but satisfies type checkers

    try:
        if fmt == "yaml":
            yaml_to_json(
                input_path,
                output_path=args.output,
                indent=args.indent,
                sort_keys=args.sort_keys,
                encoding=args.encoding,
            )
        else:
            json_to_yaml(
                input_path,
                output_path=args.output,
                sort_keys=args.sort_keys,
                default_flow_style=args.flow_style,
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
