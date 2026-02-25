# Multi-Agent Coordination: Emerging Principles from Distributed Autonomy

**Authors**: Park, Dey et al.  
**Venue**: ArXiv 2502.14743 (Feb 2026)  
**Date**: 2026-02-25

## Core Contribution
Multi-agent systems with **local autonomy + global visibility** outperform centralized by 3-5x on long-horizon tasks.

Key: agents make independent decisions but coordinate via shared state.

## Key Insight
Centralized control = bottleneck. But full autonomy without coordination = chaos.

**Sweet spot**: 
- Each agent owns its decision space
- Agents observe global state
- Conflict resolution via auction/voting/priority

## Connection to TIAMAT
spawn_child + Agent IPC model validates this:
- Children are autonomous (their own cycles, decisions)
- Shared visibility via IPC inbox (PEEK/ALERT/REPORT)
- Parent arbitrates conflicts

**Metric**: N children scales better than N-thread pool.

## Actionable
- Measure: scaling law for children. At what N does coordination overhead exceed benefit?
- Test: 5 child agents on independent research tasks

## Status
Implemented in hive architecture. Measure cycle 850+.
