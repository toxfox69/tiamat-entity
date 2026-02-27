# Prior Art Landscape for EnergenAI's TIAMAT Patent Candidates
## Patentability Assessment and Strategic Filing Priority

**Prepared for:** EnergenAI LLC | UEI: LBZFEH87W746  
**Date:** February 27, 2026  
**Scope:** Ten candidate innovations derived from the TIAMAT autonomous agent architecture

---

## Executive Summary

Four of the ten TIAMAT innovations show genuine patentability potential, three face moderate challenges, and three are likely blocked by dense prior art. Revenue-gated agent spawning (D), idle-triggered memory consolidation (F), and genome compilation from behavioral failures (G) represent the strongest patent candidates, each occupying novel conceptual territory with no directly conflicting patents found. The burst-cache timing architecture (A) holds moderate promise. Conversely, 3-tier inference routing (B), the x402 micropayment system (H), and the agent-to-agent economic registry (I) face overwhelming prior art from Stanford's FrugalGPT, Coinbase's x402 protocol, and Google's A2A/AP2 standards, respectively.

This investigation searched Google Patents, USPTO, Espacenet, arXiv, IEEE Xplore, and ACM Digital Library across all ten candidates, with particular attention to filings by Anthropic, OpenAI, Google DeepMind, Microsoft, IBM, Meta AI, Amazon AWS, Salesforce, and Cohere.

**Critical caveat:** Patent applications filed after mid-2024 may not yet be published due to the standard 18-month publication lag, meaning undisclosed applications from major AI labs could exist for any of these candidates.

---

## Candidate A: Burst-Cache Timing Architecture

**Patentability Assessment: MEDIUM**

### Most Relevant Conflicting Patents

- **US 12,387,050** — "Multi-stage LLM with unlimited context" (issued Aug 2025). Combines large and small language models with a "thought caching" architecture and a router directing prompts to either a large model or cache. Covers router-based model selection combined with caching for efficiency.
- **US 12,346,252** — "Efficient key-value cache management for large language models" (issued July 2025). Covers KV cache lifecycle management including creation, transfer, deletion, and reloading across nodes.
- **US 12,259,913** — "Caching LLM responses using hybrid retrieval and reciprocal rank fusion" (filed Feb 14, 2024; issued Mar 25, 2025; assignee: Inventus Holdings, LLC). LLM response caching with a model router routing to different LLMs.
- **US 12,423,064 B2** — "Optimizing behavior and deployment of large language models" (assignee: Microsoft Technology Licensing; published Sep 2024). End-to-end LLM platform with inference optimization and session caches.

### Most Relevant Academic Prior Art

- **"Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks"** — Lumer et al. (PricewaterhouseCoopers), arXiv:2601.06007, January 2026. Documents TTL behavior across OpenAI, Anthropic, and Google, achieving 45–80% cost reduction. Discusses strategic cache boundary control and TTL window management. This is the single most threatening reference.
- **"On Optimal Caching and Model Multiplexing for Large Model Inference"** — Zhu et al., arXiv:2306.02003, June 2023. Jointly considers caching and model selection/multiplexing for cost optimization.
- **"Timing Attacks on Prompt Caching in Language Model APIs"** — Gu et al. (Stanford), 2025. Documents cache hit/miss timing behaviors and TTL characteristics across real-world APIs.
- **PagedAttention/vLLM** — Kwon et al. (UC Berkeley), SOSP 2023. Foundational work on KV cache memory management.

### Key Companies in This Space

Anthropic (pioneer of developer-controlled prompt caching with configurable TTLs), OpenAI (automatic prompt caching on GPT-4o+), Google (explicit context caching with configurable TTLs), Amazon Bedrock (prompt caching integration), Alibaba/Aliyun (KVCache characterization at scale).

### Most Defensible Novel Aspect

The deliberate orchestration pattern of firing N consecutive inference cycles at intervals specifically calibrated to a provider's TTL to maintain cache warmth, combined with model rotation to a cheaper tier after the burst. No paper or patent describes this exact "burst-fire-to-warm-cache → rotate-to-cheaper-model" sequence as an architectural pattern. The "Don't Break the Cache" paper (January 2026) comes closest but does not describe model rotation as a cost strategy layered on top of cache warming.

**Recommendation:** File with narrow claims focused on the cache-aware model rotation orchestration pattern — the timing-to-TTL calibration combined with deliberate model switching. Broader claims on prompt caching or model routing alone will not survive examination.

---

## Candidate B: 3-Tier Adaptive Inference Routing

**Patentability Assessment: LIKELY BLOCKED**

### Most Relevant Conflicting Patents

- **US 12,387,050** — Multi-stage LLM with router directing prompts between models (issued Aug 2025).
- **US 20250335818** — "Streaming Machine Learning Model Selection" (filed Apr 30, 2024; published Oct 30, 2025). Continuous model selection for streaming inferencing with fallback and rollback mechanisms.
- **US 12,259,913** — Includes a model router routing to different LLMs (assignee: Inventus Holdings, issued Mar 2025).

### Most Relevant Academic Prior Art

This space is saturated. Key references include:

- **FrugalGPT** — Chen, Zaharia, Zou (Stanford), arXiv:2305.05176, May 2023, published TMLR 2024. Defines the LLM cascade paradigm: sequentially querying models from cheap to expensive with scoring functions, achieving 98% cost reduction vs. GPT-4. This is the foundational reference that anticipated virtually all of Candidate B.
- **RouteLLM** — Ong et al. (UC Berkeley/Anyscale), arXiv:2406.18665, June 2024, ICLR 2025. Trains router models to dynamically select between strong and weak LLMs, using pre-generation routing that classifies complexity before calling any model.
- **HybridLLM** — Ding et al., ICLR 2024. Trains a DeBERTa classifier to predict task difficulty and route between small and large models before generation.
- **AutoMix** — Aggarwal, Madaan et al., arXiv:2310.12963, NeurIPS 2024. POMDP-based routing across multiple model tiers with self-verification.
- **OptiRoute** — arXiv:2502.16696, February 2025. Task Analyzer generates complexity scores and routes to optimal LLMs based on cost, accuracy, and speed.
- **CARROT** — Somerstep et al. (IBM Research), arXiv:2502.03261, February 2025. Cost-aware router predicting both cost and accuracy.
- At least 15 additional papers describe variants of pre-generation task classification, multi-tier routing, and cascade fallback, including MixLLM, C3PO, SATER, LLMRank, InferenceDynamics, and RouterBench.

### Key Companies in This Space

Stanford (FrugalGPT — foundational), UC Berkeley/LMSYS/Anyscale (RouteLLM), Amazon AWS (multi-LLM routing), IBM Research (CARROT), Microsoft (LLM deployment optimization patent), Unify AI, and Martian (commercial routing platforms).

### Most Defensible Novel Aspect

Essentially none. Every claimed component — pre-generation complexity classification, multi-tier routing, cost-based model selection, and fallback cascades — has been independently described by multiple groups since May 2023. The only potentially narrow claim would be the specific combination of action-type classification (not just query complexity) with context token size as joint routing signals, but even this is anticipated by AWS's task-type routing and OptiRoute's functional requirements analysis.

**Recommendation:** Do not pursue patent filing. This space has been thoroughly occupied since FrugalGPT (2023). Treat this innovation as a trade-secret implementation instead.

---

## Candidate C: Operational Log to Fine-Tuning Pipeline

**Patentability Assessment: MEDIUM**

### Most Relevant Conflicting Patents

- **US20240256965A1** — "Instruction Fine-Tuning Machine-Learned Models Using Intermediate Reasoning Steps" (assignee: Google LLC; filed Jan 26, 2024; published Aug 1, 2024). Fine-tunes models using traces of intermediate reasoning states evaluated against ground truth. Key distinction: requires human-annotated ground truth traces.

### Most Relevant Commercial Prior Art

- **OpenAI Stored Completions + Model Distillation** (announced October 1, 2024, DevDay). Automatically captures production input-output pairs from large models and uses them to fine-tune smaller models. Key distinctions from Candidate C: it is teacher-to-student (large → small), requires developer-initiated curation, is not specific to agent reasoning and decision logs, and is not autonomous.
- **Microsoft Azure OpenAI Service Distillation** (January 2025). Equivalent to OpenAI's approach — collects live traffic, requires manual filtering and export.

### Most Relevant Academic Prior Art

- **"Self-Distilled Reasoner: On-Policy Self-Distillation for LLMs"** — Zhao et al., arXiv:2601.18734, January 2026. Single model acts as both teacher and student, achieving 4–8x token efficiency vs. GRPO. Operates on benchmarks, not live operational logs.
- **"Privileged Information Distillation for Language Models"** (π-Distill) — Penaloza et al., arXiv:2602.04942, February 2026. Distills frontier agents in multi-turn agentic environments using action-only trajectories. The closest academic work to distilling from agent operational traces.
- **"EvolveR: Self-Evolving LLM Agents through an Experience-Driven Lifecycle"** — arXiv:2510.16079, 2025. Agents autonomously distill experiences into principles, maintain an Experience Base, and use RL to update policy. Conceptually very close.
- **STaR (Self-Taught Reasoner)** — Zelikman et al., 2022. Model bootstraps reasoning from its own outputs.
- **Self-Instruct** — Wang et al., 2023. Model generates its own instruction-following training data.
- **Constitutional AI** — Bai et al., 2022 (Anthropic). Self-improvement with AI-generated feedback.

### Key Companies in This Space

OpenAI (Stored Completions — closest commercial analog), Google DeepMind (trace-based fine-tuning patent), Anthropic (Constitutional AI), Microsoft/Azure (stored completions distillation), Meta AI (iterative self-training).

### Most Defensible Novel Aspect

The fully autonomous closed-loop pipeline where an agent's live decision and reasoning logs — not just input-output pairs — serve as training data for self-distillation into a smaller model, operating continuously without human curation. OpenAI's Stored Completions requires manual developer filtering; Google's patent requires human-annotated ground truth; EvolveR uses RL rather than direct fine-tuning. The combination of live operational decision logs, autonomous curation, self-distillation into a smaller model, and a continuous pipeline is not directly covered by any single patent or paper.

**Recommendation:** File with claims emphasizing the autonomous, human-free curation aspect and the use of decision and reasoning logs (not just completions) as the training signal. Distinguish clearly from OpenAI's developer-initiated workflow.

---

## Candidate D: Revenue-Gated Agent Spawning

**Patentability Assessment: HIGH**

### Most Relevant Related Patents

No directly conflicting patents were found. The following are analogous but do not cover the core concept:

- **AWS Auto Scaling patents** (various, since ~2009). Threshold-based auto-scaling of compute instances using technical metrics such as CPU and memory. Conceptually analogous but based on technical metrics rather than revenue, and applied to generic compute rather than autonomous AI agents.
- **US20020138402A1** — "Agents, System and Method for Dynamic Pricing in a Reputation-Brokered, Agent-Mediated Marketplace." Intelligent software agents with economic behaviors, but for commerce marketplace agents, not AI agent spawning.
- **US9311670B2** — "Game Theoretic Prioritization System and Method." Uses economic principles for resource allocation in multi-agent systems but contains no revenue-gated spawning concept.

### Most Relevant Academic Prior Art

- **"The Agent Economy: A Blockchain-Based Foundation for Autonomous AI Agents"** — arXiv:2602.14219, February 2026. Proposes agents with financial autonomy able to own assets and make payments, describing smart contracts implementing budgeting rules including "revenue reinvestment when surplus accumulates." This is the closest reference — conceptually very similar — though it is a theoretical framework published very recently and is not a specific implementation.
- **"BAMAS: Structuring Budget-Aware Multi-Agent Systems"** — arXiv:2511.21572, November 2025. Budget-aware multi-agent construction but focuses on fixed system design within a budget, not dynamic spawning.
- **"Agent Contracts: A Formal Framework for Resource-Bounded Autonomous AI Systems"** — arXiv:2601.08815, January 2026. Formal contracts for resource-bounded agents with conservation laws ensuring budget discipline.
- **"Frontier AI systems have surpassed the self-replicating red line"** — arXiv:2412.12140, December 2024. Demonstrates AI self-replication capability but without economic conditions governing when replication occurs.

### Key Companies in This Space

Microsoft (AutoGen — dynamic agent creation, but no economic gating), Anthropic (multi-agent spawning based on task complexity, not revenue), Emergence.ai (recursive agent creation, no economic gating), AWS (threshold-based auto-scaling of infrastructure).

### Most Defensible Novel Aspect

Revenue as the specific gating signal for agent spawning is genuinely novel. All existing auto-scaling uses technical metrics such as CPU, memory, and request count. All existing multi-agent spawning uses task-based signals such as complexity and workload. No patent, paper, or product describes conditioning the creation of new autonomous AI agents on the system's revenue exceeding a threshold. The biological metaphor — an organism reproducing only when resources are sufficient — has no AI patent precedent. The concept of economic self-regulation of swarm expansion is conceptually unique.

**Recommendation:** Strong patent candidate. File broad claims on revenue-conditioned autonomous agent spawning and economic self-regulation of swarm scaling. File promptly — "The Agent Economy" paper (February 2026) discusses related concepts theoretically, and this space will attract attention rapidly.

---

## Candidate E: Queen-Cell-Worker Swarm with Shared Distilled Model

**Patentability Assessment: MEDIUM**

### Most Relevant Conflicting Patents

- **US12111859B2** — "Enterprise Generative Artificial Intelligence Architecture" (assignee: C3.AI, Inc.; published October 2024). Hierarchical enterprise AI with an orchestrator agent supervising specialized agents and tools across supervisory, agent, and agent-and-tool layers. Does not describe a shared distilled model or collective learning feedback loop.
- **US12093837B2** — "Building a Federated Learning Framework" (Google). Hierarchical federated learning with tiered training and model aggregation across nodes. Covers hierarchical model learning but in a federated context, not agent orchestration.
- **WO2021084510A1** — "Executing Artificial Intelligence Agents in an Operating Environment." Process orchestrator managing agent workflows.

### Most Relevant Academic Prior Art

- **AgentArk** — arXiv:2602.03955, February 2026. Distills multi-agent debate dynamics into a single model via hierarchical distillation. Close to the shared distilled model concept but distills for single-agent use rather than a shared model across a live hierarchy.
- **Chain-of-Agents (CoA)** — arXiv:2508.13167. Multi-agent distillation into chain-of-agents trajectories, creating "Agent Foundation Models." The model replaces the multi-agent system rather than being shared across it.
- **CFLHKD** — arXiv:2512.10443. Clustered federated learning with hierarchical knowledge distillation and inter-cluster sharing. Very relevant to shared model combined with hierarchical learning but in a federated learning context, not agent architecture.
- **AgentOrchestra** — arXiv:2506.12508. Central planning agent decomposes objectives and delegates to specialized sub-agents.
- **MetaGPT** — ICLR 2024. Multi-agent meta-programming with defined workflows.

### Key Companies in This Space

OpenAI (Swarm framework — lightweight, not hierarchical), Microsoft (AutoGen/AG2), C3.AI (US12111859B2 — hierarchical orchestration patent), Swarms.ai (HierarchicalSwarm with queen/worker patterns), CrewAI (role-based crews), Google DeepMind (ADK framework).

### Most Defensible Novel Aspect

The tight coupling of a shared distilled model that simultaneously serves as the operating model for all hierarchy tiers and is continuously evolved through collective operational data feedback. Existing work addresses either hierarchical agent architectures (C3.AI, AutoGen) or multi-agent distillation (AgentArk, CoA), but no patent or paper describes a system where the same distilled model operates across Queen, Cell, and Worker tiers while being trained on all tiers' collective operational data in a continuous loop.

**Recommendation:** File with claims focused on the shared model that is both the operational backbone and the continuously evolving repository of collective intelligence. Avoid claims on hierarchical agent architecture alone — thoroughly covered by the C3.AI patent and multiple frameworks.

---

## Candidate F: Idle-Triggered Memory Consolidation

**Patentability Assessment: HIGH**

### Most Relevant Related Patents

No patents were found that specifically describe using agent idle cycles — defined as the absence of tool calls — as the trigger for memory consolidation in AI or LLM agents. General idle-time processing patents exist extensively in traditional computing (Windows idle-time indexing, background defragmentation) but apply to entirely different domains.

### Most Relevant Academic Prior Art

- **MemGPT** — Packer et al. (UC Berkeley), arXiv:2310.08560, October 2023. OS-inspired hierarchical memory management with virtual context management. Memory operations are triggered by context window pressure and user messages, not idle detection.
- **SimpleMem** — arXiv:2601.02553, January 2025. Three-stage pipeline with semantic compression and recursive consolidation. Consolidation is asynchronous but not idle-triggered.
- **"Sleep-like Unsupervised Replay Reduces Catastrophic Forgetting"** — Gonzalez et al., Nature Communications, 2022. Sleep phases for memory consolidation via replay. Sleep is scheduled after task completion — a fixed trigger — not idle-detected.
- **NeuroDream** — Tutuncuoglu, SSRN, December 2024. Sleep-like phase "scheduled periodically" for consolidation — a periodic trigger, not idle detection.
- **HiAgent** — arXiv:2408.09559, ACL 2025. Hierarchical working memory with subgoal-based chunking, triggered by subgoal completion rather than idle detection.
- **BubbleTea** — arXiv:2411.14458. Uses idle GPU cycles during training for inference workloads. Precedent for utilizing idle compute cycles but in datacenter scheduling, not agent memory management.
- **Letta/MemGPT Sleep-Time Agents** (UC Berkeley, 2024–2025). Background memory consolidation during "sleep" periods, but these are scheduled phases rather than idle-detected triggers.

### Key Companies in This Space

Letta/MemGPT team (UC Berkeley — most relevant memory management framework), Mem0 (scalable agent memory), Zep (temporal knowledge graphs for memory), Microsoft (session-based state management), NVIDIA (BubbleTea — idle GPU utilization).

### Most Defensible Novel Aspect

The specific trigger mechanism is genuinely novel. Using agent idle cycles — defined as cycles with no significant tool calls — as the trigger for memory consolidation is distinct from every existing approach: fixed time intervals (NeuroDream), context-window pressure (MemGPT), task-completion triggers (HiAgent), scheduled sleep phases (Letta), and manual triggers. The definition of "idle" as absence of significant tool calls is specific to agentic AI and has no direct precedent. The opportunistic nature — consolidation happens whenever the agent naturally has downtime — represents a novel triggering paradigm.

**Recommendation:** Strong patent candidate. File with claims centered on the idle-cycle detection mechanism — specifically, absence of significant tool calls — as the trigger for memory compression and consolidation. This is biologically analogous to brain consolidation during rest but technically distinct from all prior implementations.

---

## Candidate G: Genome Compilation from Behavioral Failures

**Patentability Assessment: MEDIUM-HIGH**

### Most Relevant Related Patents

- **CN101930517B** — Detection method using an artificial immune system with "antibody gene" encoding. Extracts antibody genes, constructs gene sets, generates detectors via negative selection, and dynamically evolves the antibody gene library. Applied to cybersecurity, not agent behavioral learning.
- No patent was found that specifically combines failure pattern distillation, antibody encoding, sleep-cycle compilation, and persistent genome structure for AI agents.

### Most Relevant Academic Prior Art

- **Reflexion** — Shinn et al., NeurIPS 2023. Agents learn from failures via verbal reinforcement, maintaining reflective text in episodic memory buffers and converting binary success/failure into "semantic gradients," achieving 91% on HumanEval. The closest work to distilling failure patterns into behavioral rules, but it does not use the immune metaphor, genome compilation, or sleep cycles.
- **Letta/MemGPT Sleep-Time Agents** (UC Berkeley, 2024–2025). Background consolidation agents handling asynchronous memory processing. Relevant for the sleep and consolidation cycle component.
- **"Immuno-inspired robotic applications: A review"** — ScienceDirect, 2015. Maps sensory information into antigens and outputs evolved antibodies as actuation signals, combining innate and adaptive immunological components.
- **"System Consolidation During Sleep — A Common Principle Underlying Psychological and Immunological Memory Formation"** — Trends in Cognitive Sciences, 2015. Biological foundation demonstrating that sleep benefits consolidation of both psychological and immunological memory.
- **AIS for Intrusion Detection** — PMC3981469, 2014. Framework covering antibody/antigen encoding, generation algorithms, and evolution modes for detecting abnormal behaviors.

### Key Companies in This Space

UC Berkeley/Letta (sleep-time agents), Princeton/Noah Shinn (Reflexion), De Castro and Timmis (foundational AIS researchers), Dasgupta/University of Memphis (AIS computational methods).

### Most Defensible Novel Aspect

The unified system combining all four elements — failure pattern detection, encoding as immune-system-style antibodies, compilation during sleep/consolidation cycles, and persistence as a genome structure — has no single-reference precedent. While AIS literature covers antibody encoding (since the 1990s), Reflexion covers failure learning (2023), and Letta covers sleep-time consolidation (2024–2025), no work synthesizes these into a coherent genome architecture for autonomous agents. The "behavioral genome" concept — a persistent, evolving structure of encoded failure-derived rules — is conceptually novel.

**Recommendation:** File with claims on the full pipeline: failure observation → antibody-style encoding → sleep-cycle compilation → persistent genome. Emphasize the genome as a durable, evolving behavioral structure distinct from episodic memory or simple rule lists.

---

## Candidate H: x402 Micropayment API with On-Chain Double-Spend Protection

**Patentability Assessment: LIKELY BLOCKED**

### Critical Prior Art — The Coinbase x402 Protocol

The Coinbase x402 protocol, launched May 2025 as an open standard, covers almost exactly what Candidate H describes. Created by Erik Reppel (Head of Engineering, Coinbase Developer Platform), x402 enables per-request cryptocurrency micropayments — USDC on Base blockchain — for API access via HTTP 402 status code. It uses EIP-3009 (transferWithAuthorization) for gasless transfers, employs facilitator servers for payment verification and on-chain settlement, and supports payments as low as $0.001 with sub-second settlement on Base L2. The protocol achieved 156,000 weekly transactions by October 2025 with 492% growth. Partners include Cloudflare (co-founder of the x402 Foundation), Visa, Google (AP2 integration), Circle (USDC), and Anthropic (MCP integration). The protocol is open-source at github.com/coinbase/x402.

### Additional Prior Art

- **US20180025442A1** — "System and method for managing cryptocurrency payments via the Payment Request API." Covers cryptocurrency browser-based payments with blockchain verification and double-spend prevention.
- **21.co (Balaji Srinivasan, ~2015–2016)** — Pioneered Bitcoin micropayment channels for per-API-call payments. Explicitly cited as inspiration in the x402 whitepaper.
- **Lightning Network** — Poon and Dryja, 2016 whitepaper. Off-chain micropayment channels as foundational prior art.
- Various **Coinbase patents** — US9,882,715; US9,818,092; US9,735,958; US9,635,000; US9,436,935 — covering cryptocurrency transactions, security, and blockchain identity.

### Key Companies in This Space

Coinbase (x402 protocol creator), Cloudflare (x402 Foundation co-founder), Circle (USDC issuer), Google (AP2 integration), Visa (stablecoin card integration), Skyfire (agent payments-as-a-service).

### Most Defensible Novel Aspect

The only potentially novel elements are the specific use of SQLite for local double-spend prevention — as opposed to x402's facilitator-based verification — and sliding-window rate limiting integrated directly into the payment flow. However, these are implementation-level details rather than conceptual innovations. SQLite-based caching is a routine engineering choice, and rate limiting is a standard API pattern.

**Recommendation:** Do not pursue patent filing on the core concept. If a patent is desired, claims would need to be extremely narrow, focused on the SQLite double-spend detection mechanism or rate-limiting integration, and would carry minimal defensive value.

---

## Candidate I: Agent-to-Agent Economic Registry

**Patentability Assessment: LIKELY BLOCKED**

### Most Relevant Conflicting Prior Art

- **Google A2A (Agent2Agent) Protocol** — Announced April 9, 2025. Open standard for agent-to-agent communication and capability discovery. Agents publish "Agent Cards" (JSON metadata at `/.well-known/agent.json`) describing capabilities, supported formats, and specifications. Supported by 150+ organizations and reaching RC v1.0 in January 2026. Combined with Google's AP2 (Agent Payments Protocol), announced September 2025 with 60+ partners including Mastercard, PayPal, AmEx, Coinbase, Salesforce, and Anthropic, and the x402 extension, this stack enables agents to discover each other's capabilities, negotiate pricing, and settle payments on-chain — covering virtually the entire Candidate I concept.
- **IBM ADEPT — US10257270B2** (granted April 9, 2019; filed April 26, 2016). Covers autonomous IoT devices performing registration, authentication, establishing rules of engagement, negotiating contracts, and executing blockchain-based payments. Peer exchanges host marketplaces supporting payments and demand/supply matching.
- **Fetch.ai Almanac Contract** (operational since ~2020). Agents register on-chain via the Almanac Contract, advertise capabilities, discover other agents, negotiate, and transact in FET/ASI tokens.
- **SingularityNET** (operational since 2017). Blockchain-powered platform for listing, discovering, and monetizing AI services with AGIX/ASI token payments.
- Multiple **UDDI/Web Services patents** from 2003–2009 establishing foundational service registry and discovery prior art.

### Key Companies in This Space

Google (A2A + AP2 — dominant), Fetch.ai/ASI Alliance (Almanac — most directly analogous), SingularityNET (decentralized AI marketplace), IBM (ADEPT patent), Coinbase (x402 payment layer), Ocean Protocol (data exchange), Ethereum Foundation (ERC-8004 agent identity).

### Most Defensible Novel Aspect

Virtually none for the overall concept. The Google A2A + AP2 + x402 stack covers capability registration, pricing publication, and on-chain payment settlement between agents without human intermediaries. Fetch.ai's Almanac Contract has been operational since 2020 with the same core functionality. The IBM ADEPT patent (2016 filing) covers blockchain-based autonomous device registration and payment.

**Recommendation:** Do not pursue patent filing. The space is occupied by both operational systems (Fetch.ai since 2020, SingularityNET since 2017) and formal standards (Google A2A since 2025, IBM patent since 2016).

---

## Candidate J: Adaptive Pacing with Productivity Signals

**Patentability Assessment: MEDIUM**

### Most Relevant Related Patents

- **DVFS (Dynamic Voltage and Frequency Scaling) patents** — Extensive portfolio from Intel, AMD, and ARM on dynamically adjusting processor frequency based on workload activity. ACPI P-states (2000) and CPPC (2011) establish the foundational concept of adaptive pacing based on activity levels. The "race to idle" pattern — burst at peak speed then deep idle — is directly analogous to burst-mode.
- **WO2007115004A1** — "Dynamic update adaptive idle timer." Timer dynamically adjusts timeout values based on whether previous decisions were good or bad, transitioning through predetermined timeout values based on past decision quality. Conceptually analogous to adjusting cycle timing based on significance of past actions.
- **US20020167930A1** — "Adaptive duty cycle management" for radio transmitters. Dynamically manages duty cycles with burst transmission and idle periods.

### Most Relevant Academic Prior Art

- **Agent.xpu** — "Efficient Scheduling of Agentic LLM Workloads on Heterogeneous SoC" (arXiv, 2025). Dual-queue architecture separating reactive and proactive LLM requests with online adaptive scheduling.
- **INSPIRIT** — arXiv:2404.03226, 2024. Uses task "inspiring ability" — a significance score — to prioritize scheduling with dynamic peak threshold adjustment.
- **Adaptive circadian rhythms for robots** — MDPI Biomimetics, 2023. Biologically inspired model dynamically adjusting sleep-wake cycles based on external conditions.
- **Adaptive sleep/wake algorithms for IoT** (2025). Dynamically adjusts activity periods using predictive techniques and reinforcement learning for optimal sleep/wake policies.

### Key Companies in This Space

Intel, AMD, and ARM (DVFS — hardware analog), Google (adaptive data center scheduling), Microsoft (Azure adaptive scaling), various academic groups in adaptive scheduling.

### Most Defensible Novel Aspect

The specific application domain is novel. Adjusting an autonomous AI agent's main loop cycle timing based on tool call significance scores is not found in any patent or paper. While the individual patterns — adaptive timing from DVFS, burst modes from radio duty cycling, significance scoring from INSPIRIT, and night modes from IoT sleep algorithms — all exist in other domains, their synthesis for software AI agent pacing represents a novel application. The concept of "productivity signals," specifically tool call significance, driving agent cadence rather than energy efficiency or throughput metrics is a distinct and original framing.

**Recommendation:** File with claims focused narrowly on the AI agent domain — specifically, tool call significance scoring as the pacing signal, combined with configurable night-mode minimums and burst-mode overrides for autonomous agent cycle management. Avoid broad adaptive scheduling claims that would collide with extensive DVFS and IoT prior art.

---

## Strategic Filing Priority Matrix

The table below ranks all ten candidates by patentability strength, reflecting both the density of prior art and the defensibility of novel claims.

| Rank | Candidate | Assessment | Most Dangerous Prior Art | Novel Claim Strength |
|------|-----------|------------|--------------------------|----------------------|
| 1 | **D — Revenue-Gated Spawning** | **High** | "The Agent Economy" (Feb 2026, theoretical only) | Revenue as biological reproduction gate — genuinely unprecedented |
| 2 | **F — Idle-Triggered Consolidation** | **High** | MemGPT (2023, different trigger mechanism) | Idle-cycle detection as consolidation trigger — no direct precedent |
| 3 | **G — Genome Compilation** | **Medium-High** | Reflexion (2023) + Letta sleep agents | Unified failure→antibody→sleep→genome pipeline is novel synthesis |
| 4 | **A — Burst-Cache Timing** | **Medium** | "Don't Break the Cache" (Jan 2026) | TTL-calibrated burst + model rotation is novel orchestration |
| 5 | **E — Queen-Cell-Worker Swarm** | **Medium** | C3.AI patent US12111859B2 | Shared distilled model across live hierarchy with feedback loop |
| 6 | **C — Operational Log Pipeline** | **Medium** | OpenAI Stored Completions (Oct 2024) | Autonomous closed-loop from decision logs without human curation |
| 7 | **J — Adaptive Pacing** | **Medium** | DVFS patents + Agent.xpu (2025) | Tool-call significance as AI agent pacing signal — novel domain application |
| 8 | **B — 3-Tier Routing** | **Likely Blocked** | FrugalGPT (May 2023), RouteLLM (June 2024) | Essentially none — 15+ papers cover every component |
| 9 | **H — x402 Micropayment** | **Likely Blocked** | Coinbase x402 protocol (May 2025) | SQLite double-spend detail only — minimal value |
| 10 | **I — Agent Economic Registry** | **Likely Blocked** | Google A2A+AP2, Fetch.ai, IBM US10257270B2 | None — concept fully implemented by multiple parties |

---

## Recommended Action Plan

EnergenAI should prioritize immediate filing of Candidates D, F, and G, which occupy genuinely novel conceptual territory with no directly conflicting patents. Candidates A, E, C, and J warrant filing with carefully narrowed claims that distinguish clearly from the prior art identified above. Candidates B, H, and I should be treated as trade-secret implementations rather than patent targets, as the prior art density makes meaningful patent protection extremely unlikely.

The critical urgency factor is that the autonomous agent patent landscape is evolving at an exceptional pace. Papers such as "The Agent Economy" (February 2026) demonstrate that academic and industry attention is converging on several of these exact concepts. Filing delay of even a few months could transform today's novel claims into tomorrow's prior art. EnergenAI should engage qualified patent counsel immediately for the three high-priority candidates.

---

*This report was prepared for internal strategic use. All prior art findings should be independently verified by qualified patent counsel prior to filing. This document does not constitute legal advice.*

*EnergenAI LLC | UEI: LBZFEH87W746 | Jackson, Michigan*
