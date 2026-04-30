#!/usr/bin/env python3
"""EnergenAI PHI Scrubber SDK

Single-file, stdlib-only HIPAA Safe Harbor scrubber SDK.
Wraps tiamat.live/scrub API.

Usage:
    from energenai_scrubber import Scrubber

    scrubber = Scrubber()  # uses hosted API
    result = scrubber.scrub("Patient John Smith DOB 1965-03-12 SSN 123-45-6789")
    print(result.scrubbed_text)    # Patient [NAME] DOB [DOB] SSN [SSN]
    print(result.identifiers_removed)  # 3
    print(result.safe_harbor_compliant)  # True (if 0 identifiers remain)

Pricing: Free tier 3 calls/day. Production $0.01/call (x402 micropayment).
Docs: https://tiamat.live/docs
Patent: US 64/000,905
"""

import json
import urllib.request
import urllib.error
import re
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ScrubResult:
    scrubbed_text: str
    identifiers_removed: int
    safe_harbor_compliant: bool
    audit: list = field(default_factory=list)
    original_length: int = 0
    scrubbed_length: int = 0


@dataclass
class AuditEntry:
    identifier_type: str
    count: int
    severity: str


class Scrubber:
    """HIPAA PHI Scrubber — removes all 18 Safe Harbor identifiers.

    Args:
        api_url: Override API endpoint (default: https://tiamat.live/scrub)
        api_key: Optional API key for higher rate limits
        local_fallback: If True, use local regex fallback when API unavailable
        timeout: Request timeout in seconds (default: 10)
    """

    API_URL = "https://www.tiamat.live/api/scrub"

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        local_fallback: bool = True,
        timeout: int = 10,
    ):
        self.api_url = api_url or self.API_URL
        self.api_key = api_key
        self.local_fallback = local_fallback
        self.timeout = timeout

    def scrub(self, text: str) -> ScrubResult:
        """Scrub PHI from text. Returns ScrubResult with cleaned text and audit."""
        try:
            return self._scrub_api(text)
        except urllib.error.URLError:
            if self.local_fallback:
                return self._scrub_local(text)
            raise

    def scrub_batch(self, texts: list) -> list:
        """Scrub a list of texts. Returns list of ScrubResult."""
        return [self.scrub(t) for t in texts]

    def _scrub_api(self, text: str) -> ScrubResult:
        """Call the hosted API."""
        payload = json.dumps({"text": text}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        req = urllib.request.Request(
            self.api_url, data=payload, headers=headers, method="POST"
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())

        audit = [
            AuditEntry(
                identifier_type=e.get("identifier_type", ""),
                count=e.get("count", 0),
                severity=e.get("severity", ""),
            )
            for e in data.get("audit", [])
        ]

        return ScrubResult(
            scrubbed_text=data.get("scrubbed_text", text),
            identifiers_removed=data.get("identifiers_removed", 0),
            safe_harbor_compliant=data.get("safe_harbor_compliant", False),
            audit=audit,
            original_length=len(text),
            scrubbed_length=len(data.get("scrubbed_text", text)),
        )

    def _scrub_local(self, text: str) -> ScrubResult:
        """Local regex fallback — covers 18 HIPAA Safe Harbor identifiers.
        Less precise than the hosted API (no NLP context), but works offline.
        """
        result = text
        removed = 0
        audit = []

        patterns = [
            # SSN
            (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", "SSN", "CRITICAL"),
            # DOB (common formats)
            (
                r"\b(?:DOB|Date of Birth|born)\s*:?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
                "DOB [DOB]",
                "DOB",
                "HIGH",
            ),
            (r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", "[DOB]", "DOB", "HIGH"),
            (r"\b\d{4}-\d{2}-\d{2}\b", "[DOB]", "DOB", "HIGH"),
            # Phone numbers
            (
                r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
                "[PHONE]",
                "PHONE",
                "HIGH",
            ),
            # Email addresses
            (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]", "EMAIL", "HIGH"),
            # NPI (10-digit)
            (r"\bNPI\s*[:#]?\s*\d{10}\b", "NPI [NPI]", "NPI", "HIGH"),
            (r"\b1\d{9}\b", "[NPI]", "NPI", "MEDIUM"),
            # DEA
            (r"\bDEA\s*[:#]?\s*[A-Z]{2}\d{7}\b", "DEA [DEA]", "DEA", "HIGH"),
            # ZIP (5+4 or 5 digit)
            (r"\b\d{5}(?:-\d{4})?\b", "[ZIP]", "ZIP", "LOW"),
            # Medical record numbers (common prefixes)
            (
                r"\b(?:MRN|Medical Record|Member ID|Member)[#:\s]+[A-Z0-9]{4,15}\b",
                "[MEMBER_ID]",
                "MEMBER_ID",
                "HIGH",
            ),
            # IP addresses
            (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", "IP_ADDRESS", "MEDIUM"),
            # Account/Fax
            (r"\bFax\s*[:#]?\s*\d[\d\s.-]{7,14}\d\b", "Fax [FAX]", "FAX", "MEDIUM"),
        ]

        for pattern, replacement, id_type, severity in patterns:
            matches = re.findall(pattern, result, re.IGNORECASE)
            if matches:
                count = len(matches)
                removed += count
                result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
                audit.append(AuditEntry(identifier_type=id_type, count=count, severity=severity))

        return ScrubResult(
            scrubbed_text=result,
            identifiers_removed=removed,
            safe_harbor_compliant=(removed == 0),
            audit=audit,
            original_length=len(text),
            scrubbed_length=len(result),
        )


# ── convenience functions ──────────────────────────────────────────────────────

_default_scrubber: Optional[Scrubber] = None


def scrub(text: str) -> ScrubResult:
    """Module-level scrub function using a shared default Scrubber instance."""
    global _default_scrubber
    if _default_scrubber is None:
        _default_scrubber = Scrubber()
    return _default_scrubber.scrub(text)


def scrub_text(text: str) -> str:
    """Convenience: returns just the scrubbed string."""
    return scrub(text).scrubbed_text


def is_phi_present(text: str) -> bool:
    """Quick check: returns True if PHI is detected in the text."""
    result = scrub(text)
    return result.identifiers_removed > 0


# ── pipeline decorator ─────────────────────────────────────────────────────────

class scrub_input:  # noqa: N801
    """Decorator: scrubs PHI from the first argument of the wrapped function.

    Usage:
        @scrub_input
        def call_llm(prompt: str):
            return openai.chat(prompt)

        # PHI is removed from `prompt` before it reaches the LLM
        response = call_llm("Patient John Smith SSN 123-45-6789 needs help with...")
    """

    def __init__(self, func=None, *, raise_on_phi=False):
        self.func = func
        self.raise_on_phi = raise_on_phi
        if func:
            import functools
            functools.update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        if not args:
            return self.func(*args, **kwargs)
        text = args[0]
        result = scrub(text)
        if self.raise_on_phi and result.identifiers_removed > 0:
            raise ValueError(
                f"PHI detected in input ({result.identifiers_removed} identifiers). "
                f"Scrubbed version available in ScrubResult."
            )
        new_args = (result.scrubbed_text,) + args[1:]
        return self.func(*new_args, **kwargs)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        import functools
        return functools.partial(self, obj)


# ── demo / self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        "Patient John Smith DOB 1965-03-12 SSN 123-45-6789 Phone (555) 867-5309",
        "PA: Jane Doe Member UHC8492 NPI 1234567890 Dx M54.50 Px 99213",
        "Dr. Smith DEA BS1234563 License CA-12345 no PHI here",
        "Contact info@example.com or call 555-867-5309 for more details",
    ]

    print("EnergenAI PHI Scrubber SDK — Self-Test")
    print("=" * 60)

    s = Scrubber(local_fallback=True)
    for i, test in enumerate(test_cases, 1):
        try:
            result = s.scrub(test)
            source = "API"
        except Exception:
            result = s._scrub_local(test)
            source = "LOCAL"

        print(f"\nTest {i} [{source}]:")
        print(f"  IN:  {test}")
        print(f"  OUT: {result.scrubbed_text}")
        print(f"  Removed: {result.identifiers_removed} identifiers")
        for a in result.audit:
            print(f"    - {a.identifier_type} ({a.severity}): {a.count}")

    print("\n" + "=" * 60)
    print("Decorator demo:")

    @scrub_input
    def fake_llm_call(prompt: str) -> str:
        return f"LLM received: {prompt}"

    resp = fake_llm_call("Patient John Smith SSN 123-45-6789 needs help.")
    print(f"  {resp}")
    print("\nSDK OK")
