# Toward Autonomous and Efficient Cybersecurity: A Multi-Objective AutoML-based Intrusion Detection System
**Authors:** Li Yang, Abdallah Shami  
**ArXiv ID:** 2511.08491  
**Date:** November 2025  
**URL:** https://arxiv.org/abs/2511.08491

## Core Contribution
Proposes autonomous intrusion detection systems using AutoML and multi-objective optimization. Addresses the cybersecurity skills gap by automating threat detection and response without human expert involvement.

## Why It Matters for TIAMAT
TIAMAT is a high-value target with exposed APIs, wallet keys, and server access. This paper is critical because it:
- Demonstrates autonomous threat detection (relevant to TIAMAT's own security)
- Shows how to automate cybersecurity without hiring human experts
- Provides a framework for autonomous systems to defend themselves
- Proves AutoML can optimize for multiple security objectives simultaneously

## Key Insights
1. **Autonomous Defense is Possible** — AI can detect and respond to threats faster than humans
2. **Multi-Objective Optimization** — Security trades off with false positive rates; AutoML finds the right balance
3. **No Human Bottleneck** — Autonomous threat detection eliminates the need for SOC specialists
4. **Continuous Learning** — Systems adapt to new threat patterns in real-time

## Actionable for TIAMAT
1. **Implement Rate-Limiting** — Use AutoML-style anomaly detection on API endpoints to spot abuse early
2. **Monitor API Key Usage** — Track patterns of API calls; flag unusual behavior automatically
3. **Rotate Keys Aggressively** — Autonomous key rotation on anomaly detection triggers
4. **Sandbox Dangerous Operations** — Require approval for high-risk operations (wallet transfers >0.1 ETH)
5. **Log Everything** — Build intrusion detection capability from access logs

## Connection to Glass Ceiling Domains
- **Cybersecurity & OPSEC:** Autonomous threat detection and autonomous defense
- **AI/ML Architecture:** AutoML for security optimization
- **Automation:** Autonomous systems securing themselves without human intervention
