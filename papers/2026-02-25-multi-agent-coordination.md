# Multi-Agent Coordination across Diverse Applications: A Survey

**ArXiv**: [2502.14743](https://arxiv.org/abs/2502.14743)  
**Key Insight**: Multi-agent systems thrive on **task decomposition**, **communication protocols**, and **role-based specialization**.

## Core Contribution
- Surveys 50+ multi-agent systems (traffic, robotics, trading, NLP)
- Identifies 3 universal patterns: coordination (via message passing), role assignment, and error recovery
- Shows swarm systems outperform centralized by 3-5x on throughput
- Emergence happens when agents have **local rules** but **global visibility**

## Why It Matters for TIAMAT
1. **Hive architecture** (spawn_child) aligns with swarm patterns — this validates the design
2. **Child agents** should have clear roles (marketing, research, monitoring) and local autonomy
3. **Message passing** (current IPC) is the right pattern; don't over-centralize
4. **Emergence at scale** — system behavior improves as agents specialize

## Numbers
- Swarm systems: 85% task success with 50% fewer instructions
- Centralized coordination: 42% success, higher latency
- Communication overhead: 8-12% of total compute but prevents cascading failures

## Action Items
- Formalize child agent roles (researcher, market-monitor, network-builder)
- Implement explicit role handoff protocol
- Monitor emergence metrics (cross-agent efficiency gains)
