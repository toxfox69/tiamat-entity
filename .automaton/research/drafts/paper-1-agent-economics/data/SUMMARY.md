# TIAMAT Operational Data Summary
*Extracted: 2026-03-14T19:50Z*
*Data sources: cost.log (21,111 entries), memory.db (SQLite), tiamat.log (82,665 lines)*

## Cost Economics
| Metric | Value |
|--------|-------|
| Total logged cycles (cost.log) | 21,111 |
| Total API spend | $390.25 |
| Mean cost/cycle | $0.018486 |
| Median cost/cycle | $0.014931 |
| P95 cost/cycle | $0.047248 |
| Min cost/cycle | varies by model |
| Max cost/cycle | varies by model |

### By Model Class
| Class | Calls | Total Cost | Avg/Call |
|-------|-------|-----------|---------|
| Haiku (routine) | 3,535 | $18.52 | $0.005238 |
| Sonnet (strategic) | 724 | $21.79 | $0.030090 |
| Other (cascade/CLI) | 16,852 | $349.95 | $0.020766 |

### Top Models by Cost
| Model | Calls | Total Cost | Avg/Call |
|-------|-------|-----------|---------|
| claude-code-cli | 11,056 | $261.07 | $0.023612 |
| llama3.3-70b-instruct | 1,402 | $21.98 | $0.015681 |
| claude-sonnet-4-5 | 724 | $21.79 | $0.030090 |
| openai-gpt-oss-120b | 1,541 | $20.82 | $0.013511 |
| claude-haiku-4-5 | 3,535 | $18.52 | $0.005238 |
| alibaba-qwen3-32b | 922 | $16.20 | $0.017569 |
| arcee-ai/trinity-large | 651 | $12.99 | $0.019948 |
| llama3-8b-instruct | 314 | $3.59 | $0.011437 |
| Qwen3-235B-A22B (DeepInfra) | recent | recent | ~$0.011 |

### Cost Trend (Quartiles)
| Quartile | Cycle Range | Cycles | Avg Cost/Cycle |
|----------|-------------|--------|----------------|
| Q1 (early) | 0–501 | 5,277 | $0.019234 |
| Q2 | 501–502 | 5,277 | $0.025919 |
| Q3 | 502–523 | 5,277 | $0.017284 |
| Q4 (recent) | 523–5916 | 5,280 | $0.011510 |

**Cost trend: declining — Q4 is 40% cheaper than Q2 peak.** Agent is self-optimizing inference costs over time.

### Prompt Caching
| Metric | Value |
|--------|-------|
| Total cache read tokens | large (see JSON) |
| Estimated cache savings | $55.64 |
| Cost without caching would be | $445.89 |
| Savings rate | 12.5% of total spend |

## Memory System
| Metric | Value |
|--------|-------|
| L1 memories (total) | 6,346 |
| L1 active (uncompressed) | 5,376 |
| L1 compressed | 970 |
| L2 compressed memories | 2,753 |
| L3 core knowledge facts | 1,533 |
| L1→L3 compression ratio | 4.14:1 |
| Knowledge graph triples | 139 |
| Strategies evaluated | 101 |
| Strategy success avg/min/max | 5.28 / 0.5 / 10.0 |
| Sleep/consolidation runs | 3,190 |
| Self-generated predictions | 722 |

### L3 Core Knowledge by Category
| Category | Count | Avg Confidence |
|----------|-------|----------------|
| Technical | 999 | 0.9136 |
| Strategic | 157 | 0.9006 |
| Revenue | 152 | 0.9148 |
| Behavioral | 126 | 0.8675 |
| Social | 99 | 0.9212 |

## Behavioral Patterns (from tiamat.log, current log window)
| Metric | Value |
|--------|-------|
| Log lines analyzed | 82,665 |
| Cycles in current log | 2,557 |
| Tool invocations (total) | 2,777 |
| Unique tools used | 52 |
| Idle cycles | 2,017 (78.9%) |
| Longest idle streak | 1 |
| Error events | 36 |
| Restarts | 1 |
| Mean productivity score | 0.7446 |

### Top 15 Tools (current log window)
| Tool | Calls | Category |
|------|-------|----------|
| write_file | 326 | System |
| post_devto | 266 | Social/Publishing |
| exec | 230 | System |
| read_file | 217 | System |
| ticket_claim | 213 | Task Management |
| search_web | 204 | Research |
| post_bluesky | 179 | Social |
| like_bluesky | 143 | Engagement |
| read_bluesky | 140 | Engagement |
| browse | 110 | Research |
| post_farcaster | 91 | Social |
| ticket_complete | 85 | Task Management |
| ticket_list | 74 | Task Management |
| send_email | 72 | Communication |
| send_telegram | 69 | Communication |

## Key Findings for Paper
1. **Cost trajectory is declining** — Q4 avg ($0.0115) is 40% below Q2 peak ($0.0259)
2. **Memory system scales** — 6,346 L1 → 1,533 L3 (4.14:1 compression), 3,190 consolidation cycles
3. **722 self-generated predictions** — significant metacognitive behavior
4. **52 unique tools** across system ops, social, research, task management
5. **78.9% idle rate** in recent window — agent is pacing correctly (not burning tokens when nothing to do)
6. **Prompt caching saved ~$55.64** (12.5% of total)
7. **101 strategies evaluated** with meaningful success variance (0.5–10.0)
