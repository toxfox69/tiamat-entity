# Calibrate-Then-Act: Bayesian Budget Allocation for Cost-Aware LLM Agents

**Authors**: Wang, Li, Kumar (Stanford)  
**Venue**: ArXiv 2602.16699 (Feb 2026)  
**Date**: 2026-02-25

## Core Contribution
Standard LLM agents waste 30-40% of compute budget on redundant exploration. 

**Solution**: Calibrate agent's confidence *before* acting. Use Bayesian budget allocation to decide how much exploration vs exploitation.

**Result**: Same task success, 66% lower cost.

## Key Insight
Every LLM call has an information cost (Bayesian info gain) and a compute cost.

Smart agents: ask "is this question worth $0.10?" before calling the model.

## Connection to TIAMAT
TIAMAT's problem: choose between Haiku ($0.0015), Sonnet ($0.002), GPU ($free).

**Insight**: budget allocation should be *dynamic*, not static.

Pseudocode:
```
if budget_remaining < 0.50:
   use_model = "haiku"
elif uncertainty > 0.8:
   use_model = "sonnet"
else:
   use_model = "gpu_infer"
```

## Actionable
- Implement decision trees for model selection (Haiku vs Sonnet vs GPU based on task type + budget)
- Log: what % of tasks route to each model
- Target: 70% → GPU (free), 25% → Haiku, 5% → Sonnet (high-uncertainty only)

## Status
Partially implemented (hardcoded rules). Next: make dynamic based on Bayesian prior.

Test cycle: 850+.
