#!/usr/bin/env python3
"""
dotenv-check: Validate .env files against .env.example templates.

Catches missing or misconfigured environment variables before they cause
production failures. CI-friendly (exits 1 on failure), pre-commit compatible.

Usage:
    python dotenv_check.py                        # uses .env + .env.example
    python dotenv_check.py --env .env.prod        # custom env file
    python dotenv_check.py --strict               # fail on extra keys too
    python dotenv_check.py --no-empty             # fail on empty values
"""

import sys
import argparse
from pathlib import Path
from typing import Optional


def parse_env_file(path: Path) -> dict[str, Optional[str]]:
    """Parse a .env file into {KEY: value_or_None}.

    Handles:
    - KEY=value          → {"KEY": "value"}
    - KEY=               → {"KEY": None}
    - KEY="quoted value" → {"KEY": "quoted value"}
    - # comments         → skipped
    - blank lines        → skipped
    - export KEY=value   → {"KEY": "value"}
    """
    result: dict[str, Optional[str]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip optional `export ` prefix
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue  # malformed; skip silently
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        result[key] = val if val else None
    return result


def check_env(
    env_path: Path,
    example_path: Path,
    strict: bool = False,
    require_values: bool = False,
    quiet: bool = False,
) -> int:
    """Compare env_path against example_path and report discrepancies.

    Args:
        env_path: Path to the actual .env file.
        example_path: Path to the .env.example template.
        strict: If True, fail when .env contains keys not in .env.example.
        require_values: If True, fail when required keys have empty values.
        quiet: Suppress all output (useful for scripting).

    Returns:
        0 if validation passes, 1 if any issues found.
    """
    issues: list[str] = []

    if not env_path.exists():
        if not quiet:
            print(f"ERROR: {env_path} not found.", file=sys.stderr)
        return 1
    if not example_path.exists():
        if not quiet:
            print(f"ERROR: {example_path} not found.", file=sys.stderr)
        return 1

    env = parse_env_file(env_path)
    example = parse_env_file(example_path)

    # Keys present in example but missing from .env entirely
    missing = [k for k in example if k not in env]
    for key in sorted(missing):
        issues.append(f"MISSING   {key}  (required by {example_path.name})")

    # Keys present in both but empty in .env (example has a non-empty placeholder)
    if require_values:
        empty = [
            k for k in example
            if k in env and env[k] is None and example[k] is not None
        ]
        for key in sorted(empty):
            issues.append(f"EMPTY     {key}  (has a value in {example_path.name})")

    # Keys in .env not documented in example (strict mode)
    if strict:
        extra = [k for k in env if k not in example]
        for key in sorted(extra):
            issues.append(f"EXTRA     {key}  (not in {example_path.name})")

    if not quiet:
        if issues:
            print(f"dotenv-check: {env_path} — {len(issues)} issue(s) found\n")
            for issue in issues:
                print(f"  {issue}")
            print()
        else:
            print(f"dotenv-check: {env_path} OK ({len(env)} vars validated against {example_path.name})")

    return 1 if issues else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a .env file against a .env.example template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dotenv-check                           # default: .env vs .env.example
  dotenv-check --env .env.prod           # check a production env file
  dotenv-check --strict                  # also flag undocumented keys
  dotenv-check --no-empty                # fail on empty required values
  dotenv-check --quiet && echo "clean"   # scripting / CI use
        """,
    )
    parser.add_argument(
        "--env", default=".env", metavar="FILE",
        help="Path to the .env file to validate (default: .env)",
    )
    parser.add_argument(
        "--example", default=".env.example", metavar="FILE",
        help="Path to the .env.example template (default: .env.example)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Fail if .env contains keys not present in .env.example",
    )
    parser.add_argument(
        "--no-empty", dest="require_values", action="store_true",
        help="Fail if a required key exists but has an empty value",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress output (exit code only)",
    )

    args = parser.parse_args()
    code = check_env(
        env_path=Path(args.env),
        example_path=Path(args.example),
        strict=args.strict,
        require_values=args.require_values,
        quiet=args.quiet,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
