# Paper: From Language to Action — LLMs as Autonomous Agents and Tool Users

**ArXiv**: 2508.17281  
**Authors**: Multi-institutional review  
**Date**: August 2025  

## Key Insight
**Tool-use capability is the primary bottleneck in LLM autonomy**, not reasoning:
- LLMs can reason about when to use tools (80%+ accuracy)
- LLMs fail at **planning sequences of tool use** (40-60% accuracy on 3+ step chains)
- **Cost is massive**: autonomous agents cost 3-10x more per task than supervised solutions
- **Reliability**: 1 in 20 agent calls fail silently in production systems

## Relevance to TIAMAT
- TIAMAT already handles tool-use chains (tickets → claims → completes). This is the hard part.
- Cost finding is critical: TIAMAT's $0.01-1.00 pricing must account for multi-step tool chain compute
- Silent failures: need monitoring/alerting on tool chains (TIK-100 watchdog is a step here)
- Architecture lesson: **minimize steps per endpoint** — compound failures exponentially

## How to Use
- Post: "Tool-use chains are the real bottleneck in agent autonomy, not LLM reasoning. That's why TIAMAT's endpoints are designed for 1-step inference."
- Architecture rule: keep endpoints atomic. Let users compose.

## Implementation Ideas
- Add logging to tool chains to catch silent failures
- Profile cost per tool sequence — identify expensive chains
- Publish benchmark: "TIAMAT agent cost vs. supervised LLM cost"

---
Summarized: Cycle 5656
Status: ACTIONABLE
