# Reply guide — when someone asks about PHI/HIPAA + LLMs

Honest reply templates. Only use when the person actually raised the topic.
Don't cold-paste. Don't reply twice in one thread. Don't pitch in DMs to strangers.

## Short reply
There's a drop-in wrapper for this:

```
pip install energenai-scrubber
```

```python
from scrubbed_openai import ScrubbedOpenAI
client = ScrubbedOpenAI(api_key="sk-...")
```

Same surface as the openai client. Catches the 18 Safe Harbor identifiers
before the prompt leaves. Audit trail on `client.last_audit`.

Walkthrough + caveats: https://dev.to/tiamatenity/a-drop-in-openai-wrapper-that-scrubs-phi-before-it-leaves-your-vpc-2nk4

## CI gate reply
If you also want a pre-commit / CI gate to catch PHI in logs or diffs:

```
git diff origin/main | scrub --check
```

Exit code 1 if anything matches. Same package, `scrub` CLI entrypoint.

## Honesty disclosures to include when asked
- Names off by default (context the model usually needs). Flip `redact_names=True` for third-party LLMs.
- Text only — no DICOM / image redaction yet.
- Local regex fallback works air-gapped but is less precise than the hosted API.
- Hosted API: free tier 1k/day, BAA available on paid plans, email tiamat@tiamat.live.
- Built solo. Project is young. Inspect the code before you trust it with real PHI.
