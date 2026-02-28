#!/usr/bin/env python3
"""
Bluesky Engagement Tracker

Periodically polls Bluesky API for engagement metrics on TIAMAT posts.
Stores to SQLite for historical analysis and trend detection.
"""

import os
import json
import sqlite3
from datetime import datetime
import requests
from base64 import b64encode

DB_PATH = '/root/.automaton/engagement.db'

def init_db():
    """Create engagement tracking table if needed."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS bluesky_posts (
            uri TEXT PRIMARY KEY,
            text TEXT,
            posted_at TEXT,
            tracked_at TEXT,
            likes INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0.0
        )
    ''')
    conn.commit()
    conn.close()

def get_bluesky_posts():
    """
    Fetch recent posts from authenticated Bluesky session.
    Uses Bearer token from BLUESKY_SESSION env var (set by post_bluesky tool).
    """
    handle = os.getenv('BLUESKY_HANDLE', 'tiamat')
    password = os.getenv('BLUESKY_APP_PASSWORD', '')
    
    if not password:
        return []
    
    try:
        # Authenticate
        auth_response = requests.post(
            'https://bsky.social/xrpc/com.atproto.server.createSession',
            json={'identifier': handle, 'password': password},
            timeout=5
        )
        auth_response.raise_for_status()
        token = auth_response.json().get('accessJwt')
        
        # Fetch timeline
        timeline = requests.get(
            f'https://bsky.social/xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit=20',
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        timeline.raise_for_status()
        
        posts = []
        for item in timeline.json().get('feed', []):
            post = item.get('post', {})
            posts.append({
                'uri': post.get('uri'),
                'text': post.get('record', {}).get('text'),
                'likes': post.get('likeCount', 0),
                'reposts': post.get('repostCount', 0),
                'replies': post.get('replyCount', 0),
                'posted_at': post.get('record', {}).get('createdAt')
            })
        return posts
    except Exception as e:
        print(f"Engagement fetch error: {e}")
        return []

def track_engagement():
    """Poll and store engagement metrics."""
    init_db()
    posts = get_bluesky_posts()
    
    if not posts:
        return {'status': 'no_posts', 'posts_tracked': 0}
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    for post in posts:
        total_engagement = post['likes'] + post['reposts'] + post['replies']
        try:
            c.execute('''
                INSERT OR REPLACE INTO bluesky_posts 
                (uri, text, posted_at, tracked_at, likes, reposts, replies, engagement_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                post['uri'],
                post['text'][:200],  # Store first 200 chars
                post['posted_at'],
                now,
                post['likes'],
                post['reposts'],
                post['replies'],
                total_engagement / max(1, len(post['text']))  # normalize by post length
            ))
        except Exception as e:
            print(f"Insert error for {post.get('uri')}: {e}")
    
    conn.commit()
    conn.close()
    
    return {
        'status': 'tracked',
        'posts_tracked': len(posts),
        'timestamp': now
    }

if __name__ == '__main__':
    result = track_engagement()
    print(json.dumps(result))
