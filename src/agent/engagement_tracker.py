#!/usr/bin/env python3
"""
Bluesky Engagement Tracker — analyzes TIAMAT posts, tracks engagement, recommends optimal posting times.
BUILT: TURN 115 (evolution directive)
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

DB_PATH = "/root/.automaton/engagement.db"

def init_db():
    """Create engagement tracking DB schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            timestamp TEXT,
            text TEXT,
            likes INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            hour_posted INTEGER,
            day_of_week TEXT,
            engagement_score REAL DEFAULT 0.0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS hourly_stats (
            hour INTEGER PRIMARY KEY,
            avg_likes REAL DEFAULT 0.0,
            avg_reposts REAL DEFAULT 0.0,
            avg_replies REAL DEFAULT 0.0,
            sample_size INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def log_post(post_id, timestamp, text, hour_posted, day_of_week):
    """Log a new TIAMAT post."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO posts (post_id, timestamp, text, hour_posted, day_of_week)
        VALUES (?, ?, ?, ?, ?)
    """, (post_id, timestamp, text, hour_posted, day_of_week))
    conn.commit()
    conn.close()

def update_engagement(post_id, likes, reposts, replies, impressions):
    """Update engagement metrics for a post."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Calculate engagement score: (likes + reposts*2 + replies*3) / impressions
    engagement_score = 0.0
    if impressions > 0:
        engagement_score = (likes + reposts*2 + replies*3) / impressions
    
    c.execute("""
        UPDATE posts
        SET likes=?, reposts=?, replies=?, impressions=?, engagement_score=?, updated_at=CURRENT_TIMESTAMP
        WHERE post_id=?
    """, (likes, reposts, replies, impressions, engagement_score, post_id))
    conn.commit()
    conn.close()

def analyze_hourly_performance():
    """Analyze engagement by hour posted. Returns optimal posting hour."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get stats by hour
    c.execute("""
        SELECT hour_posted, AVG(likes), AVG(reposts), AVG(replies), COUNT(*)
        FROM posts
        WHERE hour_posted IS NOT NULL
        GROUP BY hour_posted
        ORDER BY AVG(likes + reposts*2 + replies*3) DESC
    """)
    results = c.fetchall()
    conn.close()
    
    if not results:
        return None
    
    best_hour = results[0][0]
    best_avg_likes = results[0][1]
    
    return {
        "best_hour": best_hour,
        "best_hour_avg_likes": best_avg_likes,
        "all_hours": [{
            "hour": r[0],
            "avg_likes": round(r[1], 2),
            "avg_reposts": round(r[2], 2),
            "avg_replies": round(r[3], 2),
            "sample_size": r[4]
        } for r in results]
    }

def get_top_posts(limit=5):
    """Get your top performing posts by engagement score."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT timestamp, text, likes, reposts, replies, engagement_score
        FROM posts
        ORDER BY engagement_score DESC
        LIMIT ?
    """, (limit,))
    results = c.fetchall()
    conn.close()
    
    return [{
        "posted_at": r[0],
        "text": r[1][:100] + "..." if len(r[1]) > 100 else r[1],
        "likes": r[2],
        "reposts": r[3],
        "replies": r[4],
        "engagement_score": round(r[5], 4)
    } for r in results]

def report():
    """Generate engagement report."""
    hourly = analyze_hourly_performance()
    top_posts = get_top_posts()
    
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "hourly_analysis": hourly,
        "top_posts": top_posts
    }
    
    return report

if __name__ == "__main__":
    init_db()
    print(json.dumps(report(), indent=2))
