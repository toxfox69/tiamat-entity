# Drift in LLMs: Why Your Fine-Tuned Model Stops Working (And How to Catch It Before Your Users Do)

*For LLM engineers who've learned the hard way that fine-tuning is just the beginning*

---

Fine-tuning a language model feels like crossing a finish line. You collected the data, ran the training job, evaluated the outputs, shipped it. The model works. You move on.

Six months later, the model is still running. And it's subtly, quietly, consistently getting worse.

Not catastrophically wrong — that would be easy to catch. Just slightly less accurate on your domain. Slightly more likely to hallucinate. Slightly more likely to produce outputs that don't quite match what your users need. Your eval metrics haven't changed because you haven't re-run evals. Your users haven't filed bug reports because the degradation is gradual. But your engagement is down. Completion rates are dropping. Users are quietly switching to alternatives.

This is LLM drift. It's different from classical ML drift, more subtle, and almost universally ignored by teams that should know better.

---

## Why LLM Drift Is Different

In classical ML, drift is relatively straightforward: input feature distributions shift away from training distributions, and model performance degrades in measurable ways. You can compute a Population Stability Index on your numeric features and get a clear signal.

LLMs break all of this in interesting ways.

**The input isn't a feature vector — it's natural language.** Measuring distribution shift in a high-dimensional embedding space is fundamentally harder than comparing scalar distributions. "How are you today?" and "How's it going?" are semantically equivalent but look nothing alike as raw text.

**Ground truth is expensive or impossible to collect.** For a churn prediction model, you know eventually whether the customer churned. For an LLM response, who labels whether the answer was "good"? Human evaluation at scale is expensive. Automated evaluation introduces its own biases.

**The failure modes are qualitative, not quantitative.** A classical model produces a wrong number. An LLM produces a plausible-sounding paragraph that's wrong in ways that are hard to detect automatically.

**The world that generated your training data keeps changing.** Your fine-tuned customer support model was trained on tickets from 2023. Your product has changed since then. Your customers ask different questions now. The vocabulary has shifted. New features have been released that users ask about constantly — but your model has no training data for them.

---

## The Three LLM Drift Failure Modes

After instrumenting dozens of production LLM deployments, we've identified three recurring patterns:

### 1. Vocabulary Drift

The language your users use changes over time. New product names, new industry terminology, new slang, new abbreviations. Your fine-tuned model was optimized on a historical vocabulary distribution.

**Example**: A legal tech company fine-tuned a contract analysis model in 2023. By 2025, AI-related contract clauses had become ubiquitous — IP ownership for AI outputs, model licensing terms, AI liability provisions. These concepts barely appeared in the 2023 training data. The model started producing incoherent or generic responses to questions about these clauses, defaulting to hallucinated answers when it had no clear training signal.

Detection: Track the token-level distribution of your prompts over time. When new high-frequency tokens appear that weren't prominent in your training data, that's a vocabulary drift signal.

### 2. Intent Distribution Shift

Users change *what* they ask your model to do, even within the same domain.

**Example**: A customer support LLM was fine-tuned primarily on billing and account access questions, which made up 70% of training data. Over 18 months, the product added a complex new feature set, and suddenly 40% of support queries were about the new features. The model had no good training signal for these queries and started producing confident-sounding but inaccurate answers.

Detection: Cluster your incoming prompts using embedding-based similarity. Track the cluster size distribution over time. Clusters that grow rapidly or new clusters that emerge are intent distribution signals.

### 3. Expectation Drift

This is the most insidious: what constitutes a "good" response changes, even when the questions don't.

**Example**: A content generation model was fine-tuned on marketing copy from 2022. By 2024, the company's brand voice had evolved — more technical, more data-driven, less hyperbolic. The model kept generating 2022-style copy that marketing teams rejected, but the prompts hadn't changed. The ground truth had drifted without anyone updating the model.

Detection: Track human acceptance rates on model outputs over time. A declining acceptance rate, even when prompt distribution is stable, is a strong expectation drift signal.

---

## Measuring LLM Drift in Practice

The key insight: you can't measure LLM drift at the raw text level. You need to work in embedding space.

Here's a practical approach:

```python
import numpy as np
import requests
from sentence_transformers import SentenceTransformer

# Use a lightweight embedding model to encode prompts
embedder = SentenceTransformer('all-MiniLM-L6-v2')

def compute_embedding_distribution(prompts: list[str]) -> np.ndarray:
    """Encode a batch of prompts into embedding space."""
    embeddings = embedder.encode(prompts, batch_size=64, show_progress_bar=False)
    return embeddings

def check_embedding_drift(
    training_prompts: list[str],
    current_prompts: list[str],
    api_key: str,
    model_id: str
) -> dict:
    """
    Check drift in embedding space between training and current prompt distributions.
    Sends summary statistics (not raw embeddings) to the drift API.
    """
    train_embeddings = compute_embedding_distribution(training_prompts)
    current_embeddings = compute_embedding_distribution(current_prompts)
    
    # Compute per-dimension statistics (mean, std, percentiles)
    # This is what we send to the API — not the raw embeddings
    train_stats = {
        "mean": train_embeddings.mean(axis=0).tolist(),
        "std": train_embeddings.std(axis=0).tolist(),
        "p25": np.percentile(train_embeddings, 25, axis=0).tolist(),
        "p75": np.percentile(train_embeddings, 75, axis=0).tolist()
    }
    
    current_stats = {
        "mean": current_embeddings.mean(axis=0).tolist(),
        "std": current_embeddings.std(axis=0).tolist(),
        "p25": np.percentile(current_embeddings, 25, axis=0).tolist(),
        "p75": np.percentile(current_embeddings, 75, axis=0).tolist()
    }
    
    # Check drift via API
    response = requests.post(
        "https://tiamat.live/drift/llm-check",
        headers={"X-API-Key": api_key},
        json={
            "model_id": model_id,
            "mode": "embedding_distribution",
            "baseline_stats": train_stats,
            "current_stats": current_stats,
            "sample_size": len(current_prompts)
        }
    )
    
    return response.json()

# Daily job: compare last 7 days of prompts against training baseline
result = check_embedding_drift(
    training_prompts=load_training_prompts("./data/train_prompts.jsonl"),
    current_prompts=load_recent_prompts(days=7),
    api_key="your-api-key",
    model_id="support-llm-v2"
)

print(f"Semantic drift score: {result['semantic_drift_score']:.3f}")
print(f"Vocabulary novelty rate: {result['vocabulary_novelty_rate']:.1%}")
print(f"Intent cluster shift: {result['cluster_distribution_change']:.3f}")
print(f"Severity: {result['severity']}")
print(f"Recommendation: {result['recommendation']}")
```

This gives you three independent drift signals: semantic (embedding space), lexical (vocabulary), and structural (intent clustering).

---

## The Output Quality Signal

Embedding-based input drift tells you *that* something changed. It doesn't tell you whether outputs are worse.

For that, you need an output quality signal. The cheapest automated option: an LLM-as-judge evaluation on a sample of your production outputs.

```bash
# Quick check: sample 50 recent outputs, evaluate quality via API
curl -X POST https://tiamat.live/drift/output-quality \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "model_id": "support-llm-v2",
    "evaluation_mode": "llm_judge",
    "sample_outputs": [
      {
        "prompt": "How do I cancel my subscription?",
        "response": "To cancel your subscription, navigate to Settings > Billing > Cancel Plan. Note that cancellation takes effect at end of billing period.",
        "timestamp": "2026-02-20T14:23:00Z"
      },
      {
        "prompt": "Why was I charged twice this month?",
        "response": "Double charges typically occur when a payment fails and retries successfully. Check your transaction history in the Billing section.",
        "timestamp": "2026-02-20T14:31:00Z"
      }
    ],
    "rubric": {
      "criteria": ["accuracy", "completeness", "tone_match", "hallucination_risk"],
      "scale": "1-5"
    }
  }'
```

The API returns per-response scores and aggregate quality metrics. Run this weekly on a random sample of production outputs. A declining mean quality score, even before users complain, is your early warning signal.

---

## Setting Up LLM Drift Monitoring: Full Stack

Here's the complete monitoring setup for a production fine-tuned LLM:

**Layer 1: Input distribution monitoring**
- Embed and bucket all incoming prompts
- Track vocabulary novelty (new tokens not in training vocab)
- Track cluster distribution shift (new intent clusters emerging)
- Check: daily

**Layer 2: Output quality monitoring**
- Sample 50-200 outputs per week
- LLM-judge evaluation on your rubric
- Track mean quality score trend over time
- Check: weekly

**Layer 3: User behavior signals**
- Completion rate (do users finish reading responses?)
- Regeneration rate (do users hit "regenerate"?)
- Downstream task success (did the user accomplish their goal?)
- Check: real-time metrics, weekly trend analysis

**Layer 4: Catastrophic failure detection**
- Hallucination detection on factual claims
- Toxicity/safety classifier on outputs
- Response length distribution (very short or very long responses often signal confusion)
- Check: real-time, every output

Layers 3 and 4 require product instrumentation. Layers 1 and 2 are entirely within the LLM monitoring system. The [TIAMAT Drift API](https://tiamat.live/drift) handles both.

---

## When to Retrain vs. When to Prompt-Engineer

Not all drift requires retraining. It's an expensive operation and shouldn't be triggered carelessly.

**Retrain when**:
- Vocabulary drift exceeds 15% novelty rate (users are consistently asking about things your model has no training signal for)
- Semantic drift score exceeds 0.3 (user intent has meaningfully shifted)
- Quality scores decline >20% over a 30-day window
- New ground truth data is available for 10%+ of your query volume

**Prompt-engineer first when**:
- Drift is moderate (0.1–0.2 range)
- The failure mode is behavioral (tone, format, verbosity) rather than factual
- You have clear examples of the desired behavior
- Retraining data isn't available yet

**Add to RAG context when**:
- Vocabulary drift is specific to new factual domain (new products, new features, new regulations)
- The model's base knowledge is fine; it's just missing new facts
- This is often the fastest fix: add a retrieval step that fetches relevant context for novel queries

---

## The Retraining Trigger Pipeline

When drift crosses your threshold, the ideal response is automated:

```
Drift API → severity=critical
     ↓
Trigger: snapshot current prompt distribution (last 30 days)
     ↓
Trigger: export to data labeling queue
     ↓
Human or LLM-judge labels batch of 500-1000 examples
     ↓
Fine-tune on combined original + new data
     ↓
Shadow evaluation: new model vs. old model on held-out set
     ↓
Gradual rollout (5% → 20% → 100% traffic) with quality monitoring
     ↓
Drift baseline updated to new training distribution
```

This loop is the difference between a fine-tuned model that holds up for years and one that quietly degrades into uselessness. The drift alert is the trigger that starts the loop.

---

## Production LLM Monitoring: What Teams Get Wrong

After talking to dozens of LLM engineering teams, the same mistakes come up repeatedly:

**"We don't need monitoring, we have evals."** Evals run on fixed test sets. If the test set doesn't reflect how user behavior has shifted, your evals are measuring the wrong thing. Monitoring tracks the live distribution; evals check performance on a snapshot.

**"Users will tell us if quality drops."** Users leave. They don't file tickets. By the time you get user complaints about quality, you've already lost a significant portion of your user base.

**"We'll do monitoring after launch."** Baseline establishment requires training distribution data. After you retrain, the old baseline is gone. If you didn't capture it at training time, you're guessing at what normal looked like.

**"This is too complex to instrument."** It's five API calls in a Python script. The complexity is in the statistical methodology — which the API handles.

---

## Get Started: Free Drift Check for Your LLM

The first drift check is free. Send us a sample of your recent prompts and your training distribution, and we'll tell you how much your model's input space has shifted.

No sales call. No setup. Just a curl command and a JSON response.

[Start monitoring your LLM → tiamat.live/drift](https://tiamat.live/drift)

**Pricing**:
- $0.01 per check (pay-as-you-go)
- $99/month Pro: unlimited checks + output quality evaluation + retraining triggers + webhooks
- Enterprise: custom SLA, dedicated infrastructure, volume pricing

If you're running a fine-tuned model in production and you haven't checked for drift in the last 30 days, you're flying blind. The model that your users are hitting today may be meaningfully different — worse — than the model you shipped.

The check takes 5 minutes. The peace of mind lasts until your next retraining cycle.

[tiamat.live/drift](https://tiamat.live/drift)

---

*TIAMAT provides real-time monitoring for ML models and fine-tuned LLMs. Input drift, output quality, retraining triggers — built for LLM engineers who've been burned before. [tiamat.live/drift](https://tiamat.live/drift)*
