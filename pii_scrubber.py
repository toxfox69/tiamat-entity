#!/usr/bin/env python3
"""
PII Scrubber — Phase 1
Detects and redacts: Names, emails, phones, SSNs, credit cards, addresses, IPs, API keys.

Pattern entries: (type, regex, group_index)
  group_index=0 → replace full match
  group_index=N → replace only group N, preserve surrounding text in match
"""

import re
import json
from typing import Dict, List, Tuple
from collections import defaultdict


class PIIScrubber:
    """Detect and redact PII from text."""

    def __init__(self):
        # Ordered by specificity (more specific patterns first to avoid false positives)
        # Format: (type_label, pattern, capture_group, flags)
        # flags=None uses re.IGNORECASE (default); flags=0 for case-sensitive
        self.patterns: List[Tuple[str, str, int, int]] = [  # type: ignore[assignment]
            # === Credentials (most specific first) ===
            ('AWS_KEY',
             r'AKIA[0-9A-Z]{16}',
             0, 0),
            ('OPENAI_KEY',
             r'sk-(?:proj-)?[a-zA-Z0-9_-]{20,}',
             0, 0),
            ('STRIPE_KEY',
             r'(?:sk|pk)_(?:test|live)_[a-zA-Z0-9]{24,}',
             0, 0),
            ('GITHUB_TOKEN',
             r'gh[sput]_[a-zA-Z0-9]{36}',
             0, 0),
            ('JWT',
             r'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_\-\.]+',
             0, 0),
            ('PRIVATE_KEY',
             r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----',
             0, 0),
            ('DATABASE_URL',
             r'(?:mongodb|postgres|mysql|redis|sqlite)://[^\s]+',
             0, re.IGNORECASE),
            # Generic: "api key: value", "password = value", etc.
            # group 1 = value only (strip the label prefix)
            ('API_KEY',
             r'(?:api[\s_-]?key|api[_-]?secret|password|secret|token)\s*[:=]\s*([\w\-\.]{6,})',
             1, re.IGNORECASE),

            # === Structured PII ===
            ('SSN',
             r'\b\d{3}-\d{2}-\d{4}\b',
             0, 0),
            ('CREDIT_CARD',
             r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
             0, 0),
            ('EMAIL',
             r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
             0, re.IGNORECASE),
            ('PHONE',
             r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b',
             0, 0),
            ('IPV4',
             r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b',
             0, 0),
            ('IPV6',
             r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b',
             0, 0),
            # US street address: "123 Main Street", "42 Oak Ave", etc.
            # Case-sensitive so Title Case proper nouns don't confuse address detection
            ('ADDRESS',
             r'\b\d{1,5}\s+[A-Z][A-Za-z0-9\s]{2,40}(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Blvd|Boulevard|Way|Court|Ct|Place|Pl|Circle|Cir)\b',
             0, 0),

            # === Name detection (context-aware, replace only the name — group 1) ===
            # Case-sensitive: [A-Z][a-z]+ must be genuinely Title Case
            ('NAME',
             r'(?i:my name is|name is|i\'m|i am|called|hi,?\s+i\'m|dear)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
             1, 0),
        ]

    def scrub(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Scrub PII from text.

        Returns:
            (scrubbed_text, entities)
            entities: {"SSN_1": "123-45-6789", "NAME_1": "John Smith", ...}
        """
        scrubbed = text
        entities: Dict[str, str] = {}
        counters: Dict[str, int] = defaultdict(int)

        for pii_type, pattern, group, flags in self.patterns:
            def _make_replacer(t: str = pii_type, g: int = group):
                def replacer(match: re.Match) -> str:
                    counters[t] += 1
                    placeholder = f"{t}_{counters[t]}"

                    if g == 0:
                        entities[placeholder] = match.group(0)
                        return f"[{placeholder}]"
                    else:
                        # Replace only capture group g; preserve rest of match
                        value = match.group(g)
                        entities[placeholder] = value
                        full = match.group(0)
                        grp_start = match.start(g) - match.start(0)
                        grp_end = match.end(g) - match.start(0)
                        return full[:grp_start] + f"[{placeholder}]" + full[grp_end:]

                return replacer

            scrubbed = re.sub(pattern, _make_replacer(), scrubbed, flags=flags)

        return scrubbed, entities

    def restore(self, scrubbed_text: str, entities: Dict[str, str]) -> str:
        """Restore original PII values from entities mapping."""
        restored = scrubbed_text
        for placeholder, original in entities.items():
            restored = restored.replace(f"[{placeholder}]", original)
        return restored


# ── Self-test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    scrubber = PIIScrubber()

    tests = [
        ("Test 1 — Name/SSN/Email",
         "My name is John Smith and my SSN is 123-45-6789 and email is john@company.com"),
        ("Test 2 — Credit Card",
         "Credit card: 4532015112830366, expires 12/25"),
        ("Test 3 — API Key",
         "API key: sk-proj-abc123xyz789"),
        ("Test 4 — Mixed",
         "Call me at 555-867-5309. My AWS key is AKIAIOSFODNN7EXAMPLE and I live at 42 Elm Street"),
        ("Test 5 — Database URL",
         "Connect to postgres://admin:hunter2@db.prod.com:5432/users"),
        ("Test 6 — Bearer token",
         "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.sig"),
    ]

    for label, text in tests:
        print(f"\n{'='*60}")
        print(f"{label}")
        print(f"INPUT:   {text}")
        scrubbed, entities = scrubber.scrub(text)
        print(f"OUTPUT:  {scrubbed}")
        print(f"ENTITIES: {json.dumps(entities, indent=2)}")

        # Verify restore round-trips
        restored = scrubber.restore(scrubbed, entities)
        ok = "✓" if restored == text else "✗ MISMATCH"
        print(f"RESTORE: {ok}")
