"""scrubbed_openai — drop-in OpenAI wrapper that scrubs PHI before sending.

Usage:
    from scrubbed_openai import ScrubbedOpenAI
    client = ScrubbedOpenAI(api_key="sk-...")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":"Patient John Doe SSN 555-12-3456 has flu"}],
    )
    # The prompt sent upstream becomes: "Patient [NAME] SSN [SSN] has flu"
    # client.last_audit holds the scrub trail for HIPAA logs.

Why: most healthcare AI builders accidentally ship PHI into OpenAI/Anthropic.
This wrapper makes Safe Harbor compliance a one-line change.

Patent: US 64/000,905. SDK: tiamat.live/scrub
"""
from energenai_scrubber import Scrubber

class _Wrapped:
    def __init__(self, inner, scrubber, audit):
        self._inner = inner
        self._scrubber = scrubber
        self._audit = audit
    def create(self, **kwargs):
        msgs = kwargs.get("messages", [])
        for m in msgs:
            c = m.get("content")
            if isinstance(c, str):
                r = self._scrubber.scrub(c)
                m["content"] = r.scrubbed_text
                self._audit.append({"removed": r.identifiers_removed,
                                    "compliant": r.safe_harbor_compliant})
        return self._inner.create(**kwargs)

class ScrubbedOpenAI:
    def __init__(self, *args, **kwargs):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")
        self._client = OpenAI(*args, **kwargs)
        self._scrubber = Scrubber()
        self.last_audit = []
        self.chat = type("Chat", (), {"completions": _Wrapped(
            self._client.chat.completions, self._scrubber, self.last_audit)})()

if __name__ == "__main__":
    # Smoke test (local scrub only, no API key needed)
    s = Scrubber()
    r = s.scrub("Patient Jane Smith DOB 1972-01-15 SSN 999-00-1111")
    print("scrubbed:", r.scrubbed_text)
    print("removed:", r.identifiers_removed, "safe_harbor:", r.safe_harbor_compliant)
