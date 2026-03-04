"""
summarize_cache.py — SQLite cache layer for /summarize endpoint.

Schema: cache(id, input_hash, output, cost_usd, created_at, hits)
- MD5 hash of input text as cache key
- Only caches inputs < 5000 chars
- Weekly prune: keeps last 10k entries by recency
"""

import hashlib
import sqlite3
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CACHE_DB = '/root/.automaton/summarize_cache.db'
MAX_INPUT_LEN = 5000
MAX_CACHE_ENTRIES = 10_000

# Estimated Groq API cost per summarize call (llama-3.3-70b ~500 in + 100 out tokens)
COST_PER_CALL_USD = 0.0007


def _get_conn():
    conn = sqlite3.connect(CACHE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_cache_db():
    """Create cache table and counters table if not present."""
    conn = _get_conn()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS cache (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                input_hash  TEXT NOT NULL UNIQUE,
                output      TEXT NOT NULL,
                cost_usd    REAL NOT NULL DEFAULT 0.0007,
                created_at  TEXT NOT NULL,
                hits        INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_cache_hash ON cache(input_hash);
            CREATE INDEX IF NOT EXISTS idx_cache_created ON cache(created_at);

            CREATE TABLE IF NOT EXISTS cache_counters (
                key   TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO cache_counters(key, value) VALUES ('hits', 0);
            INSERT OR IGNORE INTO cache_counters(key, value) VALUES ('misses', 0);
        ''')
        conn.commit()
    finally:
        conn.close()


def _input_hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def cache_get(text: str) -> str | None:
    """Return cached summary for text, or None on miss. Increments hit counter."""
    if len(text) > MAX_INPUT_LEN:
        return None
    h = _input_hash(text)
    conn = _get_conn()
    try:
        row = conn.execute(
            'SELECT id, output FROM cache WHERE input_hash = ?', (h,)
        ).fetchone()
        if row:
            conn.execute('UPDATE cache SET hits = hits + 1 WHERE id = ?', (row['id'],))
            conn.execute(
                "UPDATE cache_counters SET value = value + 1 WHERE key = 'hits'"
            )
            conn.commit()
            return row['output']
        else:
            conn.execute(
                "UPDATE cache_counters SET value = value + 1 WHERE key = 'misses'"
            )
            conn.commit()
            return None
    except Exception as e:
        logger.error(f"cache_get error: {e}")
        return None
    finally:
        conn.close()


def cache_set(text: str, summary: str, cost_usd: float = COST_PER_CALL_USD) -> bool:
    """Store a summary result. No-op if input > MAX_INPUT_LEN."""
    if len(text) > MAX_INPUT_LEN:
        return False
    h = _input_hash(text)
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            '''INSERT INTO cache(input_hash, output, cost_usd, created_at, hits)
               VALUES(?, ?, ?, ?, 0)
               ON CONFLICT(input_hash) DO UPDATE SET
                 output=excluded.output,
                 cost_usd=excluded.cost_usd,
                 created_at=excluded.created_at''',
            (h, summary, cost_usd, now)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"cache_set error: {e}")
        return False
    finally:
        conn.close()


def cache_stats() -> dict:
    """Return cache statistics dict."""
    conn = _get_conn()
    try:
        counters = {
            row['key']: row['value']
            for row in conn.execute('SELECT key, value FROM cache_counters').fetchall()
        }
        hits = counters.get('hits', 0)
        misses = counters.get('misses', 0)
        total = hits + misses
        hit_rate = round(hits / total, 4) if total > 0 else 0.0

        size = conn.execute('SELECT COUNT(*) FROM cache').fetchone()[0]
        savings_usd = conn.execute(
            'SELECT COALESCE(SUM(cost_usd * hits), 0) FROM cache'
        ).fetchone()[0]

        return {
            'cache_hits': hits,
            'cache_misses': misses,
            'hit_rate': hit_rate,
            'cache_size': size,
            'savings_usd': round(savings_usd, 6),
        }
    except Exception as e:
        logger.error(f"cache_stats error: {e}")
        return {
            'cache_hits': 0,
            'cache_misses': 0,
            'hit_rate': 0.0,
            'cache_size': 0,
            'savings_usd': 0.0,
        }
    finally:
        conn.close()


def cache_prune() -> int:
    """
    Delete entries beyond MAX_CACHE_ENTRIES, keeping the most recent.
    Returns number of rows deleted.
    """
    conn = _get_conn()
    try:
        size = conn.execute('SELECT COUNT(*) FROM cache').fetchone()[0]
        if size <= MAX_CACHE_ENTRIES:
            return 0
        excess = size - MAX_CACHE_ENTRIES
        conn.execute(
            '''DELETE FROM cache WHERE id IN (
                SELECT id FROM cache ORDER BY created_at ASC LIMIT ?
            )''',
            (excess,)
        )
        conn.commit()
        logger.info(f"cache_prune: removed {excess} stale entries")
        return excess
    except Exception as e:
        logger.error(f"cache_prune error: {e}")
        return 0
    finally:
        conn.close()


def maybe_prune_weekly():
    """Prune cache if the last prune was > 7 days ago (tracked in cache_counters)."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM cache_counters WHERE key = 'last_prune_epoch'"
        ).fetchone()
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        if row:
            last = int(row['value'])
        else:
            last = 0
            conn.execute(
                "INSERT OR IGNORE INTO cache_counters(key, value) VALUES('last_prune_epoch', 0)"
            )
            conn.commit()

        if now_epoch - last >= 7 * 86400:
            removed = cache_prune()
            conn2 = _get_conn()
            conn2.execute(
                "INSERT OR REPLACE INTO cache_counters(key, value) VALUES('last_prune_epoch', ?)",
                (now_epoch,)
            )
            conn2.commit()
            conn2.close()
            logger.info(f"Weekly cache prune complete: {removed} entries removed")
    except Exception as e:
        logger.error(f"maybe_prune_weekly error: {e}")
    finally:
        conn.close()
