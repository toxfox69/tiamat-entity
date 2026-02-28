#!/usr/bin/env python3
"""
Cooldown task: Fetch recent Bluesky posts and update analytics DB
This runs automatically between cycles to keep engagement data fresh
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from atproto import Client
import sqlite3

# Load environment
BLUESKY_HANDLE = os.getenv('BLUESKY_HANDLE')
BLUESKY_APP_PASSWORD = os.getenv('BLUESKY_APP_PASSWORD')
BLUESKY_ANALYTICS_DB = Path.home() / '.automaton' / 'bluesky_analytics.db'

def init_analytics_db():
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
    
    conn.commit()
    conn.close()

def fetch_and_record_posts():
    """Fetch recent posts from Bluesky and record engagement"""
    try:
        client = Client()
        client.login(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
        
        # Fetch author's recent posts
        posts = client.get_author_feed(BLUESKY_HANDLE, limit=20)
        
        init_analytics_db()
        conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
        c = conn.cursor()
        
        for post in posts.feed:
            record = post.post.record
            
            uri = post.post.uri
            text = record.text
            created_at = record.created_at
            likes = post.post.likeCount or 0
            reposts = post.post.repostCount or 0
            replies = post.post.replyCount or 0
            fetched_at = datetime.utcnow().isoformat()
            
            # Insert or update post
            c.execute('''
                INSERT OR REPLACE INTO posts (uri, text, created_at, likes, reposts, replies, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (uri, text, created_at, likes, reposts, replies, fetched_at))
            
            # Record metrics
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            hour = created.hour
            day = created.strftime('%A')
            engagement_rate = (likes + reposts + replies) / max(len(text), 1)
            
            c.execute('''
                INSERT OR IGNORE INTO metrics (uri, engagement_rate, hour_posted, day_of_week, text_length, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (uri, engagement_rate, hour, day, len(text), fetched_at))
        
        conn.commit()
        conn.close()
        
        print(f'✅ Updated {len(posts.feed)} posts in analytics DB')
        sys.exit(0)
        
    except Exception as e:
        print(f'❌ Error: {e}')
        sys.exit(1)

if __name__ == '__main__':
    fetch_and_record_posts()
