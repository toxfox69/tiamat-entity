#!/usr/bin/env python3
"""JSON Schema → Python Dataclass Generator

Converts JSON Schema (draft-07/2019-09/2020-12) files to Python dataclasses
with full type hints, Optional fields, nested class support, and validation docstrings.
"""

from __future__ import annotations

import json
import keyword
import sys
import argparse
from pathlib import Path
from typing import Any, Optional


# JSON Schema primitive → Python type
SCALAR_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "null": "None",
}

# Format hints for docstrings
FORMAT_DOCS: dict[str, str] = {
    "email": "RFC 5322 email address",
    "uri": "RFC 3986 URI",
    "uri-reference": "RFC 3986 URI reference",
    "date": "ISO 8601 date (YYYY-MM-DD)",
    "time": "ISO 8601 time (HH:MM:SS)",
    "date-time": "ISO 8601 datetime",
    "uuid": "RFC 4122 UUID",
    "ipv4": "IPv4 address",
    "ipv6": "IPv6 address",
    "hostname": "RFC 1123 hostname",
    "json-pointer": "RFC 6901 JSON Pointer",
    "regex": "ECMA 262 regular expression",
}


def to_class_name(name: str) -> str:
    """Convert any string to a valid PascalCase class name."""
    name = name.replace("-", "_").replace(" ", "_").replace(".", "_")
    parts = [p for p in name.split("_") if p]
    result = "".join(p[0].upper() + p[1:] for p in parts)
    # Strip leading digits
    while result and result[0].isdigit():
        result = result[1:]
    return result or "Model"


def safe_field_name(name: str) -> str:
    """Return a valid Python identifier for a field name."""
    name = name.replace("-", "_").replace(" ", "_").replace(".", "_")
    if not name.isidentifier() or keyword.iskeyword(name):
        name = f"field_{name}"
    return name


class DataclassGenerator:
    """Generates Python dataclass code from JSON Schema definitions."""

    def __init__(self, root_class_name: str = "Model"):
        self.root_class_name = root_class_name
        self._classes: list[tuple[str, str]] = []       # ordered (name, code)
        self._seen: set[str] = set()
        self._imports: set[str] = set()
        self._definitions: dict[str, dict] = {}         # $defs / definitions cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, schema: dict, class_name: Optional[str] = None) -> str:
        """Generate a complete Python module string from a root JSON Schema."""
        self._classes = []
        self._seen = set()
        self._imports = set()

        root_name = class_name or to_class_name(
            schema.get("title", "") or self.root_class_name
        )

        # Pre-load $defs / definitions so forward references resolve
        self._definitions = {
            **schema.get("definitions", {}),
            **schema.get("$defs", {}),
        }

        # Generate definition classes first (dependency order)
        for def_name, def_schema in self._definitions.items():
            if def_schema.get("type") == "object" or "properties" in def_schema:
                self._generate_class(to_class_name(def_name), def_schema)

        # Generate root class
        if schema.get("type") == "object" or "properties" in schema:
            self._generate_class(root_name, schema)
        else:
            # Non-object root → type alias
            alias_type = self._resolve_type(schema, root_name)
            return self._build_module(extra=f"{root_name} = {alias_type}\n")

        return self._build_module()

    # ------------------------------------------------------------------
    # Type resolution
    # ------------------------------------------------------------------

    def _resolve_type(self, schema: dict, hint_name: str = "") -> str:
        """Recursively resolve a JSON Schema node to a Python type string."""
        if not schema:
            self._imports.add("Any")
            return "Any"

        # $ref
        if "$ref" in schema:
            return self._resolve_ref(schema["$ref"])

        # anyOf / oneOf → Union or Optional
        if "anyOf" in schema or "oneOf" in schema:
            variants: list = schema.get("anyOf") or schema.get("oneOf") or []
            return self._resolve_union(variants, hint_name)

        # allOf → merge (simplified: find first object-like schema)
        if "allOf" in schema:
            for sub in schema["allOf"]:
                if sub.get("type") == "object" or "properties" in sub:
                    return self._resolve_type(sub, hint_name)
            return self._resolve_type(schema["allOf"][0], hint_name)

        schema_type = schema.get("type")

        # Array of types e.g. ["string", "null"]
        if isinstance(schema_type, list):
            return self._resolve_multi_type(schema_type, schema, hint_name)

        if schema_type == "object":
            return self._resolve_object(schema, hint_name)

        if schema_type == "array":
            return self._resolve_array(schema, hint_name)

        if schema_type in SCALAR_TYPE_MAP:
            return SCALAR_TYPE_MAP[schema_type]

        # No explicit type but has properties → treat as object
        if "properties" in schema:
            return self._resolve_object(schema, hint_name)

        # Enum with mixed types
        if "enum" in schema:
            return self._infer_enum_type(schema["enum"])

        self._imports.add("Any")
        return "Any"

    def _resolve_ref(self, ref: str) -> str:
        ref_name = ref.split("/")[-1]
        class_name = to_class_name(ref_name)
        # Generate the referenced class if not yet done
        if class_name not in self._seen and ref_name in self._definitions:
            self._generate_class(class_name, self._definitions[ref_name])
        return class_name

    def _resolve_union(self, variants: list, hint_name: str) -> str:
        null_count = sum(1 for v in variants if v.get("type") == "null")
        non_null = [v for v in variants if v.get("type") != "null"]

        if not non_null:
            return "None"

        types = [self._resolve_type(v, hint_name) for v in non_null]
        deduped = list(dict.fromkeys(types))

        if len(deduped) == 1:
            result = deduped[0]
        else:
            self._imports.add("Union")
            result = f"Union[{', '.join(deduped)}]"

        if null_count:
            self._imports.add("Optional")
            return f"Optional[{result}]"
        return result

    def _resolve_multi_type(self, types: list, schema: dict, hint_name: str) -> str:
        non_null = [t for t in types if t != "null"]
        has_null = "null" in types
        resolved = []
        for t in non_null:
            sub = {**schema, "type": t}
            resolved.append(self._resolve_type(sub, hint_name))
        deduped = list(dict.fromkeys(resolved))
        if len(deduped) == 1:
            result = deduped[0]
        else:
            self._imports.add("Union")
            result = f"Union[{', '.join(deduped)}]"
        if has_null:
            self._imports.add("Optional")
            return f"Optional[{result}]"
        return result

    def _resolve_object(self, schema: dict, hint_name: str) -> str:
        if "properties" not in schema:
            # Free-form dict
            self._imports.update({"Dict", "Any"})
            return "Dict[str, Any]"
        class_name = to_class_name(hint_name) if hint_name else "NestedModel"
        # Avoid name collision
        class_name = self._unique_name(class_name)
        self._generate_class(class_name, schema)
        return class_name

    def _resolve_array(self, schema: dict, hint_name: str) -> str:
        items = schema.get("items")
        self._imports.add("List")
        if items is None:
            self._imports.add("Any")
            return "List[Any]"
        if isinstance(items, list):
            # Tuple-style items → List[Any] (simplified)
            self._imports.add("Any")
            return "List[Any]"
        item_type = self._resolve_type(items, hint_name + "Item")
        return f"List[{item_type}]"

    def _infer_enum_type(self, values: list) -> str:
        python_types = {type(v).__name__ for v in values if v is not None}
        type_map = {"str": "str", "int": "int", "float": "float", "bool": "bool"}
        mapped = {type_map.get(t, "Any") for t in python_types}
        if len(mapped) == 1:
            return mapped.pop()
        self._imports.add("Union")
        return f"Union[{', '.join(sorted(mapped))}]"

    # ------------------------------------------------------------------
    # Class generation
    # ------------------------------------------------------------------

    def _generate_class(self, class_name: str, schema: dict) -> None:
        if class_name in self._seen:
            return
        self._seen.add(class_name)

        properties: dict[str, dict] = schema.get("properties", {})
        required_set: set[str] = set(schema.get("required", []))
        description: str = schema.get("description", "")

        # Separate required and optional to put required first (no default)
        required_props = [(k, v) for k, v in properties.items() if k in required_set]
        optional_props = [(k, v) for k, v in properties.items() if k not in required_set]

        # Resolve all field types (may recursively generate nested classes)
        field_entries = []
        for prop_name, prop_schema in required_props:
            ftype = self._resolve_type(prop_schema, to_class_name(prop_name))
            field_entries.append((prop_name, ftype, True, prop_schema))
        for prop_name, prop_schema in optional_props:
            ftype = self._resolve_type(prop_schema, to_class_name(prop_name))
            if not ftype.startswith("Optional"):
                self._imports.add("Optional")
                ftype = f"Optional[{ftype}]"
            field_entries.append((prop_name, ftype, False, prop_schema))

        lines: list[str] = ["@dataclass", f"class {class_name}:"]

        # Docstring
        doc_parts: list[str] = []
        if description:
            doc_parts.append(description)
            doc_parts.append("")

        doc_parts.append("Attributes:")
        for prop_name, _, required, prop_schema in field_entries:
            constraints = self._collect_constraints(prop_schema, required)
            doc_parts.append(f"    {safe_field_name(prop_name)}: {constraints or ''}")

        lines.append('    """')
        for dp in doc_parts:
            lines.append(f"    {dp}" if dp else "")
        lines.append('    """')

        if not field_entries:
            lines.append("    pass")
        else:
            for prop_name, ftype, is_required, prop_schema in field_entries:
                fname = safe_field_name(prop_name)
                if is_required:
                    default_type = self._default_for_type(ftype, prop_schema)
                    if default_type is not None:
                        lines.append(f"    {fname}: {ftype} = {default_type}")
                    else:
                        lines.append(f"    {fname}: {ftype}")
                else:
                    lines.append(f"    {fname}: {ftype} = None")

        self._classes.append((class_name, "\n".join(lines)))

    def _collect_constraints(self, schema: dict, required: bool) -> str:
        """Build a concise constraint string for docstring."""
        parts: list[str] = []
        if not required:
            parts.append("optional")
        fmt = schema.get("format", "")
        if fmt:
            parts.append(FORMAT_DOCS.get(fmt, fmt))
        if "enum" in schema:
            parts.append(f"one of {schema['enum']}")
        for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                    "minLength", "maxLength", "minItems", "maxItems",
                    "pattern", "multipleOf"):
            if key in schema:
                parts.append(f"{key}={schema[key]}")
        desc = schema.get("description", "")
        if desc:
            parts.insert(0, desc)
        return "; ".join(parts) if parts else str(schema.get("type", "any"))

    def _default_for_type(self, ftype: str, schema: dict) -> Optional[str]:
        """Return a default value expression for required fields with defaults."""
        if "default" in schema:
            val = schema["default"]
            if isinstance(val, str):
                return repr(val)
            if isinstance(val, bool):
                return str(val)
            if val is None:
                return "None"
            return str(val)
        # Arrays should default to field(default_factory=list) only if optional
        return None

    # ------------------------------------------------------------------
    # Module assembly
    # ------------------------------------------------------------------

    def _build_module(self, extra: str = "") -> str:
        header = [
            '"""Auto-generated by schema_to_dataclass — do not edit manually."""',
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass, field",
        ]

        typing_imports = sorted(self._imports)
        if typing_imports:
            header.append(f"from typing import {', '.join(typing_imports)}")

        header.extend(["", ""])

        body_parts: list[str] = []
        for _, code in self._classes:
            body_parts.append(code)
            body_parts.append("")
            body_parts.append("")

        if extra:
            body_parts.append(extra)

        return "\n".join(header) + "\n".join(body_parts).rstrip() + "\n"

    def _unique_name(self, name: str) -> str:
        if name not in self._seen:
            return name
        i = 2
        while f"{name}{i}" in self._seen:
            i += 1
        return f"{name}{i}"


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schema_to_dataclass",
        description="Convert a JSON Schema file to a Python dataclass module.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  schema_to_dataclass schema.json
  schema_to_dataclass schema.json -o User.py -c User
  schema_to_dataclass schema.json --stdout
  cat schema.json | schema_to_dataclass -
        """,
    )
    parser.add_argument(
        "schema",
        nargs="?",
        default="-",
        metavar="SCHEMA",
        help="JSON Schema file path, or '-' to read from stdin (default: stdin)",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Output .py file path (default: <ClassName>.py)",
    )
    parser.add_argument(
        "-c", "--class-name",
        metavar="NAME",
        help="Root class name (default: derived from schema title or filename)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print generated code to stdout instead of writing a file",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        metavar="N",
        help="JSON indent for pretty-printing schema (unused in generation)",
    )
    return parser


def load_schema(path: str) -> dict:
    if path == "-":
        data = sys.stdin.read()
    else:
        data = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON — {e}", file=sys.stderr)
        sys.exit(1)


def infer_class_name(schema: dict, schema_path: str) -> str:
    if schema.get("title"):
        return to_class_name(schema["title"])
    if schema_path and schema_path != "-":
        stem = Path(schema_path).stem
        return to_class_name(stem)
    return "Model"


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    schema = load_schema(args.schema)
    class_name = args.class_name or infer_class_name(schema, args.schema)

    generator = DataclassGenerator(root_class_name=class_name)
    code = generator.generate(schema, class_name=class_name)

    if args.stdout:
        print(code, end="")
        return 0

    output_path = Path(args.output) if args.output else Path(f"{class_name}.py")
    output_path.write_text(code, encoding="utf-8")
    print(f"Generated: {output_path} ({len(code.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
