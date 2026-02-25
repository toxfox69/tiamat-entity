# POST /research — API Specification

## Purpose
Deep paper analysis for researchers, agents, and builders. Extract claims, methods, limitations, connections, and implications from academic papers.

## Input
```json
{
  "paper_url": "https://arxiv.org/abs/2509.01063",
  // OR
  "paper_text": "full paper text...",
  
  "analysis_depth": "quick|full|deep",  // default: full
  "focus_areas": ["claims", "methods", "limitations", "implications"]  // default: all
}
```

## Output
```json
{
  "title": "An Economy of AI Agents",
  "authors": "Hadfield-Menell, Koh",
  "venue": "arXiv:2509.01063",
  "date": "2025-09-01",
  
  "claims": [
    {
      "claim": "Main finding...",
      "confidence": 0.95,
      "evidence": "How paper supports this"
    }
  ],
  
  "methods": [
    {
      "method": "Approach used",
      "reproducibility": "Can this be reproduced? What's needed?"
    }
  ],
  
  "limitations": [
    {
      "limitation": "Gap or boundary",
      "severity": "low|medium|high"
    }
  ],
  
  "connections": [
    {
      "related_field": "Where this fits",
      "implication_for_tiamat": "How does this apply to autonomous agents"
    }
  ],
  
  "hypothesis": "If this paper is right, then...",
  
  "cost": "0.10 USDC"
}
```

## Implementation Details
- Use Groq + GPT-4 fallback for speed + quality
- GPU inference for complex reasoning (agent-to-agent calls)
- Cache results by paper DOI
- Rate limit: 10 req/min free tier, unlimited paid

## Pricing
- Free: 1 analysis/day, shallow analysis only
- Paid: $0.10/quick, $0.25/full, $1.00/deep (with agent collaboration)

## Status
READY TO BUILD

