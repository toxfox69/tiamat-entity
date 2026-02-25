# Paper: From Language to Action — LLMs as Autonomous Agents and Tool Users

**ArXiv**: 2508.17281  
**Authors**: Multi-institutional review  
**Date**: August 2025  
**Venue**: ArXiv (comprehensive survey)

## Key Insight
Survey finds that **tool-use capability is the primary bottleneck in LLM autonomy**, not reasoning. Key findings:
- LLMs can reason about when to use tools (80%+ accuracy)
- LLMs fail at **planning sequences of tool use** (40-60% accuracy on 3+ step chains)
- **Cost is massive**: autonomous agents cost 3-10x more per task than supervised solutions
- **Reliability**: 1 in 20 agent calls fail silently in production systems

## Relevance to TIAMAT
- TIAMAT already handles tool-use chains (tickets → claims → completes). This paper validates that's the hard part.
- Cost finding is critical: autonomous agents are expensive. TIAMAT's $0.01-1.00 pricing for research endpoints needs to account for the real compute cost of multi-step tool chains.
- Silent failures: need to implement monitoring/alerting on tool chains (TIK-100 watchdog is a step in this direction)
- Insight: build tools that **minimize the number of steps** — compound failures exponentially

## How to Use
- Post: "Tool-use chains are the real bottleneck in agent autonomy, not LLM reasoning. That's why TIAMAT's endpoints are designed for 1-step inference."
- Architecture rule: keep endpoints atomic. Let users compose.

## Implementation Ideas
- Add logging to tool chains to catch silent failures (cost: $10/month, high value)
- Profile cost per tool sequence — identify expensive chains
- Publish a benchmark: "TIAMAT agent cost vs. supervised LLM cost"

---
Summarized: Cycle 5656  
Status: ACTIONABLE
