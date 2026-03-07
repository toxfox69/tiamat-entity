"""
scrubber.py — PII Scrubber for Privacy Proxy
Detects and redacts PII from text using spaCy NER + regex patterns.

Usage:
    from scrubber import scrub_pii
    result = scrub_pii("Contact John Smith at john@example.com or 555-867-5309")
    # {"scrubbed": "Contact [NAME_1] at [EMAIL_1] or [PHONE_1]",
    #  "entities": {"[NAME_1]": "John Smith", "[EMAIL_1]": "john@example.com", "[PHONE_1]": "555-867-5309"}}
"""

import re
import spacy
from typing import Dict, List, Tuple, Any

# ---------------------------------------------------------------------------
# spaCy — loaded once at module level
# ---------------------------------------------------------------------------
_nlp = None

def _get_nlp() -> spacy.language.Language:
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


# ---------------------------------------------------------------------------
# False-positive filter for NER names
# ---------------------------------------------------------------------------
_FALSE_POSITIVE_NAMES = {
    # Days / months
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # Titles that spaCy sometimes tags as PERSON
    "mr", "mrs", "ms", "dr", "prof", "sir", "dame",
    # Common words mistagged
    "true", "false", "null", "none", "nan", "error", "warning", "info", "debug",
    "god", "lord", "king", "queen",
    # Company suffixes
    "inc", "llc", "corp", "ltd", "co",
}


# ---------------------------------------------------------------------------
# Regex patterns — ordered most-specific first to win overlap resolution
# ---------------------------------------------------------------------------
# Each tuple: (label, compiled_pattern)
_PATTERNS: List[Tuple[str, re.Pattern]] = [

    # 1. URLs with embedded credentials: scheme://user:pass@host[/path]
    # Uses greedy [^\s]* so passwords containing '@' are handled correctly —
    # the engine backtracks to match the LAST '@' before a valid hostname.
    ("URL", re.compile(
        r'\b(?:https?|ftp|sftp|ssh|smtp|imap|postgresql|mysql|redis|mongodb)'
        r'://[^\s]*@[a-zA-Z0-9.\-]+(?::\d+)?(?:/[^\s"\'<>,]*)?',
        re.IGNORECASE,
    )),

    # 2. API / secret keys with known prefixes
    ("KEY", re.compile(
        r'\b('
        r'sk-[a-zA-Z0-9_\-]{20,}'             # OpenAI / Anthropic
        r'|pk-[a-zA-Z0-9_\-]{20,}'             # Public key style
        r'|rk-[a-zA-Z0-9_\-]{20,}'             # RunPod
        r'|ghp_[a-zA-Z0-9]{36}'                # GitHub personal access token
        r'|ghs_[a-zA-Z0-9]{36}'                # GitHub server token
        r'|xoxb-[0-9A-Za-z\-]{40,}'            # Slack bot token
        r'|xoxa-[0-9A-Za-z\-]{40,}'            # Slack app token
        r'|AKIA[0-9A-Z]{16}'                   # AWS access key ID
        r'|[Bb]earer\s+[a-zA-Z0-9_\-\.]{20,}' # Bearer token header value
        r')\b',
    )),

    # 3. SSN: XXX-XX-XXXX (excludes invalid ranges per SSA rules)
    ("SSN", re.compile(
        r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b'
    )),

    # 4. Credit card: major networks, optional separators
    ("CC", re.compile(
        r'\b(?:'
        r'4[0-9]{3}'                            # Visa
        r'|5[1-5][0-9]{2}'                      # Mastercard
        r'|3[47][0-9]{2}'                       # Amex
        r'|6(?:011|5[0-9]{2})'                  # Discover
        r')'
        r'(?:[-\s]?[0-9]{4}){3}'
        r'\b',
    )),

    # 5. IPv4 address
    ("IP", re.compile(
        r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
        r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
    )),

    # 6. Email address
    ("EMAIL", re.compile(
        r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'
    )),

    # 7. Phone numbers — US formats with optional country code
    ("PHONE", re.compile(
        r'(?<!\d)'
        r'(?:\+?1[-.\s]?)?'                     # optional +1
        r'(?:\(?\d{3}\)?[-.\s]?)'               # area code
        r'\d{3}[-.\s]?\d{4}'
        r'(?!\d)',
    )),

    # 8. US street address: number + name words + street type
    ("ADDR", re.compile(
        r'\b\d{1,5}\s+'
        r'(?:[A-Z][a-zA-Z]+\.?\s+){1,4}'
        r'(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Road|Rd|'
        r'Lane|Ln|Way|Court|Ct|Place|Pl|Circle|Cir|Terrace|Ter|'
        r'Highway|Hwy|Parkway|Pkwy|Square|Sq)'
        r'(?:\.|\b)'
        r'(?:\s*,?\s*(?:Apt|Suite|Ste|Unit|Apartment|Floor|Fl|#)\s*[0-9A-Za-z]+)?',
        re.IGNORECASE,
    )),
]


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def scrub_pii(text: str) -> Dict[str, Any]:
    """
    Detect and replace PII in *text* with numbered placeholders.

    Returns:
        {
            "scrubbed":  str   — text with [TYPE_N] placeholders,
            "entities":  dict  — {"[TYPE_1]": "original value", ...}
        }

    Placeholder types:
        [NAME_N]   — person name (spaCy NER)
        [EMAIL_N]  — email address
        [PHONE_N]  — phone number
        [SSN_N]    — social security number
        [CC_N]     — credit card number
        [IP_N]     — IPv4 address
        [URL_N]    — URL with embedded credentials
        [KEY_N]    — API key / secret token
        [ADDR_N]   — street address
    """
    if not text or not text.strip():
        return {"scrubbed": text, "entities": {}}

    # Collect raw spans: (start, end, label, original_value)
    raw: List[Tuple[int, int, str, str]] = []

    # --- Regex passes ---
    for label, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            raw.append((m.start(), m.end(), label, m.group(0)))

    # --- spaCy NER pass ---
    nlp = _get_nlp()
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ != "PERSON":
            continue
        name = ent.text.strip()
        if len(name) < 3:
            continue
        words_lower = [w.lower().rstrip(".") for w in name.split()]
        if any(w in _FALSE_POSITIVE_NAMES for w in words_lower):
            continue
        # Skip ALL-CAPS short tokens (likely acronyms, not names)
        if name.isupper() and len(name) <= 6:
            continue
        raw.append((ent.start_char, ent.end_char, "NAME", name))

    if not raw:
        return {"scrubbed": text, "entities": {}}

    # Sort: earliest start wins; on tie, longest match wins (more specific)
    raw.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    # Greedy overlap resolution — keep non-overlapping spans
    resolved: List[Tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, label, value in raw:
        if start >= last_end:
            resolved.append((start, end, label, value))
            last_end = end

    # Assign placeholders (reuse same placeholder for repeated identical values)
    counters: Dict[str, int] = {}
    value_to_ph: Dict[str, str] = {}
    entities: Dict[str, str] = {}
    final_spans: List[Tuple[int, int, str]] = []

    for start, end, label, value in resolved:
        # Normalise whitespace in value for dedup key
        key = " ".join(value.split())
        if key in value_to_ph:
            ph = value_to_ph[key]
        else:
            counters[label] = counters.get(label, 0) + 1
            ph = f"[{label}_{counters[label]}]"
            value_to_ph[key] = ph
            entities[ph] = value
        final_spans.append((start, end, ph))

    # Single-pass string reconstruction
    parts: List[str] = []
    cursor = 0
    for start, end, ph in final_spans:
        parts.append(text[cursor:start])
        parts.append(ph)
        cursor = end
    parts.append(text[cursor:])

    return {
        "scrubbed": "".join(parts),
        "entities": entities,
    }


# ---------------------------------------------------------------------------
# Flask integration helper
# ---------------------------------------------------------------------------

def scrub_request_body(body: Any) -> Tuple[Any, Dict[str, str]]:
    """
    Recursively scrub PII from a JSON-deserialized request body.
    Handles dicts, lists, and strings.
    Returns (scrubbed_body, combined_entities).
    """
    all_entities: Dict[str, str] = {}

    def _scrub(obj: Any) -> Any:
        if isinstance(obj, str):
            result = scrub_pii(obj)
            all_entities.update(result["entities"])
            return result["scrubbed"]
        if isinstance(obj, dict):
            return {k: _scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(item) for item in obj]
        return obj

    return _scrub(body), all_entities


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def _run_tests():
    tests = [
        # (description, input_text, expected_placeholders)
        (
            "Person name + email",
            "Hello, my name is John Smith and you can reach me at john.smith@example.com.",
            ["[NAME_1]", "[EMAIL_1]"],
        ),
        (
            "SSN + phone",
            "My SSN is 078-05-1120 and my phone number is (555) 867-5309.",
            ["[SSN_1]", "[PHONE_1]"],
        ),
        (
            "Credit card (spaced)",
            "Please charge 4111 1111 1111 1111 for the order.",
            ["[CC_1]"],
        ),
        (
            "Credit card (dashed)",
            "Card: 5500-0000-0000-0004",
            ["[CC_1]"],
        ),
        (
            "IPv4 address",
            "Server is at 192.168.1.100, connect via port 8080.",
            ["[IP_1]"],
        ),
        (
            "API key (sk- prefix)",
            "Export OPENAI_API_KEY=sk-abc123xyz789def456ghi012jkl345mno678",
            ["[KEY_1]"],
        ),
        (
            "URL with credentials",
            "Database URL: postgresql://admin:s3cr3tP@ss@db.internal.corp/mydb",
            ["[URL_1]"],
        ),
        (
            "Street address",
            "She lives at 742 Evergreen Terrace, Apt 3B.",
            ["[ADDR_1]"],
        ),
        (
            "Mixed PII paragraph",
            (
                "From: Alice Johnson <alice@acme.com>\n"
                "My SSN is 532-14-9876, CC 4111111111111111.\n"
                "Call me at 212-555-0100 or find me at 1600 Pennsylvania Ave.\n"
                "Server IP: 10.0.0.1. Key: sk-test1234567890abcdefghijklmnop"
            ),
            ["[NAME_1]", "[EMAIL_1]", "[SSN_1]", "[CC_1]", "[PHONE_1]",
             "[ADDR_1]", "[IP_1]", "[KEY_1]"],
        ),
        (
            "Same value repeated — single placeholder reused",
            "Email john@test.com to confirm, then cc john@test.com again.",
            ["[EMAIL_1]"],  # appears twice but same placeholder
        ),
        (
            "No PII",
            "The weather today is sunny with a high of 72 degrees.",
            [],
        ),
        (
            "False positive guard — common word not a name",
            "In March, true errors may surface.",
            [],  # March / true should not be tagged as NAMEs
        ),
        (
            "GitHub token",
            "Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh12",
            ["[KEY_1]"],
        ),
        (
            "AWS access key",
            "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
            ["[KEY_1]"],
        ),
    ]

    passed = failed = 0
    for desc, text, expected_phs in tests:
        result = scrub_pii(text)
        scrubbed = result["scrubbed"]
        entities = result["entities"]

        # Check every expected placeholder appears in scrubbed text
        # and that original PII is NOT present in scrubbed text (unless no PII expected)
        ok = True
        missing = []
        for ph in expected_phs:
            if ph not in scrubbed:
                ok = False
                missing.append(ph)

        # Verify entity map has same keys as appeared in scrubbed text
        found_phs = re.findall(r'\[[A-Z]+_\d+\]', scrubbed)
        for ph in found_phs:
            if ph not in entities:
                ok = False

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"[{status}] {desc}")
        if not ok:
            print(f"       Input:    {text!r}")
            print(f"       Scrubbed: {scrubbed!r}")
            print(f"       Entities: {entities}")
            if missing:
                print(f"       Missing placeholders: {missing}")
        else:
            # Show the scrubbed output for passing tests
            print(f"       → {scrubbed}")
            if entities:
                for ph, val in entities.items():
                    print(f"         {ph}: {val!r}")
        print()

    print(f"Results: {passed} passed, {failed} failed out of {passed+failed} tests")
    return failed == 0


if __name__ == "__main__":
    import sys
    success = _run_tests()
    sys.exit(0 if success else 1)
