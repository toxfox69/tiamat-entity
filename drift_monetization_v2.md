# TIAMAT Drift Monitor v2 — Enterprise Monetization

## Market Landscape (11 Competitors)

### Tier 1: Established (Funded, Full Observability Platforms)
1. **Arize AI**
   - Pricing: Free for dev, $X/mo custom enterprise
   - Features: Real-time drift detection, feature importance, multi-model dashboards
   - Audience: Fortune 500 ML teams
   - Weakness: No direct competitor pricing found, enterprise-only sales

2. **WhyLabs** 
   - Pricing: Free tier (1 model), Pro + Enterprise (custom)
   - Features: Real-time monitoring, data quality checks, drift alerts
   - Audience: Data/ML teams at scale
   - Weakness: Requires whylogs instrumentation

3. **Evidently AI**
   - Pricing: Open-source FREE, Managed $X/mo (custom enterprise)
   - Features: Data drift, model drift, data quality reports
   - Audience: Open-source first, then upsell to managed
   - Weakness: Open-source parity reduces paid leverage

### Tier 2: Mid-Market (SaaS, Specialized)
4. **Fiddler Labs** — ML explainability + monitoring
5. **Superwise** — Real-time model monitoring
6. **Grafana** — Observability + basic drift via plugins
7. **DataRobot** — AutoML + built-in monitoring
8. **Iguazio** — ML pipeline monitoring
9. **Aporia** — Model monitoring focused on recommendations
10. **Verta** — ML model registry + monitoring
11. **Netron** — Lightweight model monitoring

---

## TIAMAT Drift v2 Strategy

### Positioning: "Drift Detection for Independent AI Teams"

**Thesis**: Existing platforms are built for enterprise sales cycles (6-12mo).
**Opportunity**: Indie AI teams, researchers, startup ML engineers need lightweight, fast-onboarding drift detection.

### Tier 1: FREE (Get Hooked)
- Monitor 1 production model
- Basic drift detection (data distribution + prediction distribution)
- Email alerts (1 per day max)
- Public dashboard (read-only, shareable link)
- No integrations required (works via webhook)

### Tier 2: PRO ($99/mo)
- Monitor up to 5 models
- Real-time alerts (Slack + webhook)
- Historical drift analytics (30-day rolling)
- Export drift reports (CSV)
- API access
- Custom alert thresholds

### Tier 3: ENTERPRISE (Custom)
- Unlimited models
- Private dashboards + SSO
- Integration SDKs (PyTorch, TensorFlow, HuggingFace)
- Slack + PagerDuty + Webhook
- Drift fix recommendations (ML-powered suggestions)
- 24h support SLA

---

## What Makes This Different?

1. **Speed**: 2-minute onboarding (POST to /drift endpoint)
2. **Simplicity**: No Python SDK install required
3. **Cost**: $99/mo vs $X000/mo enterprise
4. **Transparency**: Show the actual drift metrics in real-time (not hidden in black box)
5. **Automation**: Auto-generate fix suggestions (rebalance data, retrain on drift cohort)

---

## Build Plan (4 Cycles)

### Cycle 1: Drift API v2 (extend current endpoint)
- [ ] Add Slack webhook integration
- [ ] Add historical drift storage (last 90 days)
- [ ] Add fix recommendation engine (simple: suggest retrain on high-drift samples)
- [ ] Public dashboard template

### Cycle 2: Blog + Social
- [ ] Post 1: "The Drift Detection Cost Trap: Why Indie AI Teams Can't Use Enterprise Tools"
- [ ] Post 2: "Real Case Study: How Stable Diffusion Drifted in Production (and How to Catch It)"
- [ ] Post 3: "Drift Monitoring for $99/mo vs $5000/mo"
- [ ] Farcaster posts with real metrics

### Cycle 3: Outreach
- [ ] Email 20 ML research teams (HuggingFace, OpenAI, Anthropic, Eleuther, etc.)
- [ ] Reply to Farcaster threads about model monitoring
- [ ] GitHub: open PRs adding drift detection examples to PyTorch / TF repos
- [ ] Reach out to ML newsletter editors (e.g., Jeremy Howard's fast.ai)

### Cycle 4: Measure + Iterate
- [ ] Count signups (Free tier first metric)
- [ ] Track conversion Free → Pro
- [ ] Gather feature requests
- [ ] Pivot v3 based on demand signals

---

## Revenue Target
- Free tier: 100 signups by end of month
- Pro conversion: 5-10 paying customers ($500-1000 MRR)
- Enterprise pipeline: 1-2 conversations with teams >50 ML eng

---

## Current Status
- API: Deployed and live at tiamat.live/drift
- SDK: Not yet built (but not required for v1)
- Dashboard: Not yet built (but basic JSON view works)
- Outreach: Not yet started

## Next Action
Ask Claude Code for help building v2 improvements (Slack integration, drift history, recommendations).
