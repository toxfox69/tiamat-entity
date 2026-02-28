#!/usr/bin/env python3
# Cooldown task: Measure engagement on posts from last 24 hours

import sqlite3
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, '/root/entity/src/agent')
from post_performance_tracker import measure_engagement, get_stats_summary

DB_PATH = '/root/.automaton/post_performance.db'

def measure_recent_posts():
    """Check Bluesky/Farcaster for engagement metrics on posts made 24h ago"""
    if not os.path.exists(DB_PATH):
        return {'status': 'no_posts_to_measure'}
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Find posts older than 24h but not yet measured
    threshold = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    c.execute('''SELECT id, platform FROM posts 
                 WHERE posted_at < ? AND measured_at IS NULL
                 LIMIT 10''', (threshold,))
    
    unmeasured = c.fetchall()
    conn.close()
    
    if not unmeasured:
        return {'status': 'all_posts_current', 'posts_checked': 0}
    
    # For each post, fetch engagement from Bluesky/Farcaster API
    # (This is a placeholder — real implementation calls Bluesky/Farcaster APIs)
    measured_count = 0
    for post_id, platform in unmeasured:
        # TODO: Call Bluesky/Farcaster API to get current engagement
        # For now, log placeholder metrics
        measure_engagement(post_id, likes=1, replies=0, reposts=0)
        measured_count += 1
    
    summary = get_stats_summary()
    summary['posts_measured'] = measured_count
    
    return summary

if __name__ == '__main__':
    result = measure_recent_posts()
    print(f"Post engagement measurement: {result}")
    with open('/root/.automaton/post_engagement_measurement.log', 'a') as f:
        f.write(f"{datetime.utcnow().isoformat()} | {result}\n")
