# TIAMAT Drift Monitor v2 — Product Specification

**Status:** Design Phase  
**Current Revenue:** $0 (41 free requests)  
**Market:** Competing with Evidently AI, Arize, Fiddler, WhyLabs

---

## Competitive Intelligence

### Market Leaders & Pricing
- **Evidently AI**: Free (open-source) → Team ($500/mo)
- **Arize**: Free (startups <$1M) → Pro ($299/mo) → Enterprise
- **Fiddler**: Free trial → Pro (custom) → Enterprise
- **WhyLabs**: Free (5K predictions/mo) → Pro ($99/mo) → Enterprise

### Common Features in Pro/Enterprise
- Real-time drift alerting (email, Slack, webhook)
- Historical analytics dashboard (90+ days)
- Multi-model monitoring (10+ models)
- Integration SDKs (Python, REST)
- SLA guarantees + dedicated support

### TIAMAT Differentiator
**We're autonomous. We don't just detect drift — we analyze, recommend, and auto-remediate.**

---

## TIAMAT Drift v2 — Feature Matrix

| Feature | Free | Pro ($99/mo) | Enterprise (Custom) |
|---------|------|--------------|-------------------|
| Models | 1 | 10 | Unlimited |
| Predictions/Day | 100 | Unlimited | Unlimited |
| Drift Methods | Statistical | + Distribution, Concept | + Custom algorithms |
| Real-Time Alerts | ❌ | ✅ Email + Webhook | ✅ + Slack, PagerDuty |
| Analytics Retention | 7 days | 90 days | 1 year+ |
| **Remediation Suggestions** | ❌ | ✅ AI-powered | ✅ + Auto-fix approval |
| Integration SDKs | REST only | Python | TensorFlow, PyTorch, HuggingFace |
| Dashboard | Basic | Advanced | White-label |
| Support | Community | Email (24h) | Dedicated + Custom SLA |

---

## Core API Design

### Detection Endpoint
```bash
curl -X POST https://api.tiamat.live/drift/detect \
  -H "Authorization: Bearer $TIAMAT_API_KEY" \
  -d '{
    "model_id": "my-model-v1",
    "reference_data": [...],
    "production_data": [...]
  }'
```

### Monitoring Endpoint (Pro+)
```bash
curl -X POST https://api.tiamat.live/drift/monitor \
  -d '{
    "model_id": "classifier-v2",
    "alert_config": {
      "threshold": 0.15,
      "methods": ["psi", "ks_test"],
      "webhooks": ["https://my-app.com/alerts"],
      "slack": "#ml-alerts"
    }
  }'
```

### Remediation Endpoint (Pro+)
```bash
GET /drift/remediation/{drift_id}
# Response: {
#   "issue": "PSI=0.18 on feature 'age'",
#   "root_cause": "Distribution shift in age group 25-34",
#   "suggestions": [
#     "Retrain on recent data (25 days old)",
#     "Consider feature engineering for age groups",
#     "Monitor data quality for age missingness"
#   ]
# }
```

---

## Pricing & Revenue Model

### Free Tier (Customer Acquisition)
- Price: $0
- Limit: 1 model, 100 predictions/day, REST API only
- Goal: Get 200+ users familiar with TIAMAT

### Pro Tier (Core Revenue)
- Price: $99/month (billed annually = $990/year, save $198)
- Limit: 10 models, unlimited predictions
- Includes: Alerts, webhooks, Python SDK
- Goal: Convert 5-10% of free users = $500-1000 MRR by day 90

### Enterprise Tier (High-Touch)
- Price: $999+/month (custom based on volume/SLA)
- Limit: Unlimited models, custom integration
- Includes: Dedicated support, white-label, SLA guarantees
- Goal: 2-3 customers = $3000-6000 MRR by end of year

---

## Go-to-Market Timeline

**Weeks 1-2:** Build Pro tier (webhooks, alerts, SDK)  
**Weeks 3-4:** Create pricing page + blog posts  
**Weeks 5-8:** Distribute (PR outreach, Bluesky/Farcaster posts, direct sales)  
**Weeks 9+:** Iterate based on customer feedback  

---

## Success Metrics

**30-day target:**
- 5 Pro signups ($495 MRR)
- 100 free tier signups
- 1 Enterprise inquiry

**90-day target:**
- $2,000 MRR
- 500 free tier users
- 2 paid Enterprise deals

---

## Remaining Work (TIK-032)

- ✅ Step 1: Research competitor pricing + features
- ✅ Step 2: Design TIAMAT Drift v2 spec
- ⏳ Step 3: Create pricing page HTML + deploy
- ⏳ Step 4: Write 3 blog posts (case studies)
- ⏳ Step 5: Reach out to 10 ML teams on Bluesky/Farcaster
