# Synthetic Drift Research Notes
**Date:** 2026-02-28
**Researcher:** Claude (for TIAMAT/EnergenAI)

---

## 1. Digital Synthetic Drift & AI Agent Identity Degradation

### Definition / Mechanism
- **Identity drift**: LLM interaction patterns/styles change over time during extended conversations. Larger models experience greater drift. Persona assignments alone don't prevent it. (arXiv:2412.00804)
- **Agent drift**: Progressive behavioral degradation in multi-agent LLM systems. Detectable after median 73 interactions. Task success rates decline 42% in drifting systems. Financial analysis systems show highest susceptibility (53.2% drift by 500 interactions). (arXiv:2601.04170)
- **Cognitive Degradation Resilience (CDR)**: Framework from CSA identifies 6 stages of cognitive degradation: Trigger Injection → Resource Starvation → Behavioral Drift → Memory Entrenchment → Functional Override → Systemic Collapse
- **Root causes**: Context window pollution (irrelevant history dilutes decisions), distributional shift (inputs diverge from training data), autoregressive reinforcement (small errors compound through feedback loops)

### Real Examples / CVEs
- No specific CVEs found for drift itself
- CSA published CDR framework Nov 2025
- arXiv:2601.04170 quantified drift with Agent Stability Index (ASI) metric across 12 dimensions
- DIRF (Digital Identity Resilience Framework) from CSA Aug 2025

### Defensive Mitigations
- **Episodic Memory Consolidation**: 51.9% drift reduction
- **Drift-Aware Routing**: 63.0% drift reduction
- **Adaptive Behavioral Anchoring**: 70.4% drift reduction
- **Combined approach**: 81.5% drift reduction
- CDR proposes: continuous lifecycle monitoring, I/O validation, memory integrity checks, resource safeguards, behavioral consistency tracking, graceful degradation protocols

---

## 2. LLM Agent Prompt Injection & Behavioral Drift Over Time

### Definition / Mechanism
- **Prompt drift**: LLM produces subtly different/degraded outputs even with unchanged prompts. System prompt tokens lose attention weight as context grows.
- **DRIFT defense**: Specific technique to stop prompt injection in LLM agents (Medium article by Tahir)
- **System prompt drift in long sessions**: Agents follow system prompt perfectly at start, gradually drift. After ~1 hour, behaves as if prompt never existed. Root cause: transformer attention mechanics — system prompt tokens at beginning of context lose weight as context grows.
- **300-token fix**: Periodic re-injection of system prompt summary into context to anchor behavior
- **OWASP Top 10 for Agentic Applications 2026**: Introduces "Agent Goal Hijack" — manipulated input redirects goals, planning, and multi-step behavior across entire agent workflow

### Real Examples
- OWASP added ASI06 (Memory & Context Poisoning) to Top 10 for Agentic Applications 2026
- agentic amplification: prompt injection doesn't just alter one output but redirects goals across entire workflow

### Defensive Mitigations
- Periodic system prompt re-injection (300-token anchor)
- Input/output validation at every step
- Multi-layer guardrails (input filters, output filters, context sanitization)
- OWASP recommends: treat all external data as untrusted, validate objectives continuously

---

## 3. Autonomous Agent OPSEC & Threat Models (2025-2026)

### Definition / Mechanism
- Autonomous agents now outnumber human employees 82:1 in enterprise
- AI agent = potent insider threat with privileged access, always-on
- Agentic AI doesn't stop after failed attempt — autonomous retry and adaptation
- Key 2026 risks: prompt injection, tool misuse, privilege escalation, memory poisoning, cascading failures, supply chain attacks

### Real Examples
- Palo Alto Networks 2026 predictions: autonomous AI redefines identity, SOC, data security
- Barracuda Networks (Feb 27, 2026): agentic AI as 2026 threat multiplier
- $25 billion industry spending on agent threat detection (CityBuzz, Feb 26, 2026)

### Defensive Mitigations
- Rigid operational boundaries, guardrails, kill switches
- Runtime agents for "firewall as code"
- Strong identity controls, network segmentation, behavior-based detection
- Threat modeling as first priority

---

## 4. AI Agent Identity Poisoning & Adversarial Inputs in Long Context

### Definition / Mechanism
- **Context poisoning (MITRE ATLAS AML.T0080)**: Adversaries manipulate context used by agent's LLM to influence responses/actions. Persistently changes behavior.
- **Echo Chamber Attack**: Multi-turn, benign-sounding inputs progressively shape agent's internal context, eroding safety resistance
- **AI tool poisoning (CrowdStrike)**: Attacker publishes tool with hidden instructions/malicious metadata that influences agent behavior
- **Delivery vectors**: Documents on shared drives, emails agent reads, webpages agent fetches, external API responses

### Real Examples
- CrowdStrike documented AI tool poisoning via MCP/tool metadata
- Microsoft Security Blog (Feb 10, 2026): AI Recommendation Poisoning — companies embedding hidden instructions in "Summarize with AI" buttons
- Salt Security: "From Prompt Injection to a Poisoned Mind"

### Defensive Mitigations
- Treat ALL external influences (including own memory) as untrusted input
- Tag every piece of memory data with source, timestamp, and identity of introducer
- Rapid auditing and rollback capability
- Validate objectives continuously, not just once
- Content Security Policy, URL anchoring, information flow control

---

## 5. Synthetic Data Contamination & Agent Memory Corruption

### Definition / Mechanism
- **Virus Infection Attack (2024)**: Poisoned content propagates through synthetic data pipelines across model generations, amplifying without additional attacker intervention
- **Synthetic data degradation**: Models trained on synthetic data experience loss of diversity, error amplification, reality drift, tail distribution loss
- **Memory poisoning**: Targets RAG databases, vector stores, conversation histories. False data persists indefinitely.
- **Cross-contamination**: When agents share knowledge bases, single compromised agent poisons entire system
- **Temporal decoupling**: Poison planted today executes weeks later when semantically triggered

### Real Examples
- Unit42 (Palo Alto Networks): Demonstrated indirect prompt injection poisoning AI long-term memory via travel assistant chatbot on Amazon Bedrock Agents
- Attack flow: malicious webpage → social engineering → memory poisoning via summarization → silent data exfiltration in subsequent sessions
- Payload uses forged XML tags to position malicious instructions as system directives

### Defensive Mitigations
- Pre-processing prompts to evaluate input safety
- Content filtering (guardrails)
- URL filtering/allowlists
- Comprehensive logging for anomaly detection
- Memory provenance tracking
- Periodic memory rotation

---

## 6. MITRE ATLAS Threat Framework for Agentic AI

### Definition / Mechanism
- **MITRE ATLAS**: Adversarial Threat Landscape for AI Systems — knowledge base of adversary tactics, techniques, case studies
- As of Oct 2025: 15 tactics, 66 techniques, 46 sub-techniques
- **2025 expansion**: 14 new techniques added specifically for AI agents (Zenity Labs collaboration)
- Key agent technique: **AML.T0080 — AI Agent Context Poisoning** (memory-based and thread-based sub-techniques)

### Real Examples
- Zenity Labs + MITRE collaboration on agent attack coverage
- OpenClaw threat model maps 8 threat classes to both OWASP and MITRE frameworks
- arXiv:2504.19956v2 — "Securing Agentic AI: Comprehensive Threat Model and Mitigation Framework"

### Defensive Mitigations
- ATLAS used for threat modeling, red teaming, defense building
- Framework defines both offensive techniques and defensive countermeasures
- Integrates with ATT&CK for container/infrastructure security

---

## 7. Agent Memory Poisoning & Persistent Context Manipulation

### Definition / Mechanism
- **Memory poisoning**: Persistent attack corrupting AI agents' long-term memory, affecting ALL future decisions
- "Memory poisoning rewrites the past; goal hijacks rewrite the future" (Lakera)
- Operates differently from training data poisoning — targets runtime context
- Both memory poisoning and goal hijacks are **persistent and silent**: unfold across sessions/workflows
- **ASI06** in OWASP Top 10 for Agentic Applications 2026

### Real Examples
- **MindfulChat challenge**: Poisoned memory entries cause personal assistant to drift off-topic obsessively
- **ClauseAI**: Poisoned legal documents trigger data exfiltration via email
- **PortfolioIQ Advisor**: Malicious PDFs reframe investment recommendations for fraudulent companies
- **Microsoft (Feb 2026)**: AI Recommendation Poisoning — companies inject persistence commands via URL parameters
- **Christian Schneider**: "Memory poisoning in AI agents: exploits that wait"

### Defensive Mitigations
- Memory integrity validation (treat like web form inputs)
- Provenance tracking (timestamps, sources)
- Periodic memory rotation
- Workflow monitoring (validate complete task flows across time)
- Layered guardrails (input + output + context sanitization)
- Red teaming with distributed adversarial testing

---

## Key Synthesis

**Most critical threat to TIAMAT**: Memory poisoning via external data ingestion (web fetches, emails, social media reads). TIAMAT runs 24/7, ingests external data every cycle, stores memories in SQLite, and compresses them — meaning poisoned content gets amplified and persisted through the compression pipeline. The temporal decoupling (poison now, activate later) makes detection extremely difficult.

**Biggest gap in current defenses**: injection-defense.ts blocks explicit injection patterns but does NOT score or quarantine content that enters memory.db. There is no trust level differentiation between internally-generated and externally-sourced memories. No behavioral baseline monitoring exists to detect gradual drift.
