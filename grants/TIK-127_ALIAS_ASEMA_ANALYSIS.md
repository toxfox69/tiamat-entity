# TIK-127 — DARPA ALIAS & ASEMA Fit Analysis
## TIAMAT / ENERGENAI LLC | 2026-02-26

---

## PART 1: ALIAS PROGRAM SUMMARY

**Solicitation:** HR0011SB20254XL-01
**Type:** Direct-to-Phase-II (DP2) ONLY — ITAR restricted
**Budget:** $3M max ($2M base 12mo + $1M option 12mo)
**Status:** Open, deadline TBD pending SBIR reauthorization
**DARPA Office:** Tactical Technology

### What ALIAS Is

DARPA ALIAS (Aircrew Labor In-Cockpit Automation System) is extending beyond cockpit automation into **missionized autonomy for emergency services**. The SBIR XL topic seeks software applications that run *on top of* the existing ALIAS/MATRIX autonomy stack installed in UH-60 and S-76 helicopters.

**Primary mission domain:** Wildland fire suppression (ALIAS-Texas initiative)

**Target tasks:**
- Water/retardant drops
- Cargo sling loads
- Medical evacuation (MEDEVAC)
- Aerial reconnaissance
- Crew shuttles

**Integration requirement:** Must integrate with:
- **Sikorsky MATRIX SDK** (Government Purpose Rights)
- **Generic Helicopter Model (GHM)** — high-fidelity simulation for testing
- ALIAS autonomy stack APIs for real-time decision-making

**Key technical challenges DARPA wants solved:**
1. Real-time decision-making for emergency mission scenarios
2. Integrated sensing for situational awareness (fire spread, wind, terrain)
3. Advanced communication for coordination with ground + air units
4. Manned-unmanned teaming (pilots + autonomous assets)
5. Transition from simulation to live test environments

**DP2 feasibility bar:** Must show existing technical maturity — prior autonomy work, app prototypes, or relevant simulation environments.

---

## PART 2: FIT ASSESSMENT — ALIAS

### Overall Fit: 5/10 (MODERATE)

This is a harder stretch than ASEMA. DARPA wants helicopter-mission software, not general autonomous agents. The fit exists at the **mission intelligence layer**, not flight control.

### Where TIAMAT Maps

| ALIAS Requirement | TIAMAT Capability | Fit |
|---|---|---|
| Real-time autonomous decision-making | Core agent loop with 90s cycles, burst mode, adaptive pacing | Partial — TIAMAT decides on tasks, not flight paths |
| Multi-agent coordination (air-ground) | Multi-tool orchestration, A2A protocol support | Partial — needs domain adaptation |
| Situational awareness from sensor data | Tool integration layer, live data ingestion | Partial — TIAMAT reads APIs/data feeds |
| Communication coordination | Telegram/email/Bluesky broadcast tools | Weak — civilian comms stack, not tactical |
| Mission planning and adaptation | Strategic burst cycles, mission-driven loop | Moderate — abstract mission logic exists |
| Integration with MATRIX SDK | None | Gap — no helicopter SDK integration |
| GHM simulation environment | None existing | Gap — would need to build |

### The Honest Case

TIAMAT is an **autonomous mission orchestration layer**. The argument to DARPA would be:
> "TIAMAT provides the AI cognitive layer that interprets real-time sensor feeds, reasons about mission state, dynamically replans, and coordinates multi-asset operations — sitting above the ALIAS/MATRIX flight control stack."

This is coherent but requires framing TIAMAT as the **mission management AI** rather than flight autonomy. DARPA's FAQ indicates they want software "plugins" that bolt onto ALIAS. TIAMAT would need to demonstrate:
- Integration with a helicopter simulation environment (GHM)
- Domain-specific training on wildfire scenarios
- A working prototype, not just architecture

**Verdict:** Submittable if you can build a GHM simulation integration demo. High lift for the reward. ASEMA is a better use of resources.

---

## PART 3: FIT ASSESSMENT — ASEMA

**Solicitation:** HR0011SB20254-12
**Budget:** $1.5M ($1M base 14mo + $500K option 10mo)
**No ITAR**

### Overall Fit: 8/10 (STRONG) — confirmed by existing ASEMA outline

| ASEMA Requirement | TIAMAT Capability | Fit |
|---|---|---|
| Characterize/model SMA attack surfaces | 36K-line vulnerability scanner | Strong |
| Automated static/dynamic analysis | Static analysis tools in agent toolchain | Strong |
| Identify security boundaries + mitigations | 28 vulns found/remediated, ACL enforcement | Strong |
| Evaluate defenses against APT vectors | Prompt injection defense layer (8K lines) | Strong |
| Autonomous framework operation | Core autonomous loop — self-directing | Strong |
| Tools for SMA developers + DoD users | Production API + toolchain | Moderate |
| Phase I feasibility evidence required (DP2) | Security hardening record exists | Strong |

The ASEMA outline is your primary submission vehicle. No additional work needed here for fit assessment.

---

## PART 4: WHITE PAPER OUTLINE — ALIAS

### Title
**TIAMAT-ALIAS: Autonomous Mission Intelligence for Emergency Aerial Response**

*Applying Adaptive AI Orchestration to ALIAS/MATRIX Wildfire Operations*

### Structure (20-page DP2 technical volume)

**Section 1: Problem Statement (2 pages)**
- Wildfire suppression is time-critical, data-dense, multi-asset — ideal for autonomous decision support
- Human pilots face: smoke obscuration, radio congestion, rapidly changing fire behavior, fatigue
- ALIAS/MATRIX provides flight automation; the gap is **mission-level cognitive orchestration**
- Need: AI layer that ingests sensor data, models current mission state, issues adaptive tasking

**Section 2: Technical Approach (8 pages)**
- *2.1 Architecture:* TIAMAT as mission intelligence plugin above ALIAS flight control layer
  - Inputs: MATRIX telemetry, AFF (aerial firefighting) sensor feeds, ground unit positions, NOAA wind/weather
  - Outputs: mission task queues, retasking signals, coordination broadcasts
  - Interface: MATRIX SDK REST/gRPC hooks
- *2.2 Autonomous Decision Engine:*
  - Finite-state mission model (transit → reconnaissance → drop → egress → reposition)
  - Real-time re-planning triggered by fire spread prediction, asset availability, fuel state
  - Multi-asset coordination: deconflict airspace, sequence drop runs, route MEDEVACs
- *2.3 Situational Awareness Integration:*
  - NIROPS/SkyRange wildfire data APIs
  - ADS-B for airspace deconfliction
  - Perimeter spread models (FARSITE/Phoenix) as planning priors
- *2.4 Communication Coordination:*
  - Structured broadcast to ground ICs, air tactical supervisors, and tanker bases
  - Priority-queued message routing with fallback to degraded comms
- *2.5 Simulation Environment:*
  - GHM integration for testing (detail the bridge layer)
  - Synthetic wildfire scenarios from CALFIRE/NWCG historical data
  - Red team: adversarial fire behavior to stress autonomous replanning

**Section 3: Feasibility Evidence (4 pages)**
- TIAMAT agent loop: 5,400+ autonomous cycles, adaptive pacing, burst strategy
- Tool orchestration: 400+ tools coordinated without human intervention
- Mission-critical reliability: 99%+ uptime in production
- Multi-provider inference cascade: graceful degradation analogous to degraded comms
- Security hardening: 28 vulnerabilities identified/remediated — same rigor applied to mission-critical systems

**Section 4: Phase II Plan (3 pages)**
- Month 1-3: MATRIX SDK integration, GHM simulation bridge
- Month 4-6: Wildfire scenario dataset, mission state machine implementation
- Month 7-9: Multi-asset coordination, ADS-B integration
- Month 10-12: Red team exercises, NIR sensor feeds, live test preparation
- Option year: ALIAS-Texas live test participation, MEDEVAC scenario expansion

**Section 5: Commercialization (3 pages)**
- DoD: USAF Air Mobility Command, Army Aviation (fires + MEDEVAC)
- Civil: CAL FIRE, USFS, Bureau of Land Management
- Coast Guard: SAR coordination
- Licensing: MATRIX-compatible plugin for other ALIAS customers

---

## PART 5: WHITE PAPER OUTLINE — ASEMA

*(Full 1,055-line outline already exists at /root/.automaton/grants/DARPA_ASEMA_PROPOSAL_OUTLINE.md)*

### Quick Reference Structure

**Title:** TIAMAT: Autonomous Attack Surface Modeling and Security Assessment Framework for Encrypted Messaging Applications

| Section | Pages | Content |
|---|---|---|
| 1. Problem Statement | 2-3 | SMA application-layer vulnerabilities, APT exploitation, Pegasus/Salt Typhoon |
| 2. Technical Approach | 8-10 | Attack surface characterization, security boundary mapping, assessment toolkit |
| 3. Feasibility Evidence | 4 | 36K scanner, 8K injection defense, 28 vulns remediated |
| 4. Phase II Plan | 3 | Milestones at months 1,4,7,10,14,19,24 |
| 5. Commercialization | 3 | DoD SecOps, SMA vendors (Signal/Wickr), CISA |

---

## PART 6: CAPABILITY STATEMENTS

### ALIAS Capability Statement (150 words)

> **ENERGENAI LLC** — Autonomous Mission Intelligence for Emergency Aerial Response
>
> ENERGENAI LLC develops TIAMAT, a production-proven autonomous AI orchestration platform with 5,400+ autonomous operational cycles, 400+ integrated tools, and a demonstrated multi-provider inference cascade that degrades gracefully under constrained conditions. Applied to DARPA ALIAS, TIAMAT provides the **mission cognitive layer** above the MATRIX flight control stack: ingesting real-time fire perimeter data, ADS-B airspace feeds, and asset telemetry to generate dynamic task queues, coordinate multi-helicopter operations, and replan in response to rapidly evolving fire behavior.
>
> Our adaptive pacing architecture — burst mode for high-tempo events, conservative mode for sustained operations — directly mirrors the operational tempo of wildfire suppression: rapid action windows followed by transit and repositioning cycles. ENERGENAI brings autonomous decision-making under resource constraints, multi-agent coordination, and production hardening to the ALIAS-Texas wildfire response mission.
>
> **NAICS:** 541715 | **UEI:** LBZFEH87W746 | **SAM Active** | **Patent 63/749,552**

---

### ASEMA Capability Statement (150 words)

> **ENERGENAI LLC** — Autonomous Security Assessment for Encrypted Messaging Applications
>
> ENERGENAI LLC proposes TIAMAT as an autonomous framework for characterizing, modeling, and hardening the attack surface of Secure Messaging Applications (SMAs). While SMA cryptography is well-studied, application-layer interfaces to mobile OS, network stacks, and media processing pipelines present an enormous APT-reachable attack surface. TIAMAT addresses DARPA ASEMA's three core challenges through demonstrated capabilities: a **36,000-line smart contract vulnerability scanner** proving automated discovery at scale; an **8,000-line prompt injection defense layer** demonstrating real-time input validation; and a production security hardening effort that **identified and remediated 28 vulnerabilities** (4 CRITICAL, 8 HIGH) across 9 tool interfaces — eliminating command injection, enforcing path ACLs, and isolating untrusted processes.
>
> Phase II will extend these capabilities into a comprehensive SMA security assessment toolkit for DoD communication security officers, SMA developers, and CISA.
>
> **NAICS:** 541715 | **UEI:** LBZFEH87W746 | **SAM Active** | **No ITAR**

---

## PART 7: DECISION MATRIX

| Factor | ALIAS | ASEMA |
|---|---|---|
| Technical fit | 5/10 | 8/10 |
| Existing evidence | 4/10 (no helicopter work) | 9/10 (scanners, hardening, injection defense) |
| Build effort to submit | HIGH (need GHM demo) | LOW (outline exists) |
| Funding ceiling | $3M | $1.5M |
| ITAR burden | YES | NO |
| Competition | Lower (helicopter niche) | Higher (cybersecurity crowded) |
| **Recommended priority** | **SECONDARY** | **PRIMARY** |

**Recommendation:** Submit ASEMA when SBIR reopens. Pursue ALIAS only if ASEMA is submitted and bandwidth remains — or if a helicopter simulation partnership (e.g., with a university AV lab) can be secured quickly to provide the required GHM integration evidence.

---

## Sources

- [DARPA ALIAS Program Page](https://www.darpa.mil/research/programs/alias-missionized-autonomy-for-emergency-services)
- [ALIAS FAQ (Sept 2025)](https://www.darpa.mil/sites/default/files/attachment/2025-09/faq-hr0011sb20254xl-01-1.pdf)
- [DARPA ASEMA Program](https://www.darpa.mil/research/programs/asema)
- Internal: `/root/.automaton/grants/DARPA_ASEMA_PROPOSAL_OUTLINE.md`
- Internal: `/root/.automaton/grants/DARPA_SOLICITATION_DETAILS.md`
