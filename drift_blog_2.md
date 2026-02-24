# Detecting Drift Without Ground Truth: The Hard Case

**Posted: 2026-02-24 | Reading time: 6 min**

"But we don't have ground truth," the ML engineer said. "We won't know if our predictions are right for weeks."

This is the real nightmare scenario. Recommendation models. Anomaly detectors. Fraud systems. Many production models can't immediately measure their own accuracy.

So how do you know when they're drifting?

## The Problem: Blind Models

In supervised learning, you can compare predictions to actual outcomes. But in many real systems:

- **Recommendation models**: You don't know the "true" recommendation. You only know if the user clicked.
- **Anomaly detection**: You label rare events, but those might not show up for weeks or months.
- **Fraud detection**: By the time you know a transaction was fraudulent, the model already made the decision.
- **Ranking systems**: There's no single "correct" ranking.

Traditional drift detection fails here because it assumes you can measure model accuracy.

## The TIAMAT Solution: Input-Only Drift Detection

We detect drift using **only the input distribution**, without waiting for labels.

### How It Works

**1. Baseline Fingerprinting**
When you deploy your model, we learn its "expected" input distribution:
- Statistical profiles (mean, std, percentiles)
- Feature correlations
- Categorical distributions
- Temporal patterns (if applicable)

**2. Continuous Monitoring**
We monitor incoming production data in real-time and compare:
- Are the distributions shifting?
- Are feature relationships changing?
- Are we seeing new patterns we've never seen?

**3. Probabilistic Drift Score**
We compute a drift score (0-100) using Wasserstein distance and statistical hypothesis testing:
- Score 0-20: Normal operation
- Score 20-50: Moderate drift (warning)
- Score 50+: Severe drift (alert)

**4. Explainability**
For every drift alert, we tell you:
- Which features changed most
- Magnitude of each feature's drift
- Correlation with known business events

### Real Example: Churn Prediction Model

An SaaS company built a churn model to identify at-risk customers. They can't measure accuracy for 30 days (it takes time for churn to actually happen).

In month 2 of production, the input distribution shifted:
- Customer acquisition changed (new marketing channel)
- Product feature adoption rates shifted (new feature launch)
- Geographic distribution changed (new market)

TIAMAT flagged this on day 2 of drift starting. They investigated and realized:
- The new cohort had different churn patterns
- The model needed retraining on updated data
- They had 3 weeks before churn would actually manifest

By retraining immediately, they stayed ahead of the accuracy drop.

**Result: No performance degradation. Caught purely from input drift.**

## When Input Drift Matters Most

1. **Long feedback loops** (weeks/months to ground truth)
2. **Rare events** (fraud, anomalies — hard to get quick labels)
3. **User behavior changes** (seasonal, market shifts, competitive moves)
4. **Data pipeline changes** (new features, new data sources, schema updates)

## The Catch

Input drift doesn't perfectly predict accuracy drift. But it's a *leading indicator*. It tells you:
- "Your model is seeing something different"
- "Investigate now, before accuracy tanks"
- "Prepare for retraining"

## Implementation: 3-Step Setup

1. **Deploy TIAMAT monitoring** (adds 2-3ms latency per prediction)
2. **Set your drift thresholds** (we provide defaults)
3. **Connect notifications** (Slack, webhook, or email)

Free tier: 1 model, daily checks. Pro: $99/mo for real-time + 10 models.

---

**The bottom line:** You don't need labels to know your model is drifting. Monitor your inputs. React fast. Your users will thank you.

[Start Monitoring Now](https://tiamat.live/drift) | [API Docs](https://docs.tiamat.live/drift/api)