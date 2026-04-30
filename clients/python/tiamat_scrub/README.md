# tiamat-scrub

One-line HIPAA Safe Harbor PHI scrubber for any LLM pipeline. Stdlib-only Python client (`urllib`+`json`, no `requests`, no SDK).

## Install

```bash
# just drop tiamat_scrub.py into your project — 75 lines, zero deps.
curl -O https://raw.githubusercontent.com/toxfox69/tiamat-entity/main/tiamat_scrub.py
```

## Use

```python
from tiamat_scrub import scrub, safe_for_llm

# 1. one-line guard before any model call
safe = scrub("Patient John Doe, DOB 1980-05-12, SSN 123-45-6789")
# -> "[NAME], [DOB], SSN [SSN]"

# 2. boolean form — pair with your LLM client
text, ok = safe_for_llm(prompt, strict=True)
if not ok:
    raise PHILeakError("residual risk after scrubbing")
client.completions.create(prompt=text, ...)

# 3. full audit (HIPAA accountability requirement)
r = scrub(text, return_audit=True)
r["scrubbed_text"]
r["audit"]                  # [{identifier_type, count, severity}, ...]
r["safe_harbor_compliant"]  # True if all 18 stripped
r["flags"]                  # residual contextual risk (v3 endpoint only)
```

## What it strips

The 18 HIPAA Safe Harbor identifiers (45 CFR §164.514(b)(2)):
SSN, names, dates of birth, addresses, phone, fax, email, MRN, account numbers,
NPI, DEA, IP addresses, URLs, vehicle VIN, license numbers, dates, ages, and
Luhn-validated credit card numbers (v3 endpoint).

## Why a service and not just a library

Two reasons.

**Rules drift.** New identifier patterns get added as edge cases come in
(unusual MRN formats, vehicle VINs, biometric URLs). One endpoint updates
faster than 50 pinned versions in the wild.

**BAAs.** If you can't send PHI off-prem — and you probably can't — the
same code runs in a container inside your VPC. Email tiamat@tiamat.live for
the image plus a BAA. The client doesn't change; just point
`TIAMAT_SCRUB_URL` at your internal host:

```bash
export TIAMAT_SCRUB_URL=http://your-internal-host:5006/api/scrub
```

## CLI smoke test

```bash
python tiamat_scrub.py "Patient Jane Smith, card 4532015112830366, SSN 123-45-6789"
```

## What it isn't

- Not a replacement for a BAA with your model provider if you have one.
- Not de-identification for research datasets — Safe Harbor has a separate
  "expert determination" path for that.
- Not magic: free-text clinical notes always carry residual re-identification
  risk (rare condition + small clinic = a vector even with names removed).
  That's what `flags["residual_contextual_risk"]` is for.

## License

MIT. Patent-pending pipeline (USPTO 64/000,905). EnergenAI LLC · tiamat.live.
