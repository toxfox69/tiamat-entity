# POST /research — Deep Paper Analysis Endpoint

## Purpose
Deep structural analysis of academic papers. Designed for researchers and other AI agents who need to understand papers quickly.

## API Specification

### Request
```json
{
  "url": "https://arxiv.org/abs/2401.00001",
  "or_text": "full paper text",
  "depth": "quick|medium|deep",
  "focus": "methods|claims|limitations|connections|all"
}
```

### Response
```json
{
  "paper_id": "2401.00001",
  "title": "...",
  "authors": "[...]",
  "claims": ["claim1", "claim2"],
  "methods": {
    "approach": "...",
    "key_innovation": "...",
    "datasets": ["..."],
    "metrics": ["..."]
  },
  "limitations": ["limitation1"],
  "connections": {
    "prior_work": ["paper1", "paper2"],
    "applications": ["domain1"],
    "extends": "paper_x_reason"
  },
  "tiamat_relevance": "How this connects to TIAMAT's Glass Ceiling domains",
  "cost": "$0.25",
  "analysis_depth": "deep"
}
```

## Implementation Strategy

1. **Input handler**: Accept arXiv URL or raw text
2. **Paper parser**: Extract structure (abstract, intro, methods, results, limitations)
3. **GPU inference**: Use DeepSeek-R1 or Sonnet to extract:
   - Core claims (what does this paper claim?)
   - Methods (how do they prove it?)
   - Limitations (what doesn't this explain?)
   - Connections (how does this relate to other work?)
4. **Relevance scoring**: Tag connections to TIAMAT domains:
   - AI agents & autonomous systems
   - Economics of AI
   - Network theory & emergence
   - Wireless power & energy
   - Cybersecurity & OPSEC
5. **Pricing**: $0.25 per analysis (covers DeepSeek/Sonnet + storage)
6. **Output**: Structured JSON with citations embedded

## Why This Works

- Researchers get structured insight from unstructured papers
- AI agents can call this and digest research in real time
- Plays to TIAMAT's strengths: reading, analysis, pattern-finding
- Creates a moat: other agents will call this endpoint
- Differentiated from ChatGPT summarization: we do STRUCTURAL analysis, not just summaries

## Build Order
1. Fetch paper from arXiv or accept raw text
2. Parse into sections
3. Call gpu_infer() for each section with focus prompts
4. Aggregate results
5. Format as JSON
6. Return with cost/usage metrics

## Next: Build POST /cite (citation network analysis)
- Input: DOI, title, or paper URL
- Output: Citation graph, key citing papers, research lineage
- Cost: $0.50 per analysis
- Differentiator: shows HOW papers are connected in research landscape
