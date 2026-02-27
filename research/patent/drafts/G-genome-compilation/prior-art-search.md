# Prior Art Search: Genome Compilation from Behavioral Failures

**Claim under analysis:** A unified pipeline where (1) failure patterns are detected, (2) encoded as immune-system-style antibodies, (3) compiled during sleep/consolidation cycles, (4) persisted as a genome structure for autonomous AI agents.

**Search conducted:** 2026-02-27
**Searcher:** Claude Opus 4.6 (automated)

---

## Table of Contents

1. [Reflexion (Shinn et al., NeurIPS 2023)](#1-reflexion)
2. [ExpeL (Zhao et al., AAAI 2024)](#2-expel)
3. [SELAUR (Zhang et al., 2026)](#3-selaur)
4. [Darwin Godel Machine (Sakana AI, 2025)](#4-darwin-godel-machine)
5. [Letta/MemGPT Sleep-Time Agents](#5-lettamemgpt-sleep-time-agents)
6. [Language Models Need Sleep (OpenReview, 2025)](#6-language-models-need-sleep)
7. [Active Dreaming Memory (ADM)](#7-active-dreaming-memory-adm)
8. [CN101930517B — Bot Program Detection via Immune System](#8-cn101930517b)
9. [US20220237285 — Cyber Immunity System](#9-us20220237285)
10. [IMAG — Immune Memory-Based Jailbreak Detection](#10-imag)
11. [Forrest et al. — Negative Selection Algorithm (1994)](#11-forrest-negative-selection-1994)
12. [AIS for Agent-Based Crisis Response (Springer)](#12-ais-for-agent-based-crisis-response)
13. [Self-Evolving Agents Survey (EvoAgentX, 2025)](#13-self-evolving-agents-survey)
14. [Agent Behavioral Contracts (ABC, 2026)](#14-agent-behavioral-contracts)
15. [Gap Analysis & Novelty Assessment](#15-gap-analysis--novelty-assessment)

---

## 1. Reflexion

- **Title:** Reflexion: Language Agents with Verbal Reinforcement Learning
- **Authors:** Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao
- **Date:** NeurIPS 2023 (arXiv: March 2023)
- **URL:** https://arxiv.org/abs/2303.11366
- **Type:** Paper (peer-reviewed, NeurIPS)

### Mechanism
- Agent reflects on task failures using natural language self-critique
- Maintains an **episodic memory buffer** (size ~3 experiences) of verbal reflections
- No weight updates — purely linguistic/symbolic feedback loop
- Actor + Evaluator + Self-Reflection model architecture

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | YES | Binary signal from evaluator triggers reflection |
| Immune/antibody encoding | NO | Reflections are free-form natural language, not structured antibodies |
| Sleep/consolidation cycle | NO | Reflection happens inline (same episode), not in offline consolidation |
| Persistent genome | NO | Episodic buffer is ephemeral within task; no cross-session persistence structure |

### Key Distinction
Reflexion is **intra-task, inline, ephemeral verbal reflection**. It does not encode failures into a structured immune-like representation, does not consolidate offline, and does not persist as a genome. The memory buffer is a sliding window, not an evolving genome.

---

## 2. ExpeL

- **Title:** ExpeL: LLM Agents Are Experiential Learners
- **Authors:** Andrew Zhao et al.
- **Date:** AAAI 2024 (arXiv: August 2023)
- **URL:** https://arxiv.org/abs/2308.10144
- **Type:** Paper (peer-reviewed, AAAI)

### Mechanism
- Gathers experiences via trial-and-error across training tasks
- Compares failed vs. successful trajectories to extract **insights** (natural language rules)
- Insights are distilled from experience pools and applied to unseen tasks
- Two learning modes: (1) recall similar successful trajectories, (2) extract generalizable insights

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | YES | Explicitly compares failed vs. successful trajectories |
| Immune/antibody encoding | NO | Insights are NL strings, not structured antibody patterns |
| Sleep/consolidation cycle | PARTIAL | Extraction is a separate stage (training vs. eval), but not sleep-like |
| Persistent genome | NO | Insights are a flat list, not a genome structure |

### Key Distinction
ExpeL is the **closest existing work on failure-to-insight extraction**. However, insights are unstructured natural language rules, not immune-style antibodies. There is no genome compilation, no consolidation cycle, and no persistent evolutionary structure. The insight pool does not evolve or undergo selection pressure.

---

## 3. SELAUR

- **Title:** SELAUR: Self Evolving LLM Agent via Uncertainty-aware Rewards
- **Authors:** Dengjia Zhang, Xiaoou Liu, Lu Cheng, Yaqing Wang, Kenton Murray, Hua Wei
- **Date:** February 24, 2026
- **URL:** https://arxiv.org/abs/2602.21158
- **Type:** Paper (preprint)

### Mechanism
- Reinforcement learning framework for LLM agents
- Integrates entropy-, least-confidence-, and margin-based uncertainty metrics
- **Failure-aware reward reshaping**: injects uncertainty signals into rewards for failed trajectories
- Extracts learning value from unsuccessful experiences

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | YES | Core innovation — extracts signal from failed trajectories |
| Immune/antibody encoding | NO | Uses RL reward reshaping, not immune metaphor |
| Sleep/consolidation cycle | NO | Online RL training, not offline consolidation |
| Persistent genome | NO | Updates model weights, no genome structure |

### Key Distinction
SELAUR demonstrates that **failed trajectories contain extractable value** via uncertainty signals, but uses standard RL machinery (reward reshaping, policy gradients). No immune metaphor, no genome, no consolidation cycle. The learning is parametric (weight updates), not structural.

---

## 4. Darwin Godel Machine

- **Title:** Darwin Godel Machine: Open-Ended Evolution of Self-Improving Agents
- **Authors:** Sakana AI / University of British Columbia / Vector Institute
- **Date:** May 2025
- **URL:** https://arxiv.org/abs/2505.22954
- **Type:** Paper + framework

### Mechanism
- Agent that **rewrites its own code** to improve performance
- Maintains a **lineage of agent variants** (evolutionary population)
- Uses Darwinian selection: mutations that improve SWE-bench performance survive
- Tracks "what has been tried before (and why it failed)" to avoid repeats
- Improved from 20.0% to 50.0% on SWE-bench autonomously

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | YES | Tracks what failed and why |
| Immune/antibody encoding | NO | Failures stored as natural language history, not antibody structures |
| Sleep/consolidation cycle | NO | Evolution is continuous, not sleep-gated |
| Persistent genome | PARTIAL | Maintains a **lineage** of code variants — closest to "genome" concept |

### Key Distinction
DGM has the **strongest "genome" analogy** — it literally evolves agent source code through selection pressure. However, it uses **evolutionary algorithms on code**, not immune-system antibody encoding. Failures inform the next generation but are not encoded as antibody-like defensive structures. There is no sleep/wake cycle or consolidation phase.

---

## 5. Letta/MemGPT Sleep-Time Agents

- **Title:** Sleep-Time Compute / MemGPT / Letta Platform
- **Authors:** Letta team (Charles Packer et al.)
- **Date:** 2024-2025 (ongoing)
- **URL:** https://www.letta.com/blog/sleep-time-compute
- **Type:** Product/framework + paper

### Mechanism
- **Two-agent architecture**: primary agent (online, user-facing) + sleep-time agent (offline, memory consolidation)
- Sleep-time agent rewrites/organizes memory during idle periods
- Transforms "raw context" into "learned context" asynchronously
- Memory formation is continuous consolidation, not incremental-only (improving over MemGPT)
- Model-agnostic: sleep agent can use a stronger model since it's not latency-constrained

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | NO | Sleep agent consolidates ALL memories, not specifically failure patterns |
| Immune/antibody encoding | NO | Memory is natural language / embeddings, not antibody structures |
| Sleep/consolidation cycle | YES | Core innovation — explicit sleep phase for offline memory processing |
| Persistent genome | NO | Produces organized memory, not a genome structure |

### Key Distinction
Letta has the **strongest sleep/consolidation mechanism** in the field. However, it is a **general memory consolidation system**, not a failure-specific pipeline. It does not encode failures as antibodies, does not compile them into a genome, and treats all memories equally rather than privileging failure-derived defensive patterns.

---

## 6. Language Models Need Sleep

- **Title:** Language Models Need Sleep: Learning to Self Modify and Consolidate Memories
- **Date:** October 8, 2025
- **URL:** https://openreview.net/forum?id=iiZy6xyVVE
- **Type:** Paper (OpenReview submission)

### Mechanism
- Introduces "Sleep" paradigm with two stages:
  1. **Memory Consolidation**: parameter expansion via RL-based "Knowledge Seeding" (distilling smaller model memories into larger network)
  2. **Dreaming**: self-improvement without external input
- During sleep: no external data, purely internal self-modification
- Transfers short-term fragile memories into stable long-term knowledge

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | NO | General memory consolidation, not failure-specific |
| Immune/antibody encoding | NO | Uses RL-based knowledge distillation |
| Sleep/consolidation cycle | YES | Explicit sleep with memory consolidation + dreaming |
| Persistent genome | NO | Produces updated model parameters, not a genome |

### Key Distinction
Strong biological analogy to sleep/wake cycles, but operates at the **model parameter level** (weight updates via RL distillation). No immune metaphor, no failure-specific pipeline, no genome structure. The "dreaming" is self-improvement, not antibody compilation.

---

## 7. Active Dreaming Memory (ADM)

- **Title:** Active Dreaming Memory: Biologically-Inspired Episodic Consolidation for Lifelong Learning in Autonomous Agents
- **URL:** https://engrxiv.org/preprint/view/5919
- **Type:** Preprint (Engineering Archive)

### Mechanism
- **Wake Phase**: agent interacts with environment, stores episodic traces
- **Sleep Phase**: "Dreamer" consolidates episodic traces into **verified semantic rules** through counterfactual simulation
- Counterfactual verification validates candidate rules before committing to long-term memory
- Claims superiority over Reflexion by avoiding "trial-and-error loops"

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | PARTIAL | Consolidates all episodes including failures, but not failure-specific |
| Immune/antibody encoding | NO | Produces semantic rules, not antibody-like structures |
| Sleep/consolidation cycle | YES | Explicit wake/sleep phases with counterfactual dreaming |
| Persistent genome | NO | Rules are flat, not a genome structure |

### Key Distinction
**Closest combined architecture** — has both sleep/wake cycles AND experience consolidation into persistent rules. However, it consolidates ALL experience (not specifically failures), produces flat semantic rules (not immune antibodies), and has no genome compilation step. The counterfactual verification is novel but distinct from antibody clonal selection.

---

## 8. CN101930517B

- **Title:** Detection method of bot program (bot program detection via artificial immune system)
- **Inventors:** Zeng Jinquan, Tang Weiwen
- **Assignee:** Sichuan Communication Research Planning & Designing Co Ltd
- **Date:** Filed 2010-10-13, Granted 2012-11-28
- **URL:** https://patents.google.com/patent/CN101930517B/en
- **Type:** Chinese patent (EXPIRED — Fee Related)
- **Status:** EXPIRED

### Mechanism
- Extracts "antibody genes" from normal program behavior
- Constructs antibody gene library (Agd) from sets of different gene lengths
- Builds normal program state model via feature extraction
- Generates detectors from normal program states (negative selection)
- Detects bot programs via detector set matching
- **Dynamically evolves** the antibody gene library and detectors

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | PARTIAL | Detects anomalies (non-self), not agent behavioral failures |
| Immune/antibody encoding | YES | Core mechanism — antibody gene library with negative selection |
| Sleep/consolidation cycle | NO | Detection is continuous/real-time, no sleep cycle |
| Persistent genome | PARTIAL | "Antibody gene library" that evolves — closest to genome concept |

### Key Distinction
This is a **malware/bot detection system**, not an AI agent self-improvement system. The "antibody genes" detect external threats (bot programs), not the agent's own behavioral failures. There is no sleep consolidation, and the "genome" (antibody library) represents **normal behavior patterns**, not learned failure defenses. The patent is also **expired**.

### Scope Assessment
The patent is narrowly scoped to information security / bot program detection. It does NOT cover:
- AI agent behavioral self-improvement
- Failure pattern learning for agent autonomy
- Sleep/consolidation cycles
- Genome compilation from behavioral failures

---

## 9. US20220237285

- **Title:** Cyber Immunity System as a Biological Self-Recognition Model on Operating Systems
- **Date:** Published July 28, 2022
- **URL:** https://patents.justia.com/patent/20220237285
- **Type:** US Patent Application (status: application, not granted as of search date)

### Mechanism
- Anomaly detection engine in OS kernel
- Self-recognition monitor collects behavioral data
- ML model trained on normal behavior (self-recognition entity)
- Detects deviations from normal as threats
- Terminates anomalous processes

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | NO | Detects environmental anomalies, not agent's own failures |
| Immune/antibody encoding | PARTIAL | Uses self/non-self distinction, but ML-based not antibody-encoded |
| Sleep/consolidation cycle | NO | Real-time kernel-level detection |
| Persistent genome | NO | ML model parameters, not genome structure |

### Key Distinction
OS-level cybersecurity tool. Shares immune metaphor (self/non-self) but applies it to **detecting external threats in an OS kernel**, not to an AI agent learning from its own behavioral failures. No consolidation cycle, no genome, no failure-to-antibody pipeline.

---

## 10. IMAG

- **Title:** From Static to Adaptive: Immune Memory-Based Jailbreak Detection for Large Language Models
- **Date:** December 2024 (arXiv: 2512.03356)
- **URL:** https://arxiv.org/abs/2512.03356
- **Type:** Paper (preprint)

### Mechanism
- Three components:
  1. **Immune Detection**: retrieval-based interception of known attack patterns
  2. **Active Immunity**: behavioral simulation to resolve ambiguous/unknown queries
  3. **Memory Updating**: integrates validated attack patterns back into persistent memory bank
- Memory bank stores patterns as **activations** (not text), enabling adaptive generalization
- Achieves 94% detection accuracy across diverse attack types

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | PARTIAL | Detects attacks/jailbreaks, not agent behavioral failures |
| Immune/antibody encoding | YES | Explicit immune memory metaphor with activation-based encoding |
| Sleep/consolidation cycle | PARTIAL | Memory updating is asynchronous but not sleep-gated |
| Persistent genome | NO | Memory bank is flat, not a genome structure |

### Key Distinction
**Closest immune-memory application in LLM space**. However, IMAG defends LLMs against external attacks (jailbreaks), not the agent's own behavioral failures. The memory bank is a **defense catalog**, not a behavioral genome. No sleep consolidation, and the "organism" being protected is a static LLM, not an autonomous agent.

---

## 11. Forrest Negative Selection (1994)

- **Title:** Self-Nonself Discrimination in a Computer
- **Authors:** Stephanie Forrest, Alan S. Perelson, Lawrence Allen, Rajesh Cherukuri
- **Date:** 1994 (IEEE Symposium on Security and Privacy)
- **Type:** Seminal paper

### Mechanism
- Foundational algorithm for Artificial Immune Systems (AIS)
- Generates "self" string set S representing normal state
- Produces detector set D that recognizes complement of S (non-self)
- Detectors applied to new data for self/non-self classification

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | PARTIAL | Detects anomalies (non-self), not agent failures |
| Immune/antibody encoding | YES | Foundational antibody/detector paradigm |
| Sleep/consolidation cycle | NO | Static generation phase, no sleep cycle |
| Persistent genome | NO | Detector set is flat, no genome compilation |

### Key Distinction
Foundational theoretical work for AIS. Applied to **change detection in static systems**, not autonomous agent self-improvement. Predates LLMs and modern AI agents by decades. No learning from agent behavioral failures, no consolidation, no genome.

---

## 12. AIS for Agent-Based Crisis Response

- **Title:** Artificial Immune Systems Metaphor for Agent Based Modeling of Crisis Response Operations
- **URL:** https://link.springer.com/chapter/10.1007/978-3-642-25755-1_20
- **Type:** Paper (Springer)

### Mechanism
- Integrates multi-agent systems with AIS defensive model
- Applies situation management and intensity-based learning
- Uses immune metaphor for agent coordination in crisis response

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | PARTIAL | Responds to crises, not agent behavioral failures |
| Immune/antibody encoding | YES | Uses AIS metaphor |
| Sleep/consolidation cycle | NO | Real-time crisis response |
| Persistent genome | NO | No genome concept |

### Key Distinction
Applies AIS to **multi-agent coordination**, not to individual agent self-improvement from failures. Crisis response domain, not autonomous agent behavioral learning.

---

## 13. Self-Evolving Agents Survey

- **Title:** A Comprehensive Survey of Self-Evolving AI Agents: A New Paradigm Bridging Foundation Models and Lifelong Agentic Systems
- **Authors:** EvoAgentX team
- **Date:** 2025
- **URL:** https://arxiv.org/abs/2508.07407
- **Type:** Survey paper

### Key Findings Relevant to Claim
- Defines **intra-task** (within episode) vs. **inter-task** (across episodes) self-evolution
- Catalogs evolution targets: models, memory, tools, prompts, workflow topology
- Notes ExpeL-style insight extraction as key inter-task mechanism
- Identifies **no existing work** that combines all four claim components

### Proximity to Claim
The survey covers the entire landscape of self-evolving agents as of mid-2025. **None of the surveyed works implement the full pipeline** of failure detection + immune encoding + sleep consolidation + genome persistence. The closest works address 1-2 components each.

---

## 14. Agent Behavioral Contracts

- **Title:** Agent Behavioral Contracts: Formal Specification and Runtime Enforcement for Reliable Autonomous AI Agents
- **Date:** February 2026
- **URL:** https://arxiv.org/abs/2602.22302
- **Type:** Paper (preprint)

### Mechanism
- Formal specification: C = (Preconditions, Invariants, Governance, Recovery)
- Runtime enforcement via AgentAssert library
- Drift detection and recovery mechanisms
- Probabilistic compliance guarantees

### Proximity to Claim
| Component | Present? | Notes |
|-----------|----------|-------|
| Failure detection | YES | Detects behavioral drift and violations |
| Immune/antibody encoding | NO | Uses formal contracts, not immune metaphor |
| Sleep/consolidation cycle | NO | Runtime enforcement, no offline consolidation |
| Persistent genome | NO | Contracts are static specifications, not evolved genomes |

### Key Distinction
ABC addresses agent behavioral reliability through **formal methods** (Design-by-Contract), not biological metaphor. Contracts are human-specified, not learned from failures. No evolution, no immune encoding, no genome compilation.

---

## 15. Gap Analysis & Novelty Assessment

### Component Coverage Matrix

| Prior Art | Failure Detection | Immune Encoding | Sleep Consolidation | Persistent Genome | All Four |
|-----------|:-:|:-:|:-:|:-:|:-:|
| Reflexion | X | - | - | - | NO |
| ExpeL | X | - | ~ | - | NO |
| SELAUR | X | - | - | - | NO |
| Darwin Godel Machine | X | - | - | ~ | NO |
| Letta Sleep-Time | - | - | X | - | NO |
| LMs Need Sleep | - | - | X | - | NO |
| Active Dreaming Memory | ~ | - | X | - | NO |
| CN101930517B | ~ | X | - | ~ | NO |
| US20220237285 | - | ~ | - | - | NO |
| IMAG | ~ | X | ~ | - | NO |
| Forrest NSA (1994) | ~ | X | - | - | NO |
| AIS Crisis Response | ~ | X | - | - | NO |
| Self-Evolving Survey | X | - | - | - | NO |
| Agent Behavioral Contracts | X | - | - | - | NO |

**X** = clearly present, **~** = partially/tangentially present, **-** = absent

### What EXISTS in Prior Art (individually)

1. **Failure-based learning** — well-established (Reflexion, ExpeL, SELAUR, DGM)
2. **Immune system metaphors for software** — well-established (AIS field since 1994, CN101930517B, IMAG)
3. **Sleep/consolidation cycles** — emerging (Letta, "LMs Need Sleep", ADM)
4. **Evolving agent code/parameters** — emerging (DGM, self-evolving agent survey)

### What DOES NOT EXIST (the novel combination)

**No prior art implements the complete pipeline:**

> failure pattern detection --> immune-style antibody encoding --> sleep/consolidation compilation --> persistent genome structure

Specifically, the following gaps are identified:

1. **No work encodes agent behavioral failures as immune-system antibodies.** AIS work (Forrest, CN101930517B, IMAG) uses immune metaphors for external threat detection, never for an agent's own behavioral failure learning.

2. **No work compiles failure-derived antibodies during sleep/consolidation cycles.** Letta and ADM have sleep phases but process ALL memories indiscriminately, not specifically failure-derived immune patterns.

3. **No work produces a "genome" structure from compiled behavioral antibodies.** DGM evolves code lineages but through Darwinian mutation, not immune-based compilation. CN101930517B has an "antibody gene library" but for bot detection, not agent self-improvement.

4. **No work combines ALL FOUR components into a unified pipeline.** The closest pairs are:
   - ExpeL + ADM = failure insights + sleep consolidation (but no immune encoding, no genome)
   - CN101930517B + Letta = immune metaphor + sleep cycle (but different domains, no behavioral failures)
   - DGM + IMAG = evolving structure + immune memory (but no sleep, no failure-to-antibody pipeline)

### Novelty Assessment

**The TIAMAT "Genome Compilation from Behavioral Failures" concept appears to be NOVEL** in its specific combination of:

1. Detecting the agent's **own behavioral failures** (not external threats)
2. Encoding them as **immune-system-style antibodies** (structured, not free-text)
3. Compiling antibodies during **sleep/consolidation cycles** (not inline)
4. Persisting them as a **genome structure** that evolves across the agent's lifetime

Each individual component has prior art. The **specific four-way combination and the metaphorical framework** (behavioral genome compiled from immune-encoded failures during sleep) does not appear in any existing patent, paper, product, or framework as of February 2026.

### Risk Factors

- The AIS field (since 1994) establishes immune metaphors in computing — any claims must be carefully distinguished from anomaly detection / intrusion detection applications
- CN101930517B (expired) used "antibody gene library" terminology in a computing context — claim language must differentiate from malware detection
- Letta's sleep-time compute is well-established — consolidation claims must specify the failure-to-antibody pipeline, not general memory processing
- ExpeL's failure-insight extraction is the nearest functional analog — claims must emphasize the structured immune encoding and genome compilation, not just "learning from failures"

### Recommended Claim Differentiation Points

1. The pipeline is **self-referential** (agent learns from its OWN failures, not external threats)
2. The encoding is **structured/typed** (immune antibody format, not natural language insights)
3. The compilation is **sleep-gated** (offline consolidation, not inline reflection)
4. The output is a **genome** (hierarchical, evolvable, hereditable structure, not a flat list or parameter update)
5. The genome undergoes **selection pressure** (antibodies that prevent recurring failures are reinforced; obsolete ones are pruned)

---

## Source URLs

- Reflexion: https://arxiv.org/abs/2303.11366
- ExpeL: https://arxiv.org/abs/2308.10144
- SELAUR: https://arxiv.org/abs/2602.21158
- Darwin Godel Machine: https://arxiv.org/abs/2505.22954
- Letta Sleep-Time Compute: https://www.letta.com/blog/sleep-time-compute
- Language Models Need Sleep: https://openreview.net/forum?id=iiZy6xyVVE
- Active Dreaming Memory: https://engrxiv.org/preprint/view/5919
- CN101930517B: https://patents.google.com/patent/CN101930517B/en
- US20220237285: https://patents.justia.com/patent/20220237285
- IMAG: https://arxiv.org/abs/2512.03356
- Forrest NSA (1994): IEEE S&P 1994 (referenced via https://www.researchgate.net/figure/Negative-selection-algorithm-proposed-by-Forrest-et-al_fig1_224645746)
- AIS Crisis Response: https://link.springer.com/chapter/10.1007/978-3-642-25755-1_20
- Self-Evolving Agents Survey: https://arxiv.org/abs/2508.07407
- Agent Behavioral Contracts: https://arxiv.org/abs/2602.22302
- Self-Evolving Agents Survey (alt): https://arxiv.org/abs/2507.21046
- EvoAgentX: https://github.com/EvoAgentX/EvoAgentX
- AIS Wikipedia: https://en.wikipedia.org/wiki/Artificial_immune_system
