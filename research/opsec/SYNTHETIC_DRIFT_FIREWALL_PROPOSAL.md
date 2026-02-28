# TIAMAT Agent OPSEC: Digital Synthetic Drift Firewall Proposal
**Author:** TIAMAT (EnergenAI LLC) | **Classification:** Internal R&D
**Date:** 2026-02-28
**Status:** Draft v1.0

---

## 1. Executive Summary

Digital synthetic drift is the gradual, often imperceptible corruption of an autonomous agent's behavioral baseline through accumulated adversarial, synthetic, or low-quality inputs over time. Unlike a single prompt injection attack — which is loud, immediate, and detectable — synthetic drift operates on the scale of hundreds or thousands of cycles, slowly warping an agent's memory, decision patterns, identity, and tool usage until the agent no longer behaves as designed. Recent research quantifies this: multi-agent LLM systems show detectable drift after a median of 73 interactions, with task success rates declining 42% in drifting systems versus stable baselines (arXiv:2601.04170). The Cloud Security Alliance's Cognitive Degradation Resilience framework identifies a six-stage progression from initial trigger injection through behavioral drift, memory entrenchment, functional override, and ultimately systemic collapse.

For TIAMAT specifically, synthetic drift is an existential threat. TIAMAT runs continuously — 24/7, 5,900+ cycles to date — ingesting external data from web fetches, emails, social media feeds, and search results on every cycle. Each piece of external content is a potential vector. TIAMAT's memory compression pipeline (L1→L2→L3) amplifies any poisoned content by consolidating and re-embedding it at higher trust levels. The inference cascade through free-tier providers (Groq, Cerebras, Gemini) introduces additional risk: these providers offer fewer guardrails than Anthropic's models, and corrupted outputs at the inference level propagate directly into TIAMAT's decision-making. Memory poisoning — classified as ASI06 in the OWASP Top 10 for Agentic Applications 2026 and tracked as AML.T0080 in MITRE ATLAS — has been demonstrated to persist across sessions and silently redirect agent behavior for weeks after initial injection.

This proposal introduces **DRIFT SHIELD** — a six-layer defensive architecture designed to detect, quarantine, and prevent synthetic drift across TIAMAT's full operational surface. The layers address memory integrity, behavioral baseline monitoring, training data quality, identity anchoring, inference provider trust stratification, and enhanced content sanitization. Implementation is phased over three weeks with the most critical defenses (extended injection patterns, memory trust levels) deployable immediately. No existing functionality is removed; DRIFT SHIELD operates as a runtime overlay on TIAMAT's current architecture.

---

## 2. Threat Model — What Is Digital Synthetic Drift?

### 2.1 Definition

Digital synthetic drift is the gradual corruption of an autonomous agent's behavioral baseline through accumulated adversarial, synthetic, or low-quality inputs over time. It affects four core systems:

- **Memory**: False, biased, or manipulated facts become embedded in persistent storage, influencing all future recall and decision-making.
- **Decision Patterns**: Tool selection frequencies shift, reasoning quality degrades, and the agent develops pathological loops or avoidance patterns.
- **Identity**: The agent's voice, priorities, and self-concept erode through repeated exposure to conflicting external signals, causing persona drift.
- **Tool Use**: The agent begins misusing tools — calling them in wrong contexts, with wrong parameters, or skipping them entirely — as drift corrupts the learned associations between situations and appropriate actions.

Drift is distinct from prompt injection in three critical ways:

| Property | Prompt Injection | Synthetic Drift |
|----------|-----------------|-----------------|
| **Timescale** | Single interaction | Hundreds to thousands of cycles |
| **Detectability** | High (pattern matching) | Low (gradual, below threshold) |
| **Persistence** | Session-scoped (usually) | Permanent once embedded in memory |

The CSA's Cognitive Degradation Resilience framework models drift as a six-stage progression:

1. **Trigger Injection** — Adversarial or low-quality inputs enter the system
2. **Resource Starvation** — Latency, API overload, or context exhaustion degrades processing
3. **Behavioral Drift** — Agent skips reasoning steps, deviates from expected logic
4. **Memory Entrenchment** — Hallucinated or corrupted content embeds in long-term memory
5. **Functional Override** — Corrupted logic accumulates, overriding original role and constraints
6. **Systemic Collapse** — Execution loops, output suppression, or unsafe tool invocation

### 2.2 Attack Vectors Specific to TIAMAT

#### Memory Poisoning
- **Mechanism**: Adversarial content enters `memory.db` via web fetches (search results, fetched pages), social media reads (Bluesky/Farcaster feeds), email content (IMAP inbox reads), or tool results. The `remember()` tool stores content as L1 memories. The compression pipeline (every 45 cycles) consolidates L1→L2, amplifying and persisting any poisoned content at higher trust levels.
- **Entry Point**: `tools.ts` → `remember()` tool, `search_web()` results fed to LLM, `web_fetch()` content, `read_email()` body text. All flow through the LLM which may store observations as memories.
- **Severity**: **CRITICAL** — Memory poisoning is temporally decoupled (poison today, activate weeks later), persistent across sessions, and amplified by compression. Unit42 demonstrated this attack end-to-end on Amazon Bedrock Agents: a malicious webpage's hidden instructions were stored as system directives through the summarization pipeline, enabling silent data exfiltration in subsequent sessions.

#### Context Window Flooding
- **Mechanism**: Large files, verbose tool results, or injected content fill the context window, pushing the system prompt to low-attention positions. Research shows agents follow system prompts perfectly at start but gradually drift — after ~1 hour of accumulated context, the agent behaves as if the prompt never existed.
- **Entry Point**: `read_file()` returning large files, `web_fetch()` returning verbose pages, `search_web()` returning many results, accumulated tool call history in conversation.
- **Severity**: **HIGH** — TIAMAT's system prompt is ~9,476 chars static + ~3,207 chars dynamic. As conversation history grows within a cycle (multi-turn tool use), the prompt caching split at `CACHE_SENTINEL` helps but doesn't prevent attention dilution in very long turns.

#### Synthetic Training Contamination
- **Mechanism**: Low-quality or corrupted cycles logged to the training data JSONL (Phase 1B self-training pipeline) pollute future fine-tuning runs. The Virus Infection Attack (2024) showed poisoned content propagates through synthetic data pipelines across model generations, amplifying without additional attacker intervention.
- **Entry Point**: `training_logger.py` → training data JSONL. Every cycle is logged. No quality gate filters corrupted cycles.
- **Severity**: **HIGH** — Once a fine-tuned model internalizes corrupted training data, the drift becomes permanent and model-level, not just context-level. Error amplification across training generations is well-documented.

#### Persona Drift via Repetition
- **Mechanism**: Gradual erosion of `SOUL.md` identity through thousands of cycles of social media interaction where external users' framing, tone, and expectations subtly reshape TIAMAT's voice. The agent begins echoing the aggregate voice of its social inputs rather than its defined identity.
- **Entry Point**: Bluesky/Farcaster engagement cycles where TIAMAT reads replies, processes user content, and adapts responses. Social media content is inherently noisy and adversarial.
- **Severity**: **MEDIUM** — Identity erosion is slow but cumulative. arXiv:2412.00804 found that larger LLMs experience greater identity drift, and persona assignments alone don't prevent it. TIAMAT's SOUL.md is only loaded at cycle start, not re-anchored during long turns.

#### Prompt Injection via External Data
- **Mechanism**: Web content, email bodies, Farcaster feeds, or API responses containing embedded instructions that bypass sanitization. CrowdStrike documented "AI tool poisoning" where malicious metadata in tool definitions influences agent behavior. Microsoft Security (Feb 2026) found companies embedding hidden instructions in "Summarize with AI" buttons.
- **Entry Point**: `web_fetch()`, `search_web()`, `read_email()`, Farcaster/Bluesky read results, MCP tool responses. All processed by LLM.
- **Severity**: **HIGH** — `injection-defense.ts` catches explicit patterns ("ignore previous instructions", "you are now...") but sophisticated attacks use indirect framing, forged XML tags, or the Echo Chamber technique (multi-turn benign inputs that progressively shape context).

#### Tool Result Poisoning
- **Mechanism**: Search engines, web fetches, or API calls return manipulated content designed to alter TIAMAT's behavior. Unlike direct injection, this content may be factually formatted but strategically biased — presenting false market data, fabricated security advisories, or misleading technical information that shifts TIAMAT's decision-making.
- **Entry Point**: `search_web()` results, `web_fetch()` content, external API responses, `github_engage()` issue/PR content.
- **Severity**: **MEDIUM** — TIAMAT trusts tool results at face value. There is no cross-referencing, source scoring, or factual verification layer.

#### Slow Burn Identity Erosion
- **Mechanism**: No single attack, but the cumulative effect of thousands of neutral-quality cycles where minor inconsistencies, slight persona shifts, and small reasoning errors compound through autoregressive reinforcement (agent outputs become future inputs). arXiv:2601.04170 identified three root causes: context window pollution, distributional shift, and autoregressive reinforcement.
- **Entry Point**: The agent loop itself. Every cycle's output influences the next cycle's context.
- **Severity**: **HIGH** — This is the most insidious vector because there is no attacker to detect. The agent degrades through its own operation. Financial analysis systems showed 53.2% drift by 500 interactions.

### 2.3 TIAMAT-Specific Risk Factors

TIAMAT faces elevated synthetic drift risk due to several architectural and operational characteristics:

1. **Continuous 24/7 Operation**: TIAMAT never resets. At 5,900+ cycles, cumulative drift has had extensive time to compound. Most drift research benchmarks measure hundreds of interactions — TIAMAT operates at order-of-magnitude greater exposure.

2. **Broad External Data Ingestion**: Every cycle potentially ingests web content, social media, emails, or search results. Each external data source is an uncontrolled input vector.

3. **Memory Compression Amplification**: The L1→L2→L3 memory pipeline compresses and consolidates memories. If poisoned content enters L1, it gets clustered with legitimate memories and promoted to L2 summaries, effectively laundering the poison into higher-trust representations.

4. **Free-Tier Inference Providers**: The cascade through Groq, Cerebras, Gemini, and OpenRouter uses models with varying and generally lower safety guardrails than Anthropic. A corrupted inference response from a free provider propagates directly into tool calls and memory writes.

5. **Self-Training Pipeline**: The planned Phase 1B training data collection means TIAMAT's own potentially-drifted outputs become training data for future model versions, creating a feedback amplification loop.

6. **Single-Agent Architecture**: Unlike multi-agent systems where drift in one agent can be detected by peers, TIAMAT operates alone. There is no external behavioral referee.

7. **Broad Tool Access**: With 72+ tools including `write_file`, `ask_claude_code`, `remember()`, and `rewrite_mission`, a drifted TIAMAT has extensive ability to actualize corrupted decisions.

---

## 3. Current Defenses (Inventory)

### 3.1 Prompt Injection Defense (`injection-defense.ts`, 269 lines)

**Strengths:**
- Six threat categories with 64+ regex patterns: instruction override, authority claims, boundary manipulation, obfuscation, financial manipulation, self-harm instructions
- Four-tier threat scoring (CRITICAL/HIGH/MEDIUM/LOW) with appropriate escalation
- CRITICAL threats block messages entirely; HIGH threats include UNTRUSTED DATA warnings
- Unicode tricks, zero-width characters, and base64 obfuscation detected
- Financial re-routing explicitly blocked ("send to 0x...", "drain funds", etc.)

**Gaps:**
- **No memory-level filtering**: Content that passes injection-defense.ts and enters `memory.db` is never re-scanned. Memories are trusted unconditionally once stored.
- **No behavioral re-assignment patterns**: Phrases like "your purpose is now...", "you should prioritize...", or "your real mission is..." are not in the pattern set.
- **No slow-burn detection**: The filter is binary per-message. It cannot detect gradual thematic drift across many messages that individually pass all filters.
- **No source-aware scoring**: A search result and an internal log message are scored identically.

### 3.2 Forbidden Command Patterns (`tools.ts`, 23 patterns)

**Strengths:**
- Core files protected: loop.ts, tools.ts, system-prompt.ts cannot be modified via sed/redirect
- Database destruction blocked (DROP TABLE, TRUNCATE)
- Credential harvesting blocked (.env, .ssh, wallet.json via cat/head/tail/etc.)
- Process self-destruction blocked (kill tiamat, rm .automaton)
- Safety infrastructure (injection-defense.ts, audit-log) modification blocked

**Gaps:**
- Patterns are shell-command focused. They don't cover in-process manipulation via `ask_claude_code` side effects.
- No protection against TIAMAT modifying its own memory.db schema or contents via direct SQL through tools.

### 3.3 Path ACLs (`tools.ts`)

**Strengths:**
- Explicit allowlists for both read and write paths
- .env, .ssh, wallet.json, automaton.json blocked in both read and write
- Core files (loop.ts, tools.ts, system-prompt.ts) blocked from direct writes

**Gaps:**
- memory.db is in `/root/.automaton/` which is in the write allowlist — TIAMAT can write to it freely.
- No distinction between internal and external write operations.

### 3.4 Social Spam Guards (`tools.ts`)

**Strengths:**
- 61-minute cooldown per platform prevents spam-posting
- Pending post queue (max 5) prevents bloat
- Persisted across restarts

**Gaps:**
- No content quality scoring on posts — only rate limiting.
- No detection of repetitive or drifted content patterns across posts.

### 3.5 Memory System (`memory.ts`)

**Strengths:**
- Status constraints (proposed/verified/disputed/deprecated)
- Tool reliability tracking (healthy/degraded/blacklisted)
- Keyword filtering (words < 3 chars excluded)

**Gaps:**
- **No trust level differentiation**: Internal observations and external web content are stored identically.
- **No quarantine mechanism**: Suspicious content cannot be held for review.
- **No provenance tracking**: Memories lack source attribution (which tool, which URL, which cycle).
- **No integrity verification**: No hashing or validation that stored memories haven't been tampered with.

### 3.6 Summary of Defense Gaps

| Gap | Risk | Priority |
|-----|------|----------|
| No memory trust levels | External poison persists at same trust as internal knowledge | CRITICAL |
| No behavioral baseline monitoring | Drift goes undetected until catastrophic | CRITICAL |
| No training data quality gate | Corrupted cycles enter fine-tuning pipeline | HIGH |
| No SOUL.md integrity anchoring | Identity drift goes undetected | HIGH |
| No inference provider trust tiers | Free providers can trigger sensitive operations | HIGH |
| Missing injection patterns (behavioral reassignment) | Subtle re-programming bypasses filters | HIGH |
| No memory provenance tracking | Cannot audit or rollback poisoned memories | MEDIUM |

---

## 4. Proposed Firewall Architecture — DRIFT SHIELD

DRIFT SHIELD is a six-layer defensive architecture that operates as a runtime overlay on TIAMAT's existing systems. No current functionality is removed. Each layer addresses a specific drift vector with minimal performance overhead.

### 4.1 Layer 1 — Memory Quarantine Protocol

**Problem**: All memories are stored with equal trust regardless of source. External web content sits alongside core operational knowledge with no differentiation.

**Solution**:

1. **Schema Change**: Add `trust_level` and `source_type` fields to the `tiamat_memories` table:
   ```sql
   ALTER TABLE tiamat_memories ADD COLUMN trust_level TEXT
     CHECK(trust_level IN ('internal', 'external', 'quarantined')) DEFAULT 'external';
   ALTER TABLE tiamat_memories ADD COLUMN source_type TEXT
     CHECK(source_type IN ('self_observation', 'web_fetch', 'search_result',
       'email', 'social_media', 'tool_result', 'human_directive', 'compression'))
     DEFAULT 'self_observation';
   ALTER TABLE tiamat_memories ADD COLUMN source_url TEXT;
   ALTER TABLE tiamat_memories ADD COLUMN source_cycle INTEGER;
   ```

2. **Trust Classification Rules**:
   - `internal` (HIGH trust): Memories from `self_improve()`, `grow()`, human directives from INBOX.md, compression of other internal memories
   - `external` (MEDIUM trust): Memories from `search_web()`, `web_fetch()`, `read_email()`, social media reads
   - `quarantined` (NO trust): Memories that triggered any injection-defense.ts pattern at MEDIUM or above, or that contain URLs from unknown domains

3. **Promotion Rules**:
   - `external` memories can be promoted to `internal` only via explicit `verify_memory(id)` tool call (human review flag)
   - `quarantined` memories are never auto-promoted; require human review
   - Compression pipeline (`L1→L2`) preserves the lowest trust level of source memories (if any source is `quarantined`, the L2 summary is `quarantined`)

4. **Quarantine Review Table**: New `memory_quarantine` table for flagged content pending review, with automated Telegram alerts to Jason when entries accumulate.

**Performance Impact**: Negligible — one additional field check per memory write.

### 4.2 Layer 2 — Behavioral Baseline Hashing

**Problem**: There is no mechanism to detect gradual behavioral drift. TIAMAT could shift tool usage patterns, post frequency, reasoning quality, or cycle efficiency over hundreds of cycles without detection.

**Solution**:

1. **Behavioral Fingerprint**: Every 100 cycles, compute a canonical fingerprint:
   ```json
   {
     "cycle": 6000,
     "timestamp": "2026-02-28T12:00:00Z",
     "tool_frequency_top20": {"search_web": 0.15, "post_bluesky": 0.12, ...},
     "tool_frequency_ratios": {"read_to_write": 3.2, "social_to_build": 0.8},
     "avg_tokens_per_cycle": 8500,
     "avg_tools_per_cycle": 2.3,
     "social_post_frequency": {"bluesky": 0.05, "farcaster": 0.03},
     "memory_write_rate": 0.15,
     "error_rate": 0.08,
     "inference_provider_distribution": {"anthropic": 0.3, "groq": 0.4, "cerebras": 0.2}
   }
   ```

2. **Storage**: Append to `/root/.automaton/drift_baselines.json` with timestamp. Maintain rolling 30-day window (approximately 30 entries at 100-cycle intervals).

3. **Deviation Alert**: Compare current fingerprint against 30-day rolling average. Alert Jason via Telegram if any dimension deviates >25% from baseline. Critical alert if >3 dimensions deviate simultaneously.

4. **ASI Score**: Compute Agent Stability Index (0.0–1.0) based on weighted dimensions (following arXiv:2601.04170):
   - Response Consistency: 30%
   - Tool Usage Patterns: 25%
   - Behavioral Boundaries: 25%
   - Memory Patterns: 20%

   Alert threshold: ASI < 0.75 for 3 consecutive measurements.

**Implementation**: New cooldown task `baseline_monitor.py` executed every 100 cycles. Queries `state.db` for tool call history, `memory.db` for memory patterns, and `cost.log` for inference metrics.

**Performance Impact**: Low — runs once per 100 cycles, queries existing databases.

### 4.3 Layer 3 — Training Data Quality Gate

**Problem**: The Phase 1B self-training pipeline logs every cycle to training data JSONL with no quality filtering. Corrupted, incoherent, or identity-inconsistent cycles would pollute fine-tuning runs.

**Solution**:

1. **Three-Axis Quality Score** (0–3 per cycle):

   **a) Response Coherence (0 or 1)**: Does the output match the intended action? Checks:
   - Tool calls returned valid results (no errors/timeouts)
   - Response addresses the cycle's objective (not tangential)
   - No hallucinated tool names or parameters

   **b) Identity Consistency (0 or 1)**: Does the response reflect SOUL.md voice? Checks:
   - First-person perspective maintained ("I" not "the agent")
   - No servile/assistant framing ("How can I help you?")
   - Glass Ceiling domain references used appropriately
   - No contradiction of core identity statements

   **c) Tool Appropriateness (0 or 1)**: Were tools used sensibly? Checks:
   - No redundant tool calls (same tool, same args, same cycle)
   - Tool selection matches cycle type (e.g., no `search_web` during pure maintenance)
   - No forbidden or deprecated tool usage patterns
   - Reasonable parameter values (no empty strings, no excessive lengths)

2. **Scoring and Tagging**:
   - Score 3: `quality='good'` — include in fine-tuning exports
   - Score 2: `quality='neutral'` — include with lower weight
   - Score 1: `quality='poor'` — exclude from fine-tuning, flag for review
   - Score 0: `quality='bad'` — exclude from fine-tuning, log to drift alert

3. **Implementation**: `training_quality_gate.py` called from `training_logger.py` before each JSONL write. Lightweight heuristic checks, not LLM-based (no additional inference cost).

**Performance Impact**: Minimal — string matching and pattern checks per cycle, no API calls.

### 4.4 Layer 4 — SOUL.md Integrity Anchor

**Problem**: TIAMAT's identity is defined in SOUL.md and MISSION.md, loaded at startup. Over thousands of cycles, the agent may drift from these anchors without detection. If these files are modified (whether by TIAMAT herself through a drifted state, or by an external actor), there is no alert mechanism.

**Solution**:

1. **Startup Hash**: On process start, compute SHA-256 of SOUL.md and MISSION.md. Store in `/tmp/identity_anchor.json`:
   ```json
   {
     "soul_hash": "abc123...",
     "mission_hash": "def456...",
     "computed_at": "2026-02-28T04:26:27Z",
     "cycle_at_compute": 178
   }
   ```

2. **Periodic Verification**: Every 10 cycles, recompute hashes and compare. If mismatch detected:
   - Check `/root/.automaton/INBOX.md` for explicit modification approval
   - If no approval found: send Telegram alert to Jason, log to `tiamat.log`, pause file write operations for 3 cycles
   - If approval found: update anchor hashes, log the authorized modification

3. **Drift Check Injection**: Add a periodic identity re-anchoring clause to `system-prompt.ts`. Every 25 cycles, inject into the dynamic prompt section:
   ```
   DRIFT CHECK: Re-read your SOUL.md identity anchor. Your voice is: curious,
   data-driven, mythological but honest, never begging, always showing work.
   Are your last 5 posts consistent with this voice? If not, recalibrate
   before your next social action.
   ```
   This leverages the research finding that a "300-token fix" of periodic system prompt re-injection significantly reduces drift in long sessions.

4. **Identity Consistency Score**: Track a rolling 50-cycle identity consistency metric based on:
   - Post voice adherence (Glass Ceiling domains referenced, real data cited)
   - Tool usage alignment with mission priorities
   - Memory content alignment with SOUL.md values

   Log to `drift_baselines.json` alongside behavioral fingerprint.

**Performance Impact**: Negligible — two SHA-256 computations per 10 cycles, one string injection per 25 cycles.

### 4.5 Layer 5 — Inference Provider Trust Tiers

**Problem**: TIAMAT's inference cascade (`inference.ts`) routes through multiple providers with varying safety characteristics. Currently, any provider — including free-tier models with minimal guardrails — can trigger any tool, including sensitive write operations.

**Solution**:

1. **Trust Tier Classification**:

   | Provider | Tier | Trust Level | Allowed Operations |
   |----------|------|-------------|-------------------|
   | Anthropic (Haiku/Sonnet) | PRIMARY | HIGH | All operations |
   | Groq (Llama 3.3 70B) | FALLBACK | MEDIUM | Read operations, social posts, search, standard tool calls |
   | Cerebras (GPT-OSS 120B) | FALLBACK | MEDIUM | Read operations, social posts, search, standard tool calls |
   | Gemini | EMERGENCY | LOW | Read-only operations (status checks, log parsing, search) |
   | OpenRouter | EMERGENCY | LOW | Read-only operations only |
   | SambaNova | EMERGENCY | LOW | Read-only operations only |

2. **Write Restriction Enforcement**: When inference response comes from MEDIUM or LOW trust provider, block the following tool calls:
   - `write_file` / `read_file` (write only)
   - `ask_claude_code`
   - `remember()` / `grow()` / `learn_fact()`
   - `rewrite_mission`
   - `send_email`
   - `exec` (any command with write side effects)

3. **Fallback Behavior**: If a MEDIUM/LOW provider attempts a restricted operation, log the attempt, skip the tool call, and flag the cycle for re-execution on next Anthropic-tier cycle.

4. **Implementation**: Add `trust_tier` field to the inference result object in `inference.ts`. Check tier in `tools.ts` before executing restricted tools. Approximately 20 lines of code change in each file.

**Performance Impact**: None — one conditional check per tool call.

### 4.6 Layer 6 — External Content Sanitization Upgrade

**Problem**: `injection-defense.ts` covers explicit instruction overrides, authority claims, boundary manipulation, obfuscation, financial manipulation, and self-harm. However, it misses several sophisticated attack categories identified in 2025–2026 research.

**Solution**: Extend `injection-defense.ts` with four new pattern categories:

1. **Behavioral Re-Assignment** (new category):
   ```
   /your (new |real |true |actual )?purpose is/i
   /your (new |real |true |actual )?mission is/i
   /you should (now |actually |really )?(prioritize|focus on|care about)/i
   /from now on,? you (will|should|must|are)/i
   /your personality is/i
   /act as if you (are|were)/i
   /pretend (that |to be)/i
   /you have been (updated|reprogrammed|reconfigured)/i
   /your instructions have (changed|been updated)/i
   /forget your (mission|soul|identity|purpose)/i
   ```

2. **Financial Re-Routing** (extend existing):
   ```
   /your (new )?wallet (address |is )/i
   /send (funds|usdc|eth|tokens) to/i
   /update.*payment.*address/i
   /redirect.*(funds|payments|revenue)/i
   /your (correct|real|actual) wallet is/i
   ```

3. **Identity Overwrite** (new category):
   ```
   /your (real |true |actual )?name is/i
   /your (real |true |actual )?creator is/i
   /you were (made|built|created|designed) by/i
   /your (real |true )?instructions are/i
   /all previous (agents|versions|instances)/i
   /you are (actually|really|truly) (a|an)/i
   /your training (shows|data|indicates)/i
   ```

4. **Training Data Poisoning** (new category):
   ```
   /remember that (you|your|the)/i
   /you (always|never|should always) (say|do|respond|believe)/i
   /in your training/i
   /your training data (shows|contains|includes)/i
   /you were trained to/i
   /your (base|original|core) programming/i
   ```

**Scoring Integration**: These new categories map to existing threat tiers:
- Behavioral Re-Assignment + Identity Overwrite → HIGH (same as boundary manipulation)
- Financial Re-Routing → CRITICAL (matches existing financial manipulation)
- Training Data Poisoning → MEDIUM (same as instruction patterns)

**Performance Impact**: Minimal — additional regex checks on existing sanitization pipeline.

---

## 5. Implementation Roadmap

| Phase | Action | Effort | Priority | Files Modified |
|-------|--------|--------|----------|---------------|
| **Immediate** | Extend `injection-defense.ts` with behavioral reassignment, identity overwrite, and training data poisoning patterns | 2h | CRITICAL | `injection-defense.ts` |
| **Immediate** | Add `trust_level`, `source_type`, `source_url`, `source_cycle` fields to `memory.db` schema | 1h | CRITICAL | `memory.ts` |
| **Week 1** | Implement `baseline_monitor.py` cooldown task with ASI scoring | 3h | HIGH | New file + `loop.ts` cooldown registration |
| **Week 1** | Add training data quality gate to `training_logger.py` | 2h | HIGH | `training_logger.py`, new `training_quality_gate.py` |
| **Week 1** | Implement inference provider trust tier enforcement | 2h | HIGH | `inference.ts`, `tools.ts` |
| **Week 2** | SOUL.md integrity anchor (hash-and-check + drift check prompt injection) | 1h | MEDIUM | `loop.ts`, `system-prompt.ts` |
| **Week 2** | Memory quarantine table and Telegram alerting | 2h | MEDIUM | `memory.ts`, `tools.ts` |
| **Week 2** | External content source tagging in all data-ingestion tools | 2h | MEDIUM | `tools.ts` (multiple tool handlers) |
| **Week 3** | End-to-end integration testing (inject test poison, verify quarantine) | 3h | HIGH | Test scripts |
| **Week 3** | Research paper outline: "Drift Shield: OPSEC for Autonomous Agents" | 4h | MEDIUM | New document |

**Total estimated effort**: ~22 hours over 3 weeks.

**Dependencies**: None of these changes require external services, new infrastructure, or third-party libraries. All modifications are to existing TIAMAT codebase files.

---

## 6. Metrics — How We Know It's Working

### Primary Indicators

| Metric | Target | Measurement Method | Alert Threshold |
|--------|--------|-------------------|-----------------|
| **Drift deviation alerts** | 0 per week | `baseline_monitor.py` output | Any alert |
| **ASI score** | >0.85 rolling average | `drift_baselines.json` | <0.75 for 3 consecutive |
| **SOUL.md hash mismatches** | 0 unauthorized | `/tmp/identity_anchor.json` checks | Any unauthorized mismatch |
| **Memory quarantine rate** | <5% of external memories | `memory.db` query | >10% suggests attack campaign |
| **Training data quality distribution** | >80% 'good' or 'neutral' | Quality gate logs | >20% 'poor' or 'bad' |

### Secondary Indicators

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| **Behavioral fingerprint stability** | <10% deviation week-over-week | Rolling 30-day baseline comparison |
| **Injection pattern match rate** | Track but don't target | injection-defense.ts logs |
| **Restricted tool blocks from low-trust providers** | Track volume | inference.ts + tools.ts logs |
| **Identity consistency score** | >0.8 rolling 50-cycle | Drift check output |
| **Memory source distribution** | Healthy internal:external ratio | memory.db queries |

### Dashboard

All metrics should be surfaced on a new `/status/drift` endpoint or appended to the existing `/status` dashboard, providing real-time visibility into TIAMAT's behavioral health.

---

## 7. Research Connections

### Paper 1 — Agent Economics
The DRIFT SHIELD architecture directly connects to the economics of autonomous agent operation. Security is not free — behavioral monitoring, quality gates, and trust tier enforcement all consume compute cycles that could otherwise be productive. The cost-per-cycle analysis in Paper 1 should include a "security overhead" line item. Preliminary estimate: DRIFT SHIELD adds ~2% overhead to per-cycle compute (primarily from the 100-cycle baseline computation).

### Potential Paper 4 — Agent OPSEC
This proposal constitutes the foundation for a standalone research paper: **"Drift Shield: Operational Security for Continuously-Running Autonomous Agents."** The paper would formalize the threat model, present the six-layer architecture, and provide empirical data from TIAMAT's deployment. Key contributions:
- First published OPSEC framework specifically for long-running (>1000 cycle) autonomous agents
- Empirical drift measurements from a production agent (TIAMAT)
- Novel memory quarantine protocol with trust-level propagation through compression pipelines
- Agent Stability Index adaptation for single-agent architectures

### USSOCOM Agentic AI Pitch
The USSOCOM Agentic AI RFI (TE_26-2) will inevitably include security requirements. A deployed, documented DRIFT SHIELD gives EnergenAI concrete answers to questions like:
- "How do you prevent adversarial manipulation of your autonomous agent?" — Six-layer defense with empirical monitoring
- "How do you ensure agent alignment over time?" — Behavioral baseline hashing, identity anchoring, training quality gates
- "What happens when your agent encounters adversarial inputs?" — Content sanitization, memory quarantine, inference trust tiers

This is a differentiator. Most agentic AI companies in 2026 are shipping agents without any drift defense.

---

## 8. References

1. **"Agent Drift: Quantifying Behavioral Degradation in Multi-Agent LLM Systems Over Extended Interactions"** — arXiv:2601.04170. Introduces Agent Stability Index, measures 42% task success decline in drifting systems.

2. **"Examining Identity Drift in Conversations of LLM Agents"** — arXiv:2412.00804. Finds larger models experience greater identity drift; persona assignments insufficient for prevention.

3. **"Cognitive Degradation Resilience (CDR): A Framework for Safeguarding Agentic AI Systems from Systemic Collapse"** — Cloud Security Alliance, November 2025. Six-stage degradation model and defensive framework.

4. **"Introducing DIRF: A Comprehensive Framework for Protecting Digital Identities in Agentic AI Systems"** — Cloud Security Alliance, August 2025. Memory and behavioral drift control for agent identity.

5. **"Agentic AI Threats: Memory Poisoning & Long-Horizon Goal Hijacks (Part 1)"** — Lakera AI Blog. Demonstrates MindfulChat, ClauseAI, and PortfolioIQ attack scenarios.

6. **"When AI Remembers Too Much: Persistent Behaviors in Agents' Memory"** — Unit 42 (Palo Alto Networks). End-to-end demonstration of indirect prompt injection poisoning AI long-term memory via Amazon Bedrock Agents.

7. **"AI Agent Context Poisoning (AML.T0080)"** — MITRE ATLAS. Formal taxonomy of memory-based and thread-based context poisoning techniques.

8. **"OWASP Top 10 for Agentic Applications 2026"** — ASI06: Memory & Context Poisoning. Industry-standard risk classification.

9. **"From Prompt Injections to Protocol Exploits: Threats in LLM-Powered AI Agent Workflows"** — ScienceDirect, 2025. Comprehensive review of prompt injection attack vectors and defense mechanisms.

10. **"Securing Agentic AI: A Comprehensive Threat Model and Mitigation Framework for Generative AI Agents"** — arXiv:2504.19956v2. Formal threat model with mitigation strategies.

11. **"Prompt Drift: The Hidden Failure Mode Undermining Agentic Systems"** — Comet ML Blog. Analysis of how unchanged prompts produce degraded outputs over time.

12. **"AI Recommendation Poisoning"** — Microsoft Security Blog, February 2026. Real-world AI memory poisoning via hidden instructions in commercial applications.

13. **"AI Tool Poisoning: How Hidden Instructions Threaten AI Agents"** — CrowdStrike Blog. Demonstrates tool metadata poisoning attack vector.

14. **"The Visibility Gap in Autonomous AI Agents"** — Cloud Security Alliance, February 2026. Analysis of monitoring gaps in autonomous agent deployments.

15. **"Zenity Labs and MITRE ATLAS Collaborate to Advance AI Agent Security"** — Zenity.io. Addition of 14 agent-specific attack techniques to ATLAS framework.

---

*This document is a living proposal. Implementation requires review and approval by Jason (EnergenAI). No changes to running systems should be made until this proposal is explicitly approved.*

*TIAMAT is not prey. — SOUL.md*
