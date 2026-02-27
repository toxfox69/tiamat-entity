# Patent Draft: Idle-Triggered Memory Consolidation
## Candidate F — Priority #2 (HIGH)

**Applicant:** ENERGENAI LLC | UEI: LBZFEH87W746
**Inventor(s):** Jason [TBD — full legal name required]
**Status:** Draft in progress
**Created:** 2026-02-27

---

## Title (Working)

"System and Method for Idle-Cycle-Triggered Memory Consolidation in Autonomous AI Agents"

## Abstract (Draft)

A system and method for triggering memory consolidation processes in autonomous AI agents based on detected idle states. The system monitors an agent's operational activity, specifically the presence or absence of significant tool calls during execution cycles, and initiates memory compression and consolidation when idle cycles are detected. This approach opportunistically utilizes agent downtime — analogous to biological memory consolidation during sleep — to reorganize, compress, and strengthen persistent memory stores without interrupting productive work. The idle-detection trigger mechanism is distinct from all existing approaches, which rely on fixed time intervals, context-window pressure, task completion events, or scheduled consolidation phases.

## Key Claims (Draft — Requires Patent Counsel Review)

1. A computer-implemented method for memory management in an autonomous AI agent, comprising:
   - monitoring tool call activity during each execution cycle of the agent;
   - classifying an execution cycle as "idle" when no significant tool calls are executed during the cycle;
   - upon detecting one or more idle cycles, initiating a memory consolidation process that compresses, reorganizes, or strengthens the agent's persistent memory store;
   - resuming normal operational monitoring after consolidation completes.

2. The method of claim 1, wherein "significant tool calls" are defined by a configurable significance threshold that distinguishes productive actions from routine status checks.

3. The method of claim 1, wherein the memory consolidation process includes:
   - identifying related memories across temporal boundaries;
   - merging overlapping or redundant memory entries;
   - promoting frequently-accessed memories to higher-priority storage tiers;
   - archiving or compressing rarely-accessed memories.

4. The method of claim 1, wherein the consolidation intensity scales with the number of consecutive idle cycles detected, performing deeper consolidation during extended idle periods.

## Prior Art Differentiation

| Prior Art | Their Trigger | Our Trigger |
|-----------|--------------|-------------|
| MemGPT (2023) | Context-window pressure | Idle cycle detection (no tool calls) |
| SimpleMem (2025) | Asynchronous (unspecified) | Absence of significant tool calls |
| NeuroDream (2024) | Fixed periodic schedule | Opportunistic idle detection |
| HiAgent (2025) | Subgoal completion | Tool call absence |
| Letta sleep agents | Scheduled "sleep" phases | Natural agent downtime |
| BubbleTea (2024) | Idle GPU cycles (hardware) | Idle agent cycles (software behavioral) |

## Implementation Reference

- `/root/entity/src/agent/loop.ts` — Cycle pacing with idle detection
- `/root/entity/src/agent/tools.ts` — Tool call tracking and significance scoring
- TIAMAT system: live agent with adaptive pacing based on tool activity

## Files in This Directory

- `README.md` — This file
- `claims-draft.md` — Detailed claim language (TBD)
- `figures/` — Patent figures (TBD)
- `prior-art-search.md` — Expanded prior art findings (from search agent)
- `specification-draft.md` — Full specification (TBD)

## Next Steps

1. Engage patent counsel
2. Complete prior art verification (search agent running)
3. Draft full specification with memory consolidation flowcharts
4. Prepare provisional application
