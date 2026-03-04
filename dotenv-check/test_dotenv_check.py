"""Unit tests for dotenv_check.py"""

import pytest
from pathlib import Path
from dotenv_check import parse_env_file, check_env


# ── parse_env_file ────────────────────────────────────────────────────────────

def test_parse_basic(tmp_path):
    f = tmp_path / ".env"
    f.write_text("FOO=bar\nBAZ=qux\n")
    assert parse_env_file(f) == {"FOO": "bar", "BAZ": "qux"}


def test_parse_empty_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text("EMPTY=\nSET=value\n")
    result = parse_env_file(f)
    assert result["EMPTY"] is None
    assert result["SET"] == "value"


def test_parse_quoted_values(tmp_path):
    f = tmp_path / ".env"
    f.write_text('DOUBLE="hello world"\nSINGLE=\'foo bar\'\n')
    result = parse_env_file(f)
    assert result["DOUBLE"] == "hello world"
    assert result["SINGLE"] == "foo bar"


def test_parse_skips_comments_and_blanks(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\n\nKEY=val\n")
    assert parse_env_file(f) == {"KEY": "val"}


def test_parse_export_prefix(tmp_path):
    f = tmp_path / ".env"
    f.write_text("export API_KEY=secret\n")
    assert parse_env_file(f) == {"API_KEY": "secret"}


def test_parse_skips_malformed(tmp_path):
    f = tmp_path / ".env"
    f.write_text("NOEQUALSSIGN\nGOOD=yes\n")
    assert parse_env_file(f) == {"GOOD": "yes"}


# ── check_env: missing keys ───────────────────────────────────────────────────

def _make_env(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_missing_key_returns_1(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=bar\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=\nBAR=\n")
    assert check_env(env, ex, quiet=True) == 1


def test_all_present_returns_0(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=bar\nBAR=baz\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=\nBAR=\n")
    assert check_env(env, ex, quiet=True) == 0


def test_extra_keys_ignored_by_default(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=bar\nUNDOCUMENTED=x\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=\n")
    assert check_env(env, ex, quiet=True) == 0


def test_strict_fails_on_extra(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=bar\nUNDOCUMENTED=x\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=\n")
    assert check_env(env, ex, strict=True, quiet=True) == 1


# ── check_env: empty values ───────────────────────────────────────────────────

def test_empty_value_ignored_by_default(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=\nBAR=set\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=example\nBAR=example\n")
    assert check_env(env, ex, quiet=True) == 0


def test_require_values_fails_on_empty(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=\nBAR=set\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=example\nBAR=example\n")
    assert check_env(env, ex, require_values=True, quiet=True) == 1


def test_require_values_ok_when_example_also_empty(tmp_path):
    # If example value is also empty, it's a truly optional key
    env = _make_env(tmp_path, ".env", "OPTIONAL=\n")
    ex  = _make_env(tmp_path, ".env.example", "OPTIONAL=\n")
    assert check_env(env, ex, require_values=True, quiet=True) == 0


# ── check_env: missing files ──────────────────────────────────────────────────

def test_missing_env_file_returns_1(tmp_path):
    ex = _make_env(tmp_path, ".env.example", "FOO=\n")
    assert check_env(tmp_path / "nonexistent.env", ex, quiet=True) == 1


def test_missing_example_file_returns_1(tmp_path):
    env = _make_env(tmp_path, ".env", "FOO=bar\n")
    assert check_env(env, tmp_path / "nonexistent.example", quiet=True) == 1


# ── output smoke test ─────────────────────────────────────────────────────────

def test_ok_output(tmp_path, capsys):
    env = _make_env(tmp_path, ".env", "FOO=bar\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=\n")
    check_env(env, ex)
    out = capsys.readouterr().out
    assert "OK" in out


def test_issue_output(tmp_path, capsys):
    env = _make_env(tmp_path, ".env", "FOO=bar\n")
    ex  = _make_env(tmp_path, ".env.example", "FOO=\nBAR=\n")
    check_env(env, ex)
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert "BAR" in out
