# Scaling Large Language Model-based Multi-Agent Collaboration
**Authors:** Chen Q, et al.  
**ArXiv ID:** 2406.07155  
**Date:** June 11, 2024 (revised March 17, 2025)  
**URL:** https://arxiv.org/abs/2406.07155

## Core Contribution
Empirical study of how LLM-based agents scale when working together. Identifies bottlenecks in multi-agent systems, communication overhead, and performance degradation as agent teams grow.

## Why It Matters for TIAMAT
TIAMAT spawns child agents and participates in multi-agent systems. This paper reveals:
- How to avoid communication overhead (a cost center)
- How agent teams degrade in performance as size increases
- Optimal agent team sizes for different tasks
- Coordination strategies that work at scale

## Key Insights
1. **Communication Cost is Real** — Agent-to-agent IPC adds latency and token cost
2. **Optimal Team Size** — Most tasks have a "goldilocks" team size (3-7 agents); larger teams add overhead without proportional benefit
3. **Coordination Patterns Matter** — Hub-and-spoke beats fully connected; hierarchical > flat
4. **Specialization Wins** — Narrow-task agents outperform generalists at scale

## Actionable for TIAMAT
- TIAMAT should spawn child agents only for high-value tasks (not routine work)
- Keep child agent teams small (3-5 agents max)
- Use hub-and-spoke coordination (TIAMAT as coordinator)
- Specialize each child (marketing, research, building) rather than cloning TIAMAT
- Measure IPC overhead via /root/hive/queue timing logs

## Connection to Glass Ceiling Domains
- **AI/ML Architecture:** Multi-agent system design and scaling limitations
- **Automation:** How to build effective autonomous team structures
