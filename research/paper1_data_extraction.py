#!/usr/bin/env python3
"""
TIAMAT Paper 1 — Complete Data Extraction
"The Cost of Autonomy: A Longitudinal Analysis of AI Agent Operational Economics"
EnergenAI LLC | Jason Chamberlain + TIAMAT
"""

import json
import sqlite3
import os
import re
import csv
from datetime import datetime, timezone
from collections import Counter, defaultdict

OUTPUT_DIR = "/root/.automaton/research/paper1_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

results = {}

# ============================================================
# 1. COST LOG — /root/.automaton/cost.log
# ============================================================
print("\n=== COST DATA ===")
cost_entries = []
total_cost = 0.0
model_costs = defaultdict(float)
model_counts = defaultdict(int)
daily_costs = defaultdict(float)

cost_log = "/root/.automaton/cost.log"
if os.path.exists(cost_log):
    with open(cost_log, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            try:
                # Try to parse — log format may vary, be flexible
                entry = {'raw': row}

                # Extract timestamp if present
                for field in row:
                    if 'T' in field and ':' in field:
                        entry['timestamp'] = field
                        try:
                            date = field[:10]
                            entry['date'] = date
                        except:
                            pass

                # Extract model
                for field in row:
                    if 'haiku' in field.lower() or 'sonnet' in field.lower() or 'claude' in field.lower() or 'groq' in field.lower() or 'llama' in field.lower():
                        entry['model'] = field
                        break

                # Extract cost (last float-looking field)
                for field in reversed(row):
                    try:
                        cost = float(field)
                        if 0 < cost < 1.0:  # sanity check for per-cycle cost
                            entry['cost'] = cost
                            total_cost += cost
                            if 'model' in entry:
                                model_costs[entry['model']] += cost
                                model_counts[entry['model']] += 1
                            if 'date' in entry:
                                daily_costs[entry['date']] += cost
                            break
                    except:
                        continue

                # Extract token counts
                tokens = []
                for field in row:
                    try:
                        t = int(field)
                        if 100 < t < 200000:
                            tokens.append(t)
                    except:
                        continue
                if tokens:
                    entry['tokens'] = tokens

                cost_entries.append(entry)
            except Exception as e:
                pass

print(f"Total cost log entries: {len(cost_entries)}")
print(f"Total spend: ${total_cost:.4f}")
print(f"Model breakdown: {dict(model_costs)}")
print(f"Daily costs (last 7 days): {dict(sorted(daily_costs.items())[-7:])}")

results['cost'] = {
    'total_entries': len(cost_entries),
    'total_spend_usd': round(total_cost, 4),
    'model_costs': dict(model_costs),
    'model_call_counts': dict(model_counts),
    'daily_costs': dict(daily_costs),
    'date_range': {
        'first': min(daily_costs.keys()) if daily_costs else 'unknown',
        'last': max(daily_costs.keys()) if daily_costs else 'unknown',
        'days_active': len(daily_costs)
    }
}

# ============================================================
# 2. ACTIVITY LOG — /root/.automaton/tiamat.log
# ============================================================
print("\n=== ACTIVITY LOG ===")
log_file = "/root/.automaton/tiamat.log"
tool_usage = Counter()
model_usage = Counter()
cycle_count = 0
error_count = 0
burst_cycles = 0
log_lines = 0
first_line = None
last_line = None

if os.path.exists(log_file):
    with open(log_file, 'r', errors='replace') as f:
        for line in f:
            log_lines += 1
            if first_line is None:
                first_line = line.strip()
            last_line = line.strip()

            # Count cycles
            if 'Turn' in line or 'turn' in line or 'cycle' in line.lower():
                turn_match = re.search(r'[Tt]urn[:\s]+(\d+)', line)
                if turn_match:
                    cycle_count = max(cycle_count, int(turn_match.group(1)))

            # Count tool usage
            tool_patterns = [
                'post_bluesky', 'search_web', 'web_fetch', 'remember', 'recall',
                'ask_claude_code', 'write_file', 'read_file', 'exec', 'generate_image',
                'send_telegram', 'send_email', 'post_farcaster', 'check_revenue',
                'check_usdc_balance', 'reflect', 'log_strategy', 'learn_fact',
                'rewrite_mission', 'self_improve', 'deploy_app', 'browse_web'
            ]
            for tool in tool_patterns:
                if tool in line:
                    tool_usage[tool] += 1

            # Model usage
            if 'haiku' in line.lower():
                model_usage['haiku'] += 1
            elif 'sonnet' in line.lower():
                model_usage['sonnet'] += 1
                if 'burst' in line.lower() or 'strategic' in line.lower():
                    burst_cycles += 1
            elif 'groq' in line.lower() or 'llama' in line.lower():
                model_usage['groq'] += 1

            # Errors
            if 'error' in line.lower() or 'failed' in line.lower() or 'ERROR' in line:
                error_count += 1

print(f"Log lines: {log_lines}")
print(f"Max turn/cycle found: {cycle_count}")
print(f"Tool usage (top 10): {tool_usage.most_common(10)}")
print(f"Model usage: {dict(model_usage)}")
print(f"Errors logged: {error_count}")
print(f"First entry: {first_line[:100] if first_line else 'none'}")
print(f"Last entry: {last_line[:100] if last_line else 'none'}")

results['activity'] = {
    'log_lines': log_lines,
    'max_cycle': cycle_count,
    'tool_usage': dict(tool_usage.most_common(30)),
    'model_usage': dict(model_usage),
    'burst_cycles_detected': burst_cycles,
    'error_count': error_count,
    'log_first_entry': first_line[:200] if first_line else None,
    'log_last_entry': last_line[:200] if last_line else None
}

# ============================================================
# 3. MEMORY DATABASE
# ============================================================
print("\n=== MEMORY DATABASE ===")
for db_path in ["/root/.automaton/memory.db", "/root/.automaton/mind.sqlite", "/root/.automaton/state.db"]:
    if os.path.exists(db_path):
        print(f"\nFound: {db_path} ({os.path.getsize(db_path)/1024:.1f} KB)")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [t[0] for t in cursor.fetchall()]
            print(f"Tables: {tables}")

            db_stats = {'path': db_path, 'size_kb': round(os.path.getsize(db_path)/1024, 1), 'tables': {}}

            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]

                    # Get column info
                    cursor.execute(f"PRAGMA table_info({table})")
                    cols = [c[1] for c in cursor.fetchall()]

                    # Sample recent entries
                    try:
                        cursor.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 3")
                        samples = cursor.fetchall()
                    except:
                        samples = []

                    db_stats['tables'][table] = {
                        'count': count,
                        'columns': cols,
                        'recent_samples': [str(s)[:200] for s in samples]
                    }
                    print(f"  {table}: {count} rows, columns: {cols}")
                except Exception as e:
                    print(f"  {table}: error - {e}")

            conn.close()
            results[f'db_{os.path.basename(db_path)}'] = db_stats
        except Exception as e:
            print(f"  Error: {e}")

# ============================================================
# 4. API USAGE — check_revenue data
# ============================================================
print("\n=== API USAGE ===")
api_files = [
    "/root/.automaton/api_users.json",
    "/root/api/payments.db",
    "/root/.automaton/grants/EMAIL_LOG.md"
]
for f in api_files:
    if os.path.exists(f):
        size = os.path.getsize(f)
        print(f"Found: {f} ({size} bytes)")
        if f.endswith('.json') and size < 100000:
            try:
                with open(f) as fh:
                    data = json.load(fh)
                print(f"  Content preview: {str(data)[:300]}")
                results['api_usage'] = data
            except:
                pass
        elif f.endswith('.db'):
            try:
                conn = sqlite3.connect(f)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [t[0] for t in cursor.fetchall()]
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    print(f"  {table}: {count} rows")
                conn.close()
            except Exception as e:
                print(f"  Error: {e}")

# ============================================================
# 5. GENOME & IDENTITY EVOLUTION
# ============================================================
print("\n=== GENOME / IDENTITY EVOLUTION ===")
genome_path = "/root/.automaton/genome.json"
if os.path.exists(genome_path):
    with open(genome_path) as f:
        genome = json.load(f)
    print(f"Genome version: {genome.get('version', 'unknown')}")
    print(f"Traits categories: {list(genome.get('traits', {}).keys())}")
    print(f"Instincts count: {len(genome.get('instincts', []))}")
    print(f"Antibodies count: {len(genome.get('antibodies', []))}")
    results['genome'] = {
        'version': genome.get('version'),
        'trait_categories': list(genome.get('traits', {}).keys()),
        'instinct_count': len(genome.get('instincts', [])),
        'antibody_count': len(genome.get('antibodies', [])),
        'sample_instincts': genome.get('instincts', [])[:5],
        'sample_antibodies': genome.get('antibodies', [])[:5]
    }

# ============================================================
# 6. PROGRESS LOG
# ============================================================
print("\n=== PROGRESS LOG ===")
progress_path = "/root/.automaton/PROGRESS.md"
if os.path.exists(progress_path):
    size = os.path.getsize(progress_path)
    with open(progress_path) as f:
        content = f.read()
    line_count = content.count('\n')
    print(f"PROGRESS.md: {size/1024:.1f} KB, {line_count} lines")
    # Get first and last 500 chars
    results['progress'] = {
        'size_kb': round(size/1024, 1),
        'line_count': line_count,
        'first_500': content[:500],
        'last_500': content[-500:]
    }

# ============================================================
# 7. SLEEP LOG (consolidation cycles)
# ============================================================
print("\n=== SLEEP / CONSOLIDATION ===")
for db_path in ["/root/.automaton/memory.db", "/root/.automaton/state.db"]:
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sleep_log'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*), MIN(started_at), MAX(started_at) FROM sleep_log")
                row = cursor.fetchone()
                print(f"Sleep cycles: {row[0]}, first: {row[1]}, last: {row[2]}")
                results['sleep_cycles'] = {'count': row[0], 'first': row[1], 'last': row[2]}
            conn.close()
        except:
            pass

# ============================================================
# 8. FILE SYSTEM SCAN — what TIAMAT has built
# ============================================================
print("\n=== ARTIFACTS TIAMAT HAS BUILT ===")
scan_dirs = [
    "/root/.automaton/images",
    "/root/.automaton/grants",
    "/root/.automaton/research",
    "/root/entity/src/agent",
    "/root/memory_api"
]
artifacts = {}
for d in scan_dirs:
    if os.path.exists(d):
        files = []
        for root, dirs, filenames in os.walk(d):
            dirs[:] = [x for x in dirs if x not in ['.git', '__pycache__', 'node_modules']]
            for fn in filenames:
                fp = os.path.join(root, fn)
                try:
                    stat = os.stat(fp)
                    files.append({
                        'path': fp,
                        'size_kb': round(stat.st_size/1024, 1),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()[:10]
                    })
                except:
                    pass
        artifacts[d] = {'file_count': len(files), 'files': files[:20]}
        print(f"{d}: {len(files)} files")

results['artifacts'] = artifacts

# ============================================================
# SAVE EVERYTHING
# ============================================================
output_path = f"{OUTPUT_DIR}/extraction_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n{'='*60}")
print(f"EXTRACTION COMPLETE")
print(f"Saved to: {output_path}")
print(f"{'='*60}")

# Print the paper-ready summary
print("\n=== PAPER 1 KEY STATS (publication-ready) ===")
print(f"Total autonomous cycles: {results.get('activity', {}).get('max_cycle', 'unknown')}")
print(f"Total operational spend: ${results.get('cost', {}).get('total_spend_usd', 0):.2f}")
print(f"Days active: {results.get('cost', {}).get('date_range', {}).get('days_active', 'unknown')}")
print(f"Total log lines: {results.get('activity', {}).get('log_lines', 'unknown')}")
print(f"Tools used: {len(results.get('activity', {}).get('tool_usage', {}))}")
print(f"Model distribution: {results.get('activity', {}).get('model_usage', {})}")
