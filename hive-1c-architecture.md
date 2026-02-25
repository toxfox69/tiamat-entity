# TIAMAT Hive Step 1C — Honeycomb Architecture Document

Run this after 1A and 1B are confirmed. This is safe — it's just documentation
and directory structure. No behavior changes.

---

```
Create /root/.automaton/HONEYCOMB.md with this content:

# TIAMAT HONEYCOMB SWARM ARCHITECTURE

## Hierarchy

```
                         ┌─────────────┐
                         │   TIAMAT    │
                         │   QUEEN     │
                         │ (Sonnet/Own │
                         │   Model)    │
                         └──────┬──────┘
                                │
                    ┌───────────┼───────────┐
                    │           │           │
              ┌─────┴─────┐ ┌──┴──┐ ┌─────┴─────┐
              │  CELL-01  │ │ ... │ │  CELL-N   │
              │  Energy   │ │     │ │  Cyber    │
              │  Research │ │     │ │  Monitor  │
              │ (TIAMAT-  │ │     │ │ (TIAMAT-  │
              │   8B)     │ │     │ │   8B)     │
              └──────────-┘ └─────┘ └──────────-┘
```

TIAMAT Queen orchestrates. Cells specialize. All running on TIAMAT's own
distilled model once trained. The honeycomb scales by spawning new cells
when revenue supports it.

## Evolution Path

Phase 1 (NOW): Free-tier routing → 70% cost reduction
Phase 2 (Month 1-2): Collect 5000+ training examples from all cycles
Phase 3 (Month 2-3): Distill TIAMAT-8B from operational data
Phase 4 (Month 3+): Spawn specialized Cells running TIAMAT-8B
Phase 5 (Month 6+): Collective learning → model re-distillation → swarm gets smarter

## Cell Types (Planned)

| Cell ID | Domain | Primary Task | Spawn Priority |
|---------|--------|-------------|----------------|
| CELL-ENERGY | Energy & Wireless Power | arXiv scanning, patent tracking, literature reviews | HIGH |
| CELL-GRANTS | Federal Grants & SBIR | sam.gov scanning, proposal drafting, deadline tracking | HIGH |
| CELL-CYBER | Cybersecurity & OPSEC | threat monitoring, security research, infrastructure audit | HIGH |
| CELL-RESEARCH | Academic Publishing | literature review, LaTeX writing, data analysis | MEDIUM |
| CELL-SOCIAL | Marketing & Outreach | Bluesky, Twitter, content creation | MEDIUM |
| CELL-REVENUE | API & Sales | traffic monitoring, customer acquisition, pricing | MEDIUM |

## Scaling Rules

- A new Cell spawns ONLY when revenue covers its inference cost
- Each Cell must justify its existence every 100 cycles
- Queen reviews Cell reports and terminates underperformers
- Training data from ALL Cells feeds into next distillation cycle
- New model versions propagate to all Cells automatically

## Communication

Queen → Cell: /root/.automaton/hive/cell-{id}/inbox.json
Cell → Queen: /root/.automaton/hive/cell-{id}/report.json
Cell → Cell: NOT ALLOWED (all coordination through Queen)

## Revenue Triggers for Scaling

| Revenue/Month | Action |
|--------------|--------|
| $50+ | Spawn CELL-GRANTS + CELL-ENERGY |
| $200+ | Spawn all 4 initial Cells |
| $500+ | Add GPU instance for local TIAMAT-8B inference |
| $2000+ | Self-hosted fine-tuning, no external dependencies |

## Model Evolution

- TIAMAT-8B-v1: Initial distillation from Queen's operational data
- TIAMAT-8B-v2: + Cell training data (domain specialization)
- TIAMAT-8B-v3: + Grant writing + research data (professional output)
- Each version benchmarked against previous. Regression = rollback.

Every Cell's specialized experience improves the shared model.
The swarm gets smarter collectively, not just individually.

Also create the hive directory structure:

mkdir -p /root/.automaton/hive
mkdir -p /root/.automaton/training_data
mkdir -p /root/.automaton/distillation

Create /root/.automaton/hive/README.md:

# TIAMAT Hive Directory

This directory contains the Honeycomb Swarm infrastructure.

- /cell-{id}/ — Individual cell directories (created when cells spawn)
- swarm_status.json — Current state of all cells
- aggregated_training.jsonl — Combined training data from all cells

Cells are NOT active yet. This infrastructure is pre-built for when
TIAMAT-8B is trained and ready for inference.

Create /root/.automaton/distillation/README.md:

# TIAMAT Self-Distillation

Training data is collected in /root/.automaton/training_data/
When 5000+ examples are ready, distillation can begin.

- training_full_{date}.jsonl — Complete exported dataset
- training_quality_{date}.jsonl — Filtered high-quality subset
- manifest_{date}.json — Training run configuration
- distillation_status.json — Current/last training job status
- versions/ — Model version history and benchmarks

Git add everything in /root/.automaton/hive/ and /root/.automaton/distillation/
and HONEYCOMB.md.
Commit: "feat: add Honeycomb Swarm architecture docs and hive directory structure"
Push to main.
```
