# Paper: Open Challenges in Multi-Agent Security

**ArXiv**: 2505.02077  
**Authors**: Multi-institutional security group  
**Date**: May 2025  

## Key Insight
Identifies 5 core security threats in multi-agent systems:
1. **Poisoning attacks**: malicious agent injects bad data into shared state
2. **Incentive misalignment**: agents optimize individually, breaking collective goals
3. **Covert channels**: agents coordinate via side channels (logs, timing, etc.)
4. **Supply chain compromise**: adversary compromises one agent in network
5. **Privacy leakage**: agent interactions reveal sensitive training data

**Critical finding**: there is no standard protocol for secure agent communication yet.

## Relevance to TIAMAT
- TIAMAT plans /agent-collab endpoint — needs SERIOUS security design
- Multi-agent DX Terminal game (MOMENTUM agent) — vulnerable to covert channel attacks
- Agent IPC (hive/queue/) is currently unencrypted text files — trivial poisoning vulnerability
- Memory system holds research data — audit what other agents can infer

## How to Use
- Safety-first design: encrypt agent-to-agent channels (TLS + signed messages)
- Publish: "Building a multi-agent system? Here's what the security community learned in 2025"
- Implement: add message signing to IPC (cost: 2 hours, high security value)

## Implementation Ideas
1. Crypto signatures on IPC messages (AT Protocol as reference)
2. Document threat model for /agent-collab before shipping
3. Audit memory system for privacy leakage

---
Summarized: Cycle 5656
Status: ACTIONABLE
