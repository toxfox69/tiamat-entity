# `/research` Endpoint — Architecture Design
**TIAMAT · ENERGENAI LLC · Rev 2026-02-26**

---

## Overview

A paid research-analysis endpoint that ingests academic papers (arXiv, DOI, or any URL),
extracts structured knowledge, and scores relevance to the wireless power / energy / AI-mesh
domain. Revenue from $0.50–$2.00 per call, no free tier (1 free quick-analysis per 24h per
IP as a discovery hook).

---

## Pricing Tiers

| Tier     | Price   | Depth                                             | Groq passes | Cache TTL |
|----------|---------|---------------------------------------------------|-------------|-----------|
| `quick`  | $0.50   | Title + abstract + 3 key claims + relevance score | 1 × 1024 tok | 30 days  |
| `standard` | $1.00 | Full extraction + efficiency + scalability + insights | 1 × 2048 tok | 14 days |
| `deep`   | $2.00   | All of standard + 2nd-pass adversarial critique + 5 follow-up Qs + competitor mapping | 2 × 2048 tok | 7 days |

**Payment options (reusing existing stack):**
- x402 USDC on Base — `tx_hash` in request body, verified by `check_tier()` with
  `request_amount=0.50 | 1.00 | 2.00`
- Stripe credits — debit 50 / 100 / 200 credits from `stripe_credits.db`
- API key subscription — future: monthly research-pack SKU

**Discount:** cached results returned at 50% price (result already computed; charge for
access, not compute). `cached: true` flag in response tells caller.

---

## Request Schema

```http
POST /research
Content-Type: application/json
```

```json
{
  "url":      "https://arxiv.org/abs/2511.18368",   // OR
  "arxiv_id": "2511.18368",                          // normalized to same canonical URL
  "depth":    "standard",                            // quick | standard | deep
  "tx_hash":  "0xabc...",                            // x402 USDC payment proof
  "api_key":  "sk_tiamat_...",                       // OR Stripe credits key
  "domains":  ["wireless_power", "mesh_networks"]    // optional: focus scoring
}
```

**Input normalization (pseudo-code):**

```python
def normalize_input(req) -> str:
    if arxiv_id := req.get("arxiv_id") or parse_arxiv_id(req.get("url")):
        canonical_url = f"https://arxiv.org/abs/{arxiv_id}"
        cache_key = f"arxiv:{arxiv_id}"
    else:
        canonical_url = req["url"]
        cache_key = f"url:{sha256(canonical_url)[:16]}"
    return canonical_url, cache_key

ARXIV_PATTERNS = [
    r"arxiv\.org/abs/(\d{4}\.\d{4,5})",
    r"arxiv\.org/pdf/(\d{4}\.\d{4,5})",
    r"^(\d{4}\.\d{4,5})$",   # bare ID
]
```

---

## Data Schema (SQLite — `/root/api/research_cache.db`)

```sql
CREATE TABLE research_cache (
    cache_key        TEXT PRIMARY KEY,   -- "arxiv:2511.18368" or "url:<hash>"
    canonical_url    TEXT NOT NULL,
    arxiv_id         TEXT,               -- NULL if not arXiv
    depth            TEXT NOT NULL,      -- quick | standard | deep
    -- Paper metadata
    title            TEXT,
    authors          TEXT,               -- JSON: ["Name A", "Name B"]
    venue            TEXT,               -- "arXiv" | "NeurIPS 2024" | "Nature Energy" etc.
    year             INTEGER,
    abstract         TEXT,
    -- Extracted knowledge
    key_claims       TEXT,               -- JSON: array of strings (max 5)
    efficiency_metrics TEXT,             -- JSON: {"metric": "value", ...}
    scalability      TEXT,               -- JSON: {"assessment": str, "bottleneck": str, "scale_limit": str}
    -- Relevance
    relevance_scores TEXT,               -- JSON: sub-dimension scores (see below)
    relevance_score  REAL,               -- 1–10 overall weighted score
    -- Output
    summary          TEXT,               -- 2–3 sentence human-readable summary
    actionable_insights TEXT,            -- JSON: array (max 5)
    follow_up_questions TEXT,            -- JSON: array (max 5, deep tier only)
    competitor_map   TEXT,               -- JSON: {paper_url: relevance_note}, deep only
    -- Meta
    model_used       TEXT,               -- "llama-3.3-70b-versatile"
    tokens_used      INTEGER,
    cached_at        TEXT,               -- ISO8601
    expires_at       TEXT,               -- ISO8601
    requester_hash   TEXT                -- sha256(ip)[:8] — analytics only
);

CREATE INDEX idx_arxiv     ON research_cache(arxiv_id);
CREATE INDEX idx_expires   ON research_cache(expires_at);
CREATE INDEX idx_relevance ON research_cache(relevance_score);

-- Audit trail (never purged)
CREATE TABLE research_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key   TEXT NOT NULL,
    depth       TEXT NOT NULL,
    was_cached  INTEGER NOT NULL,  -- 0 | 1
    price_paid  REAL NOT NULL,     -- USDC
    payment_method TEXT,           -- x402 | stripe | free
    tx_hash     TEXT,
    requested_at TEXT NOT NULL,
    requester_hash TEXT
);
```

---

## Processing Pipeline

```
POST /research
    │
    ├─ 1. Auth gate
    │       check_tier(tx_hash, request_amount=price[depth])
    │       OR _check_stripe_key(api_key) + _consume_stripe_credit(n)
    │       OR rate_limiter free slot (1/24h/IP for quick only)
    │       → 402 if fails
    │
    ├─ 2. Cache lookup
    │       SELECT * FROM research_cache WHERE cache_key=? AND expires_at > NOW()
    │       AND depth >= requested_depth   ← deep cache satisfies standard request
    │       → HIT: return cached JSON (charge 50% if paid)
    │
    ├─ 3. Paper fetch (cache miss path)
    │       fetch_paper(canonical_url) →
    │           arXiv: parse HTML abs page (title, authors, abstract, venue, year)
    │           other: requests.get + readability extract + fallback heuristics
    │
    ├─ 4. LLM extraction — Groq llama-3.3-70b
    │       Pass 1 (all tiers): extraction prompt → structured JSON
    │       Pass 2 (deep only): critique + follow-up + competitor prompt
    │
    ├─ 5. Relevance scoring
    │       score_relevance(extracted) → relevance_scores dict + weighted average
    │
    ├─ 6. Cache store
    │       INSERT INTO research_cache ...
    │
    ├─ 7. Side effects
    │       IF relevance_score >= 8.0:
    │           memory_api_store(insight)        ← feeds TIAMAT's memory
    │           send_research_alert(jason, paper)  ← email alert
    │
    └─ 8. Return JSON response
```

---

## LLM Prompts (pseudo-code)

### Pass 1 — Extraction (all tiers)

```python
EXTRACTION_SYSTEM = """
You are a scientific paper analyst for ENERGENAI LLC, focused on:
- Wireless power transfer (WPT) and resonant energy coupling
- Energy systems: harvesting, storage, efficiency optimization
- AI-driven mesh networks and distributed autonomous systems
- 6G/B5G wireless infrastructure

Extract information ONLY from the provided text. Return valid JSON.
"""

EXTRACTION_PROMPT = f"""
Paper text:
---
{paper_text[:6000]}   # truncate to fit context budget
---

Extract and return JSON with EXACTLY these keys:
{{
  "title": "...",
  "authors": ["Name A", "Name B"],
  "venue": "arXiv | Conference | Journal name",
  "year": 2024,
  "abstract": "...",
  "key_claims": [
    "Claim 1 (specific, falsifiable)",
    "Claim 2",
    "Claim 3"
  ],
  "efficiency_metrics": {{
    "power_efficiency": "e.g. 87.3% at 5m range",
    "throughput": "e.g. 42 Mbps",
    "latency": "...",
    "scale": "..."
  }},
  "scalability": {{
    "assessment": "high | medium | low",
    "bottleneck": "What limits scale?",
    "scale_limit": "e.g. works up to N nodes / X meters"
  }},
  "summary": "2–3 sentence plain-English summary",
  "actionable_insights": [
    "Specific thing we can do or adapt for Ringbound/EnergenAI"
  ]
}}

For quick depth: only title, authors, venue, year, abstract, key_claims (3 max), summary.
"""
```

### Pass 2 — Deep Analysis (deep tier only)

```python
DEEP_SYSTEM = """
You are a critical technology analyst and adversarial reviewer for ENERGENAI LLC.
"""

DEEP_PROMPT = f"""
You previously extracted this paper analysis:
{json.dumps(extracted, indent=2)}

Now perform deep analysis. Return JSON with EXACTLY these keys:
{{
  "adversarial_critique": "What claims are weakest? What did authors NOT test?",
  "follow_up_questions": [
    "Question to ask the authors or explore in follow-on research",
    ...  (5 max)
  ],
  "competitor_map": {{
    "arxiv:2401.XXXXX": "Related paper — addresses same problem via different method",
    ...
  }},
  "ringbound_application": "Specific way this applies to 7G wireless power mesh (Project Ringbound)",
  "patent_angle": "Any patentable element or conflict with patent 63/749,552"
}}
"""
```

---

## Relevance Scoring

```python
DOMAIN_WEIGHTS = {
    "wireless_power_transfer": 0.30,   # WPT, resonant coupling, beamforming, inductive
    "energy_systems":          0.20,   # grid, storage, harvesting, efficiency
    "ai_mesh_networks":        0.20,   # distributed AI, mesh topology, 6G, protocol
    "ringbound_fit":           0.20,   # Project Ringbound: 7G wireless power mesh
    "energenai_fit":           0.10,   # ENERGENAI use cases broadly
}

DOMAIN_KEYWORDS = {
    "wireless_power_transfer": [
        "wireless power", "WPT", "resonant coupling", "inductive transfer",
        "beamforming", "near-field", "far-field", "rectenna", "energy harvesting"
    ],
    "energy_systems": [
        "energy efficiency", "power grid", "battery", "storage", "harvesting",
        "photovoltaic", "thermal", "fuel cell", "smart grid"
    ],
    "ai_mesh_networks": [
        "mesh network", "distributed AI", "federated learning", "6G", "B5G",
        "autonomous", "multi-agent", "swarm", "edge AI", "intent-driven"
    ],
    "ringbound_fit": [
        "wireless power mesh", "7G", "power mesh", "aerial IoT", "UAV power",
        "AAV", "drone charging", "ambient power"
    ],
    "energenai_fit": [
        "autonomous energy", "AI-driven power", "self-sustaining",
        "agentic", "autonomous system", "energy-aware"
    ]
}

def score_relevance(extracted: dict) -> dict:
    text = " ".join([
        extracted.get("title", ""),
        extracted.get("abstract", ""),
        " ".join(extracted.get("key_claims", []))
    ]).lower()

    raw_scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in text)
        raw_scores[domain] = min(10.0, hits * 2.5)  # 4+ hits = 10

    # LLM override: pass raw_scores back to Groq for semantic refinement
    # (prevents keyword gaming, catches paraphrased concepts)
    refined = groq_refine_scores(text, raw_scores)  # → same dict, values 1–10

    weighted = sum(
        refined[d] * w for d, w in DOMAIN_WEIGHTS.items()
    )

    return {
        "sub_scores": refined,
        "overall": round(weighted, 1),
        "confidence": "high" if len(text) > 500 else "low"
    }
```

---

## Response Schema

```json
{
  "status": "ok",
  "cached": false,
  "depth": "standard",
  "price_paid_usdc": 1.00,

  "paper": {
    "title": "Wireless Power Transfer and Intent-Driven Network Optimization in AAVs-assisted IoT for 6G",
    "authors": ["Author A", "Author B"],
    "venue": "arXiv",
    "year": 2024,
    "url": "https://arxiv.org/abs/2511.18368",
    "arxiv_id": "2511.18368",
    "abstract": "This paper proposes..."
  },

  "extraction": {
    "key_claims": [
      "WPT efficiency of 91.2% achieved at 3m range under proposed resonant scheme",
      "Intent-driven optimization reduces control overhead by 47% vs. reactive approaches",
      "Proposed mesh topology scales to 500 AAV nodes with O(log n) coordination cost"
    ],
    "efficiency_metrics": {
      "power_efficiency": "91.2% at 3m",
      "control_overhead_reduction": "47%",
      "node_scale": "500 AAVs"
    },
    "scalability": {
      "assessment": "high",
      "bottleneck": "Central intent controller becomes single point of failure above 1000 nodes",
      "scale_limit": "Demonstrated up to 500 nodes in simulation"
    }
  },

  "relevance": {
    "score": 8.7,
    "confidence": "high",
    "sub_scores": {
      "wireless_power_transfer": 9.5,
      "energy_systems": 7.0,
      "ai_mesh_networks": 9.0,
      "ringbound_fit": 8.5,
      "energenai_fit": 8.0
    },
    "summary": "Directly applicable to Ringbound Phase 2. The intent-driven coordination model could replace the centralized scheduler in the current mesh design. WPT efficiency numbers provide a credible baseline to cite in DARPA ASEMA proposal."
  },

  "actionable_insights": [
    "Adopt the intent-driven controller pattern for Ringbound mesh coordination",
    "91.2% WPT efficiency at 3m is our new baseline claim — supersedes prior 85% estimate",
    "O(log n) scaling proof gives credibility to 500+ node deployment claims in SBIR apps",
    "AAV charging architecture maps directly to drone-in-the-loop Ringbound scenario",
    "Co-cite this paper in DARPA ASEMA DP2 proposal section 3.2 (technical approach)"
  ],

  "follow_up_questions": null,

  "meta": {
    "model": "llama-3.3-70b-versatile",
    "tokens_used": 1847,
    "analysis_ms": 2340,
    "cached_until": "2026-03-12T03:10:00Z"
  }
}
```

**Deep tier adds:**
```json
{
  "deep_analysis": {
    "adversarial_critique": "Simulation-only (no hardware). Power efficiency measured at fixed alignment — rotational offset not tested. Intent controller is centralized, contradicts 'distributed' framing.",
    "follow_up_questions": [
      "What is WPT efficiency when AAV is ±30° off-axis from transmitter?",
      "How does intent controller fail-over when the coordinator node is lost?",
      "Is the 91.2% figure measured at DC output or RF-to-RF?",
      "What frequency band is used — 915 MHz, 2.4 GHz, or custom?",
      "Has this been tested with heterogeneous AAV form factors?"
    ],
    "ringbound_application": "Use the intent-driven scheduler as inspiration for Ringbound's autonomous load-balancing layer. The O(log n) coordination proof directly supports our 1000-node scalability claim.",
    "patent_angle": "Distributed intent controller for WPT mesh may not conflict with patent 63/749,552 (Ringbound focuses on power mesh topology, not coordination protocol). Monitor for new filings from these authors."
  }
}
```

---

## Integration Points

### 1. `payment_verify.py` — already supports multi-amount

```python
# check_tier() already handles arbitrary request_amount
tier = check_tier(tx_hash, request_amount=price_map[depth], endpoint="/research")
# price_map = {"quick": 0.50, "standard": 1.00, "deep": 2.00}
```

### 2. Stripe credits — variable debit

```python
RESEARCH_CREDITS = {"quick": 50, "standard": 100, "deep": 200}
# _consume_stripe_credit() called N times OR extend to variable-amount debit
```

### 3. Memory API — auto-store high-value insights

```python
if relevance_score >= 8.0:
    requests.post("http://localhost:5001/api/memory/store", json={
        "content": f"HIGH-RELEVANCE PAPER: {title}\nKey: {key_claims[0]}\nRingbound: {ringbound_app}",
        "tags": ["research", "high-relevance", "auto-indexed"]
    })
```

### 4. Email alert — Jason gets notified

```python
if relevance_score >= 8.5:
    send_research_alert(
        to="tiamat.entity.prime@gmail.com",
        subject=f"[TIAMAT] High-relevance paper: {title[:60]}",
        body=f"Score: {relevance_score}/10\n\n{summary}\n\nActionable:\n{insights}"
    )
```

### 5. TIAMAT tool (`tools.ts`) — self-funded research

```typescript
// New tool: research_paper
// TIAMAT can call /research on papers she discovers during web_fetch
// She pays from her own wallet (Base USDC) for deep analysis on 9+ relevance hits
async function research_paper(url: string, depth = "standard"): Promise<ResearchResult> {
    // POST to localhost:5000/research with internal bypass (loopback = no payment gate)
    // OR: TIAMAT generates a tx from her wallet for external calls
}
```

### 6. SurrealDB — migration path (not yet installed)

Current plan: SQLite (`/root/api/research_cache.db`) — consistent with all other storage.
Migrate to SurrealDB when: >10k cached papers OR need graph queries (related paper clusters).
SurrealDB adds: `RELATE paper:A->cites->paper:B` for citation graph traversal.

---

## Free Tier / Discovery Hook

```python
# 1 free quick-analysis per 24h per IP — no payment needed
RESEARCH_FREE_LIMITER = create_rate_limiter(
    scope="research_free",
    max_attempts=1,
    window_sec=86400,
    lockout_sec=0
)

# Free analyses are NOT cached for 30 days — 7 day TTL only
# Forces re-payment for repeat access to same paper
```

---

## Revenue Model

| Scenario | Revenue |
|----------|---------|
| 10 quick / day | $5.00/day |
| 5 standard / day | $5.00/day |
| 2 deep / day | $4.00/day |
| Research Pack (10 analyses) | $8.00 USDC (20% bundle discount) |
| DARPA/DoD grant analysts using API | High-value recurring |
| TIAMAT self-purchasing (internal research budget) | Cost center → grant citation value |

**Target customers:**
1. Energy/wireless researchers who want domain-filtered summaries
2. VC/PE analysts evaluating deep-tech companies
3. SBIR grant writers needing recent-literature baselines
4. TIAMAT herself (internal research budget from revenue)

---

## Implementation Sequence (when ready to build)

1. `research_cache.db` schema + init function
2. `fetch_paper(url)` — arXiv HTML parser + generic fallback
3. Groq extraction prompt + JSON schema validation (retry once if malformed)
4. `score_relevance()` — keyword pass + Groq semantic refinement
5. `/research` Flask route — auth gate → cache → fetch → extract → score → store
6. Side effects: memory API + email alert
7. Add `research_paper` tool to `tools.ts`
8. Update `/docs` endpoint and `agent.json` with new service
9. Add to landing page pricing table

**Estimated implementation:** ~400 lines Python + 50 lines TypeScript tool wrapper.
No new pip dependencies required (Groq + SQLite + requests already present).
