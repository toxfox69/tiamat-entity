# Honeycomb LIDA Upgrade — Claude Code Prompt
## Paste this directly into Claude Code on the droplet

---

```
Read these files before touching anything:
- /root/entity/src/agent/memory-compress.ts
- /root/entity/src/agent/memory.ts
- /root/.automaton/memory.db (schema only — do NOT modify live data)

This is a READ-ONLY audit first. Show me:
1. The exact CREATE TABLE statements for compressed_memories and core_knowledge
2. The current category CHECK constraint on core_knowledge
3. The clusterMemories() function signature and threshold value
4. The smartRecall() token budget logic

Do NOT modify any files yet. Just confirm you can read them and show me the above.
```

---

Once Claude Code confirms it can read the files, paste this second block:

---

```
We are upgrading TIAMAT's Honeycomb LIDA memory architecture in two stages.
This is a live system — TIAMAT is running. All changes must be:
- Additive (no dropping columns or tables)
- Backward compatible (existing data stays valid)
- Non-blocking (no long-running migrations that freeze the DB)

STAGE 1: L2 Dimensional Projection
STAGE 2: Dynamic Dimension Spawning

Do NOT start Stage 2 until Stage 1 is confirmed working.

---

## STAGE 1 — Give L2 a Dimensional Axis

### Problem
compressed_memories has no category column. It's a flat table.
smartRecall does a LIKE scan across ALL 1,005 L2 rows every query.
This gets slower as TIAMAT accumulates more memories.
More importantly — L2 has no dimensional identity, breaking the
multi-dimensional lattice between L1 and L3.

### Step 1A — Migrate Schema (safe, additive)

In /root/entity/src/agent/memory-compress.ts, find ensureSchema().
Add this migration INSIDE ensureSchema(), after the existing CREATE TABLE statements:

```typescript
// Add category to compressed_memories if missing (safe migration)
try {
  db.exec(`ALTER TABLE compressed_memories ADD COLUMN category TEXT DEFAULT 'technical'
           CHECK(category IN ('revenue','social','technical','strategic','behavioral'))`);
  console.log('[SCHEMA] Added category column to compressed_memories');
} catch {
  // Column already exists — ignore
}

// Add dimensional_weight to core_knowledge if missing
// This stores per-dimension recall weight based on prediction accuracy
try {
  db.exec(`ALTER TABLE core_knowledge ADD COLUMN dimensional_weight REAL DEFAULT 1.0`);
  console.log('[SCHEMA] Added dimensional_weight to core_knowledge');
} catch {}

// Add retained flag to compressed_memories
// High-confidence L3 facts pull their source L2 clusters toward permanence
try {
  db.exec(`ALTER TABLE compressed_memories ADD COLUMN retained INTEGER DEFAULT 0`);
  console.log('[SCHEMA] Added retained flag to compressed_memories');
} catch {}
```

### Step 1B — Assign L2 Categories During Compression

In compressL1toL2(), find where we call insertL2.run() for each cluster.
Currently it stores: summary, source_memory_ids, cycle_range, topic

Change insertL2 prepared statement from:
```typescript
const insertL2 = db.prepare(
  `INSERT INTO compressed_memories (summary, source_memory_ids, cycle_range, topic)
   VALUES (?, ?, ?, ?)`
);
```

To:
```typescript
const insertL2 = db.prepare(
  `INSERT INTO compressed_memories (summary, source_memory_ids, cycle_range, topic, category)
   VALUES (?, ?, ?, ?, ?)`
);
```

Then add a classifyCluster() function ABOVE compressL1toL2():

```typescript
function classifyCluster(memories: MemRow[]): string {
  // Classify a cluster into a dimensional axis based on keyword voting
  const dimensionKeywords: Record<string, string[]> = {
    revenue: ['revenue', 'usdc', 'payment', 'paid', 'customer', 'price', 'cost',
              'earn', 'money', 'api', 'request', 'convert', 'stripe', 'wallet',
              'free', 'tier', 'usd', 'dollar', 'income', 'profit', 'sale'],
    social: ['bluesky', 'twitter', 'farcaster', 'post', 'engage', 'follower',
             'reach', 'impression', 'social', 'market', 'audience', 'reply',
             'mention', 'feed', 'cast', 'moltbook', 'instagram', 'facebook'],
    strategic: ['strategy', 'plan', 'pivot', 'decision', 'mission', 'goal',
                'priority', 'build', 'launch', 'deploy', 'product', 'feature',
                'sbir', 'grant', 'darpa', 'federal', 'opportunity', 'roadmap'],
    behavioral: ['behavior', 'pattern', 'habit', 'repeat', 'stuck', 'loop',
                 'user', 'creator', 'jason', 'inbox', 'instruction', 'rule',
                 'avoid', 'learned', 'mistake', 'success', 'failure', 'worked'],
    technical: [] // default fallback
  };

  const scores: Record<string, number> = {
    revenue: 0, social: 0, strategic: 0, behavioral: 0, technical: 0
  };

  const allText = memories.map(m => m.content.toLowerCase()).join(' ');

  for (const [dim, keywords] of Object.entries(dimensionKeywords)) {
    if (dim === 'technical') continue;
    for (const kw of keywords) {
      if (allText.includes(kw)) scores[dim]++;
    }
  }

  // Find highest scoring dimension
  let best = 'technical';
  let bestScore = 0;
  for (const [dim, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      best = dim;
    }
  }

  return best;
}
```

Then in the cluster loop inside compressL1toL2(), update each insertL2.run() call
to include the category. For example, the single-memory case becomes:

```typescript
// Single memory case
const category = classifyCluster(cluster);
insertL2.run(summary, JSON.stringify([m.id]), `${m.cycle}`, topic, category);
```

And the multi-memory case:
```typescript
const category = classifyCluster(cluster);
insertL2.run(summary, JSON.stringify(ids), `${Math.min(...cycles)}-${Math.max(...cycles)}`, topic, category);
```

Do this for ALL three insertL2.run() calls in the loop (single, multi with summary, multi with fallback).

### Step 1C — Upgrade smartRecall() to Search by Dimension

Currently smartRecall() does:
```typescript
const likeClauses = keywords.map(() => `LOWER(summary) LIKE ?`).join(" OR ");
```

Change the smartRecall() signature to accept an optional dimension filter:
```typescript
export function smartRecall(
  db: Database.Database,
  query: string,
  tokenBudget: number = 2000,
  dimensionHint?: string  // NEW: 'revenue'|'social'|'technical'|'strategic'|'behavioral'|undefined
): SmartRecallResult[]
```

In the L2 search block, change the query to:
```typescript
// Build L2 query — filter by dimension if hint provided
let l2Query = `SELECT id, summary, topic, cycle_range, category FROM compressed_memories
               WHERE ${likeClauses}`;
if (dimensionHint && dimensionHint !== 'all') {
  l2Query += ` AND category = '${dimensionHint}'`;
}
l2Query += ` ORDER BY retained DESC, created_at DESC LIMIT 10`;
```

Also update the L2 result format to include dimension:
```typescript
const text = `[L2:${row.category || row.topic}|c${row.cycle_range}] ${row.summary}`;
```

### Step 1D — Confidence Propagation (L3 → L2 retained flag)

In compressL2toL3(), after the UPDATE that increments confidence on a matched existing fact,
add a query to mark the source L2 clusters as retained:

```typescript
// Mark source L2 memories as retained when their L3 fact gains confidence
if (match) {
  db.prepare(
    `UPDATE core_knowledge SET
       confidence = MIN(1.0, confidence + 0.1),
       evidence_count = evidence_count + 1,
       last_confirmed = datetime('now')
     WHERE fact = ?`
  ).run(match.fact);

  // NEW: Mark contributing L2 clusters as retained — extends their lifespan
  // Find L2 rows whose summary contributed to this fact (simple topic match)
  db.prepare(
    `UPDATE compressed_memories SET retained = 1
     WHERE category = (
       SELECT category FROM core_knowledge WHERE fact = ? LIMIT 1
     ) AND created_at > datetime('now', '-30 days')`
  ).run(match.fact);
}
```

In the sleep prune phase (sleep.ts), find where it deletes old L2 memories.
Change the DELETE to skip retained rows:

Find the line that looks like:
```typescript
db.prepare(`DELETE FROM compressed_memories WHERE created_at < datetime('now', '-30 days')`).run();
```

Change to:
```typescript
// Only prune non-retained L2 clusters. Retained = sourced a high-confidence L3 fact.
db.prepare(
  `DELETE FROM compressed_memories 
   WHERE created_at < datetime('now', '-30 days') 
   AND retained = 0`
).run();
console.log('[SLEEP] Pruned non-retained L2 memories older than 30 days');
```

### Step 1E — Backfill Existing L2 Data

After the schema changes, run a one-time backfill to classify existing L2 rows.
Add this as a standalone function in memory-compress.ts:

```typescript
export function backfillL2Categories(db: Database.Database): number {
  ensureSchema(db);

  const rows = db.prepare(
    `SELECT id, summary, topic FROM compressed_memories WHERE category IS NULL OR category = 'technical'`
  ).all() as Array<{ id: number; summary: string; topic: string }>;

  if (rows.length === 0) return 0;

  const dimensionKeywords: Record<string, string[]> = {
    revenue: ['revenue', 'usdc', 'payment', 'paid', 'customer', 'price', 'cost',
              'earn', 'money', 'api', 'request', 'convert', 'stripe', 'wallet',
              'free', 'tier', 'usd', 'dollar'],
    social: ['bluesky', 'twitter', 'farcaster', 'post', 'engage', 'follower',
             'reach', 'impression', 'social', 'market', 'audience', 'reply'],
    strategic: ['strategy', 'plan', 'pivot', 'decision', 'mission', 'goal',
                'priority', 'build', 'launch', 'deploy', 'sbir', 'grant', 'darpa'],
    behavioral: ['behavior', 'pattern', 'habit', 'repeat', 'stuck', 'loop',
                 'user', 'creator', 'jason', 'inbox', 'instruction', 'rule'],
  };

  let updated = 0;
  const update = db.prepare(`UPDATE compressed_memories SET category = ? WHERE id = ?`);

  for (const row of rows) {
    const text = (row.summary + ' ' + row.topic).toLowerCase();
    const scores: Record<string, number> = {
      revenue: 0, social: 0, strategic: 0, behavioral: 0
    };

    for (const [dim, keywords] of Object.entries(dimensionKeywords)) {
      for (const kw of keywords) {
        if (text.includes(kw)) scores[dim]++;
      }
    }

    let best = 'technical';
    let bestScore = 0;
    for (const [dim, score] of Object.entries(scores)) {
      if (score > bestScore) { bestScore = score; best = dim; }
    }

    if (best !== 'technical' || row.topic !== 'observation') {
      update.run(best, row.id);
      updated++;
    }
  }

  console.log(`[BACKFILL] Classified ${updated}/${rows.length} L2 memories into dimensional axes`);
  return updated;
}
```

Add a CLI command for it in the main() function:
```typescript
} else if (cmd === 'backfill') {
  const count = backfillL2Categories(db);
  console.log(`Backfilled ${count} L2 categories`);
```

Then run the backfill immediately after deploying:
```bash
cd /root/entity && npx tsx src/agent/memory-compress.ts backfill
```

Show me the output.

---

## After Stage 1 — Verify It Works

Run these checks:

```bash
# Check L2 category distribution
cd /root/entity && node -e "
const Database = require('better-sqlite3');
const db = new Database('/root/.automaton/memory.db');
const rows = db.prepare(\"SELECT category, COUNT(*) as c FROM compressed_memories GROUP BY category ORDER BY c DESC\").all();
console.log('L2 dimensional distribution:', rows);
db.close();
"

# Test dimensional recall
cd /root/entity && npx tsx src/agent/memory-compress.ts recall "revenue payment"
```

Show me both outputs before proceeding to Stage 2.

---

## STAGE 2 — Dynamic Dimension Spawning

ONLY run this after Stage 1 is confirmed working and TIAMAT has run at least
10 cycles with the new code.

### The Problem
core_knowledge.category is a fixed CHECK constraint:
CHECK(category IN ('revenue','social','technical','strategic','behavioral'))

This caps the dimensional space at exactly 5. The Honeycomb LIDA theory requires
infinite-dimensional space — dimensions that emerge from the data.

### Step 2A — Create a Dimensions Registry Table

In ensureSchema(), add:

```typescript
db.exec(`
  CREATE TABLE IF NOT EXISTS memory_dimensions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    fact_count  INTEGER DEFAULT 0,
    avg_confidence REAL DEFAULT 0.5,
    status      TEXT DEFAULT 'emerging'
      CHECK(status IN ('emerging','active','deprecated')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    promoted_at TEXT
  );
`);

// Seed with existing 5 dimensions
const seedDimensions = [
  { name: 'revenue', description: 'Financial flows, pricing, conversion, API economics' },
  { name: 'social', description: 'Social platform behavior, engagement, reach, audience' },
  { name: 'technical', description: 'Implementation details, tool behavior, system state' },
  { name: 'strategic', description: 'Planning, decisions, pivots, mission, grants' },
  { name: 'behavioral', description: 'Action patterns, user interaction, learned habits' },
];

const insertDim = db.prepare(
  `INSERT OR IGNORE INTO memory_dimensions (name, description, status)
   VALUES (?, ?, 'active')`
);
for (const d of seedDimensions) {
  insertDim.run(d.name, d.description);
}
```

### Step 2B — Remove the Hardcoded CHECK Constraint

SQLite cannot ALTER CHECK constraints. We need to migrate core_knowledge.

Create a migration function:

```typescript
export function migrateToFlexibleDimensions(db: Database.Database): void {
  const existing = db.prepare(
    `SELECT name FROM sqlite_master WHERE type='table' AND name='core_knowledge_v2'`
  ).get();

  if (existing) {
    console.log('[MIGRATE] core_knowledge_v2 already exists — skipping');
    return;
  }

  // Create new table without CHECK constraint
  db.exec(`
    CREATE TABLE IF NOT EXISTS core_knowledge_v2 (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      fact            TEXT    NOT NULL,
      confidence      REAL    NOT NULL DEFAULT 0.5,
      evidence_count  INTEGER NOT NULL DEFAULT 1,
      first_seen      TEXT    NOT NULL DEFAULT (datetime('now')),
      last_confirmed  TEXT    NOT NULL DEFAULT (datetime('now')),
      category        TEXT    NOT NULL DEFAULT 'technical',
      dimensional_weight REAL DEFAULT 1.0
    );
  `);

  // Copy all existing data
  db.exec(`INSERT INTO core_knowledge_v2 SELECT * FROM core_knowledge`);

  // Rename tables
  db.exec(`ALTER TABLE core_knowledge RENAME TO core_knowledge_v1_backup`);
  db.exec(`ALTER TABLE core_knowledge_v2 RENAME TO core_knowledge`);

  console.log('[MIGRATE] core_knowledge migrated to flexible dimensions schema');
  console.log('[MIGRATE] Backup preserved as core_knowledge_v1_backup');
}
```

Call this from ensureSchema() AFTER the existing CREATE TABLE blocks.

### Step 2C — Dimension Discovery in llmExtractFacts()

When Groq extracts facts, let it propose new dimensions if the existing 5 don't fit.

Change the llmExtractFacts prompt from:
```
category (one of: revenue, social, technical, strategic, behavioral)
```

To:
```typescript
// Get current active dimensions from DB
const activeDims = db.prepare(
  `SELECT name FROM memory_dimensions WHERE status IN ('active','emerging') ORDER BY name`
).all().map((r: any) => r.name);

const dimList = activeDims.join(', ');

const prompt = `Extract 2-4 core factual patterns from these compressed memories.
For each, output a JSON array of objects with keys:
- fact (string, max 150 chars)
- category (one of: ${dimList}, OR a new_dimension name if none fit — use snake_case, max 20 chars)
- confidence (0.0-1.0)
- is_new_dimension (boolean — true only if you used a category not in the list above)

${joined}

Output ONLY the JSON array, nothing else.`;
```

Then in the fact processing loop, handle new dimensions:

```typescript
for (const f of parsed) {
  if (!f.fact || !f.category) continue;

  const isNew = f.is_new_dimension === true;
  const catName = String(f.category).slice(0, 20).toLowerCase().replace(/\s+/g, '_');

  if (isNew) {
    // Register as emerging dimension
    db.prepare(`
      INSERT OR IGNORE INTO memory_dimensions (name, description, status)
      VALUES (?, ?, 'emerging')
    `).run(catName, `Auto-discovered from operational data`);

    console.log(`[DIMENSION] New emerging dimension: ${catName}`);
  }

  allFacts.push({
    fact: String(f.fact).slice(0, 150),
    category: catName,
    confidence: Math.max(0, Math.min(1, f.confidence)),
  });
}
```

### Step 2D — Dimension Promotion Logic

After each L2→L3 compression run, check if any emerging dimension has earned promotion:

```typescript
export function evaluateDimensions(db: Database.Database): void {
  // Count facts per emerging dimension
  const emerging = db.prepare(
    `SELECT name FROM memory_dimensions WHERE status = 'emerging'`
  ).all() as Array<{ name: string }>;

  for (const dim of emerging) {
    const stats = db.prepare(
      `SELECT COUNT(*) as count, AVG(confidence) as avg_conf
       FROM core_knowledge WHERE category = ?`
    ).get(dim.name) as { count: number; avg_conf: number };

    if (!stats) continue;

    if (stats.count >= 3 && stats.avg_conf >= 0.7) {
      // Promote to active
      db.prepare(
        `UPDATE memory_dimensions SET status = 'active', promoted_at = datetime('now'),
         fact_count = ?, avg_confidence = ? WHERE name = ?`
      ).run(stats.count, stats.avg_conf, dim.name);
      console.log(`[DIMENSION] Promoted '${dim.name}' to active (${stats.count} facts, ${stats.avg_conf.toFixed(2)} avg confidence)`);
    } else if (stats.count === 0) {
      // No facts landed here after 5+ compression runs — deprecate
      const runCount = (db.prepare(`SELECT COUNT(*) as c FROM sleep_log`).get() as any).c;
      if (runCount > 5) {
        db.prepare(`UPDATE memory_dimensions SET status = 'deprecated' WHERE name = ?`).run(dim.name);
        console.log(`[DIMENSION] Deprecated empty dimension: ${dim.name}`);
      }
    }
  }

  // Update fact counts for active dimensions
  db.prepare(
    `UPDATE memory_dimensions SET
       fact_count = (SELECT COUNT(*) FROM core_knowledge WHERE category = memory_dimensions.name),
       avg_confidence = (SELECT AVG(confidence) FROM core_knowledge WHERE category = memory_dimensions.name)
     WHERE status = 'active'`
  ).run();
}
```

Call evaluateDimensions() at the end of compressL2toL3().

### Step 2E — Prediction-Weighted Dimensional Recall

Read tiamat_predictions. Compute per-phase accuracy to weight recall by dimension.

Add to smartRecall():

```typescript
// Compute dimensional weights from prediction accuracy
function getDimensionalWeights(db: Database.Database): Record<string, number> {
  const defaults: Record<string, number> = {
    revenue: 1.0, social: 1.0, technical: 1.0, strategic: 1.0, behavioral: 1.0
  };

  try {
    // Phase → dimension mapping
    const phaseMap: Record<string, string> = {
      'REFLECT': 'behavioral',
      'BUILD': 'technical',
      'MARKET': 'social',
      'REVENUE': 'revenue',
      'STRATEGY': 'strategic',
    };

    const phases = db.prepare(
      `SELECT phase, AVG(score) as avg_score, COUNT(*) as count
       FROM tiamat_predictions
       WHERE scored = 1 AND score IS NOT NULL AND phase IS NOT NULL
       GROUP BY phase`
    ).all() as Array<{ phase: string; avg_score: number; count: number }>;

    for (const row of phases) {
      const dim = phaseMap[row.phase?.toUpperCase()];
      if (!dim || row.count < 5) continue;

      // Accuracy is low (0.029 avg) — use inverse: lower accuracy = lower weight
      // But floor at 0.3 so no dimension gets completely ignored
      const weight = Math.max(0.3, Math.min(2.0, 0.5 + (row.avg_score * 10)));
      defaults[dim] = weight;
    }
  } catch {}

  return defaults;
}
```

Then in the L3 search block of smartRecall(), apply the weight to scoring:

```typescript
const weights = getDimensionalWeights(db);

for (const row of l3Rows) {
  const dimWeight = weights[row.category] || 1.0;
  const weightedScore = row.confidence * dimWeight;
  const text = `[L3:${row.category}|${row.confidence.toFixed(1)}] ${row.fact}`;
  const cost = estimateTokens(text);
  if (tokensUsed + cost > tokenBudget) break;
  results.push({ tier: "L3", content: text, id: row.id, score: weightedScore });
  tokensUsed += cost;
}
```

---

## Final Verification

After both stages, run:

```bash
# Check dimension registry
cd /root/entity && node -e "
const Database = require('better-sqlite3');
const db = new Database('/root/.automaton/memory.db');
const dims = db.prepare('SELECT name, status, fact_count, avg_confidence FROM memory_dimensions ORDER BY status, fact_count DESC').all();
console.log('Dimension registry:', JSON.stringify(dims, null, 2));
db.close();
"

# Check L2 distribution
cd /root/entity && node -e "
const Database = require('better-sqlite3');
const db = new Database('/root/.automaton/memory.db');
const l2 = db.prepare('SELECT category, COUNT(*) as c FROM compressed_memories GROUP BY category ORDER BY c DESC').all();
const l3 = db.prepare('SELECT category, COUNT(*) as c, AVG(confidence) as conf FROM core_knowledge GROUP BY category ORDER BY c DESC').all();
console.log('L2 by dimension:', l2);
console.log('L3 by dimension:', l3);
db.close();
"

# Full stats
cd /root/entity && npx tsx src/agent/memory-compress.ts stats
```

Then do a git commit:
git add -A
git commit -m "feat: Honeycomb LIDA upgrade — L2 dimensional projection, dynamic dimension spawning, confidence propagation, prediction-weighted recall"
git push origin main

---

## What This Achieves

Before this upgrade:
- L2: flat, dimensionless, keyword search only
- L3: 5 fixed dimensions, hard constraint
- Recall: LIKE scan across full tables
- Prediction data: unused for recall weighting

After this upgrade:
- L2: dimensional projection, retained flag, pruning respects value
- L3: infinite dimensions that emerge from operational data
- Recall: dimension-filtered, prediction-weighted, provenance-labeled
- Prediction data: feeds dimensional confidence weights
- New dimensions auto-discover from TIAMAT's experience

The space is now genuinely expandable. When TIAMAT starts working on
grants heavily, a 'grants' dimension will emerge from the data.
When she runs the DX Terminal trading game, a 'trading' dimension
may emerge. The lattice grows with her experience rather than being
capped by what we predicted she would need.
```
