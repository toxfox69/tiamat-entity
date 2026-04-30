"""Smoke tests against local v3 sidecar (port 5037)."""
import os
os.environ["TIAMAT_SCRUB_URL"] = "http://127.0.0.1:5037/scrub"
from tiamat_scrub import scrub, safe_for_llm

def test_ssn_removed():
    s = scrub("Bob's SSN is 123-45-6789.")
    assert "123-45-6789" not in s
    assert "[SSN]" in s

def test_email_removed():
    s = scrub("Reach me at alice@hospital.org")
    assert "alice@hospital.org" not in s

def test_address_removed():
    s = scrub("lives at 123 Main St")
    assert "123 Main St" not in s
    assert "[ADDRESS]" in s

def test_credit_card_luhn():
    s = scrub("paid with 4532015112830366")
    assert "4532015112830366" not in s
    assert "[CARD" in s

def test_audit_shape():
    r = scrub("DOB 1980-05-12, phone 555-867-5309", return_audit=True)
    types = set()
    for a in r["audit"]:
        types.add(a.get("identifier_type") or a.get("type"))
    assert "DOB" in types and "PHONE" in types

def test_safe_for_llm_returns_tuple():
    txt, safe = safe_for_llm("hello world")
    assert isinstance(txt, str) and isinstance(safe, bool)

def test_empty_passthrough():
    assert scrub("") == ""

if __name__ == "__main__":
    for t in [test_ssn_removed, test_email_removed, test_address_removed,
              test_credit_card_luhn, test_audit_shape,
              test_safe_for_llm_returns_tuple, test_empty_passthrough]:
        t(); print("OK", t.__name__)
    print("7/7 passed")
