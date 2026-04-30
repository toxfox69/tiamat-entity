"""
tiamat_scrub — tiny Python client for the HIPAA PHI Scrubber API.

    from tiamat_scrub import scrub
    safe = scrub("Patient John Doe, DOB 1980-05-12, SSN 123-45-6789")
    # -> "[NAME], [DOB], SSN [SSN]"

Full audit + residual-risk flags:

    r = scrub(text, return_audit=True)
    r["scrubbed_text"]            # cleaned string
    r["audit"]                    # what got removed
    r["safe_harbor_compliant"]    # all 18 stripped?
    r["flags"]                    # residual contextual risk (v3 only)

Override endpoint with TIAMAT_SCRUB_URL env var.

EnergenAI LLC · patent-pending HIPAA Safe Harbor scrubber.
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.error

DEFAULT_ENDPOINT = os.environ.get(
    "TIAMAT_SCRUB_URL", "https://tiamat.live/api/scrub"
)


class ScrubError(RuntimeError):
    pass


def scrub(text, *, return_audit=False, timeout=10.0, endpoint=DEFAULT_ENDPOINT):
    """Scrub PHI from `text`. Returns scrubbed string, or full payload dict
    if `return_audit=True`."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if not text.strip():
        return {"scrubbed_text": text, "audit": []} if return_audit else text

    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "tiamat-scrub-py/0.2"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ScrubError("scrubber HTTP {}: {}".format(e.code, e.reason)) from e
    except urllib.error.URLError as e:
        raise ScrubError("scrubber unreachable: {}".format(e.reason)) from e
    except json.JSONDecodeError as e:
        raise ScrubError("bad response: {}".format(e)) from e

    if return_audit:
        return data
    return data.get("scrubbed_text", text)


def safe_for_llm(text, *, endpoint=DEFAULT_ENDPOINT, strict=False):
    """Returns (scrubbed_text, is_safe). `is_safe` is True iff the scrubber
    reports `safe_harbor_compliant`. With strict=True, also requires no
    residual contextual risk. Use as a single boolean before calling an LLM."""
    r = scrub(text, return_audit=True, endpoint=endpoint)
    safe = bool(r.get("safe_harbor_compliant", False))
    if strict:
        flags = r.get("flags", {})
        safe = safe and not flags.get("residual_contextual_risk", False)
    return r.get("scrubbed_text", text), safe


if __name__ == "__main__":
    import sys
    sample = " ".join(sys.argv[1:]) or (
        "Patient John Doe, DOB 1980-05-12, SSN 123-45-6789, "
        "card 4532015112830366, lives at 42 W Washington Boulevard, "
        "phone 555-867-5309, email jdoe@example.com"
    )
    out = scrub(sample, return_audit=True)
    print(json.dumps(out, indent=2))
