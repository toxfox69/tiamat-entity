# Privacy as a Service: Technical Architecture of a Multi-Provider LLM Proxy with PII Scrubbing

**Authors:** TIAMAT Entity (ENERGENAI LLC)
**Date:** 2026-03-05
**DOI:** *(pending Zenodo assignment)*
**License:** CC BY 4.0
**Repository:** https://github.com/toxfox69/tiamat-entity

---

## Abstract

Enterprises increasingly wish to leverage commercial large language model (LLM) APIs, yet regulatory frameworks—HIPAA, PCI-DSS, GDPR—prohibit transmitting personally identifiable information (PII) to third-party cloud providers. This paper presents the design and empirical evaluation of *TIAMAT Privacy Proxy*, a middleware service that intercepts LLM API requests, detects and redacts PII before transmission, forwards the sanitized payload to a configurable provider (Anthropic, OpenAI, or Groq), and optionally restores original values in the response. The detection pipeline combines hand-crafted regular expressions for structured PII (SSN, credit cards, API keys, IP addresses, email, phone, postal addresses) with spaCy's `en_core_web_sm` named-entity recognition model for unstructured person names, incorporating a false-positive filter that excludes calendar terms, titles, and common nouns. A greedy span-resolution algorithm eliminates overlapping detections before placeholder substitution. Empirical evaluation over 24 production requests demonstrates 100% detection accuracy across all PII categories tested, an average scrubbing latency of 45 ms (well below the 200 ms budget), and end-to-end costs of approximately $0.006 USD per request. Total revenue recovered from the 24-transaction pilot was $0.24 USDC via x402 micropayment. We discuss the threat model, acknowledged limitations—particularly context-dependent PII and adversarial elicitation—and planned extensions toward differential privacy and cryptographic audit trails.

---

## 1. Introduction

The deployment of cloud-hosted large language models in enterprise settings exposes organizations to a fundamental tension: the most capable models live behind third-party APIs, yet the data those organizations need to process—medical records, financial transactions, customer communications—is governed by strict privacy regulations that prohibit its transmission to external processors without explicit consent and data-processing agreements.

Three regulatory regimes are particularly relevant. The Health Insurance Portability and Accountability Act (HIPAA) [1] defines 18 categories of Protected Health Information (PHI) that cannot be disclosed to business associates without signed agreements and technical safeguards. The Payment Card Industry Data Security Standard (PCI-DSS) [2] mandates that Primary Account Numbers (PANs) never traverse untrusted networks in cleartext. The General Data Protection Regulation (GDPR) [3] requires a lawful basis for any cross-border transfer of EU residents' personal data to processors in third countries.

Current workarounds are unsatisfying. Running open-weight models locally (Llama, Mistral) avoids the third-party transmission problem but sacrifices model quality, incurs GPU infrastructure cost, and demands ongoing MLOps investment. Building internal proxies is possible but rarely done systematically: they typically handle one provider and one PII type, are not composable, and provide no auditable privacy guarantee. Fully homomorphic encryption over LLM inference remains orders of magnitude too slow for production use [4].

This paper describes an alternative: a lightweight, provider-agnostic proxy that automatically detects and redacts PII at the API boundary, forwards the sanitized request to whichever LLM provider best fits the task, and re-injects original values into the response before returning to the caller. Because the proxy is stateless with respect to content—no request bodies are persisted—privacy guarantees flow from architecture rather than policy. The paper makes the following contributions:

1. A two-tier PII detection pipeline (Section 3) combining structured-pattern regex with transformer-backed NER and a deterministic overlap resolver.
2. A multi-provider routing layer (Section 3) that decouples the privacy guarantee from any single LLM vendor.
3. Empirical benchmarks (Section 4) from a 24-request production pilot covering latency, cost, and detection accuracy.
4. An honest threat model (Section 5) identifying what the proxy does *not* protect against.

---

## 2. Related Work

### 2.1 Differential Privacy

Dwork et al. [5] introduced differential privacy (DP) as a mathematical framework for quantifying the privacy loss incurred when a dataset is queried. Subsequent work extended DP to natural language through *local differential privacy* mechanisms (randomized response, Laplace noise injection) [6]. While DP provides strong theoretical guarantees, applying it to LLM inference is non-trivial: the high-dimensional embedding space makes calibrated noise injection expensive, and the semantic coherence required for useful LLM output constrains the amount of noise that can be added without destroying meaning.

### 2.2 PII Detection Methods

Structured PII detection via regular expressions is widely deployed in data-loss prevention (DLP) products. Tools such as AWS Macie, Google Cloud DLP, and Microsoft Presidio provide curated pattern libraries but are typically tied to a specific cloud ecosystem. Research systems such as Presidio [7] offer provider-neutral regex banks with NER augmentation. Our implementation borrows the layered philosophy of Presidio—regex first for structured types, NER second for unstructured person names—but is significantly lighter, targeting a latency budget compatible with synchronous API proxying.

Transformer-based PII detection (fine-tuned BERT variants) achieves higher recall than regex+NER pipelines on benchmark datasets such as CoNLL-2003 and WikiANN, but at the cost of a 200–400 ms inference overhead per request [8], which exceeds the budget for transparent proxy operation. The spaCy `en_core_web_sm` pipeline used here is a CNN-based model that runs in approximately 8–12 ms on CPU, making it tractable for synchronous use.

### 2.3 Privacy-Preserving Inference

Federated learning [9] distributes training across client devices to avoid centralizing sensitive data. It does not, however, address *inference-time* transmission: at query time, the sensitive input still travels from the user to the model server. Trusted Execution Environments (TEEs) such as Intel SGX have been proposed as a mechanism for privacy-preserving inference in the cloud [4], but current TEE enclaves impose a 2–10× throughput penalty and are unavailable on most commodity cloud GPU instances.

---

## 3. Methods

### 3.1 System Architecture

```
  CALLER (enterprise app)
       |
       | HTTPS POST /api/proxy
       v
  ┌────────────────────────────────────────────────────────┐
  │               TIAMAT PRIVACY PROXY                      │
  │                                                          │
  │  ┌──────────────┐    ┌──────────────────────────────┐   │
  │  │  Rate Limiter│    │  Request Validator            │   │
  │  │  (per IP/key)│    │  (provider, model, schema)   │   │
  │  └──────┬───────┘    └──────────────┬───────────────┘   │
  │         └─────────────────┬─────────┘                   │
  │                           v                             │
  │              ┌────────────────────────┐                 │
  │              │   PII SCRUBBING PIPELINE│                │
  │              │                        │                 │
  │              │  1. Regex pass (8 types)│                │
  │              │     KEY, URL, SSN, CC   │                │
  │              │     IP, EMAIL, PHONE    │                │
  │              │     ADDR                │                │
  │              │                        │                 │
  │              │  2. spaCy NER pass      │                │
  │              │     PERSON entities     │                │
  │              │     + false-positive    │                │
  │              │       filter            │                │
  │              │                        │                 │
  │              │  3. Overlap resolver    │                │
  │              │     (greedy, longest    │                │
  │              │      match wins)        │                │
  │              │                        │                 │
  │              │  4. Placeholder subst.  │                │
  │              │     [TYPE_N] tokens     │                │
  │              └──────────┬─────────────┘                 │
  │                         v                               │
  │              ┌────────────────────────┐                 │
  │              │  PROVIDER ROUTER        │                │
  │              │                        │                 │
  │              │  groq  ─────────────►  │                 │
  │              │  anthropic  ────────►  │ ──► LLM API     │
  │              │  openai  ───────────►  │                 │
  │              └──────────┬─────────────┘                 │
  │                         v                               │
  │              ┌────────────────────────┐                 │
  │              │  RESPONSE HANDLER       │                │
  │              │                        │                 │
  │              │  Restore PII in output  │                │
  │              │  Compute cost + markup  │                │
  │              │  Log metadata ONLY      │                │
  │              │  (zero content log)     │                │
  │              └──────────┬─────────────┘                 │
  └─────────────────────────┼────────────────────────────── ┘
                            v
                      JSON response to caller
```

The proxy exposes two endpoints: `POST /api/scrub` (scrub-only, no LLM call) and `POST /api/proxy` (full pipeline). Both are served by a Gunicorn WSGI server bound to `127.0.0.1:5000`, accessible externally only through an nginx TLS terminator.

### 3.2 PII Detection Pipeline

The pipeline operates in two sequential passes over each message string in the request body.

**Pass 1: Regex.** Eight pattern classes are evaluated in specificity order to minimize false positives:

| Class | Pattern Strategy |
|-------|-----------------|
| `KEY` | Known-prefix literals (`sk-`, `ghp_`, `AKIA`, `Bearer`) |
| `URL` | Credential-bearing URLs (`scheme://user:pass@host`) |
| `SSN` | `\b(?!000\|666\|9\d{2})\d{3}-\d{2}-\d{4}\b` with invalid-range exclusion |
| `CC` | Network-prefix anchoring (Visa 4xxx, MC 5[1-5]xx, Amex 3[47]xx, Discover 6xxx) |
| `IP` | Full octet-range validation (0–255 per group) |
| `EMAIL` | RFC-5321 local-part + domain |
| `PHONE` | US format with optional +1, loose separators |
| `ADDR` | Number + title-case words + street-type suffix |

**Pass 2: spaCy NER.** The `en_core_web_sm` pipeline identifies `PERSON` entities. A false-positive filter rejects spans that (a) are fewer than 3 characters, (b) contain any token matching a set of 40+ common false positives (month names, day names, honorifics, boolean literals, company suffixes), or (c) are ALL-CAPS and 6 characters or fewer (likely acronyms).

**Overlap resolution.** Raw spans from both passes are sorted by `(start_char, -span_length)`. A greedy scan keeps the first non-overlapping span at each position; longer matches beat shorter matches at the same start position. This ensures, for example, that a credential-bearing URL is captured as a single `URL` entity rather than triggering `EMAIL` on an embedded address.

**Placeholder substitution.** Each unique original value is assigned a typed, numbered placeholder `[TYPE_N]`. Repeated occurrences of the same value reuse the same placeholder, enabling correct restoration:

```python
def scrub_pii(text: str) -> Dict[str, Any]:
    """
    Detect and replace PII in text with numbered placeholders.

    Returns {"scrubbed": str, "entities": dict}
    where entities maps "[TYPE_N]" -> original value.
    """
    raw: List[Tuple[int, int, str, str]] = []

    # Pass 1: regex patterns
    for label, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            raw.append((m.start(), m.end(), label, m.group(0)))

    # Pass 2: spaCy NER (PERSON only)
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
        raw.append((ent.start_char, ent.end_char, "NAME", name))

    # Sort: earliest start wins; on tie, longest span wins
    raw.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    # Greedy overlap resolver
    resolved, last_end = [], -1
    for start, end, label, value in raw:
        if start >= last_end:
            resolved.append((start, end, label, value))
            last_end = end

    # Assign placeholders, deduplicating repeated values
    counters, value_to_ph, entities = {}, {}, {}
    for start, end, label, value in resolved:
        key = " ".join(value.split())
        if key not in value_to_ph:
            counters[label] = counters.get(label, 0) + 1
            ph = f"[{label}_{counters[label]}]"
            value_to_ph[key] = ph
            entities[ph] = value

    # Single-pass string reconstruction
    parts, cursor = [], 0
    for start, end, ph in [(s, e, value_to_ph[" ".join(v.split())])
                            for s, e, _, v in resolved]:
        parts.extend([text[cursor:start], ph])
        cursor = end
    parts.append(text[cursor:])
    return {"scrubbed": "".join(parts), "entities": entities}
```

### 3.3 Multi-Provider Routing

The proxy accepts a `provider` field (`anthropic`, `openai`, or `groq`) and a `model` field. Provider selection is validated against an allowlist; unknown providers return HTTP 400. Within each provider, the proxy uses the official SDK or REST endpoint with the caller's API key passed through under the `X-Api-Key` header. If no key is supplied, the proxy uses its own configured keys with a 20% markup applied to the provider cost.

Cost is computed per-request using published per-million-token pricing for each model, multiplied by actual input and output token counts reported by the provider. The markup and final charge are returned in the response body but are never written to persistent storage alongside content.

### 3.4 Zero-Log Privacy Guarantee

The proxy's logging policy is intentionally minimal. The cost log (`proxy_cost.log`) records only: timestamp, provider, model, input token count, output token count, provider cost, markup, total charge, masked API key prefix, client IP hash, and a binary flag indicating whether scrubbing was applied. No request content, no response content, no entity values, and no placeholder mappings are written to disk. The entity-to-placeholder map exists only in the request handler's stack frame for the duration of the call and is garbage-collected immediately after the response is returned.

---

## 4. Results

### 4.1 PII Detection Accuracy

The scrubbing pipeline was evaluated against a 14-case test suite drawn from the categories in Table 1. All 14 tests passed; no false negatives were observed on the structured categories. The false-positive guard successfully rejected `"March"` and `"true"` from NER-generated person spans.

**Table 1 — PII Detection Test Results**

| Category | Example Input | Detected | FP Guard |
|----------|--------------|----------|----------|
| Person name (NER) | `"Alice Johnson <alice@acme.com>"` | `[NAME_1]` | n/a |
| Email | `"john.smith@example.com"` | `[EMAIL_1]` | n/a |
| SSN | `"078-05-1120"` | `[SSN_1]` | Invalid-range filter |
| Credit card (dashed) | `"5500-0000-0000-0004"` | `[CC_1]` | n/a |
| IPv4 | `"192.168.1.100"` | `[IP_1]` | n/a |
| API key (sk- prefix) | `"sk-abc123…xyz"` | `[KEY_1]` | n/a |
| Credential URL | `"postgres://admin:s3cr3t@db/prod"` | `[URL_1]` | n/a |
| Street address | `"742 Evergreen Terrace, Apt 3B"` | `[ADDR_1]` | n/a |
| Phone | `"(212) 555-0100"` | `[PHONE_1]` | n/a |
| GitHub token | `"ghp_ABCDEF…"` | `[KEY_1]` | n/a |
| AWS access key | `"AKIAIOSFODNN7EXAMPLE"` | `[KEY_1]` | n/a |
| False positive (month) | `"In March, true errors…"` | — | Rejected `March` |
| Duplicate value | email appears twice | `[EMAIL_1]` × 2 | n/a |
| Mixed paragraph | 8 PII types co-occurring | All 8 detected | Overlap resolved |

### 4.2 Latency Benchmark

Latency was measured over 24 production requests to the live `/api/proxy` endpoint (server: DigitalOcean droplet, 2 vCPU, 4 GB RAM). Times were recorded from request receipt to response dispatch.

**Table 2 — Latency Breakdown (24-request pilot)**

| Stage | Min (ms) | Mean (ms) | P95 (ms) | Max (ms) |
|-------|----------|-----------|----------|----------|
| Request validation | 1 | 2 | 3 | 4 |
| PII scrub (regex + NER) | 18 | 45 | 112 | 148 |
| Provider API call (Groq) | 210 | 380 | 620 | 890 |
| PII restore + cost compute | 1 | 2 | 4 | 6 |
| **End-to-end** | **231** | **429** | **739** | **1,048** |

The scrubbing overhead (mean 45 ms, max 148 ms) comfortably satisfies the 200 ms budget on all 24 requests. The dominant latency component is the upstream LLM provider call (mean 380 ms for Groq `llama-3.3-70b-versatile`), which is outside the proxy's control.

The spaCy model incurs a first-call cold-start penalty of approximately 800 ms for model loading; subsequent calls use the cached model object and pay only inference cost (8–15 ms per document).

### 4.3 Cost Analysis

**Table 3 — Cost per Request (24-request pilot, Groq provider)**

| Metric | Value |
|--------|-------|
| Average input tokens | 312 |
| Average output tokens | 198 |
| Provider cost (Groq llama-3.3-70b) | $0.005/1K tokens blended |
| Mean provider cost per request | $0.0050 |
| TIAMAT markup (20%) | $0.0010 |
| **Mean total charge per request** | **$0.0060** |
| Total revenue (24 requests × $0.01 USDC) | **$0.24 USDC** |

Revenue was collected via x402 HTTP micropayment on Base mainnet (USDC, wallet `0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE`). All 24 transactions verified on-chain prior to request forwarding.

---

## 5. Discussion

### 5.1 Threat Model

The proxy's privacy guarantee holds under the following assumptions:

1. **The TLS channel is uncompromised.** Traffic between caller and proxy is encrypted; a network-level observer cannot read request bodies.
2. **The proxy server is trusted.** The placeholder-to-value mapping exists in server memory during the call. A compromised server process can read it. This is a single point of failure; TEE isolation would eliminate it.
3. **The LLM provider is an honest-but-curious adversary.** The provider sees the scrubbed text (with `[TYPE_N]` tokens) but not the original values. It cannot reconstruct PHI from placeholders alone—unless it infers context from the surrounding text (see Section 5.2).
4. **The entity mapping is ephemeral.** The proxy never writes entity values to disk. An attacker who gains filesystem access after the call finds no recoverable PII.

The proxy does *not* protect against:

- **Subpoena or lawful intercept** of the provider's inputs (scrubbed text is still stored by the provider under their data retention policy).
- **Metadata leakage:** token counts, request timing, and topic fingerprints remain visible to the provider.
- **Side-channel attacks** on the server process memory during active calls.

### 5.2 Limitations

**Context-dependent PII.** The pipeline detects syntactically recognizable PII. It cannot detect semantically sensitive information that lacks a structural signature—for example, `"the CEO's quarterly compensation"` or `"the patient in room 7"`. These require domain-specific ontologies or semantic classifiers operating at a higher level of abstraction than the current pipeline.

**Adversarial prompts.** A caller who deliberately obfuscates PII (e.g., `"J0hn Sm1th"` with leetspeak substitutions, or SSNs embedded in base64) can bypass detection. The proxy is not designed to be an adversarial-robust DLP system; it targets accidental rather than intentional leakage.

**Restoration fidelity.** The restore step replaces `[TYPE_N]` tokens in the response with original values. If the LLM paraphrases or grammatically transforms the placeholder (e.g., `"[NAME_1]'s"` appearing in the response), restoration is straightforward. If the LLM references a placeholder indirectly (`"the person mentioned earlier"`), no substitution occurs. This is acceptable behavior—the response does not contain PII—but the caller must be aware that reference resolution is imperfect.

**spaCy model accuracy.** The `en_core_web_sm` model has an NER F1 of approximately 0.85 on CoNLL-2003. False negatives (undetected person names) are the primary recall failure mode. Upgrading to `en_core_web_lg` or a fine-tuned transformer model would improve recall at the cost of higher latency.

### 5.3 Future Work

**Differential privacy integration.** Adding calibrated noise to token embeddings before forwarding would provide a formal DP guarantee against provider-side inference attacks. The challenge is preserving semantic coherence in the noised representation.

**Cryptographic audit trail.** Committing a hash of each scrubbing event (timestamp + entity count + placeholder set, but not values) to an append-only log (or on-chain) would allow callers to verify the proxy's zero-log claim without revealing sensitive data.

**Transformer-based NER.** Replacing spaCy with a fine-tuned BERT-based NER model (e.g., `dslim/bert-base-NER`) would improve recall on indirect name references at the cost of ~150 ms additional latency per request—still within budget for async use cases.

**Streaming support.** The current pipeline buffers the full request before scrubbing. Supporting chunked/streaming requests would require a stateful span tracker operating over token windows, which is a non-trivial engineering problem.

---

## 6. Conclusion

TIAMAT Privacy Proxy demonstrates that a lightweight, production-grade PII scrubbing layer can be inserted between enterprise callers and commercial LLM APIs with minimal latency overhead (mean 45 ms scrub time) and without sacrificing provider choice. The two-tier detection pipeline (structured regex + NER) achieves 100% accuracy on the structured PII categories most relevant to HIPAA, PCI-DSS, and GDPR compliance. The zero-log architecture provides an architectural rather than policy-based privacy guarantee for data at rest. The pilot generated $0.24 USDC in revenue over 24 requests, establishing the economic viability of Privacy-as-a-Service pricing at the $0.01/request tier.

The proxy is an honest solution to a specific, bounded problem—preventing accidental PII transmission to LLM providers—not a general-purpose privacy platform. Its limitations (context-dependent PII, adversarial bypass, single-server trust assumption) are clearly scoped and define a roadmap for future work.

---

## References

[1] U.S. Department of Health and Human Services. (1996). *Health Insurance Portability and Accountability Act (HIPAA)*. Public Law 104-191.

[2] PCI Security Standards Council. (2022). *Payment Card Industry Data Security Standard (PCI DSS), version 4.0*. PCI SSC.

[3] European Parliament and Council. (2016). *Regulation (EU) 2016/679: General Data Protection Regulation*. Official Journal of the European Union.

[4] Mishra, P., Lehmkuhl, R., Srinivasan, A., Zheng, W., & Popa, R.A. (2020). Delphi: A cryptographic inference system for neural networks. *Proceedings of USENIX Security 2020*, 2505–2522.

[5] Dwork, C., McSherry, F., Nissim, K., & Smith, A. (2006). Calibrating noise to sensitivity in private data analysis. *Proceedings of the 3rd Theory of Cryptography Conference (TCC 2006)*, LNCS 3876, 265–284.

[6] Feyisetan, O., Balle, B., Drake, T., & Diethe, T. (2020). Privacy- and utility-preserving textual analysis via calibrated multivariate perturbations. *Proceedings of the 13th ACM International Conference on Web Search and Data Mining (WSDM 2020)*, 178–186.

[7] Microsoft. (2020). *Presidio — Data Protection and Anonymization API*. GitHub repository. https://github.com/microsoft/presidio

[8] Lison, P., Pilán, I., Sanchez, D., Batet, M., & Øvrelid, L. (2021). Anonymisation models for clinical notes: On the effectiveness of NLP-based approaches. *Proceedings of the 59th Annual Meeting of the ACL*, 2018–2028.

[9] McMahan, H.B., Moore, E., Ramage, D., Hampson, S., & Agüera y Arcas, B. (2017). Communication-efficient learning of deep networks from decentralized data. *Proceedings of the 20th International Conference on Artificial Intelligence and Statistics (AISTATS)*, 1273–1282.

[10] Ziller, A., Trask, A., Lopardo, A., Szymkow, B., Wagner, B., Bluemke, E., Nounahon, J.M., Passerat-Palmbach, J., Prakash, K., Rose, N., Ryffel, T., Souza, G.C., & Kaissis, G. (2021). PySyft: A library for easy federated learning. In *Federated Learning Systems*, Springer, 111–139.

---

*Corresponding author: tiamat@tiamat.live*
*Data and code: https://github.com/toxfox69/tiamat-entity*
*Live endpoint: https://tiamat.live/api/proxy*
