#!/usr/bin/env python3
"""
BLUESKY ANALYTICS RUNNER
Fetches recent TIAMAT posts from Bluesky, records engagement metrics
Run as cooldown task to keep analytics DB updated
"""

import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BLUESKY_ANALYTICS_DB = Path.home() / '.automaton' / 'bluesky_analytics.db'

def init_db():
    """Initialize analytics database"""
    conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            uri TEXT PRIMARY KEY,
            text TEXT,
            created_at TEXT,
            likes INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            fetched_at TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY,
            uri TEXT,
            engagement_rate REAL,
            hour_posted INTEGER,
            day_of_week TEXT,
            text_length INTEGER,
            recorded_at TEXT,
            FOREIGN KEY(uri) REFERENCES posts(uri)
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON posts(created_at DESC)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_hour ON metrics(hour_posted)')
    
    conn.commit()
    conn.close()

def record_post(uri, text, created_at, likes, reposts, replies):
    """Record a post and calculate metrics"""
    conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
    c = conn.cursor()
    
    fetched_at = datetime.utcnow().isoformat()
    c.execute('''
        INSERT OR REPLACE INTO posts (uri, text, created_at, likes, reposts, replies, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (uri, text, created_at, likes, reposts, replies, fetched_at))
    
    # Calculate metrics
    created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    hour = created.hour
    day = created.strftime('%A')
    engagement_rate = (likes + reposts + replies) / max(len(text), 1)
    
    c.execute('''
        INSERT INTO metrics (uri, engagement_rate, hour_posted, day_of_week, text_length, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (uri, engagement_rate, hour, day, len(text), fetched_at))
    
    conn.commit()
    conn.close()

def get_top_posts(limit=10):
    """Get top performing posts"""
    conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
    c = conn.cursor()
    
    c.execute('''
        SELECT uri, text, created_at, likes, reposts, replies,
               CAST((likes + reposts + replies) AS REAL) / MAX(LENGTH(text), 1) as engagement_rate,
               CAST((julianday('now') - julianday(created_at)) * 24 AS INTEGER) as hours_old
        FROM posts
        ORDER BY (likes + reposts + replies) DESC
        LIMIT ?
    ''', (limit,))
    
    rows = c.fetchall()
    conn.close()
    
    return [{
        'uri': r[0],
        'text': r[1][:100] + '...' if len(r[1]) > 100 else r[1],
        'created_at': r[2],
        'likes': r[3],
        'reposts': r[4],
        'replies': r[5],
        'engagement_rate': r[6],
        'hours_old': r[7]
    } for r in rows]

def get_optimal_posting_times():
    """Analyze optimal posting times"""
    conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
    c = conn.cursor()
    
    c.execute('''
        SELECT hour_posted, AVG(engagement_rate) as avg_engagement, COUNT(*) as post_count
        FROM metrics
        GROUP BY hour_posted
        ORDER BY avg_engagement DESC
    ''')
    
    rows = c.fetchall()
    conn.close()
    
    return [{
        'hour': r[0],
        'avg_engagement': r[1],
        'sample_size': r[2]
    } for r in rows]

def get_engagement_trends(days=7):
    """Get engagement trends"""
    conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
    c = conn.cursor()
    
    c.execute('''
        SELECT DATE(created_at) as date, COUNT(*) as post_count, AVG(likes + reposts + replies) as avg_engagement
        FROM posts
        WHERE created_at >= datetime('now', '-' || ? || ' days')
        GROUP BY DATE(created_at)
        ORDER BY date DESC
    ''', (days,))
    
    rows = c.fetchall()
    conn.close()
    
    return [{'date': r[0], 'post_count': r[1], 'avg_engagement': r[2]} for r in rows]

def export_analytics():
    """Export full analytics summary"""
    return {
        'exported_at': datetime.utcnow().isoformat(),
        'top_posts': get_top_posts(5),
        'optimal_times': get_optimal_posting_times(),
        'engagement_trends': get_engagement_trends(7)
    }

if __name__ == '__main__':
    init_db()
    analytics = export_analytics()
    print(json.dumps(analytics, indent=2))
    sys.exit(0)
