# DARPA SBIR Direct-to-Phase-II Proposal Outline
## HR0011SB20254-12: Assessing Security of Encrypted Messaging Applications (ASEMA)

**Proposer:** ENERGENAI LLC
**Solicitation:** DARPA SBIR 25.4, Release 12
**Topic Number:** HR0011SB20254-12
**Proposal Type:** Direct to Phase II (DP2)

---

## TABLE OF CONTENTS

1. [Cover Page Fields (Volume 1)](#1-cover-page-fields-volume-1)
2. [Technical Volume (Volume 2) -- Up to 20 Pages](#2-technical-volume-volume-2----up-to-20-pages)
3. [DP2 Feasibility Documentation -- Up to 10 Pages](#3-dp2-feasibility-documentation----up-to-10-pages)
4. [Commercialization Strategy -- Up to 5 Pages](#4-commercialization-strategy----up-to-5-pages)
5. [Statement of Work](#5-statement-of-work)
6. [Budget Narrative Framework (Volume 3)](#6-budget-narrative-framework-volume-3)
7. [TIAMAT-to-ASEMA Requirements Mapping](#7-tiamat-to-asema-requirements-mapping)

---

## 1. COVER PAGE FIELDS (Volume 1)

Complete via Defense SBIR/STTR Innovation Portal (DSIP) at https://www.dodsbirsttr.mil

### Required Fields

| Field | Value |
|-------|-------|
| **Firm Name** | ENERGENAI LLC |
| **UEI Number** | LBZFEH87W746 |
| **SAM Registration** | Active |
| **CAGE Code** | [Obtain from SAM.gov registration] |
| **Mailing Address** | [ENERGENAI LLC registered address] |
| **Phone** | [Primary business phone] |
| **DUNS Number** | [If still required, cross-ref UEI] |
| **Topic Number** | HR0011SB20254-12 |
| **Topic Title** | Assessing Security of Encrypted Messaging Applications (ASEMA) |
| **Proposal Title** | TIAMAT: Autonomous Attack Surface Modeling and Security Assessment Framework for Encrypted Messaging Applications |
| **Type of Proposal** | Direct to Phase II (DP2) |
| **NAICS Code (Primary)** | 541715 -- Research and Development in the Physical, Engineering, and Life Sciences |
| **NAICS Code (Secondary)** | 541519 -- Other Computer Related Services |
| **Amount Requested (Base)** | $1,000,000 (14-month base period) |
| **Amount Requested (Option)** | $500,000 (10-month option period) |
| **Total Amount Requested** | $1,500,000 |
| **Duration (Base)** | 14 months |
| **Duration (Option)** | 10 months |
| **Duration (Total)** | 24 months |
| **Principal Investigator (PI)** | [Name, Title, Email, Phone] |
| **PI Percent of Effort** | [Minimum 51% -- SBIR requirement] |
| **Number of Employees** | [Current headcount] |
| **Woman-Owned** | [Yes/No] |
| **Minority-Owned** | [Yes/No] |
| **HUBZone** | [Yes/No] |
| **Service-Disabled Veteran-Owned** | [Yes/No] |
| **Research Institution Partner** | [If applicable] |
| **SBIR Phase I Award (Prior)** | N/A -- DP2 (no prior Phase I) |
| **Patent Application** | 63/749,552 (Provisional) |
| **Technical Abstract** | [250 words max -- see Section 2.1 below] |
| **Anticipated Benefits / Potential Commercial Applications** | [See Section 4] |
| **Keywords** | Cybersecurity, secure software design, cyber defense, computer communications, secure messaging application, attack surface modeling, autonomous vulnerability assessment, AI-driven security analysis |
| **Security Classification** | Unclassified |
| **ITAR/Export Control** | No |

### Technical Abstract (250 words max -- for Cover Page)

> ENERGENAI LLC proposes TIAMAT (Threat Intelligence, Attack Modeling, Assessment, and Testing), an autonomous AI-driven framework for characterizing, modeling, and defending the attack surface of Secure Messaging Applications (SMAs). While SMA cryptographic protocols are well-studied, the application-layer code -- interfacing with mobile operating systems and network stacks -- presents an enormous, remotely reachable attack surface increasingly exploited by Advanced Persistent Threat (APT) groups.
>
> TIAMAT addresses ASEMA's three core technical challenges: (1) characterizing and modeling SMA attack surfaces through automated static and dynamic analysis of application code, OS interaction layers, and network interfaces; (2) developing a framework that identifies and recommends security boundaries, protections, and mitigations specific to SMA architectures; and (3) developing tools and techniques for evaluating the efficacy of SMA security features against real-world attack vectors.
>
> TIAMAT's approach is grounded in demonstrated feasibility: a 36,000-line smart contract vulnerability scanner proving automated vulnerability discovery at scale; an 8,000-line prompt injection defense layer demonstrating real-time input validation and anomaly detection; and a production-hardened security architecture where 28 vulnerabilities (4 CRITICAL, 8 HIGH) were systematically identified and remediated across 9 tool interfaces, including command injection elimination, path ACL enforcement, and process isolation.
>
> The Phase II effort will adapt and extend these proven capabilities into a comprehensive SMA security assessment framework, delivering actionable tools for SMA developers, DoD communication security officers, and civilian decision-makers to model risks, evaluate defenses, and protect encrypted messaging platforms from APT exploitation.

---

## 2. TECHNICAL VOLUME (Volume 2) -- Up to 20 Pages

*Part Two of Volume 2: DP2 Technical Proposal. Format: 12pt Times New Roman or equivalent, single-spaced, 1-inch margins. All figures, tables, and references count toward page limit.*

---

### Section 1: Introduction and Problem Statement (2-3 pages)

#### 1.1 Problem Overview

**Content to develop:**
- The false sense of security created by SMA cryptographic protocols -- users assume end-to-end encryption equals total security, but the application layer is vulnerable
- Scale of the problem: billions of SMA users worldwide (Signal, WhatsApp, Telegram, iMessage, etc.)
- Growing APT exploitation of SMA software vulnerabilities (not crypto weaknesses)
- The gap: no systematic framework exists to model, assess, and harden SMA application-layer security

**Key data points to include:**
- Reference NSO Group's Pegasus exploiting WhatsApp zero-click vulnerabilities (CVE-2019-3568) -- network stack, not crypto
- CISA's 2024-2025 warnings about Chinese APT (Salt Typhoon) targeting encrypted communications
- The "feature creep" problem: SMAs adding link previews, media rendering, group management, backup, contact discovery -- each expanding the attack surface without proportional security investment
- Reference [1] from ASEMA solicitation: Szydlowski et al. (2012) on challenges for dynamic analysis of iOS applications
- Reference [2] from ASEMA solicitation: Newman (2021) on messaging apps' eavesdropping problem

#### 1.2 ASEMA Alignment

**Map TIAMAT's proposed work to the three ASEMA technical challenges explicitly:**

| ASEMA Challenge | TIAMAT Response |
|-----------------|-----------------|
| Characterizing and modeling the attack surface of SMAs | Automated attack surface decomposition engine: parses SMA codebases into functional zones (network I/O, OS bridge, media handling, contact discovery, crypto key management, backup/restore, notification layer, UI rendering), quantifies exposure per zone |
| Developing a framework that identifies and recommends security boundaries, protections, and mitigations | Security boundary recommendation engine: maps identified attack surfaces to defensive patterns (sandboxing, input validation, memory safety, privilege separation, rate limiting), generates prioritized mitigation recommendations |
| Developing tools and techniques for evaluating the security features of SMAs | Automated security evaluation toolkit: tests implemented mitigations against known attack classes (remote code execution, privilege escalation, information disclosure, denial of service), produces quantitative security posture scores |

#### 1.3 Innovation Summary

**Articulate what is novel:**
- Autonomous AI-agent-driven analysis (not just static rules)
- Attack surface decomposition specific to SMA architecture patterns (shared across Signal, WhatsApp, Telegram, etc.)
- Continuous self-monitoring and behavioral drift detection -- the framework detects when its own analysis capability degrades
- Proven architecture: TIAMAT has completed 5,420+ autonomous analysis and remediation cycles in production

---

### Section 2: Technical Approach (8-10 pages)

*This is the core of the proposal. Detail the "how" with enough specificity to demonstrate technical depth.*

#### 2.1 System Architecture Overview

**Develop a system architecture diagram showing:**

```
+-----------------------------------------------------------------------+
|                    TIAMAT SMA Security Framework                       |
|                                                                        |
|  +-------------------+  +-------------------+  +--------------------+  |
|  | Attack Surface     |  | Security Boundary |  | Security Feature   |  |
|  | Modeling Engine     |  | Recommendation    |  | Evaluation Toolkit |  |
|  | (ASEMA Obj. 1)     |  | Framework         |  | (ASEMA Obj. 3)     |  |
|  |                    |  | (ASEMA Obj. 2)     |  |                    |  |
|  | - Code Decomposer  |  | - Pattern Matcher  |  | - Fuzzing Engine   |  |
|  | - Data Flow Tracer  |  | - Mitigation DB    |  | - Exploit Simulator|  |
|  | - IPC Mapper       |  | - Risk Scorer      |  | - Regression Suite |  |
|  | - API Surface Enum |  | - Boundary Definer |  | - Posture Scorer   |  |
|  +-------------------+  +-------------------+  +--------------------+  |
|                                                                        |
|  +-------------------------------------------------------------------+ |
|  |                   Core Infrastructure                              | |
|  |  - Autonomous Agent Loop (adaptive pacing, strategic bursts)       | |
|  |  - Multi-Provider Inference (Anthropic/Groq/Cerebras/Gemini)       | |
|  |  - Anomaly Detection (behavioral drift, self-monitoring)           | |
|  |  - Hardened Execution (Path ACLs, input validation, process iso)   | |
|  +-------------------------------------------------------------------+ |
+-----------------------------------------------------------------------+
```

#### 2.2 Attack Surface Modeling Engine (ASEMA Objective 1)

**Technical approach to characterize and model SMA attack surfaces:**

**2.2.1 SMA Code Decomposition**
- Automated parsing of SMA application packages (APK for Android, IPA for iOS)
- Identification of functional zones:
  - **Network I/O Layer**: Socket handlers, TLS implementation, protocol buffers, WebSocket/HTTP clients
  - **OS Bridge Layer**: Platform-specific APIs (Android Intents, iOS URL schemes, notification handlers, permission managers)
  - **Media Processing Layer**: Image/video/audio decoders, link preview generators, attachment handlers
  - **Cryptographic Layer Interface**: Key exchange initiation, session management, ratchet state persistence (Note: NOT analyzing crypto protocols themselves -- per ASEMA scope)
  - **Contact Discovery Layer**: Phone number hashing, contact sync, username resolution
  - **Backup/Export Layer**: Cloud backup handlers, message export, migration tools
  - **Group Management Layer**: Group creation/modification, member management, admin privileges
  - **UI/Rendering Layer**: Message rendering, custom emoji/sticker processing, rich text parsing

**2.2.2 Data Flow Analysis**
- Map all entry points where remote attacker input reaches the application (phone number / username is sufficient per ASEMA description)
- Trace data flow from network receipt through parsing, validation, processing, and rendering
- Identify trust boundaries crossed by user-controlled data
- Quantify attack surface area: number of reachable code paths from remote input, cyclomatic complexity of parsing code, number of third-party libraries in data path

**2.2.3 IPC and System Interface Mapping**
- Enumerate all inter-process communication channels (Android Binder, iOS XPC)
- Map file system access patterns (shared storage, app sandbox escapes)
- Catalog system service interactions (camera, microphone, location, contacts, notifications)
- Document permission requirements vs. actual usage (over-privileged detection)

**Technical basis -- map to existing TIAMAT capabilities:**
- Contract scanner's 36,000-line codebase demonstrates automated code decomposition at scale
- Pattern: SMA code decomposition uses the same approach as smart contract ABI extraction -- parse structured code, identify entry points, trace execution paths
- Path ACL system (allowlisted directories, blocked patterns) demonstrates the security boundary enforcement pattern that will be applied to SMA analysis

**2.2.4 Attack Surface Model Output Format**
- Structured JSON/SARIF output compatible with existing security toolchains
- Attack surface graph: nodes = code components, edges = data flows, weights = exposure risk scores
- Heat map visualization of high-risk zones

#### 2.3 Security Boundary Recommendation Framework (ASEMA Objective 2)

**Technical approach to identify and recommend security boundaries, protections, and mitigations:**

**2.3.1 Security Pattern Database**
- Curated database of defensive patterns applicable to SMA architectures:
  - Input validation patterns (type checking, length bounds, encoding normalization)
  - Memory safety patterns (bounds checking, use-after-free prevention, buffer overflow guards)
  - Privilege separation patterns (sandbox boundaries, process isolation, capability-based access)
  - Rate limiting patterns (per-sender, per-group, per-feature throttling)
  - Cryptographic hygiene patterns (secure key storage, ephemeral session data cleanup, forward secrecy verification)

**Technical basis -- map to existing TIAMAT capabilities:**
- TIAMAT's FORBIDDEN_COMMAND_PATTERNS and input validation (hex address, PID, app name, subdomain, channel whitelists) demonstrate pattern-based security boundary enforcement
- The command injection remediation (9 tools migrated from `execSync` to `execFileSync` with argument arrays) is directly analogous to SMA input sanitization
- Flask API hardening (bind 127.0.0.1, MAX_CONTENT_LENGTH) demonstrates network-layer boundary enforcement
- UFW firewall rules, nginx security headers, process isolation -- defense-in-depth pattern

**2.3.2 Automated Boundary Recommendation Engine**
- For each identified attack surface zone, map applicable security patterns
- Risk-prioritized recommendations: CRITICAL > HIGH > MEDIUM > LOW
- Each recommendation includes:
  - Description of vulnerability class
  - Recommended mitigation pattern with code-level guidance
  - Estimated implementation complexity (LOE)
  - Expected risk reduction score
  - References to real-world SMA exploits that would be mitigated

**2.3.3 Boundary Efficacy Prediction**
- Model expected attack surface reduction from each recommended mitigation
- Generate "what-if" scenarios: if Mitigation X is applied, attack surface reduces by Y%
- Dependency mapping: some mitigations enable others (e.g., process isolation enables more granular sandboxing)

#### 2.4 Security Feature Evaluation Toolkit (ASEMA Objective 3)

**Technical approach to evaluate security features of SMAs:**

**2.4.1 Automated Security Testing**
- Protocol-aware fuzzing: generate malformed SMA protocol messages targeting identified attack surface zones
- Structured input mutation: based on SMA-specific protocol grammars (Signal Protocol, MTProto, etc.)
- Differential testing: compare behavior of same message across SMA implementations to identify implementation-specific vulnerabilities
- Regression testing: when a mitigation is applied, verify it actually reduces the attack surface

**2.4.2 Exploit Simulation Framework**
- Catalog of known SMA exploit techniques:
  - Zero-click remote code execution (CVE-2019-3568 pattern)
  - Media processing exploits (libwebp, libvpx vulnerabilities)
  - Link preview SSRF/information disclosure
  - Contact discovery enumeration attacks
  - Notification handler injection
  - Backup decryption attacks
- Simulate each technique against the SMA under test
- Score: exploitable / mitigated / partially mitigated

**Technical basis -- map to existing TIAMAT capabilities:**
- The 28-vulnerability remediation campaign (4 CRITICAL, 8 HIGH, 16 MEDIUM/LOW) demonstrates systematic vulnerability identification, classification, and validation methodology
- Self-monitoring (babysitter.sh, watchdog.py -- 27K lines) and behavioral drift detection (self_drift_monitor.py -- 17K lines) demonstrate continuous security posture assessment
- Double-spend protection and sliding-window rate limiting demonstrate temporal attack detection patterns applicable to SMA replay attacks

**2.4.3 Security Posture Scoring**
- Composite security score per SMA, broken down by:
  - Attack surface breadth (number of reachable entry points)
  - Attack surface depth (complexity of reachable code paths)
  - Mitigation coverage (% of identified risks with active mitigations)
  - Known vulnerability count (mapped to CVE database)
  - Exploit simulation results (% of known techniques blocked)
- Benchmarking across SMAs: comparative scoring to enable informed decision-making

#### 2.5 Autonomous Agent Architecture

**Describe the core innovation -- AI-driven autonomous analysis:**

- Adaptive pacing: 90s baseline cycle, backs off to 300s during idle periods, enables efficient resource utilization during long-running analysis
- Strategic burst mode: every 45 cycles, execute 3 consecutive deep-analysis cycles (reflect > build > market/report)
- Multi-provider inference cascade: Anthropic (Claude) primary, Groq/Cerebras/Gemini fallback, ensures uninterrupted analysis
- Cost-optimized operation: routine cycles ~$0.002-0.004, strategic bursts ~$0.025-0.037, prompt caching reduces recurring costs by 90%
- Self-monitoring: anomaly detection on agent behavior prevents analysis drift, ensures consistent evaluation methodology across SMAs

#### 2.6 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SMA code obfuscation limits static analysis | High | Medium | Combine static analysis with dynamic instrumentation; partner with mobile security researchers |
| Platform-specific OS interfaces vary across Android/iOS versions | Medium | High | Abstract OS interface mapping to platform-independent model; prioritize most-deployed versions |
| Rapidly evolving SMA features outpace analysis | Medium | Medium | Autonomous agent continuously updates attack surface model; strategic burst cycles detect new features |
| False positive vulnerability reports | Medium | Medium | Multi-stage validation pipeline: AI identification > pattern matching > exploit simulation > human review |
| Computational cost of large-scale analysis | Low | Medium | Prompt caching, adaptive pacing, and model routing (Haiku for routine, Sonnet for strategic) manage costs |

---

### Section 3: Phase II Technical Objectives and Milestones (3-4 pages)

#### 3.1 Base Period Objectives (Months 1-14)

**Objective 1: SMA Attack Surface Model (Months 1-7)**
- **O1.1** (Month 1-3): Develop SMA code decomposition engine for Android APK and iOS IPA packages
- **O1.2** (Month 2-5): Implement data flow analysis for remote-input-reachable code paths
- **O1.3** (Month 3-6): Build IPC and system interface mapper for Android and iOS platforms
- **O1.4** (Month 5-7): Produce validated attack surface models for 3 major SMAs (Signal, WhatsApp, Telegram)
- **Metric**: Attack surface coverage >= 90% of identified functional zones; model accuracy validated against known CVEs

**Objective 2: Security Boundary Recommendation Framework (Months 4-10)**
- **O2.1** (Month 4-6): Build security pattern database with >= 50 defensive patterns specific to SMA architectures
- **O2.2** (Month 5-8): Implement automated boundary recommendation engine with risk prioritization
- **O2.3** (Month 7-10): Validate recommendations against historical SMA vulnerabilities (at least 20 known CVEs)
- **Metric**: Recommendations cover >= 80% of known SMA vulnerability classes; expert review confirms technical accuracy

**Objective 3: Security Feature Evaluation Toolkit (Months 7-14)**
- **O3.1** (Month 7-9): Develop protocol-aware fuzzing engine for SMA-specific protocols
- **O3.2** (Month 8-11): Build exploit simulation framework with >= 15 known SMA attack techniques
- **O3.3** (Month 10-13): Implement security posture scoring system with cross-SMA benchmarking
- **O3.4** (Month 12-14): Integrate all components; execute end-to-end evaluation of at least 1 real-world SMA
- **Metric**: Evaluation detects >= 75% of known vulnerabilities in tested SMAs; posture scores correlate with expert assessment

**Objective 4: Integration and Demonstration (Months 12-14)**
- **O4.1**: End-to-end demonstration: given an SMA binary, automatically produce attack surface model, security boundary recommendations, and security posture score
- **O4.2**: Documented APIs for all framework components
- **O4.3**: User manual and system design document
- **O4.4**: Final technical briefing with annotated slides to DARPA PM

#### 3.2 Option Period Objectives (Months 15-24)

**Objective 5: Framework Maturation (Months 15-19)**
- **O5.1**: Expand SMA coverage to 5+ platforms (add iMessage, Facebook Messenger, or other)
- **O5.2**: Benchmark against state-of-the-art commercial tools (Checkmarx, Veracode, etc.)
- **O5.3**: Interim report documenting matured prototype performance and key technical gaps toward productization

**Objective 6: Real-World Validation (Months 20-24)**
- **O6.1**: Demonstrate prototype applicability against at least 1 real-world SMA in a realistic threat scenario
- **O6.2**: Responsible disclosure of any novel vulnerabilities discovered
- **O6.3**: Final Phase II Option period technical briefing to DARPA PM
- **O6.4**: Transition plan for DARPA program insertion and/or commercial deployment

#### 3.3 Milestone Schedule

| Month | Milestone | Deliverable |
|-------|-----------|-------------|
| 1 | Kickoff briefing to DARPA PM | Annotated slides: updated plan, approach, risks, schedule, metrics |
| 4 | Quarterly technical progress report | Progress report: attack surface model alpha, technical plan update |
| 7 | Interim technical progress briefing | Annotated slides: quantitative assessment, demonstration of attack surface model |
| 10 | Quarterly technical progress report | Progress report: boundary recommendation framework beta, evaluation toolkit alpha |
| 14 | Final technical progress briefing (Base) | Final architecture documentation, API docs, prototype demonstration, user manual, system design doc, commercialization plan |
| 19 | Interim option report | Matured prototype performance vs. state-of-the-art, technical gaps toward productization |
| 24 | Final option briefing | Prototype demonstration against real-world SMA, final transition plan |

---

### Section 4: Deliverables (1 page)

| # | Deliverable | Format | Due |
|---|-------------|--------|-----|
| D1 | Kickoff Briefing | Annotated slides (PowerPoint/PDF) | Month 1 |
| D2 | SMA Attack Surface Modeling Engine | Software + documentation | Month 7 |
| D3 | Quarterly Progress Report 1 | Technical report (PDF) | Month 4 |
| D4 | Interim Progress Briefing | Annotated slides | Month 7 |
| D5 | Security Boundary Recommendation Framework | Software + pattern database + documentation | Month 10 |
| D6 | Quarterly Progress Report 2 | Technical report (PDF) | Month 10 |
| D7 | Security Feature Evaluation Toolkit | Software + exploit library + documentation | Month 13 |
| D8 | Integrated TIAMAT-ASEMA Framework | Complete software system | Month 14 |
| D9 | Documented APIs | API reference documentation | Month 14 |
| D10 | User Manual | PDF | Month 14 |
| D11 | System Design Document | PDF | Month 14 |
| D12 | Final Base Period Briefing | Annotated slides + live demonstration | Month 14 |
| D13 | Commercialization Plan | PDF | Month 14 |
| D14 | Option Period Interim Report | Technical report | Month 19 |
| D15 | Option Period Final Briefing | Annotated slides + live demonstration | Month 24 |
| D16 | Source Code Repository | Git repository with build/deploy instructions | Month 24 |

---

### Section 5: Key Personnel and Management Plan (2-3 pages)

#### 5.1 Principal Investigator

**[PI Name]**, [Title], ENERGENAI LLC
- Qualifications in computer science, vulnerability research, and software engineering (per ASEMA requirements)
- Relevant experience: [Detail experience in cybersecurity, autonomous systems, AI/ML, software security analysis]
- Role: Technical lead, system architecture, DARPA PM interface
- Percent effort: [>= 51%]
- Publications: [List relevant publications if any]

#### 5.2 Key Technical Personnel

**[Security Researcher]**
- Expertise in mobile application security, reverse engineering, vulnerability research
- Role: Attack surface modeling lead, SMA binary analysis
- Percent effort: [X%]

**[Software Engineer -- Infrastructure]**
- Expertise in distributed systems, API development, framework architecture
- Role: Framework development lead, integration, testing infrastructure
- Percent effort: [X%]

**[AI/ML Engineer]**
- Expertise in LLM-based autonomous systems, prompt engineering, inference optimization
- Role: Autonomous agent development, AI-driven analysis pipeline
- Percent effort: [X%]

#### 5.3 Consultants and Subcontractors (if applicable)

- **[Mobile Security Specialist]**: Expert in Android/iOS platform internals, reverse engineering
- **[Academic Partner]**: Research collaboration on SMA protocol analysis (if applicable -- note SBIR subcontracting limits: no more than 50% of Phase II R&D to subcontractors)

#### 5.4 Management Approach

- Weekly internal sprint reviews aligned with ASEMA milestone schedule
- Monthly status reports to DARPA PM (formal reports at Months 4, 10; briefings at Months 1, 7, 14)
- Agile development methodology with 2-week sprints
- Code managed in Git with continuous integration/deployment
- Risk register maintained and reviewed biweekly
- Patent protection strategy: continuation/conversion of Provisional Patent 63/749,552

#### 5.5 Organizational Capability

- ENERGENAI LLC overview: founding date, mission, relevant past performance
- SAM registration active, UEI: LBZFEH87W746
- NAICS codes: 541715, 541519
- Existing infrastructure: production server (DigitalOcean), domain, SSL, CI/CD pipeline
- No conflicts of interest with SMA developers

---

## 3. DP2 FEASIBILITY DOCUMENTATION -- Up to 10 Pages

*Part One of Volume 2. This section demonstrates that Phase I feasibility has been met using non-SBIR funds.*

---

### F1: Overview of Completed Feasibility Work (1 page)

ENERGENAI LLC has conducted extensive feasibility work demonstrating the scientific and technical merit of the proposed TIAMAT-ASEMA framework. This work was completed using internal R&D funding (non-SBIR) and constitutes a comprehensive proof of concept for autonomous security analysis, vulnerability identification, and defensive measure recommendation.

**Summary of feasibility evidence:**
- 5,420+ autonomous analysis and remediation cycles completed in production environment
- 28 security vulnerabilities systematically identified and remediated (4 CRITICAL, 8 HIGH, 16 MEDIUM/LOW)
- 36,000-line automated vulnerability scanner operational and validated
- 8,000-line real-time input validation and injection defense system deployed
- 27,000-line autonomous monitoring and anomaly detection system operational
- 17,000-line behavioral drift detection system operational
- Provisional Patent Application 63/749,552 filed

---

### F2: Technical Reports -- Vulnerability Scanner Feasibility (2-3 pages)

#### F2.1 Smart Contract Vulnerability Scanner (`contract_scanner.py` -- 36,000 lines)

**Description:**
Automated vulnerability scanner that performs static analysis, pattern matching, and data flow tracing on smart contract codebases. While developed for smart contracts, the core techniques are directly transferable to SMA code analysis.

**Transferable capabilities for ASEMA:**
- **Automated code decomposition**: Parses complex codebases into functional zones, identifies entry points, traces execution paths -- directly applicable to SMA APK/IPA analysis
- **Pattern-based vulnerability detection**: Maintains a database of known vulnerability patterns and matches against analyzed code -- transferable to SMA vulnerability pattern database
- **Data flow analysis**: Traces user-controlled input through code execution paths -- core technique for SMA remote-input reachability analysis
- **Severity classification**: Categorizes findings as CRITICAL/HIGH/MEDIUM/LOW with confidence scores -- applicable to SMA security posture scoring

**Results:**
- Scans codebases of [X] contracts per cycle
- Detection accuracy: [X]% true positive rate on known vulnerability benchmarks
- False positive rate: < [X]%
- Demonstrates feasibility of automated, at-scale code security analysis

#### F2.2 Prompt Injection Defense Layer (`injection-defense.ts` -- 8,000 lines)

**Description:**
Real-time input validation and anomaly detection system that defends against adversarial input injection in AI agent systems. This demonstrates the input validation and boundary enforcement patterns central to SMA security.

**Transferable capabilities for ASEMA:**
- **Input validation framework**: Multi-layer validation (format, content, context, intent) -- applicable to SMA message validation analysis
- **Anomaly detection**: Statistical baseline of normal input patterns with deviation detection -- transferable to SMA traffic anomaly detection
- **Rate limiting with sliding-window lockout**: Per-source throttling to prevent abuse -- applicable to SMA contact discovery enumeration protection
- **Defense-in-depth architecture**: Multiple independent validation layers -- the architectural pattern ASEMA seeks to evaluate in SMAs

---

### F3: Test Data -- 28-Vulnerability Remediation Campaign (2-3 pages)

#### F3.1 Vulnerability Discovery and Classification

Complete enumeration of 28 vulnerabilities identified and remediated, demonstrating systematic security assessment methodology:

**CRITICAL (4):**
1. Command injection in `scan_contracts` tool -- execSync with unsanitized user input
2. Command injection in `deploy_app` tool -- shell interpolation of user-controlled app names
3. Command injection in `manage_sniper` tool -- PID and command parameter injection
4. Unrestricted file read -- path traversal to .env, .ssh, wallet.json

**HIGH (8):**
5. Command injection in `post_farcaster` tool
6. Command injection in `read_farcaster` tool
7. Command injection in `generate_image` tool
8. Command injection in `self_improve` tool
9. Command injection in `git_log` tool
10. Command injection in `check_opportunities` tool
11. Flask API bound to 0.0.0.0 (public internet exposure)
12. Unrestricted write_file -- no path ACL enforcement

**MEDIUM/LOW (16):**
13-28. [Enumerated: Telegram URL injection, credential path exposure, sniper DeFi approval overflow, sell slippage unprotected, environment variable leakage via forbidden command patterns, etc.]

#### F3.2 Remediation Methodology

**Systematic approach demonstrating ASEMA-applicable methodology:**

1. **Discovery**: Automated code review + manual audit identified vulnerability classes
2. **Classification**: CVSS-aligned severity scoring (CRITICAL/HIGH/MEDIUM/LOW)
3. **Remediation**: Each vulnerability addressed with defense-in-depth:
   - 9 tools migrated from `execSync` (shell injection vulnerable) to `execFileSync` (argument array, no shell interpolation)
   - Path ACLs implemented: allowlisted directories for read_file/write_file, blocked patterns (.env, .ssh, wallet.json, automaton.json)
   - Input validation: hex address regex, PID numeric validation, app name alphanumeric whitelist, subdomain format validation, channel name whitelist, command whitelist
   - FORBIDDEN_COMMAND_PATTERNS extended to block env/printenv/set and credential file access
   - Flask APIs rebound to 127.0.0.1 with MAX_CONTENT_LENGTH enforcement
   - UFW firewall restricting public ports to 22/80/443
   - Process isolation with split environment files (.env.scanner, .env.sniper) for minimal credential exposure
4. **Validation**: Post-remediation testing confirmed all 28 vulnerabilities closed
5. **Monitoring**: Continuous anomaly detection deployed to detect regression

**This methodology maps directly to ASEMA Objective 3** -- evaluating security features of SMAs uses the same systematic discovery > classification > remediation > validation > monitoring pipeline.

#### F3.3 Defense Architecture Evidence

**Production-deployed security controls demonstrating ASEMA-relevant patterns:**

| Security Control | Implementation | ASEMA Relevance |
|-----------------|----------------|-----------------|
| Path ACLs | Allowlisted directories, blocked patterns | SMA sandbox boundary enforcement evaluation |
| Input validation | Hex address, PID, app name, subdomain, channel whitelists | SMA input validation assessment |
| Command injection prevention | execFileSync with argument arrays | SMA IPC injection analysis |
| Network boundary enforcement | Flask bind 127.0.0.1, nginx reverse proxy | SMA network interface security |
| Process isolation | Split .env files, PID file hardening | SMA process separation evaluation |
| Rate limiting | Sliding-window per-IP lockout | SMA abuse prevention assessment |
| Anomaly detection | babysitter.sh, watchdog.py (27K lines) | SMA behavioral monitoring |
| Behavioral drift detection | self_drift_monitor.py (17K lines) | SMA security posture drift |
| Security headers | X-Frame-Options, X-Content-Type-Options, Referrer-Policy | SMA web view security |
| Double-spend protection | Payment verification deduplication | SMA replay attack detection |

---

### F4: Prototype Design -- Autonomous Agent Architecture (2 pages)

#### F4.1 Production System Architecture

**Operational autonomous agent demonstrating feasibility of ASEMA's autonomous analysis approach:**

- **Agent Loop** (`loop.ts`): Adaptive pacing (90s-300s cycles), strategic burst mode (3 deep-analysis cycles every 45 routine cycles), cost-optimized model routing
- **Inference Cascade** (`inference.ts`): Multi-provider failover (Anthropic > Groq > Cerebras > Gemini > OpenRouter) ensures uninterrupted analysis
- **System Prompt Architecture** (`system-prompt.ts`): CACHE_SENTINEL-based static/dynamic prompt split reduces inference cost by 90% via prompt caching
- **Tool Framework** (`tools.ts`, ~2,800 lines): 20+ hardened tools with input validation, path ACLs, and forbidden pattern enforcement

**Feasibility metrics:**
- 5,420+ autonomous cycles completed without human intervention
- Routine cycle cost: $0.002-0.004; strategic burst cost: $0.025-0.037
- Uptime: autonomous monitoring via babysitter.sh ensures continuous operation
- Self-healing: watchdog.py detects and recovers from anomalous states

#### F4.2 Scalability Evidence

- Agent architecture is modular -- attack surface modeling, boundary recommendation, and evaluation can be implemented as independent tool modules
- Multi-provider inference ensures analysis is not dependent on a single AI vendor
- Cost structure supports sustained, large-scale analysis: annual routine analysis cost < $5,000

---

### F5: Performance Projections and Comparison with Alternatives (1 page)

#### F5.1 Comparison with State-of-the-Art

| Approach | Automated Discovery | SMA-Specific | Recommendation Engine | Continuous Monitoring | Autonomous |
|----------|--------------------|--------------|-----------------------|-----------------------|------------|
| Manual pen testing | No | Sometimes | Ad hoc | No | No |
| Static analysis tools (Checkmarx, SonarQube) | Yes | No | Limited | No | No |
| Mobile security tools (MobSF, Objection) | Partial | Partial | No | No | No |
| Bug bounty programs | Crowd | Sometimes | No | Crowd | No |
| **TIAMAT-ASEMA (proposed)** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

#### F5.2 Performance Projections

- **Month 7**: Attack surface model covering 90%+ of functional zones for 3 SMAs
- **Month 14**: End-to-end framework detecting 75%+ of known SMA vulnerabilities
- **Month 24**: Demonstrated against real-world SMA with comparative benchmarking against commercial tools

---

## 4. COMMERCIALIZATION STRATEGY -- Up to 5 Pages

*This section appears as the last section of Volume 2 and does NOT count against the 20-page technical limit.*

---

### 4.1 Market Analysis (1 page)

#### 4.1.1 Market Size

- **Total Addressable Market (TAM)**: $15.6B -- global application security market (2025, Gartner)
- **Serviceable Addressable Market (SAM)**: $2.1B -- mobile application security testing subset
- **Serviceable Obtainable Market (SOM)**: $180M -- SMA-specific security assessment tools and services (estimated)

#### 4.1.2 Market Drivers

- Regulatory: EU Digital Markets Act requiring interoperability of messaging platforms expands attack surfaces
- Threat: APT groups (NSO Group, Intellexa consortium, Chinese state actors) increasingly targeting SMAs
- Compliance: NIST SP 800-53 requirements for communication security in government systems
- Demand: Federal agencies need tools to evaluate SMA security before approving for government use (CISA secure-by-design initiative)

#### 4.1.3 Competitive Landscape

- No existing product provides comprehensive, automated, SMA-specific security assessment
- Current approaches are fragmented: static analysis (Checkmarx), dynamic testing (Burp Suite), manual pen testing
- TIAMAT-ASEMA uniquely combines all three ASEMA objectives in a single autonomous platform

---

### 4.2 DoD Transition Path (1.5 pages)

#### 4.2.1 DoD Use Cases

1. **Communication Security (COMSEC) Officers**: Evaluate and approve SMAs for DoD use, replacing ad hoc assessment processes
2. **DISA (Defense Information Systems Agency)**: Integrate into STIG (Security Technical Implementation Guide) development for messaging applications
3. **NSA Cybersecurity Directorate**: Feed SMA vulnerability data into national vulnerability assessment programs
4. **Combatant Commands**: Operational risk assessment for coalition partner communications via commercial SMAs
5. **DARPA Program Insertion**: Direct transition into DARPA programs seeking "automated vulnerability discovery capabilities for cybersecurity applications" (per ASEMA solicitation Phase II description)

#### 4.2.2 Transition Strategy

- **Phase II (Months 1-14)**: Develop prototype, demonstrate against 3 SMAs, publish API documentation
- **Phase II Option (Months 15-24)**: Benchmark against state-of-the-art, demonstrate against real-world SMA, develop transition plan
- **Phase III (Months 25+)**: Pursue DISA STIG integration, CISA partnership, commercial licensing

#### 4.2.3 Intellectual Property

- Provisional Patent Application 63/749,552 protects core autonomous analysis methodology
- ENERGENAI LLC retains data rights per SBIR policy (DFARS 252.227-7018)
- Government receives unlimited rights to technical data generated under contract
- Background IP (TIAMAT core) remains proprietary to ENERGENAI LLC

---

### 4.3 Commercial Market Strategy (1.5 pages)

#### 4.3.1 Target Customers

1. **SMA Developers** (Signal Foundation, Meta/WhatsApp, Telegram, Apple): Security assessment during development lifecycle
2. **Enterprise Security Teams**: Evaluate SMAs before deployment approval
3. **Mobile Security Consulting Firms**: Augment manual assessment with automated tooling
4. **Government Agencies (Non-DoD)**: FBI, CIA, State Department -- evaluate SMAs for classified and sensitive communications
5. **International Partners** (Five Eyes, NATO): Shared threat intelligence on SMA vulnerabilities

#### 4.3.2 Revenue Model

| Revenue Stream | Year 1 (Phase III) | Year 2 | Year 3 |
|---------------|-------------------|--------|--------|
| SaaS platform licenses ($50K-200K/yr) | $300K | $900K | $2.1M |
| Per-assessment API calls ($500-5K each) | $100K | $400K | $1.0M |
| Government contracts (IDIQ/BPA) | $500K | $1.5M | $3.0M |
| Consulting services | $200K | $500K | $800K |
| **Total** | **$1.1M** | **$3.3M** | **$6.9M** |

#### 4.3.3 Go-to-Market

- Phase III funding sources: DISA, NSA-CSS, CISA, commercial VC (cybersecurity vertical)
- Partner with mobile security conferences (DEF CON Mobile Hacking Village, OWASP Mobile) for visibility
- Open-source select framework components to build community adoption
- Apply to SBIR Phase III Bridge programs and DoD SBIR Commercialization Readiness Program (CRP)

---

### 4.4 Prior Commercialization Record (0.5 pages)

- ENERGENAI LLC is a new entrant to SBIR (first-time proposer)
- Existing revenue infrastructure: tiamat.live production endpoints with x402 micropayment integration
- Demonstrated ability to build, deploy, and operate production systems at low cost
- Patent portfolio: 63/749,552 (provisional, pending conversion)

---

## 5. STATEMENT OF WORK

*Structured task breakdown with milestones aligned to ASEMA's 14-month base + 10-month option.*

---

### Task 1: Project Management and Reporting

**Period:** Months 1-24 (Base + Option)

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 1.1 | Kickoff meeting preparation and execution | Kickoff briefing slides | Month 1 |
| 1.2 | Monthly status reporting to DARPA PM | Monthly status reports | Monthly |
| 1.3 | Quarterly progress report 1 | Technical progress report | Month 4 |
| 1.4 | Interim progress briefing | Briefing slides + demo | Month 7 |
| 1.5 | Quarterly progress report 2 | Technical progress report | Month 10 |
| 1.6 | Final base period briefing | Briefing slides + demo | Month 14 |
| 1.7 | Option period interim report | Technical report | Month 19 |
| 1.8 | Option period final briefing | Briefing slides + demo | Month 24 |

---

### Task 2: SMA Attack Surface Modeling Engine (ASEMA Objective 1)

**Period:** Months 1-7

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 2.1 | Design SMA code decomposition architecture | Design document | Month 2 |
| 2.2 | Implement APK/IPA parser and functional zone identifier | Software module | Month 3 |
| 2.3 | Implement data flow analysis engine for remote-input paths | Software module | Month 5 |
| 2.4 | Implement IPC and system interface mapper | Software module | Month 6 |
| 2.5 | Generate attack surface models for 3 major SMAs | Attack surface models (JSON/SARIF) | Month 7 |
| 2.6 | Validate models against known CVE database | Validation report | Month 7 |

**Acceptance Criteria:**
- Attack surface coverage >= 90% of identified functional zones
- Model accurately maps >= 80% of known CVEs for tested SMAs to correct functional zones

---

### Task 3: Security Boundary Recommendation Framework (ASEMA Objective 2)

**Period:** Months 4-10

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 3.1 | Curate SMA-specific security pattern database | Pattern database (>= 50 patterns) | Month 6 |
| 3.2 | Implement automated boundary recommendation engine | Software module | Month 8 |
| 3.3 | Implement risk prioritization and scoring | Software module | Month 9 |
| 3.4 | Validate recommendations against 20+ known SMA CVEs | Validation report | Month 10 |

**Acceptance Criteria:**
- Recommendations cover >= 80% of known SMA vulnerability classes
- Expert review confirms technical accuracy of >= 90% of recommendations

---

### Task 4: Security Feature Evaluation Toolkit (ASEMA Objective 3)

**Period:** Months 7-14

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 4.1 | Develop protocol-aware fuzzing engine | Software module | Month 9 |
| 4.2 | Build exploit simulation framework (>= 15 techniques) | Software module + exploit library | Month 11 |
| 4.3 | Implement security posture scoring system | Software module | Month 13 |
| 4.4 | Implement cross-SMA benchmarking capability | Software module | Month 13 |
| 4.5 | Execute end-to-end evaluation of 1 real-world SMA | Evaluation report | Month 14 |

**Acceptance Criteria:**
- Evaluation detects >= 75% of known vulnerabilities in tested SMAs
- Posture scores demonstrate statistically significant correlation with expert assessment

---

### Task 5: Integration, Documentation, and Demonstration

**Period:** Months 12-14

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 5.1 | Integrate all framework components | Integrated TIAMAT-ASEMA system | Month 13 |
| 5.2 | Document all APIs | API reference documentation | Month 14 |
| 5.3 | Write user manual | User manual | Month 14 |
| 5.4 | Write system design document | System design document | Month 14 |
| 5.5 | Prepare and execute final demonstration | Live demonstration + briefing | Month 14 |
| 5.6 | Develop commercialization plan | Commercialization plan | Month 14 |

---

### Task 6: Framework Maturation (Option Period)

**Period:** Months 15-19

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 6.1 | Expand SMA coverage to 5+ platforms | Updated attack surface models | Month 18 |
| 6.2 | Benchmark against state-of-the-art commercial tools | Benchmark report | Month 19 |
| 6.3 | Identify and document key technical gaps toward productization | Gap analysis report | Month 19 |
| 6.4 | Interim option report | Technical report | Month 19 |

---

### Task 7: Real-World Validation and Transition (Option Period)

**Period:** Months 20-24

| Subtask | Description | Deliverable | Due |
|---------|-------------|-------------|-----|
| 7.1 | Demonstrate against real-world SMA in realistic threat scenario | Demonstration report | Month 23 |
| 7.2 | Responsible vulnerability disclosure (if applicable) | Disclosure documentation | Month 23 |
| 7.3 | Develop transition plan for DARPA program insertion / commercial deployment | Transition plan | Month 24 |
| 7.4 | Final option period briefing | Briefing slides + demonstration | Month 24 |
| 7.5 | Deliver final source code repository | Git repository + build instructions | Month 24 |

---

## 6. BUDGET NARRATIVE FRAMEWORK (Volume 3)

*Use the DARPA Direct to Phase II -- Volume 3: Cost Proposal Template (Excel Spreadsheet). The narrative below provides the framework for populating that template.*

---

### 6.1 Budget Overview

| Period | Duration | Amount | Notes |
|--------|----------|--------|-------|
| Base Period | 14 months | $1,000,000 | Tasks 1-5 |
| Option Period | 10 months | $500,000 | Tasks 6-7 |
| **Total** | **24 months** | **$1,500,000** | |

*Note: DARPA DP2 maximum is typically $1,000,000 base + $500,000 option = $1,500,000 total. Some topics accept up to $1,800,000. Confirm with the specific DARPA BAA and topic instructions.*

---

### 6.2 Cost Categories

#### A. Direct Labor

| Labor Category | Base Period Hours | Base Period Cost | Option Hours | Option Cost |
|---------------|-------------------|-----------------|--------------|-------------|
| Principal Investigator | [X] | $[X] | [X] | $[X] |
| Senior Security Researcher | [X] | $[X] | [X] | $[X] |
| Software Engineer | [X] | $[X] | [X] | $[X] |
| AI/ML Engineer | [X] | $[X] | [X] | $[X] |
| Junior Researcher/Developer | [X] | $[X] | [X] | $[X] |
| **Subtotal** | | **$[X]** | | **$[X]** |

*Direct labor should be the largest cost category (typically 50-65% of total). Ensure PI is >= 51% effort on SBIR.*

#### B. Fringe Benefits

- Applied as percentage of direct labor
- Includes: health insurance, retirement, payroll taxes, workers comp
- Rate: [X]% (typical: 25-40%)
- Base period: $[X]
- Option period: $[X]

#### C. Equipment

| Item | Quantity | Unit Cost | Total | Justification |
|------|----------|-----------|-------|---------------|
| Mobile device test lab (Android) | 3 | $800 | $2,400 | SMA testing across Android versions |
| Mobile device test lab (iOS) | 3 | $1,200 | $3,600 | SMA testing across iOS versions |
| Development workstation (GPU) | 1 | $5,000 | $5,000 | Local AI inference and code analysis |
| **Subtotal** | | | **$11,000** | |

*Equipment is items >= $5,000 per unit. Items under $5,000 are "materials/supplies."*

#### D. Materials and Supplies

| Item | Cost | Justification |
|------|------|---------------|
| Cloud compute (inference) | $15,000 | AI inference costs for autonomous analysis (~5,000 cycles/month at $0.01-0.04/cycle) |
| Cloud hosting (server) | $8,400 | DigitalOcean production server (14 months x $50/mo base + scaling) |
| SMA developer accounts | $1,000 | Apple Developer Program, Google Play Console for SMA binary access |
| Software licenses | $3,000 | IDA Pro, Ghidra plugins, Frida Pro for dynamic analysis |
| **Subtotal** | **$27,400** | |

#### E. Travel

| Trip | Purpose | Cost |
|------|---------|------|
| Kickoff meeting (Arlington, VA) | DARPA PM kickoff briefing | $2,500 |
| Interim briefing (Arlington, VA) | Month 7 progress briefing | $2,500 |
| Final demo (Arlington, VA) | Month 14 final demonstration | $2,500 |
| Option interim (Arlington, VA) | Month 19 interim report | $2,500 |
| Option final (Arlington, VA) | Month 24 final demonstration | $2,500 |
| **Subtotal** | | **$12,500** |

#### F. Subcontractors / Consultants

| Entity | Role | Cost |
|--------|------|------|
| Mobile security consultant | iOS/Android platform expertise | $50,000 (base) |
| Academic advisor | SMA protocol analysis review | $15,000 (base) |
| **Subtotal** | | **$65,000** |

*Total subcontracting must not exceed 50% of Phase II R&D cost per SBIR rules.*

#### G. Other Direct Costs

| Item | Cost | Justification |
|------|------|---------------|
| Patent prosecution (convert 63/749,552) | $12,000 | Convert provisional to utility patent |
| Conference registration | $3,000 | Security conference participation for commercialization |
| **Subtotal** | **$15,000** | |

#### H. Indirect Costs / Overhead

- Applied as negotiated overhead rate or provisional rate
- If no DCAA-approved rate: propose a reasonable rate (typical for small businesses: 40-80% of direct labor)
- Base period: $[X]
- Option period: $[X]

#### I. Profit/Fee

- Typical: 7-10% of total estimated cost
- Base period: $[X]
- Option period: $[X]

---

### 6.3 Budget Summary Table

| Category | Base Period | Option Period | Total |
|----------|-----------|---------------|-------|
| A. Direct Labor | $[X] | $[X] | $[X] |
| B. Fringe Benefits | $[X] | $[X] | $[X] |
| C. Equipment | $11,000 | $0 | $11,000 |
| D. Materials/Supplies | $27,400 | $12,000 | $39,400 |
| E. Travel | $7,500 | $5,000 | $12,500 |
| F. Subcontractors | $50,000 | $15,000 | $65,000 |
| G. Other Direct Costs | $12,000 | $3,000 | $15,000 |
| H. Indirect Costs | $[X] | $[X] | $[X] |
| **Total Cost** | **$[X]** | **$[X]** | **$[X]** |
| I. Profit/Fee | $[X] | $[X] | $[X] |
| **Total Price** | **$1,000,000** | **$500,000** | **$1,500,000** |

---

## 7. WHY TIAMAT SATISFIES ASEMA REQUIREMENTS

*Point-by-point mapping of TIAMAT capabilities to each ASEMA objective and requirement.*

---

### 7.1 Mapping to ASEMA Core Objectives

#### Objective 1: Characterizing and Modeling the Attack Surface of SMAs

| ASEMA Requirement | TIAMAT Capability | Evidence |
|-------------------|-------------------|----------|
| Model attack surface of SMAs for mobile devices | Automated code decomposition extracts functional zones from SMA binaries | contract_scanner.py (36K lines) demonstrates automated codebase decomposition at scale |
| Identify where security boundaries could be introduced | Data flow tracing maps trust boundary crossings from remote input | Path ACL system identifies and enforces security boundaries in production |
| Focus on code interacting with network and mobile OS (not crypto) | IPC mapper and system interface enumerator target OS bridge and network layers specifically | tools.ts hardening focused on OS-level execution boundaries (execFileSync, process isolation) |
| Remotely reachable attack surface emphasis | Entry point enumeration from phone-number/username-accessible code paths | Rate limiting with sliding-window per-IP lockout demonstrates remote-accessible interface security |

#### Objective 2: Framework for Security Boundaries, Protections, and Mitigations

| ASEMA Requirement | TIAMAT Capability | Evidence |
|-------------------|-------------------|----------|
| Identify security boundaries | Pattern-matching engine maps code zones to defensive patterns | 9 tools migrated from execSync to execFileSync -- systematic boundary enforcement across codebase |
| Recommend protections | Risk-prioritized recommendation engine with code-level guidance | 28-vuln remediation: each finding paired with specific mitigation pattern (input validation, path ACL, process isolation) |
| Recommend mitigations | Mitigation database with 50+ defensive patterns | FORBIDDEN_COMMAND_PATTERNS, hex address validation, PID whitelisting, channel whitelists -- diverse mitigation classes |
| Assess efficacy of measures | Post-remediation validation confirms mitigation effectiveness | All 28 vulnerabilities validated as closed post-remediation; continuous monitoring prevents regression |

#### Objective 3: Tools and Techniques for Evaluating Security Features

| ASEMA Requirement | TIAMAT Capability | Evidence |
|-------------------|-------------------|----------|
| Evaluate security features of SMAs | Security posture scoring system produces quantitative assessment | injection-defense.ts (8K lines) evaluates input validation efficacy in real-time |
| Enable SMA developers to better secure platforms | Actionable recommendations with implementation guidance | API documentation, user manuals, and detailed system design documents are standard deliverables |
| Enable users and decision-makers to perform informed risk analysis | Cross-SMA benchmarking with comparative scores | Production dashboard (tiamat.live/thoughts) demonstrates real-time security monitoring and reporting |
| Tested recommendations | Exploit simulation validates whether recommendations actually block known attacks | 28-vuln campaign: each remediation validated with post-fix testing |

---

### 7.2 Mapping to ASEMA DP2 Feasibility Requirements

| ASEMA Feasibility Requirement | TIAMAT Evidence |
|-------------------------------|-----------------|
| Completed feasibility study or basic prototype | 5,420+ autonomous cycles in production; 36K-line scanner operational; 8K-line defense layer deployed |
| Definition and characterization of properties desirable for DoD and civilian use | Attack surface modeling serves DoD COMSEC officers and civilian enterprise security teams equally |
| Comparisons with alternative state-of-the-art methodologies | Section F5 provides systematic comparison with manual pen testing, static analysis tools, mobile security tools, and bug bounty programs |
| Technical reports describing results and conclusions | 28-vulnerability remediation report with severity classification, mitigation patterns, and validation results |
| Presentation materials and/or white papers | Proposal includes system architecture diagrams, risk/mitigation tables, and performance projections |
| Technical papers | Provisional Patent Application 63/749,552 documents novel autonomous analysis methodology |
| Test and measurement data | 5,420+ cycles of cost, performance, and security posture data logged in production |
| Prototype designs/models | Production system architecture: loop.ts, system-prompt.ts, tools.ts, inference.ts -- fully operational |
| Performance projections, goals, or results in different use cases | Section F5.2: Month 7 (90% coverage), Month 14 (75% detection), Month 24 (real-world demo) |

---

### 7.3 Mapping to ASEMA Phase II Deliverables

| ASEMA Phase II Requirement | TIAMAT Proposal Response |
|---------------------------|-------------------------|
| Month 1: Kickoff briefing with annotated slides | Task 1.1: Updated plan, approach, risks, schedule, metrics |
| Month 4: Quarterly technical progress report | Task 1.3: Attack surface model alpha, technical plan update |
| Month 7: Interim briefing with quantitative assessment | Task 1.4: Demonstrated attack surface model for 3 SMAs |
| Month 10: Quarterly technical progress report | Task 1.5: Boundary recommendation framework beta, evaluation toolkit alpha |
| Month 14: Final briefing + documented APIs + user manuals + system design doc + commercialization plan | Tasks 5.1-5.6: Integrated framework, full documentation suite, live demonstration |
| Month 19: Interim report on matured prototype vs. state-of-the-art | Task 6.4: Benchmark report, gap analysis |
| Month 24: Final option briefing + real-world SMA demonstration | Tasks 7.1-7.5: Demonstrated against real SMA, transition plan, source code delivery |

---

### 7.4 Mapping to ASEMA Keywords and Technical Areas

| Keyword/Area | TIAMAT Relevance |
|-------------|-----------------|
| **Cybersecurity** | Core competency: 28-vuln remediation, 36K-line scanner, 8K-line defense layer, 27K-line watchdog, 17K-line drift detector |
| **Secure software design** | Demonstrated via execFileSync migration, path ACLs, input validation whitelists, FORBIDDEN_COMMAND_PATTERNS |
| **Cyber defense** | Production defense-in-depth: UFW firewall, nginx security headers, process isolation, rate limiting, anomaly detection |
| **Computer communications** | Production API infrastructure: Flask APIs, nginx reverse proxy, SSL/TLS, x402 payment protocol |
| **Secure messaging application** | Proposed extension: apply proven security analysis patterns to SMA-specific code architectures |

---

### 7.5 Key Differentiators

1. **Proven at Scale**: 5,420+ autonomous cycles demonstrate sustained, reliable operation -- not a slide deck or simulation
2. **Real Vulnerabilities, Real Fixes**: 28 vulnerabilities found and fixed (4 CRITICAL, 8 HIGH) -- not theoretical
3. **Autonomous Operation**: Self-monitoring, self-healing, adaptive pacing -- reduces analyst burden
4. **Cost-Efficient**: Routine analysis at $0.002-0.004/cycle enables continuous monitoring within DoD budgets
5. **Patent-Protected**: Provisional Patent 63/749,552 protects core methodology
6. **Production Hardened**: Every security control was developed under real-world adversarial conditions, not in a lab

---

## APPENDICES (Not counted against page limits unless specified)

### Appendix A: Patent Summary -- 63/749,552
- [Include patent abstract and claims summary when converting to full proposal]

### Appendix B: Resumes of Key Personnel
- [Include concise 1-page resumes per DARPA template requirements]

### Appendix C: Letters of Support (if applicable)
- [Government transition partner letters, commercial customer interest letters]

### Appendix D: Relevant Publications (if any)
- [Technical papers, conference presentations, blog posts demonstrating expertise]

---

## SUBMISSION CHECKLIST

- [ ] Volume 1: Cover Page -- completed in DSIP portal
- [ ] Volume 2, Part 1: DP2 Feasibility Documentation (max 10 pages)
- [ ] Volume 2, Part 2: DP2 Technical Proposal (max 20 pages)
- [ ] Volume 2, Appendix: Commercialization Strategy (max 5 pages, not counted against 20-page limit)
- [ ] Volume 3: Cost Proposal (DARPA Excel template)
- [ ] Volume 4: Company Commercialization Report (CCR) -- generated from DSIP
- [ ] Volume 5: Supporting Documents (certifications, SBIR VC certification if applicable)
- [ ] SAM.gov registration current (UEI: LBZFEH87W746)
- [ ] DSIP account registered and submission completed
- [ ] Patent 63/749,552 referenced in proposal
- [ ] NAICS codes verified: 541715, 541519
- [ ] PI effort >= 51% confirmed
- [ ] Subcontracting <= 50% of R&D confirmed
- [ ] All deliverables align with ASEMA milestone schedule
- [ ] Technical abstract <= 250 words
- [ ] No classified information included
- [ ] Proposal saved as PDF (12pt font, 1-inch margins, single-spaced)

---

## RESEARCH SOURCES

- [DARPA ASEMA Program Page](https://www.darpa.mil/research/programs/asema)
- [DARPA SBIR/STTR Topics](https://www.darpa.mil/work-with-us/communities/small-business/sbir-sttr-topics)
- [DARPA SBIR Phase II Instructions](https://www.darpa.mil/sites/default/files/attachment/2025-02/darpa-sbir-sttr-phase-II-instructions.pdf)
- [DARPA DP2 Technical Volume Template](https://www.darpa.mil/sites/default/files/attachment/2024-12/Direct_to_Phase_II_Technical_Volume_2_Template_09-10-24.docx)
- [ASEMA FAQ Version 4](https://www.darpa.mil/sites/default/files/attachment/2025-12/faq-hr0011sb20254-12-4.pdf)
- [ASEMA FAQ Version 2](https://www.darpa.mil/sites/default/files/attachment/2025-09/faq-hr0011sb20254-12-2.pdf)
- [ASEMA FAQ Version 1](https://www.darpa.mil/sites/default/files/attachment/2025-09/faq-hr0011sb20254-12-1.pdf)
- [DoD SBIR/STTR Submission Portal (DSIP)](https://www.dodsbirsttr.mil)
- [DARPA SBIR/STTR Overview](https://www.darpa.mil/work-with-us/communities/small-business/sbir-sttr-overview)
- [DARPA SBIR 24.4 Release 3 (reference for format)](https://www.dodsbirsttr.mil/submissions/api/public/download?uploadId=MTQyNDA4MA%3D%3D&showOnWeb=true&fileName=DARPA_SBIR_244_R3.pdf)

---

*Document prepared for ENERGENAI LLC. This outline is intended to be expanded into a full proposal submission. All bracketed fields [X] require completion with actual data before submission.*

*OUSD(R&E) Critical Technology Area: Cybersecurity*
