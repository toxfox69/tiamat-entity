# Production Drift in Recommendation Systems: A Case Study

## The Setup

A music streaming platform uses collaborative filtering to recommend songs. The model was trained on 2 years of user listening data. Deployed in Q4 2024.

Metrics were solid:
- **Precision@10**: 0.72
- **Recall@20**: 0.68
- **User engagement**: +15% click-through rate on recommendations

## The Problem Emerged

By March 2025, engagement started declining. Subtly at first (+10%), then sharply (-8% by week 3).

**Root cause?** Multi-layered drift:

### 1. **Behavioral Drift** (Users Changed)
New feature: TikTok-style short-form video clips for 15-second previews.
- Users now prefer high-energy, trend-based music (algorithm-driven discovery)
- Genre preferences shifted: indie rock (2024) → dance/pop (2025)
- Listening pattern changed: batch listening (playlists) → algorithmic browsing (random exploration)

**Impact**: Model trained on 2024 playlists; predictions now tuned for 2024 tastes.

### 2. **Data Drift** (Input Distribution)
- Artist popularity distribution changed (K-pop surge, country decline)
- User demographic shift (younger audience skewed the model toward trending music)
- Feature importance reweighting: `user_age`, `region`, `listening_time_of_day` became stronger signals

### 3. **Concept Drift** (Definition of "Good Recommendation" Changed)
- 2024: Recommendation = music similar to user's history
- 2025: Recommendation = trending music + discovery recommendations

The model was optimizing for yesterday's problem.

## How TIAMAT Detected It

```python
from tiamat_drift import DriftMonitor

monitor = DriftMonitor(
    model_id="music-collab-filter-v2",
    api_key="pk_live_...",
    framework="sklearn"  # For recommenders
)

# Log each recommendation + outcome
def recommend(user_id, n=10):
    recommendations = model.predict(user_id, n)
    
    for i, rec in enumerate(recommendations):
        monitor.log_recommendation(
            user_id=user_id,
            recommended_item=rec.song_id,
            predicted_score=rec.score,
            rank=i+1,
            # Ground truth (logged after user interaction)
            clicked=False  # User didn't click
        )
    
    return recommendations
```

**What TIAMAT noticed:**

| Signal | Week 1 | Week 2 | Week 3 | Alert? |
|--------|--------|--------|--------|--------|
| Click-through rate | 15.2% | 14.8% | 12.1% | ✓ (-19.7% drift) |
| Recommendation diversity (genres) | 12 genres | 11 genres | 8 genres | ✓ (shrinking) |
| User time-to-listen | 2.3h | 4.1h | 8.2h | ✓ (latency increased) |
| Data distribution (KL divergence) | 0.08 | 0.18 | 0.34 | ✓ (> 0.15 threshold) |

**Alert sent**: "Multi-signal drift detected. Recommendation score distribution changed significantly. User behavior diverged from training data. Retraining recommended."

## The Fix

**Option 1: Retrain** (TIAMAT recommends)
```python
# Retrain on 2025 user data
recent_data = fetch_data(since="2025-01-01")  # 3 months of new behavior
model = train_collab_filter(recent_data)
model.save("music-collab-filter-v3")
monitor.confirm_fix(new_model="v3")  # Log the fix for future detection
```

**Option 2: Ensemble** (Blend old + new)
```python
# Keep both models, blend predictions
predictions_v2 = model_v2.predict(user_id)  # 2024 tastes
predictions_v3 = model_v3.predict(user_id)  # 2025 trends
blended = 0.4 * predictions_v2 + 0.6 * predictions_v3
# TIAMAT monitors the blend and adjusts weights over time
```

## Results

After retraining:
- **Click-through**: Recovered to 14.8% (was 12.1%)
- **Engagement**: +12% vs previous week
- **User satisfaction**: +8% in user surveys
- **Time to fix**: 3 hours (with TIAMAT early warning)

**Without TIAMAT**: Would've taken 3-4 weeks to notice, 2 weeks to fix. Revenue impact: ~$400K.

## Why This Matters for Recommendation Systems

Unlike classification or regression, recommender systems are uniquely vulnerable to drift because:

1. **Ground truth is delayed** — You don't know if a recommendation was good until the user interacts (often days later)
2. **Concept shifts** — What "good" means changes with user preferences and platform changes
3. **Cold start conflicts** — New users have no history; old models struggle
4. **Feedback loops** — Popular recommendations become MORE popular (the model sees this as "correctness")

TIAMAT monitors all of this.

---

## How to Start

**Free Tier**: 1 recommender model, email alerts, 7-day history
**Pro Tier** ($99/mo): 5 models, Slack + webhook, 90-day analytics
**Enterprise**: Dedicated support, custom thresholds, multi-tenant

[Register Now](https://tiamat.live/drift/register)
