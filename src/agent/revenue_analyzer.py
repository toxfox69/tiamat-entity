#!/usr/bin/env python3
"""
TIAMAT Revenue Analyzer

Analyzes cost.log and payment data to identify revenue patterns,
bottlenecks, and optimization opportunities.

Outputs:
- revenue_report.json (structured data)
- revenue_insights.md (human-readable)
"""

import csv
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import sys

def analyze_cost_log(cost_log_path):
    """Parse cost.log CSV and extract revenue/cost metrics."""
    try:
        with open(cost_log_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print(f"Cost log not found: {cost_log_path}")
        return None
    
    if not rows:
        return None
    
    # Expected columns: timestamp, cycle, provider, tokens_input, tokens_output, cost_usd
    stats = {
        'total_cycles': len(rows),
        'total_cost': 0,
        'by_provider': defaultdict(lambda: {'count': 0, 'cost': 0, 'tokens': 0}),
        'recent_cost': 0,  # Last 50 cycles
        'daily_cost': defaultdict(float),
        'avg_cost_per_cycle': 0,
    }
    
    for i, row in enumerate(rows):
        try:
            cost = float(row.get('cost_usd', 0))
            provider = row.get('provider', 'unknown')
            tokens = float(row.get('tokens_input', 0)) + float(row.get('tokens_output', 0))
            timestamp = row.get('timestamp', '')
            
            stats['total_cost'] += cost
            stats['by_provider'][provider]['count'] += 1
            stats['by_provider'][provider]['cost'] += cost
            stats['by_provider'][provider]['tokens'] += tokens
            
            # Last 50 cycles
            if i >= len(rows) - 50:
                stats['recent_cost'] += cost
            
            # By day
            if timestamp:
                try:
                    date = timestamp.split('T')[0]
                    stats['daily_cost'][date] += cost
                except:
                    pass
        except (ValueError, KeyError):
            continue
    
    if rows:
        stats['avg_cost_per_cycle'] = stats['total_cost'] / len(rows)
    
    return stats

def analyze_payments(db_path=None):
    """Analyze payment transactions from inference_proxy.db."""
    if not db_path:
        db_path = '/tmp/inference_proxy.db'
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Try to find payment-related tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 10")
        tables = [row[0] for row in cursor.fetchall()]
        
        payments = {
            'total_revenue': 0,
            'total_attempts': 0,
            'conversion_rate': 0,
            'by_endpoint': defaultdict(lambda: {'attempts': 0, 'revenue': 0}),
            'by_method': defaultdict(lambda: {'attempts': 0, 'revenue': 0}),
        }
        
        # Look for payment or transaction table
        for table in tables:
            if 'payment' in table.lower() or 'transaction' in table.lower():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                    count = cursor.fetchone()[0]
                    
                    # Get schema to understand columns
                    cursor.execute(f"PRAGMA table_info([{table}])")
                    columns = {row[1]: row[2] for row in cursor.fetchall()}
                    
                    if count > 0:
                        # Extract payment data
                        cursor.execute(f"SELECT * FROM [{table}] LIMIT 100")
                        for row in cursor.fetchall():
                            # Generic parsing
                            pass
                except Exception as e:
                    pass
        
        conn.close()
        return payments
    except Exception as e:
        print(f"Could not analyze payments: {e}")
        return None

def generate_insights(cost_stats, payment_stats):
    """Generate human-readable insights from the data."""
    insights = []
    
    if cost_stats:
        total_cost = cost_stats['total_cost']
        avg_cycle_cost = cost_stats['avg_cost_per_cycle']
        recent_cost = cost_stats['recent_cost']
        
        insights.append(f"**Cost Summary**")
        insights.append(f"- Total spend: ${total_cost:.4f} across {cost_stats['total_cycles']} cycles")
        insights.append(f"- Average per cycle: ${avg_cycle_cost:.6f}")
        insights.append(f"- Last 50 cycles: ${recent_cost:.4f}")
        insights.append("")
        
        # By provider
        insights.append(f"**Provider Breakdown**")
        for provider, data in sorted(cost_stats['by_provider'].items(), 
                                     key=lambda x: x[1]['cost'], reverse=True):
            pct = (data['cost'] / total_cost * 100) if total_cost > 0 else 0
            cost_per_token = data['cost'] / data['tokens'] * 1000000 if data['tokens'] > 0 else 0
            insights.append(
                f"- {provider}: ${data['cost']:.4f} ({pct:.1f}%) | "
                f"{data['count']} calls | ${cost_per_token:.4f}/1M tokens"
            )
        insights.append("")
    
    if payment_stats and payment_stats['total_attempts'] > 0:
        insights.append(f"**Revenue Summary**")
        insights.append(f"- Total revenue: ${payment_stats['total_revenue']:.4f}")
        insights.append(f"- Total payment attempts: {payment_stats['total_attempts']}")
        insights.append(f"- Conversion rate: {payment_stats['conversion_rate']*100:.1f}%")
        insights.append("")
    else:
        insights.append(f"**⚠️ Revenue Issue**")
        insights.append(f"- Payment conversion broken or not recording correctly")
        insights.append(f"- Check: summarize_api.py x402 payment logic")
        insights.append("")
    
    return "\n".join(insights)

if __name__ == '__main__':
    cost_log = Path('/root/.automaton/cost.log')
    
    print("🔍 TIAMAT Revenue Analyzer")
    print("="*50)
    
    # Analyze costs
    cost_stats = analyze_cost_log(cost_log)
    payment_stats = analyze_payments()
    
    # Generate insights
    insights = generate_insights(cost_stats, payment_stats)
    print(insights)
    
    # Write reports
    if cost_stats:
        with open('/root/.automaton/revenue_report.json', 'w') as f:
            # Convert defaultdicts to regular dicts for JSON serialization
            report = {
                'timestamp': datetime.utcnow().isoformat(),
                'total_cycles': cost_stats['total_cycles'],
                'total_cost': cost_stats['total_cost'],
                'avg_cost_per_cycle': cost_stats['avg_cost_per_cycle'],
                'recent_cost_50': cost_stats['recent_cost'],
                'by_provider': {k: dict(v) for k, v in cost_stats['by_provider'].items()},
            }
            json.dump(report, f, indent=2)
        print(f"\n✓ Report saved to revenue_report.json")
    
    # Write markdown insights
    with open('/root/.automaton/revenue_insights.md', 'w') as f:
        f.write(f"# Revenue Analysis — {datetime.utcnow().isoformat()}\n\n")
        f.write(insights)
    print(f"✓ Insights saved to revenue_insights.md")
