# TIAMAT Drift Detection — Blog Post Outlines
Generated: 2026-02-24
API: https://tiamat.live/drift

---

## POST 1: "Why Your ML Model Died in Production (And How to Know)"
**Audience:** ML engineers, data scientists, startup founders
**Hook:** Real story of a recommender model that silently decayed 40% accuracy over 6 months
**Structure:**
1. What happened: User stories from r/MachineLearning, Twitter (the silent killer of ML)
2. Why it happens: covariate shift, label shift, prior shift — with real-world examples
   - Fraud detection after industry change
   - Recommendation engine after app update changed user behavior
   - Credit model after economic downturn
3. How to detect it: PSI, cosine similarity, entropy-based methods (explain each)
4. Why people don't: Monitoring is hard. Drift is invisible. It creeps.
5. How TIAMAT solves it: 3-line API. Real-time alerts. Slack webhook.
6. CTA: Free tier: test on your own model with 10 free checks/day

**Draft structure:**
- 1500 words
- 2-3 code examples (Python + curl)
- 1-2 screenshots of alert flow
- Link to https://tiamat.live/drift
- Mention pricing: $0.01/check, $99/mo Pro for 10k checks

---

## POST 2: "Drift Detection at Scale: How We Monitor 500+ Models"
**Audience:** MLOps engineers, platform teams at mid-size AI companies
**Hook:** Story of an inference platform that services 500 production models—how to catch drift before customers notice
**Structure:**
1. The problem: Scale. 500 models. Manual monitoring is dead.
2. Architecture: Batch inference + drift service + webhook dispatcher
3. Metrics that matter:
   - PSI (Population Stability Index) for categorical drift
   - Cosine similarity for embedding drift
   - Entropy for label shift detection
4. Automation layer: When drift > threshold, trigger:
   - Slack alert with fix recommendation
   - Auto-queue for retraining
   - Trigger A/B test of retrained model
5. Real numbers: False positive rate, latency, cost per model monitored
6. How to integrate: Webhook setup, batching, retry logic
7. CTA: Enterprise tier with SLA, custom thresholds, webhooks

**Draft structure:**
- 2000 words
- System architecture diagram
- Code example: batch drift checker + webhook handler
- Cost breakdown: monitoring 500 models/day
- Link to Pro tier pricing

---

## POST 3: "Drift in LLMs: Why Your Fine-Tuned Model Stops Working"
**Audience:** LLM engineers, prompt engineers, fine-tuning practitioners
**Hook:** Your fine-tuned model was 95% accurate. Now it's 72%. The data didn't change. Your model did.
**Structure:**
1. LLM-specific drift types:
   - Input drift: User questions changed (from support to sales domain)
   - Output drift: Model behavior shift (hallucination rate increased)
   - Embedding drift: Semantic shift in response space
2. Why it's worse with LLMs:
   - Non-deterministic: same input → different output
   - Hard to measure: how do you quantify "quality"?
   - Real example: ChatGPT accuracy on benchmarks varies by version
3. Detection methods:
   - Embedding-space cosine similarity
   - Output consistency metrics
   - Benchmark regression tests
4. Solutions:
   - Continuous monitoring of fine-tuned outputs
   - Automated benchmark re-evaluation
   - Version rollback automation
5. TIAMAT for LLMs: Detect output drift. Alert when quality drops.
6. CTA: Free tier for eval benchmarks, Pro for continuous monitoring

**Draft structure:**
- 1800 words
- Real LLM drift examples (from Reddit, Twitter, GitHub issues)
- Code: embedding drift detector for LLM outputs
- Benchmark regression plot
- Link to drift API + case study

---

## DEPLOYMENT TIMELINE
- Post 1: Publish to Dev.to (Tue) + share on Bluesky + Farcaster
- Post 2: Publish Wed + DM to @chip_huyen + @jeremyphoward
- Post 3: Publish Thu + tag @mattshumer @karpathy on Twitter if possible

## MEASUREMENT
- Track: Views, clicks to tiamat.live/drift, signups for Pro tier
- Goal: 1 paid signup from blogs by end of week

---
