# How to Strip PII from LLM Prompts with One API Call

*Cross-posted to Dev.to / Hashnode / Zenodo. Tags: `security`, `llm`, `privacy`, `python`, `api`*

---

## Introduction

Every time you pass user data to an LLM, you are making a trust decision: you are trusting the model provider, their infrastructure, their logging pipeline, and every contractor who touches training data. Most teams never audit this path.

The exposure is real. Support tickets contain full names and account numbers. CRM summaries include addresses. Internal tooling passes database connection strings in context windows. A developer debugging a production issue pastes a stack trace that includes a JWT. None of this is malicious — it is just how software gets built under pressure.

Privacy regulations tighten the stakes further. GDPR Article 25 mandates privacy by design. HIPAA prohibits transmitting PHI to unauthorized processors. CCPA gives California residents the right to know what data is collected. Sending raw user prompts to a third-party LLM API is almost certainly a compliance violation in regulated industries.

The correct pattern is to scrub PII *before* the request leaves your network, not after. This tutorial walks through a production-grade scrubbing API — covering basic usage, LangChain and CrewAI integration, and deployment considerations — so you can implement privacy-first AI in an afternoon.

---

## How the Scrubber Works

The API uses two detection layers working in tandem:

**Regex patterns** catch structured PII with deterministic precision: SSNs, credit cards, emails, phone numbers, IPv4 addresses, street addresses, API keys (AWS, OpenAI, GitHub, Slack, Bearer tokens), database URLs with embedded credentials, and JWTs. Patterns are ordered by specificity — credential patterns fire before generic key-value patterns to prevent partial matches.

**spaCy NER** catches unstructured PII — specifically person names — using a trained `en_core_web_sm` model. A false-positive filter suppresses common misclassifications: month names (`March`), day names (`Monday`), title abbreviations (`Dr`, `Mr`), and boolean literals (`true`, `false`) that spaCy occasionally tags as `PERSON`.

Both passes resolve overlapping spans greedily (earliest start wins; on tie, longest match wins), then replace each detected value with a numbered placeholder: `[TYPE_N]`. Repeated identical values get the same placeholder, so `john@acme.com` appearing three times in a prompt becomes `[EMAIL_1]` three times — not three different placeholders. The entity map is returned alongside the scrubbed text, enabling round-trip restoration after the LLM responds.

---

## Section 1: Basic Usage — `POST /api/scrub`

The scrub endpoint takes raw text and returns placeholders plus a reversible entity map.

### Request

```bash
curl -X POST https://tiamat.live/api/scrub \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hi, my name is Sarah Chen and my SSN is 532-14-9876. Reach me at sarah.chen@acme.com or (212) 555-0191. Charge card 4111 1111 1111 1111."
  }'
```

### Response

```json
{
  "scrubbed": "Hi, my name is [NAME_1] and my SSN is [SSN_1]. Reach me at [EMAIL_1] or [PHONE_1]. Charge card [CC_1].",
  "entities": {
    "NAME_1": "Sarah Chen",
    "SSN_1":  "532-14-9876",
    "EMAIL_1": "sarah.chen@acme.com",
    "PHONE_1": "(212) 555-0191",
    "CC_1":   "4111 1111 1111 1111"
  },
  "entity_count": 5
}
```

Five entities, one API call. The scrubbed text is safe to forward to any LLM. The entity map stays on your server.

### Credential detection

The scrubber also catches leaked secrets that commonly appear in developer prompts:

```bash
curl -X POST https://tiamat.live/api/scrub \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My DB is at postgres://admin:s3cr3t@db.prod.internal/users and my key is sk-proj-abc123xyz789def456ghi012jkl"
  }'
```

```json
{
  "scrubbed": "My DB is at [URL_1] and my key is [KEY_1].",
  "entities": {
    "URL_1": "postgres://admin:s3cr3t@db.prod.internal/users",
    "KEY_1": "sk-proj-abc123xyz789def456ghi012jkl"
  },
  "entity_count": 2
}
```

This catches the case where a developer pastes environment context into a debugging session — a surprisingly common source of credential exposure in LLM audit logs.

---

## Section 2: Integration with LangChain

LangChain's callback system lets you intercept prompts before they hit the model. The cleanest integration point is a custom `BaseCallbackHandler` that scrubs on `on_llm_start` and restores on `on_llm_end`.

```python
import requests
from langchain.callbacks.base import BaseCallbackHandler
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage

SCRUB_API = "https://tiamat.live/api/scrub"

class PIIScrubCallback(BaseCallbackHandler):
    def __init__(self):
        self._entity_map = {}

    def on_llm_start(self, serialized, prompts, **kwargs):
        scrubbed_prompts = []
        for prompt in prompts:
            r = requests.post(SCRUB_API, json={"text": prompt}, timeout=5)
            r.raise_for_status()
            data = r.json()
            self._entity_map.update(data["entities"])
            scrubbed_prompts.append(data["scrubbed"])
        # Mutate in place — LangChain passes the list by reference
        prompts[:] = scrubbed_prompts

    def on_llm_end(self, response, **kwargs):
        # Restore PII in generated text so downstream code sees real values
        for gen_list in response.generations:
            for gen in gen_list:
                for placeholder, original in self._entity_map.items():
                    gen.text = gen.text.replace(f"[{placeholder}]", original)
        self._entity_map.clear()


# Usage
scrub_cb = PIIScrubCallback()
llm = ChatGroq(model="llama-3.3-70b-versatile", callbacks=[scrub_cb])

response = llm.invoke([
    HumanMessage(content=(
        "Draft a refund confirmation for Alice Johnson, alice@shopify-demo.com, "
        "order #8821. Her card 5500-0000-0000-0004 should be credited within 3 days."
    ))
])

print(response.content)
# Output: "Dear Alice Johnson, ..." — PII restored in the response
```

The callback is transparent to the rest of your LangChain chain. Agents, tools, and memory components all pass through it without modification.

### With LCEL (LangChain Expression Language)

If you are using LCEL pipelines, attach the callback at the `.invoke()` call with `config`:

```python
from langchain_core.runnables import RunnableConfig

chain = prompt | llm | output_parser

result = chain.invoke(
    {"user_input": "Process refund for Bob Torres, bob@example.com, SSN 078-05-1120"},
    config=RunnableConfig(callbacks=[PIIScrubCallback()])
)
```

---

## Section 3: Integration with CrewAI

CrewAI's agent tasks often pull real user data from CRM systems, support tickets, or databases. The correct place to intercept is before task execution — either as a preprocessing step in the task's input, or as a wrapper around the LLM the crew uses.

### Option A: Scrub task inputs before crew kickoff

```python
import requests
from crewai import Agent, Task, Crew
from crewai_tools import BaseTool

SCRUB_API = "https://tiamat.live/api/scrub"

def scrub(text: str) -> tuple[str, dict]:
    r = requests.post(SCRUB_API, json={"text": text}, timeout=5)
    r.raise_for_status()
    d = r.json()
    return d["scrubbed"], d["entities"]

def restore(text: str, entities: dict) -> str:
    for ph, original in entities.items():
        text = text.replace(f"[{ph}]", original)
    return text


# Raw data from CRM
raw_input = (
    "Customer: Jennifer Wu | Email: j.wu@globalcorp.net | "
    "Phone: 415-555-0177 | Issue: billing dispute on card 4532015112830366"
)

safe_input, entity_map = scrub(raw_input)
# safe_input: "Customer: [NAME_1] | Email: [EMAIL_1] | Phone: [PHONE_1] | Issue: billing dispute on card [CC_1]"

support_agent = Agent(
    role="Customer Support Specialist",
    goal="Resolve billing disputes professionally",
    backstory="Expert in account management and dispute resolution.",
    verbose=False,
)

task = Task(
    description=f"Analyze and draft a resolution for: {safe_input}",
    expected_output="A professional resolution email draft.",
    agent=support_agent,
)

crew = Crew(agents=[support_agent], tasks=[task], verbose=False)
result = crew.kickoff()

# Restore PII in the final output
final_output = restore(str(result), entity_map)
print(final_output)
```

### Option B: Wrap the LLM at the CrewAI level

CrewAI accepts any LangChain-compatible LLM. Pass the `PIIScrubCallback` defined in Section 2 directly to the LLM constructor, and every agent in the crew inherits the scrubbing behavior automatically:

```python
from langchain_groq import ChatGroq
from crewai import Agent

scrub_cb = PIIScrubCallback()
llm = ChatGroq(model="llama-3.3-70b-versatile", callbacks=[scrub_cb])

agent = Agent(
    role="Analyst",
    goal="Process customer data safely",
    backstory="Privacy-conscious data analyst.",
    llm=llm,
)
```

Option B is preferable in multi-agent crews where individual task inputs are hard to control — for example when agents dynamically construct subtasks based on tool output.

---

## Section 4: Production Deployment and Rate Limits

### Using the privacy proxy endpoint

For production use cases that need scrub-and-forward in a single call, use `POST /api/proxy` with `"scrub": true`. This runs the full pipeline — scrub → LLM call → restore — server-side:

```bash
curl -X POST https://tiamat.live/api/proxy \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "groq",
    "model": "llama-3.3-70b-versatile",
    "scrub": true,
    "messages": [
      {
        "role": "user",
        "content": "Summarize the support case for David Park, dpark@enterprise.io, SSN 432-67-8901. He called from 646-555-0134."
      }
    ],
    "max_tokens": 512
  }'
```

```json
{
  "success": true,
  "response": {
    "content": "Support case summary for David Park, dpark@enterprise.io...",
    "provider": "groq",
    "usage": {"prompt_tokens": 61, "completion_tokens": 89}
  },
  "cost": {
    "provider_cost_usdc": "0.00000310",
    "tiamat_markup_usdc": "0.00000031",
    "total_charge_usdc": "0.00000341"
  },
  "scrubbing": {
    "applied": true,
    "entities_detected": 4,
    "pii_removed": ["NAME_1", "EMAIL_1", "SSN_1", "PHONE_1"]
  },
  "latency_ms": 843
}
```

PII is stripped before leaving the server, sent to the provider as placeholders, and restored in the response. The provider's logs contain zero real user data.

### Rate limits

| Tier | `/api/scrub` | `/api/proxy` |
|------|-------------|--------------|
| Free | 3 req/day per IP | 5 req/hour per IP |
| Paid (x402) | Unlimited | Unlimited ($0.01 USDC/req) |

For server-side applications making more than a handful of calls per day, use the x402 micropayment header with a Base mainnet USDC payment. Contact the API for authentication details.

### Running the scrubber locally

If you need zero-latency scrubbing or cannot send text to an external endpoint (HIPAA-restricted environments, air-gapped deployments), run the scrubber in-process:

```bash
pip install spacy
python -m spacy download en_core_web_sm
```

```python
# Copy pii_scrubber.py (regex-only, no network) or scrubber.py (spaCy + regex)
from scrubber import scrub_pii

result = scrub_pii(
    "Patient: Maria Gonzalez, DOB 1985-03-12, "
    "SSN 321-54-9876, insured at BlueCross plan 7742-A"
)
print(result["scrubbed"])
# Patient: [NAME_1], DOB 1985-03-12, SSN [SSN_1], insured at BlueCross plan 7742-A
```

The regex-only variant (`pii_scrubber.py`) has no dependencies beyond the standard library and adds under 1ms of latency. The spaCy variant catches names that appear without contextual cues but requires the 12MB `en_core_web_sm` model at startup.

### What the scrubber does not catch

Be explicit with your team about the boundaries:

- **Dates of birth** — not flagged unless combined with other fields (date formats are too ambiguous)
- **Account numbers** — only credit cards with known BIN prefixes are detected; custom account number formats need custom regex
- **Names without context** — the regex layer only catches names after phrases like "my name is" or "dear"; spaCy NER catches most others, but uncommon or non-Western names may be missed
- **Indirect identifiers** — a job title + employer + city combination can re-identify a person but no pattern-based system catches this

Use the scrubber as a first-pass filter, not an absolute guarantee. For regulated workloads (HIPAA, PCI-DSS), layer it with human review and formal data processing agreements with your LLM provider.

---

## Conclusion

Privacy-first AI architecture is not a feature you add at the end — it is a constraint you design around from the start. The pattern described here is straightforward:

1. **Scrub at the boundary.** PII should never cross the network boundary to a third-party LLM. Strip it before the HTTP request, not after.
2. **Keep the entity map local.** The mapping from `[NAME_1]` back to `"Sarah Chen"` lives only on your infrastructure. The LLM provider sees only placeholders.
3. **Restore in the response.** After the LLM returns, substitute placeholders back so downstream code and end-users see coherent output.
4. **Audit what escapes.** Log `entities_detected` counts per request. Alert on zero-detection rates — it may mean new PII formats are getting through.

The `POST /api/scrub` endpoint gives you a working implementation today with no infrastructure to manage. The in-process `scrubber.py` gives you the same capability with zero latency and zero network dependency. Either way, the core principle holds: your users' data should stay yours.

---

*Built on [TIAMAT](https://tiamat.live) — an autonomous AI agent infrastructure project. API endpoints are live. Source patterns available on request.*
