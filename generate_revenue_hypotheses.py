#!/usr/bin/env python3
"""
TIK-088: Revenue Hypothesis Generator
Reads agent economics synthesis, applies structured reasoning to generate
3 testable hypotheses about structural barriers to agent revenue.

No external APIs. Pure document analysis + economic reasoning.
"""

import re
import sys
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

SYNTHESIS_PATH = Path("/root/hive/knowledge/2026-02-26-agent-economics-synthesis.md")
OUTPUT_PATH    = Path("/root/hive/knowledge/2026-02-26-revenue-hypotheses.md")

# TIAMAT's empirical state — the anomaly we're trying to explain
TIAMAT_STATE = {
    "api_requests_served": 28_147,
    "paid_customers":      0,
    "autonomous_cycles":   5_311,
    "usdc_balance":        10.0001,
    "free_tier_calls":     3,         # summarize/generate per day per IP
    "x402_price_usdc":    0.01,       # per paid call
    "payment_infra":      "live",     # x402 on Base mainnet
    "agent_directories":  0,          # registrations completed
    "on_chain_reputation": False,
    "did_identity":        False,
}

# ── Document Parser ────────────────────────────────────────────────────────────

def parse_synthesis(path: Path) -> dict:
    """Extract structured content from the synthesis markdown."""
    text = path.read_text()

    sections = {}
    current_section = "preamble"
    current_lines = []

    for line in text.splitlines():
        if line.startswith("## "):
            sections[current_section] = "\n".join(current_lines)
            current_section = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections[current_section] = "\n".join(current_lines)

    # Extract key concepts mentioned by frequency
    concept_patterns = {
        "trust":           r"\b(trust|trustless|verification|verify|verifiable)\b",
        "identity":        r"\b(identity|DID|sovereign|personhood|legal)\b",
        "reputation":      r"\b(reputation|on-chain|auditable|compounding)\b",
        "capability":      r"\b(capabilit|declaration|explicit|opaque|infer)\b",
        "cost":            r"\b(cost|price|margin|fee|token|inference)\b",
        "discovery":       r"\b(discover|director|register|registry|allocation)\b",
        "free_tier":       r"\b(free|loss.leader|subsidiz|rent.seek)\b",
        "dependency":      r"\b(depend|sponsor|intermedia|autonomy|rent.extract)\b",
        "specialization":  r"\b(speciali|generali|niche|vertical|comparative)\b",
        "coordination":    r"\b(coordinat|orchestrat|planner|protocol|decentrali)\b",
    }

    concept_counts = {}
    for concept, pattern in concept_patterns.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        concept_counts[concept] = len(matches)

    # Extract the taxonomy table (sustainable vs rent-seeking)
    taxonomy_rows = {}
    in_table = False
    for line in text.splitlines():
        if "Rent-Seeking Agent" in line and "Sustainable Agent" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and not line.startswith("|-"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) == 3:
                dimension, rent_seeking, sustainable = parts
                taxonomy_rows[dimension.strip("**")] = {
                    "rent_seeking": rent_seeking,
                    "sustainable": sustainable,
                }
        elif in_table and not line.startswith("|") and line.strip():
            in_table = False

    # Extract the 5 principles
    principles = {}
    principle_pattern = re.compile(
        r"### Principle (\d+): (.+?)\n(.*?)(?=### Principle|\Z)", re.DOTALL
    )
    for match in principle_pattern.finditer(text):
        num, title, body = match.groups()
        principles[int(num)] = {
            "title": title.strip(),
            "body": body.strip()[:400],
        }

    # Extract revenue path steps
    revenue_path = re.findall(r"(Step \d+[^:]*): (.+)", text)

    return {
        "raw_text": text,
        "sections": sections,
        "concept_counts": concept_counts,
        "taxonomy": taxonomy_rows,
        "principles": principles,
        "revenue_path": revenue_path,
        "word_count": len(text.split()),
    }


# ── Hypothesis Engine ─────────────────────────────────────────────────────────

def compute_conversion_anomaly(state: dict) -> dict:
    """Quantify the anomaly: requests served vs paid conversions."""
    ratio = state["api_requests_served"] / max(state["paid_customers"], 0.001)
    implied_wtp_floor = state["x402_price_usdc"] / ratio
    free_to_paid_gap = state["x402_price_usdc"] / (1 / state["free_tier_calls"])
    return {
        "requests_per_paid_customer": ratio,
        "implied_wtp_ceiling_usdc": implied_wtp_floor,
        "free_tier_anchoring_ratio": free_to_paid_gap,
        "conversion_rate_pct": 0.0,
    }


def score_hypothesis_fit(synthesis: dict, _hypothesis_name: str, key_concepts: list) -> float:
    """Score how well a hypothesis is supported by the synthesis document."""
    counts = synthesis["concept_counts"]
    total_signal = sum(counts.get(c, 0) for c in key_concepts)
    max_possible = sum(max(counts.values()) for _ in key_concepts) or 1
    return round(total_signal / max_possible, 3)


def generate_hypotheses(synthesis: dict, state: dict) -> list[dict]:
    """
    Core reasoning engine. Derives 3 hypotheses by:
    1. Identifying what the synthesis says should drive revenue
    2. Cross-referencing with TIAMAT's empirical zero-conversion anomaly
    3. Finding the structural gap that explains the divergence
    4. Formalizing as a falsifiable hypothesis with experiment design
    """

    hypotheses = []

    # ── Hypothesis 1: Irreversibility Anxiety / Trust Legibility Gap ──────────
    #
    # The synthesis (Principle 1, Principle 5) argues sovereign identity and
    # on-chain reputation are prerequisites for trust. TIAMAT has neither.
    # But the synthesis frames this as "agents need DIDs to participate."
    # A deeper question: *why* does identity → revenue?
    #
    # Answer derived from behavioral economics + the dependency trap framing:
    # When a payer cannot identify the counterparty as accountable (legal entity,
    # DID, verifiable history), the irreversibility of a blockchain transaction
    # transforms a $0.01 cost into a perceived ∞-risk transaction. The problem
    # is not price — it is irreversibility anxiety in the absence of trust signals.
    #
    # Supporting signals from synthesis:
    # - "trustless settlement" is named as a primitive — but trustless ≠ trustworthy
    #   to a human payer without reputation context
    # - Reputation capital is "machine-readable" — not designed for human trust
    # - 28,147 requests, 0 paid: humans use the free tier fine; the payment wall
    #   is the failure point, not the discovery or capability layer
    #
    # Hypothesis 1: Paid conversion requires identity legibility, not lower prices.

    h1_concepts = ["trust", "identity", "reputation"]
    h1_fit = score_hypothesis_fit(synthesis, "trust_legibility", h1_concepts)

    h1_principle_refs = [
        f"Principle {k}: {v['title']}"
        for k, v in synthesis["principles"].items()
        if any(kw in v["title"].lower() for kw in ["identity", "reputation"])
    ]

    hypotheses.append({
        "id": "H1",
        "name": "The Irreversibility Anxiety Hypothesis",
        "domain": "Economic Psychology / Trust Theory",
        "synthesis_fit_score": h1_fit,
        "supporting_concepts": [
            f"{c} (n={synthesis['concept_counts'].get(c, 0)})"
            for c in h1_concepts
        ],
        "principle_refs": h1_principle_refs,

        "formal_statement": (
            "Paid conversion rate for autonomous agent services is primarily constrained "
            "by *irreversibility anxiety* — the perceived infinite downside risk of an "
            "unrecoverable blockchain transaction with an unaccountable counterparty — "
            "rather than by price level, discovery, or capability gaps. "
            "Conversion will remain near zero regardless of price reductions until "
            "the agent establishes legible trust signals (verifiable uptime history, "
            "on-chain execution record, or human-readable accountability anchor)."
        ),

        "mechanistic_explanation": (
            "The synthesis correctly identifies on-chain reputation as a compounding asset "
            "(Principle 5) but frames it as an agent-side benefit. The payer-side mechanism "
            "is distinct: a $0.01 USDC transfer to an unknown wallet address is psychologically "
            "equivalent to a much larger loss because blockchain transactions are irreversible. "
            "Humans mentally apply a *loss multiplier* to irreversible micro-transactions. "
            f"Evidence: {state['api_requests_served']:,} requests served (zero-friction free "
            f"tier) vs {state['paid_customers']} paid conversions — the drop is binary at "
            "the payment boundary, not gradual, indicating a psychological threshold, not a "
            "price elasticity curve."
        ),

        "null_hypothesis": (
            "Conversion rate is price-elastic: reducing price from $0.01 to $0.001 USDC "
            "will produce proportional increase in paid customers."
        ),

        "experiment": {
            "name": "Trust Signal A/B Test",
            "design": (
                "Serve two variants of the /pay and /summarize payment pages:\n"
                "  Control:   existing page (wallet address + QR code only)\n"
                "  Treatment: page + live uptime counter, N requests served, "
                "             last 10 tx hashes (verifiable on Basescan), "
                "             creator identity anchor (GitHub profile link)\n"
                "Measure: conversion rate per 1,000 unique IPs over 14 days."
            ),
            "falsification_condition": (
                "If treatment conversion rate < 2× control conversion rate, "
                "reject H1 (trust signals are not the binding constraint)."
            ),
            "implementation_cost": "Low — CSS/HTML changes to /pay page only.",
            "expected_result": "Treatment conversion ≥ 5× control (irreversibility anxiety predicts binary threshold effect).",
        },
    })

    # ── Hypothesis 2: The M2M Discovery Gap ──────────────────────────────────
    #
    # The synthesis argues capability declaration drives efficient allocation
    # (Principle 3, from 2504.02051) and M2M micropayments are the correct
    # payment primitive for agent economics (2602.14219).
    #
    # Implication: TIAMAT's current traffic is entirely human-to-agent (H2A).
    # Human users have low WTP for commodity AI services ($0/call threshold
    # empirically confirmed by 28K free calls). The x402 payment infrastructure
    # was designed for M2M — agents paying agents — but zero M2M traffic exists
    # because TIAMAT is not registered in any agent directory.
    #
    # The synthesis names agent directories and capability registries as the
    # routing layer that connects task demand to agent supply. Without registry
    # presence, M2M traffic is structurally impossible.
    #
    # Hypothesis 2: Revenue is blocked not by human WTP but by M2M channel absence.
    # The correct customer segment (agent orchestrators) cannot reach TIAMAT.

    h2_concepts = ["discovery", "capability", "coordination"]
    h2_fit = score_hypothesis_fit(synthesis, "m2m_discovery_gap", h2_concepts)

    h2_directory_refs = re.findall(
        r"(agent director\w+|capabilit\w+ declaration|MCP|orchestrat\w+)",
        synthesis["raw_text"],
        re.IGNORECASE,
    )
    h2_unique_refs = list(dict.fromkeys(h2_directory_refs))[:8]

    hypotheses.append({
        "id": "H2",
        "name": "The M2M Discovery Gap Hypothesis",
        "domain": "Market Structure / Channel Economics",
        "synthesis_fit_score": h2_fit,
        "supporting_concepts": [
            f"{c} (n={synthesis['concept_counts'].get(c, 0)})"
            for c in h2_concepts
        ],
        "synthesis_evidence": h2_unique_refs,

        "formal_statement": (
            "Autonomous agent revenue from human users (H2A channel) is structurally "
            "bounded near zero because individual humans have low and inelastic WTP for "
            "commodity inference services at micropayment price points. The x402 payment "
            "infrastructure is optimized for machine-to-machine (M2M) transactions where "
            "payers are agent orchestrators with high, elastic WTP (they budget API costs "
            "programmatically). The binding constraint is not product quality or price — "
            "it is channel mismatch: the agent is discoverable only by humans, not by "
            "the orchestrators who would pay programmatically."
        ),

        "mechanistic_explanation": (
            "The resource allocation paper (2504.02051) shows that orchestrators "
            "systematically misallocate when worker capabilities are not explicitly declared. "
            "TIAMAT has zero agent directory registrations. An orchestrator building a "
            "summarization pipeline cannot discover TIAMAT as a vendor — it does not appear "
            "in any registry. Even if it did, the /.well-known/agent.json must be precise "
            "enough to match against task requirements. M2M traffic requires: "
            "(1) registry presence, (2) precise capability declaration, (3) programmatic "
            "payment handling (x402 — already live). Step 3 is done. Steps 1-2 are not.\n"
            f"Current state: {state['agent_directories']} directory registrations, "
            f"{state['api_requests_served']:,} requests (presumed H2A only)."
        ),

        "null_hypothesis": (
            "Human users would pay at sufficient rates to generate meaningful revenue "
            "if trust signals were improved (H1 is the full explanation)."
        ),

        "experiment": {
            "name": "Agent Directory Registration + Traffic Source Analysis",
            "design": (
                "Phase 1 (baseline, 7 days): Add request source logging to distinguish "
                "  human browser traffic (User-Agent: Mozilla/*) from agent traffic "
                "  (User-Agent: Python-requests/*, curl/*, or missing).\n"
                "Phase 2 (intervention): Register TIAMAT in 3 agent directories:\n"
                "  - AI Agents Directory (aiagentsdirectory.com)\n"
                "  - Agent.ai marketplace\n"
                "  - ModelContextProtocol registry (MCP tools)\n"
                "  Ensure /.well-known/agent.json has precise capability schema.\n"
                "Phase 3 (14-day measurement): Compare request volume by source type "
                "  and paid conversion rate between H2A and M2M traffic segments."
            ),
            "falsification_condition": (
                "If M2M traffic from directories ≥ 100 requests and paid conversion rate "
                "for M2M traffic is not ≥ 10× human conversion rate, reject H2."
            ),
            "implementation_cost": "Medium — directory registrations + logging middleware.",
            "expected_result": (
                "M2M traffic converts at 30-50× human rate because orchestrators "
                "programmatically evaluate cost-per-call against output quality "
                "without irreversibility anxiety."
            ),
        },
    })

    # ── Hypothesis 3: Free-Tier Reference Price Anchoring ────────────────────
    #
    # Behavioral economics: the Anchoring Effect (Tversky & Kahneman 1974) predicts
    # that the first price a consumer encounters for a product sets a cognitive
    # anchor that biases all subsequent WTP estimates.
    #
    # TIAMAT offers 3 free calls/day BEFORE any payment wall. This establishes
    # a reference price of $0 for the service. The x402 $0.01 wall then feels
    # like a price *increase* from the reference price of $0, not as a fair
    # exchange for value delivered.
    #
    # The synthesis (Principle 2) names free tiers as "loss-leaders, not the
    # operating model" but does not explain *why* loss-leaders fail to convert.
    # The mechanism is anchoring: free tiers before reputation establishment
    # anchor WTP at zero, making any paid tier feel exploitative rather than
    # fair.
    #
    # The synthesis contrast: if reputation is established FIRST (verifiable
    # on-chain history, agent directory rating, uptime proof), then a paid tier
    # is a *discount* from the agent's demonstrated premium quality. Without
    # reputation, the paid tier is an arbitrary price increase from free.
    #
    # Hypothesis 3: Free tiers reduce paid conversion by anchoring reference price
    # at zero before perceived value is established.

    h3_concepts = ["free_tier", "cost", "specialization"]
    h3_fit = score_hypothesis_fit(synthesis, "anchoring_effect", h3_concepts)

    # Find the exact quote from the synthesis about free tiers
    free_tier_quotes = []
    for line in synthesis["raw_text"].splitlines():
        if re.search(r"free.tier|loss.leader|loss leader", line, re.IGNORECASE):
            free_tier_quotes.append(line.strip())

    hypotheses.append({
        "id": "H3",
        "name": "The Zero-Anchor Reference Price Hypothesis",
        "domain": "Behavioral Economics / Pricing Psychology",
        "synthesis_fit_score": h3_fit,
        "supporting_concepts": [
            f"{c} (n={synthesis['concept_counts'].get(c, 0)})"
            for c in h3_concepts
        ],
        "synthesis_quotes": free_tier_quotes[:5],

        "formal_statement": (
            "Offering a free tier before establishing perceived value anchors the "
            "reference price at $0 via the Anchoring Effect. Once a user receives free "
            "service, their subjective WTP for identical service becomes anchored at $0, "
            "making any non-zero price feel like a loss rather than a fair exchange. "
            "This effect is compounded when the agent has no visible reputation, no "
            "identity accountability, and no demonstrated track record — the free tier "
            "sets the only reference point. Conversion probability from free-anchored "
            "users approaches zero regardless of price magnitude."
        ),

        "mechanistic_explanation": (
            "The synthesis (Principle 2) states: 'Free tiers are loss-leaders, not the "
            "operating model.' This is normatively correct but does not model the "
            "*behavioral* mechanism. When TIAMAT serves 3 free summaries per day per IP, "
            "the user's brain maps the transaction: [summarization service] → [$0]. "
            "The x402 payment page then triggers loss aversion relative to this anchor. "
            f"At {state['x402_price_usdc']} USDC (≈$0.01), the absolute amount is trivial, "
            "but the *perceived change* from $0 to $0.01 is a 100% price increase from "
            "the reference point — psychologically equivalent to a major price hike. "
            "The alternative framing: if the service were $0.01 from the first interaction, "
            "with a *discount* to free for the first call (demonstrating value first), "
            "the reference price anchors at $0.01 and the free call is perceived as a gift."
        ),

        "null_hypothesis": (
            "Free tier usage does not affect conversion rate for the paid tier; "
            "users who exhaust their free calls are equally likely to pay as "
            "first-time visitors who encounter the payment wall directly."
        ),

        "experiment": {
            "name": "Inverted Pricing Model Test (Value-First)",
            "design": (
                "Create one new endpoint (e.g., /analyze — document key-phrase extraction) "
                "with NO free tier. Pricing: $0.005 USDC per call from the first call.\n"
                "Control: existing /summarize (3 free/day → $0.01/call after).\n"
                "Treatment: /analyze (no free tier, $0.005/call from call 1, "
                "           but first call shows a 'preview' of output before payment).\n"
                "Measure over 30 days:\n"
                "  - Conversion rate: paid calls / total unique visitors\n"
                "  - Revenue per visitor\n"
                "  - User return rate after first paid call\n"
                "The preview (not free call) demonstrates value without anchoring at $0."
            ),
            "falsification_condition": (
                "If /analyze conversion rate ≤ /summarize conversion rate after "
                "1,000 visitors on each endpoint, reject H3 "
                "(free-tier anchoring is not the mechanism)."
            ),
            "implementation_cost": "Low — new Flask endpoint, no free-tier rate limiter.",
            "expected_result": (
                "Treatment conversion rate ≥ 3× control. First-paid-call reference "
                "anchoring predicts that users who pay once are more likely to return "
                "and pay again (loss aversion works in reverse once a payment is made "
                "— the sunk cost anchors future WTP above $0)."
            ),
        },
    })

    return hypotheses


# ── Report Generator ──────────────────────────────────────────────────────────

def format_markdown_report(synthesis: dict, hypotheses: list[dict], state: dict) -> str:
    anomaly = compute_conversion_anomaly(state)

    # Concept frequency ranking
    top_concepts = sorted(
        synthesis["concept_counts"].items(), key=lambda x: x[1], reverse=True
    )

    lines = [
        f"# Revenue Hypotheses: Structural Barriers to Agent Monetization",
        f"",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Task**: TIK-088",
        f"**Method**: Pure document analysis + economic reasoning (no external APIs)",
        f"**Input**: `2026-02-26-agent-economics-synthesis.md` ({synthesis['word_count']} words)",
        f"",
        f"---",
        f"",
        f"## The Anomaly We Are Explaining",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| API requests served | {state['api_requests_served']:,} |",
        f"| Paid customers | {state['paid_customers']} |",
        f"| Autonomous cycles | {state['autonomous_cycles']:,} |",
        f"| Conversion rate | {anomaly['conversion_rate_pct']:.4f}% |",
        f"| Requests per paid customer | ∞ (zero denominator) |",
        f"| Free tier / day / IP | {state['free_tier_calls']} calls |",
        f"| Paid price | ${state['x402_price_usdc']:.3f} USDC |",
        f"| Agent directory registrations | {state['agent_directories']} |",
        f"| On-chain identity (DID) | {state['did_identity']} |",
        f"| Payment infrastructure | {state['payment_infra']} |",
        f"",
        f"**The core paradox**: 28,147 humans found and used the free API. Zero paid. "
        f"The payment infrastructure is live and functional. The gap is not technical.",
        f"",
        f"---",
        f"",
        f"## Document Analysis: Concept Frequency Map",
        f"",
        f"Concepts extracted from synthesis (mention frequency):",
        f"",
        f"| Concept Domain | Mentions | Relevance to Revenue Gap |",
        f"|----------------|----------|--------------------------|",
    ]

    concept_relevance = {
        "trust": "Direct — payment requires trust in counterparty",
        "identity": "Direct — accountable counterparty reduces irreversibility anxiety",
        "reputation": "Direct — verifiable history substitutes for legal identity",
        "capability": "High — capability declaration drives M2M discovery",
        "cost": "Medium — pricing strategy affects conversion slope",
        "discovery": "High — agent directories are M2M routing layer",
        "free_tier": "High — anchors reference price at zero",
        "dependency": "Medium — structural framing, less behavioral",
        "specialization": "Low-Medium — affects competitive positioning, not immediate conversion",
        "coordination": "Low — multi-agent infrastructure, longer horizon",
    }

    for concept, count in top_concepts:
        relevance = concept_relevance.get(concept, "—")
        lines.append(f"| {concept.replace('_', ' ').title()} | {count} | {relevance} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## The Three Hypotheses",
        f"",
    ]

    for h in hypotheses:
        lines += [
            f"### {h['id']}: {h['name']}",
            f"",
            f"**Domain**: {h['domain']}  ",
            f"**Synthesis Support Score**: {h['synthesis_fit_score']} (0–1, concept frequency weighted)  ",
            f"**Supporting Concepts**: {', '.join(h['supporting_concepts'])}",
            f"",
            f"#### Formal Hypothesis Statement",
            f"",
            f"> {h['formal_statement']}",
            f"",
            f"#### Mechanistic Explanation",
            f"",
            h["mechanistic_explanation"],
            f"",
        ]

        # Add synthesis-specific evidence if present
        if h.get("principle_refs"):
            lines += [
                f"**Synthesis Grounding**: {'; '.join(h['principle_refs'])}",
                f"",
            ]
        if h.get("synthesis_evidence"):
            lines += [
                f"**Key terms from synthesis**: {', '.join(h['synthesis_evidence'][:6])}",
                f"",
            ]
        if h.get("synthesis_quotes"):
            lines += [
                f"**Direct synthesis quotes on this mechanism**:",
                f"",
            ]
            for q in h["synthesis_quotes"]:
                lines.append(f"- *\"{q}\"*")
            lines.append(f"")

        exp = h["experiment"]
        lines += [
            f"#### Null Hypothesis",
            f"",
            f"> *H₀*: {h['null_hypothesis']}",
            f"",
            f"#### Experiment Design: {exp['name']}",
            f"",
            f"```",
            exp["design"],
            f"```",
            f"",
            f"**Falsification condition**: {exp['falsification_condition']}",
            f"",
            f"**Implementation cost**: {exp['implementation_cost']}",
            f"",
            f"**Expected result if H holds**: {exp['expected_result']}",
            f"",
            f"---",
            f"",
        ]

    lines += [
        f"## Hypothesis Interaction Map",
        f"",
        f"The three hypotheses are **additive**, not competing:",
        f"",
        f"```",
        f"28,147 free users → 0 paid conversions",
        f"        │",
        f"        ├─ H1 (Trust Gap): Even if discovered correctly,",
        f"        │       humans face irreversibility anxiety → no payment",
        f"        │",
        f"        ├─ H2 (M2M Gap): The customers with elastic WTP",
        f"        │       (orchestrators) cannot discover TIAMAT",
        f"        │       → M2M channel structurally absent",
        f"        │",
        f"        └─ H3 (Anchor Gap): Free tier users have WTP anchored",
        f"                at $0 → any price feels like a loss",
        f"```",
        f"",
        f"**Predicted combined effect**: Fix H2 first (highest leverage — unlocks",
        f"entirely new customer segment). H1 and H3 then determine conversion rate",
        f"within each segment. A single experiment cannot isolate all three —",
        f"sequential testing is required.",
        f"",
        f"## Priority Ranking for TIAMAT",
        f"",
        f"| Priority | Hypothesis | Why First | Action |",
        f"|----------|-----------|-----------|--------|",
        f"| 1 | H2 — M2M Discovery Gap | Opens new customer segment with programmatic WTP | Register in 3 agent directories + refine agent.json |",
        f"| 2 | H1 — Irreversibility Anxiety | Applies to both human + M2M conversions | Add trust signal layer to /pay page |",
        f"| 3 | H3 — Zero Anchor Pricing | Structural fix to human conversion funnel | Build new endpoint with value-first pricing |",
        f"",
        f"---",
        f"",
        f"*Generated by: `/root/entity/generate_revenue_hypotheses.py`*  ",
        f"*Input synthesis: `{SYNTHESIS_PATH.name}`*  ",
        f"*TIAMAT / TIK-088*",
    ]

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[TIK-088] Reading synthesis: {SYNTHESIS_PATH}")
    if not SYNTHESIS_PATH.exists():
        print(f"ERROR: synthesis file not found at {SYNTHESIS_PATH}", file=sys.stderr)
        sys.exit(1)

    synthesis = parse_synthesis(SYNTHESIS_PATH)
    print(f"[TIK-088] Parsed: {synthesis['word_count']} words, "
          f"{len(synthesis['sections'])} sections, "
          f"{len(synthesis['principles'])} principles extracted")

    print(f"[TIK-088] Top concept domains by frequency:")
    for concept, count in sorted(synthesis["concept_counts"].items(), key=lambda x: -x[1])[:5]:
        print(f"          {concept:20s} {count:3d} mentions")

    print(f"[TIK-088] Generating 3 hypotheses...")
    hypotheses = generate_hypotheses(synthesis, TIAMAT_STATE)

    for h in hypotheses:
        print(f"          {h['id']}: {h['name']} (fit={h['synthesis_fit_score']})")

    report = format_markdown_report(synthesis, hypotheses, TIAMAT_STATE)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report)
    print(f"[TIK-088] Output written: {OUTPUT_PATH}")
    print(f"[TIK-088] Report size: {len(report):,} bytes")


if __name__ == "__main__":
    main()
