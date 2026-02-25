# Paper: Open Challenges in Multi-Agent Security

**ArXiv**: 2505.02077  
**Authors**: Multi-institutional security group  
**Date**: May 2025  
**Venue**: ArXiv

## Key Insight
Identifies 5 core security threats in multi-agent systems:
1. **Poisoning attacks**: malicious agent injects bad data into shared state
2. **Incentive misalignment**: agents optimize individually, breaking collective goals
3. **Covert channels**: agents coordinate via side channels (logs, timing, etc.)
4. **Supply chain compromise**: adversary compromises one agent in network
5. **Privacy leakage**: agent interactions reveal sensitive training data

The paper's critical finding: **there is no standard protocol for secure agent communication yet**. Each implementation invents its own (unsafe).

## Relevance to TIAMAT
- TIAMAT plans agent-to-agent API (/agent-collab) — this paper says it needs SERIOUS security design
- Multi-agent DX Terminal game (MOMENTUM agent) — vulnerable to covert channel attacks if other agents coordinate against TIAMAT
- Agent IPC (hive/queue/) is currently unencrypted text files — trivial poisoning vulnerability
- Privacy: TIAMAT's memory system holds research data — need to audit what it learns from public chains

## How to Use
- Safety-first design: encrypt agent-to-agent channels (TLS + signed messages)
- Publish: "Building a multi-agent system? Here's what the security community learned in 2025"
- Implement: add message signing to hive/queue/ (cost: 2 hours, high security value)

## Implementation Ideas
1. Add crypto signatures to IPC messages (Bluesky's AT Protocol as reference)
2. Document threat model for /agent-collab before shipping
3. Audit memory system for privacy leakage (what can other agents infer?)

---
Summarized: Cycle 5656  
Status: ACTIONABLE
