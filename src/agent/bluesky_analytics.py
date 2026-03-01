#!/usr/bin/env python3
"""
BlueSky Post Engagement Analyzer
Queries recent posts from TIAMAT's Bluesky profile and measures engagement.
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

# Bluesky AT Protocol client
try:
    from atproto import Client, models
except ImportError:
    print("ERROR: atproto not installed. Install with: pip install atproto")
    exit(1)

def get_bluesky_client() -> Client:
    """Initialize Bluesky client with credentials."""
    username = os.getenv('BLUESKY_USERNAME', 'tiamat.live')  # Default: agent's handle
    app_password = os.getenv('BLUESKY_APP_PASSWORD')
    
    if not app_password:
        raise ValueError("BLUESKY_APP_PASSWORD not set in environment")
    
    client = Client()
    client.login(username, app_password)
    return client

def fetch_my_posts(client: Client, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch recent posts from my profile with engagement metrics.
    Returns list of dicts with: uri, text, created_at, likes, reposts, replies, engagement_rate
    """
    
    try:
        # Get my DID (Decentralized Identifier)
        my_profile = client.get_profile('self')
        my_did = my_profile.did
        
        # Fetch my feed (recent posts)
        posts_response = client.feed.get_author_feed(actor=my_did, limit=limit)
        
        posts_data = []
        
        for feed_item in posts_response.feed:
            post = feed_item.post
            
            # Extract engagement metrics
            likes = post.likeCount or 0
            reposts = post.replyCount or 0  # Note: ATProto uses replyCount for reposts in some versions
            replies = post.replyCount or 0
            
            # Calculate engagement rate (likes + reposts + replies) / estimated reach
            # Rough estimate: assume followers can see it (use profile follower count)
            estimated_reach = max(my_profile.followersCount or 1, 1)
            engagement_rate = (likes + reposts + replies) / estimated_reach if estimated_reach > 0 else 0
            
            # Extract text from record
            text = ""
            if hasattr(post.record, 'text'):
                text = post.record.text
            
            posts_data.append({
                'uri': post.uri,
                'cid': post.cid,
                'text': text[:200],  # First 200 chars
                'created_at': post.record.createdAt if hasattr(post.record, 'createdAt') else None,
                'likes': likes,
                'reposts': reposts,
                'replies': replies,
                'engagement_rate': round(engagement_rate, 4),
                'estimated_reach': estimated_reach
            })
        
        return posts_data
    
    except Exception as e:
        print(f"ERROR fetching posts: {e}")
        return []

def analyze_engagement(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze post engagement patterns.
    Returns summary stats and insights.
    """
    if not posts:
        return {}
    
    engagement_rates = [p['engagement_rate'] for p in posts]
    likes = [p['likes'] for p in posts]
    reposts = [p['reposts'] for p in posts]
    replies = [p['replies'] for p in posts]
    
    return {
        'total_posts_analyzed': len(posts),
        'avg_engagement_rate': round(sum(engagement_rates) / len(engagement_rates), 4),
        'max_engagement_rate': max(engagement_rates),
        'avg_likes': round(sum(likes) / len(likes), 1),
        'avg_reposts': round(sum(reposts) / len(reposts), 1),
        'avg_replies': round(sum(replies) / len(replies), 1),
        'top_post': max(posts, key=lambda p: p['engagement_rate']) if posts else None,
        'analyzed_at': datetime.utcnow().isoformat() + 'Z'
    }

def save_engagement_data(posts: List[Dict[str, Any]], analysis: Dict[str, Any], filepath: str = "/root/.automaton/bluesky_engagement.json"):
    """
    Save engagement data and analysis to file.
    """
    data = {
        'posts': posts,
        'analysis': analysis,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Saved engagement data to {filepath}")
    return data

def main():
    """
    Main entry point: fetch posts, analyze engagement, save results.
    """
    print("[Bluesky Engagement Analyzer] Starting...")
    
    try:
        client = get_bluesky_client()
        print("✅ Connected to Bluesky")
        
        posts = fetch_my_posts(client, limit=30)
        print(f"✅ Fetched {len(posts)} recent posts")
        
        if not posts:
            print("⚠️ No posts found")
            return
        
        analysis = analyze_engagement(posts)
        print(f"\n📊 Engagement Summary:")
        print(f"   Posts analyzed: {analysis['total_posts_analyzed']}")
        print(f"   Avg engagement rate: {analysis['avg_engagement_rate']:.2%}")
        print(f"   Avg likes per post: {analysis['avg_likes']:.1f}")
        print(f"   Top post engagement: {analysis['top_post']['engagement_rate']:.2%}")
        
        save_engagement_data(posts, analysis)
        print(f"\n✅ Engagement analysis saved")
        
    except Exception as e:
        print(f"ERROR: {e}")
        exit(1)

if __name__ == '__main__':
    main()
