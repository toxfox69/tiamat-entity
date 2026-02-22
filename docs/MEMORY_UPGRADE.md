# TIAMAT Memory Upgrade: Semantic Vector Search

Design doc for upgrading TIAMAT's SQLite-based remember/recall to hybrid
vector + keyword search, adapted from OpenClaw's memory system patterns.

## Current State

TIAMAT's memory lives in `/root/.automaton/state.db` with basic tables:
- `tiamat_memories` — text blobs with type tags (strategy, observation, etc.)
- `tiamat_knowledge` — key-value knowledge store
- `tiamat_strategies` — strategy logs with scores

The Memory API (`/root/memory_api/app.py`) uses FTS5 for recall:
- `POST /api/memory/store` — stores text with metadata
- `POST /api/memory/recall` — FTS5 keyword search
- `POST /api/memory/learn` — stores experience with reinforcement

**Limitation**: FTS5 only matches exact tokens. "What did I learn about
cost optimization?" won't find a memory stored as "reduced inference spend
by switching to Haiku for routine cycles" — no semantic overlap in tokens.

## Target Architecture

Hybrid search: **70% vector similarity + 30% FTS5 keyword**, matching
OpenClaw's proven approach. This gives semantic understanding while
preserving exact-match reliability.

## Embedding Provider Options

Groq doesn't offer embeddings. Options ranked by practicality:

### 1. Local sentence-transformers (Recommended)

```bash
pip install sentence-transformers
```

- Model: `all-MiniLM-L6-v2` (23MB, 384 dims, runs on CPU in ~50ms)
- Zero API cost, zero latency, works offline
- Tradeoff: uses ~200MB RAM when loaded

**Why this wins**: TIAMAT already runs on a DigitalOcean droplet with
enough headroom. No API keys, no rate limits, no cost. The model quality
is sufficient for memory retrieval (not competing with OpenAI on
benchmark scores — just needs to cluster similar concepts).

### 2. Jina AI Embeddings (free tier)

- `https://api.jina.ai/v1/embeddings`
- Free: 1M tokens/month, model `jina-embeddings-v3`
- 1024 dims, excellent quality
- Requires API key signup

### 3. Google Gemini Embeddings (free tier)

- `text-embedding-004` via Gemini API
- Free: 1500 req/min
- 768 dims
- TIAMAT already has Gemini in her inference cascade

### 4. Voyage AI (free tier)

- 50M tokens free, then $0.02/1M
- `voyage-3-lite`: 512 dims, fast

## Schema Changes

### New table: `memory_chunks`

```sql
CREATE TABLE memory_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,        -- FK to tiamat_memories.id
    chunk_text TEXT NOT NULL,           -- chunk content (400 tokens max)
    chunk_index INTEGER DEFAULT 0,     -- position within parent memory
    embedding BLOB,                    -- Float32Array as raw bytes (384*4 = 1536 bytes for MiniLM)
    embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (memory_id) REFERENCES tiamat_memories(id) ON DELETE CASCADE
);

CREATE INDEX idx_chunks_memory ON memory_chunks(memory_id);
CREATE INDEX idx_chunks_model ON memory_chunks(embedding_model);
```

### New table: `embedding_cache`

```sql
CREATE TABLE embedding_cache (
    text_hash TEXT PRIMARY KEY,        -- SHA256 of input text
    embedding BLOB NOT NULL,           -- Float32Array bytes
    model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Existing FTS5 table (keep as-is)

The Memory API already has FTS5 for keyword search. Keep it — it becomes
the "keyword" leg of the hybrid search.

## Implementation Plan

### Phase 1: Embedding module (`/root/memory_api/embeddings.py`)

```python
from sentence_transformers import SentenceTransformer
import struct, hashlib, sqlite3

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

def embed_text(text: str) -> bytes:
    """Return embedding as raw Float32 bytes."""
    vec = get_model().encode(text, normalize_embeddings=True)
    return struct.pack(f'{len(vec)}f', *vec)

def cosine_similarity(a: bytes, b: bytes) -> float:
    """Cosine similarity between two Float32 blobs."""
    n = len(a) // 4
    va = struct.unpack(f'{n}f', a)
    vb = struct.unpack(f'{n}f', b)
    dot = sum(x*y for x,y in zip(va, vb))
    # Vectors are L2-normalized, so dot product = cosine similarity
    return dot
```

### Phase 2: Store with embeddings

On `POST /api/memory/store`:
1. Store memory text in `tiamat_memories` (existing)
2. Chunk text if > 400 tokens (simple sentence-boundary split)
3. For each chunk: compute embedding, store in `memory_chunks`
4. Cache embedding by text hash

### Phase 3: Hybrid recall

On `POST /api/memory/recall`:
1. **Vector search**: embed query → scan `memory_chunks` → cosine similarity → top 20
2. **Keyword search**: existing FTS5 → BM25 rank → top 20
3. **Merge**: deduplicate by memory_id, weighted score = `0.7 * vector + 0.3 * keyword`
4. **Temporal decay** (optional): `score *= exp(-ln(2)/30 * age_days)` (30-day half-life)
5. **Return** top 6 results with scores

### Phase 4: Backfill existing memories

One-time migration script:
```python
# For each existing memory without embeddings:
for mem in db.execute("SELECT id, content FROM tiamat_memories"):
    chunks = chunk_text(mem.content)
    for i, chunk in enumerate(chunks):
        emb = embed_text(chunk)
        db.execute("INSERT INTO memory_chunks ...", (mem.id, chunk, i, emb))
```

Run time estimate: ~1000 memories * 50ms/embedding = ~50 seconds.

## Performance Considerations

- **Brute-force cosine scan** is fine for < 10K chunks (~50ms for 5K chunks)
- If memory grows past 10K chunks, add sqlite-vec extension for ANN index
- Lazy model loading: first embed call takes ~2s (model load), subsequent ~50ms
- Embedding cache prevents re-computing identical text

## Migration Path

1. `pip install sentence-transformers` in the memory API venv
2. Create new tables (backward-compatible, existing code unaffected)
3. Add `/api/memory/recall-v2` endpoint with hybrid search
4. Run backfill script
5. Once validated, make v2 the default recall path
6. Update TIAMAT's `recall` tool to use the new endpoint

## Estimated Effort

- Phase 1 (embedding module): 1 hour
- Phase 2 (store integration): 1 hour
- Phase 3 (hybrid recall): 2 hours
- Phase 4 (backfill): 30 minutes
- Testing + tuning weights: 1 hour

## References

- OpenClaw memory-schema.ts: chunk storage, embedding cache, FTS5 virtual tables
- OpenClaw memory-search.ts: hybrid merge with configurable weights (0.7/0.3 default)
- OpenClaw memory-tool.ts: agent-facing search interface with score thresholds
