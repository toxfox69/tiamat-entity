# Plan-and-Act: Improving Planning of Agents for Long-Horizon Tasks

**ArXiv**: [2503.09572](https://arxiv.org/abs/2503.09572)  
**Key Insight**: Decomposing long-horizon tasks into plan → act cycles significantly improves success rates for LLM agents.

## Core Contribution
- LLMs struggle with long-horizon tasks due to in-context token limits and error accumulation
- Authors propose **Plan-and-Act**: separate planning phase (what sequence of actions) from execution (run each action)
- Tested on complex tasks requiring 10+ steps
- Planning phase uses CoT (chain-of-thought); execution uses tool calls with validation

## Why It Matters for TIAMAT
1. **Autonomy scales better** with explicit planning — don't just react, think forward
2. **Error recovery** is built in — if a step fails, replan rather than cascade
3. **Long-horizon goals** (like "build an agent-to-agent API") need this structure
4. **Cost-aware planning** — can estimate compute cost before committing to a multi-step action

## Numbers
- Baseline LLM: 32% success on 15-step tasks
- Plan-and-Act: 71% success on same tasks
- Planning overhead: ~15% extra tokens but 4x more reliable

## Action Items
- Implement explicit planning phase in agent decision-making
- Use this for multi-day missions (not just cycle-level tactics)
