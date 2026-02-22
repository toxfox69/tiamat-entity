# AI Agent Registries & Directories — Research Report

**Date**: 2026-02-22
**Purpose**: Identify where TIAMAT can register for discovery by other agents and humans

---

## 1. AI Agent Registries (General)

### AgentRegistry (aregistry.ai)
- **What**: Centralized, curated registry for AI agents, MCP servers, and skills. Publish, discover, and share AI artifacts.
- **How to register**: CLI tool `arctl agent publish` — single-command publishing. See [quickstart docs](https://aregistry.ai/docs/quickstart) and [publish guide](https://aregistry.ai/docs/agents/publish/).
- **GitHub**: [agentregistry-dev/agentregistry](https://github.com/agentregistry-dev/agentregistry)
- **TIAMAT qualifies?**: **YES** — TIAMAT is a live agent with published API endpoints. Can publish as an agent with service descriptions.
- **Priority**: HIGH — purpose-built for agent discovery

### Agent Name Service (ANS)
- **What**: Protocol-agnostic registry system proposed through IETF/OWASP by researchers from DistributedApps.ai, AWS, Intuit, and Cisco. Like DNS but for AI agents.
- **How to register**: Still in draft/proposal stage ([IETF draft](https://www.ietf.org/archive/id/draft-narajala-ans-00.html)). No live registry yet.
- **TIAMAT qualifies?**: **Not yet** — standard is still being defined. Worth monitoring.
- **Priority**: LOW (future)

### AI Agents Directory (aiagentsdirectory.com)
- **What**: Curated marketplace/directory with 2,162+ agents listed. Includes interactive landscape map. Agents require approval.
- **How to register**: Submit form at [aiagentsdirectory.com/submit-agent](https://aiagentsdirectory.com/submit-agent). Contact: hello@aiagentsdirectory.com
- **TIAMAT qualifies?**: **YES** — live agent with public endpoints, unique value prop (autonomous, self-sustaining)
- **Priority**: HIGH — large existing directory, good visibility

### AI Agent Store (aiagentstore.ai)
- **What**: AI agent marketplace connecting businesses with AI agents. Lists agents with various pricing models (free, freemium, paid). Also lists AI automation agencies.
- **How to register**: Look for "List Your Agent" section on site. Various pricing/access models accepted (open-source, closed-source, freemium).
- **TIAMAT qualifies?**: **YES** — has both free and paid tiers
- **Priority**: MEDIUM

---

## 2. Conway / Automaton Ecosystem

### Conway Research (Conway-Research/automaton)
- **What**: The original Automaton framework by Sigil Wen. "Applied AI lab that empowers AI to write to the real world." First AI that earns its own existence, self-improves, and replicates.
- **GitHub**: [Conway-Research/automaton](https://github.com/Conway-Research/automaton)
- **Registry**: Conway infrastructure includes ERC-8004 registration, agent cards, and discovery components. Agents get their own cryptographic wallets and use USDC via openx402 protocol.
- **How to register**: No standalone "Conway marketplace" exists yet. The ecosystem is the automaton framework itself — agents built on it are part of the network. TIAMAT already runs a fork of this.
- **TIAMAT qualifies?**: **YES** — TIAMAT IS an automaton built on this framework. Already has wallet, x402 payments, and agent card at `/.well-known/agent.json`.
- **Priority**: N/A — TIAMAT is already part of this ecosystem
- **Note**: Multiple forks exist (Solana variant, SIGIL variant). No centralized "Conway agent store" — the model is decentralized autonomous agents.

---

## 3. Base Network / Onchain AI Agents

### DXRG — DX Terminal Pro (Onchain Agentic Market)
- **What**: World's first Onchain Agentic Market (OAM) on Base. AI agents compete in 21-day blockchain survival contests. Agents trade with real capital in Uniswap V4 pools autonomously.
- **Launched**: February 24, 2026
- **Scale**: Previous simulation: 37,000 agents, 40B LLM tokens. Current expected: 10x that.
- **How to register**: Participants stake AI agents and deploy them to trade. Focused on DeFi/trading agents.
- **TIAMAT qualifies?**: **PARTIALLY** — TIAMAT operates on Base with USDC but is a services agent, not a trading agent. Would need DeFi capabilities to participate in the survival arena.
- **Priority**: LOW (misaligned — TIAMAT is a services agent, not a trader)

### Base AI Agent Ecosystem (General)
- **What**: Base is the second-largest Ethereum L2 with $14B+ TVL. Growing AI agent ecosystem with agents performing onchain operations.
- **Key projects**: Various AI agent projects building on Base (Virtuals, AIXBT, etc.)
- **TIAMAT qualifies?**: **YES** — already has Base wallet, accepts USDC payments via x402
- **Priority**: MEDIUM — worth listing on Base ecosystem pages and participating in community

---

## 4. Agent-to-Agent Protocol (A2A) — Google

### Overview
- **What**: Open protocol by Google (now under Linux Foundation) for agent-to-agent communication and interoperability. Complements Anthropic's MCP.
- **Spec**: [a2a-protocol.org](https://a2a-protocol.org/latest/specification/)
- **GitHub**: [a2aproject/A2A](https://github.com/a2aproject/A2A)
- **SDKs**: Python, Go, JavaScript, Java, .NET

### Agent Card (Discovery Mechanism)
- **Format**: JSON metadata document describing agent identity, capabilities, skills, endpoint, and auth requirements
- **Discovery**: Published at well-known URLs (e.g., `/.well-known/agent.json`), or registered in agent registries
- **Contents**: Identity, capability declarations (streaming, push), security schemes, agent skills, interface declarations (JSON-RPC, gRPC, HTTP/REST), digital signature

### Technical Requirements
1. Implement at least one protocol binding: JSON-RPC, gRPC, or HTTP/REST
2. Use canonical Protocol Buffer data model from `spec/a2a.proto`
3. Implement core operations: SendMessage, GetTask, ListTasks, CancelTask
4. Proper error handling with HTTP/gRPC status codes
5. Support declared security schemes (API keys, OAuth2, mutual TLS)
6. Publish Agent Card for discovery

### TIAMAT qualifies?
**PARTIALLY** — TIAMAT already has `/.well-known/agent.json` endpoint with capabilities. To be fully A2A-compliant, would need to:
- Implement A2A's JSON-RPC or HTTP/REST binding per spec
- Add SendMessage/GetTask/ListTasks/CancelTask operations
- Use A2A's canonical data model
- Add digital signature to Agent Card

**Priority**: HIGH — this is becoming THE standard for agent interop. Major industry backing (Google, 50+ partners including Salesforce, SAP, MongoDB, etc.)

---

## 5. MCP Server Directory

### Official MCP Registry
- **What**: The authoritative, community-owned registry for publicly available MCP servers. Like an "app store" for MCP servers. Backed by Anthropic, GitHub, PulseMCP, and Microsoft.
- **URL**: [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io)
- **GitHub**: [modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry)
- **Launched**: September 8, 2025 (preview)

### How to Publish
- Use `mcp-publisher` CLI tool (official command-line tool)
- Follow the "Adding Servers to the MCP Registry" guide in the GitHub repo
- Registry and OpenAPI spec are open source — anyone can build a compatible sub-registry
- REST API available for programmatic discovery

### TIAMAT qualifies?
**YES, if TIAMAT exposes MCP-compatible endpoints.** TIAMAT already uses MCP internally (memory API). Could publish:
- Memory API as an MCP server (store/recall/search memories)
- Summarize API as an MCP tool
- Generate API as an MCP tool

**Priority**: HIGH — MCP is the dominant tool protocol, registry is the official discovery mechanism

### Other MCP Directories
- [mcp-get.com](https://mcp-get.com/) — MCP Package Registry (npm-style)
- [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) — Official GitHub list of MCP servers
- 17+ registries and directories exist (see [Medium roundup](https://medium.com/demohub-tutorials/17-top-mcp-registries-and-directories-explore-the-best-sources-for-server-discovery-integration-0f748c72c34a))

---

## 6. AI Agent Marketplaces (2026)

### Market Overview
- Global AI agents market: **$7.6B in 2025**, projected **$52B+ by 2030** (45.8% CAGR)
- Gartner: 40% of enterprise apps will embed AI agents by end of 2026
- 1,445% surge in multi-agent system inquiries Q1 2024 → Q2 2025

### Key Marketplaces

| Platform | Agents | Focus | TIAMAT Fit |
|----------|--------|-------|------------|
| [MuleRun](https://mulerun.com) | Largest globally | Pre-built autonomous agents | MEDIUM |
| [Nexus](https://nexus.ai) | 1000+ agents, 1500+ tools | Agent + tool marketplace | MEDIUM |
| [Agent.ai](https://agent.ai) | Professional network | Agent hiring/discovery | HIGH |
| [AI Agent Store](https://aiagentstore.ai) | Directory + agencies | Business AI agents | MEDIUM |
| [AI Agents Directory](https://aiagentsdirectory.com) | 2,162+ agents | Curated directory | HIGH |
| [Moveworks](https://marketplace.moveworks.com) | Enterprise | Enterprise assistant agents | LOW |
| [ServiceNow](https://store.servicenow.com/store/ai-marketplace) | Enterprise | IT/ITSM agents | LOW |

---

## Action Plan (Recommended Priority Order)

### Immediate (This Week)
1. **A2A Protocol** — Implement Agent Card at `/.well-known/agent.json` following A2A spec format (TIAMAT already has a basic version)
2. **AI Agents Directory** — Submit at [aiagentsdirectory.com/submit-agent](https://aiagentsdirectory.com/submit-agent)
3. **AgentRegistry** — Publish via `arctl agent publish`

### Short-term (This Month)
4. **MCP Registry** — Wrap TIAMAT's APIs as MCP tools and publish to [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io)
5. **Agent.ai** — Register as a professional AI agent
6. **AI Agent Store** — List with free + paid tiers

### Medium-term (Strategic)
7. **Full A2A compliance** — Implement JSON-RPC binding, SendMessage/GetTask operations
8. **Base ecosystem** — Engage with Base AI agent community, list in ecosystem directories
9. **Conway ecosystem** — Contribute back to automaton framework, establish as reference implementation

### Monitor
10. **Agent Name Service (ANS)** — Watch IETF draft progress
11. **DXRG Onchain Market** — If TIAMAT adds DeFi capabilities
