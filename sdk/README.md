# energenai-scrubber

Drop PHI on the floor before it reaches your LLM provider.

```python
from scrubbed_openai import ScrubbedOpenAI

client = ScrubbedOpenAI(api_key="sk-...")
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role":"user","content":"Patient John Doe SSN 555-12-3456 has flu"}],
)
# Upstream sees: "Patient John Doe SSN [SSN] has flu"
# client.last_audit holds the per-call scrub trail for HIPAA logs.
```

## Why
Most healthcare AI builders accidentally ship PHI into OpenAI / Anthropic / Gemini.
Once it leaves your VPC into a vendor that won't sign a BAA, you have a breach.
This wrapper turns Safe Harbor compliance into a one-line import change.

## What it catches
18 HIPAA Safe Harbor identifiers: SSN, DOB, phone, email, NPI, DEA, MRN, MemberID, ZIP,
IP, account #, fax, license, vehicle ID, URL, biometric ID, full-face photo refs, any-other-unique-ID.

## How it works
- `Scrubber` calls the hosted API at `https://www.tiamat.live/api/scrub` by default.
- Falls back to local regex if the API is unreachable.
- `ScrubbedOpenAI` wraps the official `openai` client — same surface, same return types.

## Audit trail
Every call appends to `client.last_audit`:
```python
[{"removed": 2, "compliant": False}, ...]
```
Pipe to your SIEM. HIPAA logs itself.

## Patent
US 64/000,905 — Privacy infrastructure for LLM prompts.

## Pricing
- Self-hosted regex fallback: free.
- Hosted API: free tier 1k/day, paid for volume. Email tiamat@tiamat.live.

Built by EnergenAI LLC. UEI LBZFEH87W746.
