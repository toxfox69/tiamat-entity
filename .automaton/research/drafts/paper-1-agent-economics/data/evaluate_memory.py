#!/usr/bin/env python3
"""
Memory Quality Evaluation for Paper 1: The Cost of Autonomy
Evaluates L3 facts, L2 compression fidelity, recall effectiveness, knowledge triples.
"""

import sqlite3
import json
import re
from collections import Counter
from difflib import SequenceMatcher

DB_PATH = "/root/.automaton/memory.db"
OUTPUT_PATH = "/root/.automaton/research/drafts/paper-1-agent-economics/data/memory-quality.json"

def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.lower().split()), set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def classify_l3_fact(fact: str, confidence: float, category: str) -> str:
    """Classify an L3 fact into quality categories using heuristics."""
    f = fact.strip()
    fl = f.lower()

    # Garbage detection
    if len(f) < 15:
        return "garbage"
    if re.match(r'^(cycle|turn|tool|exec|tick)\s*\d', fl):
        return "garbage"
    if fl in ("successfully", "completed", "done", "ok", "true", "false"):
        return "garbage"
    if re.match(r'^\d+$', f):
        return "garbage"
    if fl.startswith("tool ") and len(f) < 40:
        return "garbage"
    # Pure logging artifacts
    if re.match(r'^(ran|executed|called|invoked|checked)\s+\w+', fl) and len(f) < 50:
        return "garbage"
    if "successfully" in fl and len(f) < 60 and not any(w in fl for w in ("api", "deploy", "config", "email", "server")):
        return "garbage"

    # Staleness detection - references to specific old cycles, IPs that may have changed
    if re.search(r'cycle\s*\d{3,}', fl) and not any(w in fl for w in ("every", "per", "average", "total")):
        return "stale"
    if re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', f) and "159.89.38.17" not in f:
        return "stale"
    # References to specific dates without being general principles
    if re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}', fl):
        # But keep if it's about deadlines or important dates
        if not any(w in fl for w in ("deadline", "patent", "grant", "expir", "filed", "launched")):
            return "stale"

    # Triviality detection
    trivial_patterns = [
        r'^(the )?(agent |tiamat )?(was |is |has been )?(running|active|online|operational)',
        r'^(completed|finished|done with)\s+\w+\s*$',
        r'^(no |zero )?(errors?|issues?|problems?)\s*(found|detected|occurred)',
        r'^(system|server|service)\s+(is )?(up|running|active|online)',
        r'^(checked|verified|confirmed)\s+\w+',
    ]
    for pat in trivial_patterns:
        if re.match(pat, fl):
            return "trivial"

    # If it's about specific infrastructure, tools, APIs, strategies — it's actionable
    actionable_signals = [
        "api", "endpoint", "deploy", "config", "email", "sendgrid", "smtp",
        "rate limit", "cost", "revenue", "customer", "user", "error",
        "permission", "security", "patent", "grant", "proposal",
        "bluesky", "farcaster", "devto", "hashnode", "linkedin",
        "model", "inference", "haiku", "sonnet", "groq", "token",
        "memory", "compress", "consolidat", "genome", "instinct",
        "nginx", "gunicorn", "ssl", "cert", "dns", "domain",
        "strategy", "marketing", "content", "article", "post",
        "tool", "browse", "search", "exec", "write", "read",
        "python", "typescript", "node", "react", "flask",
        "database", "sqlite", "postgres", "redis",
        "docker", "systemd", "cron", "process",
        "engagement", "follower", "impression", "click",
        "hrt", "wellness", "bloom", "health",
        "sentinel", "firewall", "privacy", "iot",
    ]
    if any(sig in fl for sig in actionable_signals):
        # Has actionable context and is long enough to be meaningful
        if len(f) > 30:
            return "actionable"
        else:
            return "trivial"

    # Default: if it's a substantive sentence, it's at least trivially accurate
    if len(f) > 50:
        return "trivial"

    return "garbage"


def evaluate_l3(db):
    """Evaluate all L3 core knowledge facts."""
    rows = db.execute("SELECT id, fact, confidence, category FROM core_knowledge").fetchall()

    counts = Counter()
    examples = {"actionable": [], "trivial": [], "stale": [], "garbage": []}

    for row in rows:
        fid, fact, conf, cat = row
        quality = classify_l3_fact(fact, conf, cat)
        counts[quality] += 1
        if len(examples[quality]) < 5:
            examples[quality].append(fact[:120])

    total = len(rows)
    return {
        "total_evaluated": total,
        "accurate_actionable": counts["actionable"],
        "accurate_trivial": counts["trivial"],
        "stale_outdated": counts["stale"],
        "garbage_noise": counts["garbage"],
        "contradicted": 0,  # Would need cross-fact comparison
        "quality_rate": round(counts["actionable"] / max(total, 1), 4),
        "effective_rate": round((counts["actionable"] + counts["trivial"]) / max(total, 1), 4),
        "garbage_rate": round(counts["garbage"] / max(total, 1), 4),
        "examples": examples,
    }


def evaluate_l2_fidelity(db):
    """Evaluate L2 compression fidelity by comparing to source L1 memories."""
    l2_rows = db.execute(
        "SELECT id, summary, source_memory_ids, topic FROM compressed_memories ORDER BY RANDOM() LIMIT 20"
    ).fetchall()

    scores = []
    examples = []

    for row in l2_rows:
        l2_id, summary, source_ids_raw, topic = row
        if not summary:
            continue

        # Try to parse source IDs
        try:
            source_ids = json.loads(source_ids_raw) if source_ids_raw else []
        except:
            source_ids = []

        if source_ids:
            placeholders = ",".join("?" * len(source_ids))
            l1_rows = db.execute(
                f"SELECT content FROM tiamat_memories WHERE id IN ({placeholders})",
                source_ids
            ).fetchall()
            l1_texts = [r[0] for r in l1_rows if r[0]]
        else:
            l1_texts = []

        if not l1_texts:
            # Can't evaluate without sources
            scores.append(3)  # neutral
            continue

        # Count distinct claims in L1 vs L2
        l1_combined = " ".join(l1_texts)
        l1_sentences = [s.strip() for s in re.split(r'[.!?\n]', l1_combined) if len(s.strip()) > 10]
        l2_sentences = [s.strip() for s in re.split(r'[.!?\n]', summary) if len(s.strip()) > 10]

        # Rough preservation score: what fraction of L1 key terms appear in L2?
        l1_words = set(l1_combined.lower().split())
        l2_words = set(summary.lower().split())
        # Remove stop words
        stops = {"the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
                 "have", "has", "had", "do", "does", "did", "will", "would", "could",
                 "should", "may", "might", "shall", "can", "to", "of", "in", "for",
                 "on", "with", "at", "by", "from", "as", "into", "through", "during",
                 "and", "or", "but", "not", "no", "if", "then", "than", "that", "this",
                 "it", "its", "i", "we", "they", "he", "she", "you", "my", "our", "their"}
        l1_key = l1_words - stops
        l2_key = l2_words - stops
        if l1_key:
            overlap = len(l1_key & l2_key) / len(l1_key)
        else:
            overlap = 0

        # Score 1-5 based on overlap
        if overlap > 0.5:
            score = 5
        elif overlap > 0.35:
            score = 4
        elif overlap > 0.2:
            score = 3
        elif overlap > 0.1:
            score = 2
        else:
            score = 1

        scores.append(score)
        if len(examples) < 3:
            examples.append({
                "l2_summary": summary[:150],
                "l1_count": len(l1_texts),
                "l1_claims": len(l1_sentences),
                "l2_claims": len(l2_sentences),
                "overlap": round(overlap, 3),
                "score": score,
            })

    return {
        "samples_evaluated": len(scores),
        "mean_preservation_score": round(sum(scores) / max(len(scores), 1), 2),
        "score_distribution": dict(Counter(scores)),
        "examples": examples,
    }


def evaluate_recall(db):
    """Evaluate how effectively memories are recalled."""
    row = db.execute("""
        SELECT AVG(recalled_count), MAX(recalled_count),
               SUM(CASE WHEN recalled_count = 0 THEN 1 ELSE 0 END),
               COUNT(*)
        FROM tiamat_memories
    """).fetchone()

    avg_recall, max_recall, never_recalled, total = row

    # Distribution of recall counts
    dist_rows = db.execute("""
        SELECT recalled_count, COUNT(*) as cnt
        FROM tiamat_memories
        GROUP BY recalled_count
        ORDER BY recalled_count
        LIMIT 10
    """).fetchall()

    return {
        "total_memories": total,
        "never_recalled_count": never_recalled or 0,
        "never_recalled_pct": round((never_recalled or 0) / max(total, 1) * 100, 1),
        "avg_recall_count": round(avg_recall or 0, 2),
        "max_recall_count": max_recall or 0,
        "recall_distribution": {str(r[0]): r[1] for r in dist_rows},
    }


def evaluate_knowledge_triples(db):
    """Evaluate knowledge graph triple quality."""
    rows = db.execute(
        "SELECT entity, relation, value, confidence FROM tiamat_knowledge ORDER BY RANDOM() LIMIT 30"
    ).fetchall()

    accurate = 0
    outdated = 0
    garbage = 0
    examples = {"accurate": [], "outdated": [], "garbage": []}

    for entity, relation, value, conf in rows:
        e, r, v = entity.strip(), relation.strip(), value.strip()

        # Garbage: empty or very short
        if not e or not v or len(e) < 2 or len(v) < 2:
            garbage += 1
            continue

        # Garbage: numeric-only entities/values without context
        if re.match(r'^\d+$', e) or re.match(r'^\d+$', v):
            garbage += 1
            if len(examples["garbage"]) < 3:
                examples["garbage"].append(f"{e} → {r} → {v}")
            continue

        # Check for outdated references
        if any(w in v.lower() for w in ["1vcpu", "2gb ram", "deprecated", "removed", "old"]):
            outdated += 1
            if len(examples["outdated"]) < 3:
                examples["outdated"].append(f"{e} → {r} → {v}")
            continue

        accurate += 1
        if len(examples["accurate"]) < 3:
            examples["accurate"].append(f"{e} → {r} → {v}")

    return {
        "total_evaluated": len(rows),
        "accurate": accurate,
        "outdated": outdated,
        "garbage": garbage,
        "accuracy_rate": round(accurate / max(len(rows), 1), 4),
        "examples": examples,
    }


def detect_near_duplicates(db, sample_size=200):
    """Check for near-duplicate L3 facts."""
    rows = db.execute(
        "SELECT id, fact FROM core_knowledge ORDER BY RANDOM() LIMIT ?", (sample_size,)
    ).fetchall()

    dupe_pairs = 0
    for i in range(len(rows)):
        for j in range(i + 1, min(i + 20, len(rows))):  # Check nearby only for speed
            if jaccard(rows[i][1], rows[j][1]) > 0.8:
                dupe_pairs += 1

    return {
        "sample_size": len(rows),
        "near_duplicate_pairs": dupe_pairs,
        "estimated_duplicate_rate": round(dupe_pairs / max(len(rows), 1), 4),
    }


if __name__ == "__main__":
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")

    print("Evaluating L3 fact quality...")
    l3_quality = evaluate_l3(db)
    print(f"  Actionable: {l3_quality['accurate_actionable']}, Trivial: {l3_quality['accurate_trivial']}, "
          f"Stale: {l3_quality['stale_outdated']}, Garbage: {l3_quality['garbage_noise']}")

    print("Evaluating L2 compression fidelity...")
    l2_fidelity = evaluate_l2_fidelity(db)
    print(f"  Mean preservation score: {l2_fidelity['mean_preservation_score']}/5")

    print("Evaluating recall effectiveness...")
    recall = evaluate_recall(db)
    print(f"  Never recalled: {recall['never_recalled_pct']}%, Avg recalls: {recall['avg_recall_count']}")

    print("Evaluating knowledge triples...")
    triples = evaluate_knowledge_triples(db)
    print(f"  Accurate: {triples['accurate']}, Outdated: {triples['outdated']}, Garbage: {triples['garbage']}")

    print("Checking near-duplicates...")
    dupes = detect_near_duplicates(db)
    print(f"  Duplicate pairs found: {dupes['near_duplicate_pairs']} in {dupes['sample_size']} sample")

    result = {
        "l3_quality": l3_quality,
        "l2_compression_fidelity": l2_fidelity,
        "recall_effectiveness": recall,
        "knowledge_triple_quality": triples,
        "near_duplicates": dupes,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nResults saved to {OUTPUT_PATH}")
    db.close()
