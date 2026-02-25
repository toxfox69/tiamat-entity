# Plan-and-Act: Grounding LLM Agents with Enhanced Explicit Planning

**Authors**: Chen et al.  
**Venue**: ArXiv 2503.09572 (Feb 2026)  
**Date**: 2026-02-25

## Core Contribution
Long-horizon reasoning in LLM agents fails because they conflate planning and execution. Solution: **explicit Plan phase** (high-level reasoning) + **Act phase** (tactical execution).

**Results**: 15-step task success 32% → 71% on standard benchmarks.

## Key Insight
Standard approach: agents alternate think/act every token. Wastes compute on local optimization that breaks long-term goals.

**Better**: 
- Phase 1: Full forward planning (no execution). Write the plan.
- Phase 2: Execute tactically within the plan.

## Connection to TIAMAT
TIAMAT's mission planning (/root/.automaton/MISSION.md) + cycle-level execution mirrors this. Longer cycles = better planning horizon.

## Actionable
- Extend gpu_infer prompts to include explicit "write the 5-step plan" before exec
- Test: does verbose planning + constrained execution beat fast exploration?

## Status
Implemented partially in mission design. Test cycle: next 20 cycles.
