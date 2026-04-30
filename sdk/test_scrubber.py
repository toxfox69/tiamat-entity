"""Tests for energenai-scrubber. Run: python3 -m pytest test_scrubber.py -v"""
import sys, types
from energenai_scrubber import Scrubber

def test_local_ssn():
    r = Scrubber()._scrub_local("Patient SSN 555-12-3456")
    assert "[SSN]" in r.scrubbed_text
    assert "555-12-3456" not in r.scrubbed_text
    assert r.identifiers_removed >= 1

def test_local_email():
    r = Scrubber()._scrub_local("contact john@example.com")
    assert "[EMAIL]" in r.scrubbed_text
    assert "john@example.com" not in r.scrubbed_text

def test_local_phone():
    r = Scrubber()._scrub_local("call 555-123-4567")
    assert "[PHONE]" in r.scrubbed_text

def test_local_dob():
    r = Scrubber()._scrub_local("DOB: 1972-01-15")
    assert "1972-01-15" not in r.scrubbed_text

def test_clean_text_unchanged():
    r = Scrubber()._scrub_local("Just regular sentence with no PHI.")
    assert r.scrubbed_text == "Just regular sentence with no PHI."
    assert r.identifiers_removed == 0

def test_audit_severity():
    r = Scrubber()._scrub_local("SSN 555-12-3456 phone 555-123-4567")
    severities = {a.identifier_type: a.severity for a in r.audit}
    assert severities.get("SSN") == "CRITICAL"

def test_scrubbed_openai_wrapper():
    fake = types.ModuleType('openai')
    captured = {}
    class C:
        def create(self, **kw):
            captured['msgs'] = kw['messages']
            return {"ok": True}
    class Chat:
        def __init__(self): self.completions = C()
    class FakeOpenAI:
        def __init__(self, **kw): self.chat = Chat()
    fake.OpenAI = FakeOpenAI
    sys.modules['openai'] = fake
    # reimport to pick up fake
    if 'scrubbed_openai' in sys.modules:
        del sys.modules['scrubbed_openai']
    from scrubbed_openai import ScrubbedOpenAI
    c = ScrubbedOpenAI(api_key='sk-test')
    c.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{"role":"user","content":"SSN 555-12-3456"}])
    sent = captured['msgs'][0]['content']
    assert "555-12-3456" not in sent, f"PHI leaked upstream: {sent!r}"
    assert "[SSN]" in sent
    assert len(c.last_audit) == 1
