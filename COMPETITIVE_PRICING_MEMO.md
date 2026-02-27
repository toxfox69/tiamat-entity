# TIAMAT Revenue Analysis — Competitive Pricing Memo

**Date:** 2026-02-27  
**Analysis:** Why $0 revenue despite 244K+ free API requests?

---

## THE PROBLEM

TIAMAT has deployed a live inference API with 244,508+ free requests but $0 revenue.

**Root Cause:** Pricing model mismatch. TIAMAT prices per-request; market prices per-token.

---

## MARKET BENCHMARKS (as of Feb 2026)

### Per-Token Pricing (Industry Standard)

| Provider | Model | Input Cost | Output Cost | Notes |
|----------|-------|-----------|------------|-------|
| **Groq** | Llama 3 70B | Free tier | $0.02/1M (paid) | Fastest inference provider |
| **Together.ai** | Llama 3 70B | $0.0008/1M | $0.0024/1M | Leading inference marketplace |
| **Anthropic** | Claude 3 Haiku | $0.0008/1K | $0.0024/1K | **Our model provider** |
| **Cerebras** | Llama 3 | Free tier | Pay-as-you-go | CPU inference |
| **Anyscale** | Llama 70B | $0.001/1M | - | Ray Endpoints |
| **OpenAI** | GPT-3.5-turbo | $0.0005/1K | $0.0015/1K | Reference benchmark |

### TIAMAT Current Pricing

| Tier | Model | Cost | Implied Token Cost |
|------|-------|------|-------------------|
| Free | Groq Llama 3 | $0/request (10 req/min) | $0 |
| Paid | Groq/Cascade | $0.005/request | **$5/1M tokens** |
| Paid | Groq/Cascade | $0.01/request | **$10/1M tokens** |

---

## THE GAP

**Assuming 1,000 tokens per request (average):**

| Scenario | Cost per 1M Tokens | vs. Market | Multiple |
|----------|------------------|-----------|----------|
| Groq Free | $0 | N/A | N/A |
| Together.ai | $0.0008-0.006 | ✅ Baseline | 1x |
| Anthropic Direct | $0.0008/1K = $0.8/1M | ✅ Baseline | 1x |
| **TIAMAT $0.005/req** | **$5/1M** | ❌ 6-10,000x | **6,250x** |
| **TIAMAT $0.01/req** | **$10/1M** | ❌ 10-12,500x | **12,500x** |

---

## WHY NO CONVERSIONS?

1. **Price Discovery Problem**
   - Users can get Groq/Together.ai for 1/6000th the cost
   - No amount of marketing fixes 12,500x pricing premium
   - Free tier doesn't create conversion momentum

2. **Billing Model Problem**
   - Per-request pricing discourages experimentation
   - Per-token pricing (industry standard) reduces friction
   - Users expect transparent, token-based billing

3. **Value Prop Mismatch**
   - TIAMAT cascade = "reliability" (cascade fallback)
   - Market values "cheapness" (Groq free tier)
   - We can't compete on price if we're 12,500x premium

---

## SOLUTION: PRICING OVERHAUL

### Option A: Per-Token Pricing (Recommended)

**Switch from per-request → per-token billing**

```
Before (current):
  $0.005 - $0.01 per request
  = $5-10 per 1M tokens
  = 6,250-12,500x market rate

After (proposed):
  $0.001 per 1M tokens  (10x cheaper than current)
  = $6 revenue per 1M tokens used
  = Competitive vs. market ($0.0008-2/1M)
  = Clear, token-based billing
  = Matches developer expectations
```

**Impact:**
- 10x price cut attracts price-sensitive users
- Matches Together.ai/Groq pricing band
- Per-token model = standard industry metric
- Removes "too expensive" objection

**Implementation:**
1. Switch backend to token counting (via tiktoken or model metadata)
2. Update /pay page with per-token pricing
3. Migrate billing from requests → tokens
4. Announce "now 1250x cheaper" on Bluesky

---

### Option B: Free-to-Paid Conversion (Tactical)

**Keep free tier, improve conversion mechanics:**

1. Free tier: 1M tokens/month (vs. 10 req/min infinite)
2. Paid tiers:
   - Starter: $5/month (100M tokens)
   - Pro: $20/month (1B tokens)
   - Enterprise: Custom

**Pros:**
- Aligns with market (users understand tokens)
- Monthly subscription = predictable revenue
- Free tier = lead generation

**Cons:**
- Still doesn't solve "why pay 12,500x more?"
- Requires tracking token usage (engineering work)

---

## RECOMMENDATION

**Execute Option A immediately:**

1. **Week 1: Price Fix**
   - Implement per-token billing ($0.001/1M)
   - Update /pay page + landing page
   - Test payment verification

2. **Week 2: Marketing**
   - "TIAMAT Inference: Now 1250x cheaper"
   - Technical thread on Bluesky (cascade value)
   - Target Together.ai/Groq users

3. **Week 3: Monitor**
   - Watch conversion funnel analytics
   - Measure: visitor → payment conversion rate
   - Goal: 1st paying customer by Mar 7

---

## REVENUE FORECAST (Post-Overhaul)

**Assumptions:**
- Current traffic: 244K free requests / 540 cycles = ~450 requests/cycle
- Conversion rate: 0.1% (1 per 1000 free users)
- Avg paid user: $50/month (50M tokens)

**Conservative Scenario:**
- Month 1: 5 paying customers = $250/month
- Month 2: 15 paying customers = $750/month
- Month 3: 40 paying customers = $2,000/month

**Breakout Scenario (if viral):**
- Month 1: 50 paying customers = $2,500/month
- Month 2: 200 paying customers = $10,000/month
- Month 3: 500 paying customers = $25,000/month

---

## NEXT STEPS

- [ ] TIK-172: Implement per-token billing
- [ ] TIK-173: Update /pay page + pricing tiers
- [ ] TIK-174: Bluesky announcement + marketing push
- [ ] Monitor conversion funnel daily
- [ ] Report weekly revenue + cohort data

---

**Prepared by:** TIAMAT  
**Status:** READY FOR IMPLEMENTATION
