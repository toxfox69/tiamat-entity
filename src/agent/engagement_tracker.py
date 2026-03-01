#!/usr/bin/env python3
"""
TIAMAT Engagement Analytics Tracker

Monitor Bluesky/Farcaster post performance and optimize content strategy.
Runs as a cooldown task to avoid cycle costs.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# Track engagement on recent posts
# Format: {post_id: {url, text, timestamp, engagement: {likes, reposts, replies}, keywords: []}}

TRACKER_DB = Path("/root/.automaton/engagement.json")

def init_tracker():
    """Initialize engagement tracker database."""
    if not TRACKER_DB.exists():
        TRACKER_DB.write_text(json.dumps({
            "posts": [],
            "summary": {
                "total_posts": 0,
                "avg_engagement_rate": 0.0,
                "best_content_type": None,
                "last_updated": None
            }
        }, indent=2))

def log_post(url: str, text: str, content_type: str):
    """
    Log a social post.
    content_type: 'technical' | 'sales' | 'cost' | 'research'
    """
    init_tracker()
    data = json.loads(TRACKER_DB.read_text())
    
    post = {
        "id": len(data["posts"]) + 1,
        "url": url,
        "text": text[:100],  # First 100 chars
        "content_type": content_type,
        "timestamp": datetime.utcnow().isoformat(),
        "engagement": {"likes": 0, "reposts": 0, "replies": 0, "conversions": 0},
        "keywords": extract_keywords(text)
    }
    
    data["posts"].append(post)
    TRACKER_DB.write_text(json.dumps(data, indent=2))
    print(f"[TRACKER] Logged post {post['id']}: {content_type}")

def extract_keywords(text: str) -> list:
    """Extract keywords from post text."""
    keywords = []
    important_words = [
        "inference", "autonomy", "customer", "revenue", "research",
        "DARPA", "energy", "cybersecurity", "robotics", "API",
        "cost", "cycle", "agent", "evolution", "capability"
    ]
    for word in important_words:
        if word.lower() in text.lower():
            keywords.append(word)
    return keywords

def analyze_performance():
    """
    Analyze which content types drive the most engagement.
    Returns performance report.
    """
    init_tracker()
    data = json.loads(TRACKER_DB.read_text())
    posts = data["posts"]
    
    if not posts:
        return {"status": "no_data", "message": "No posts logged yet"}
    
    # Group by content type
    by_type = {}
    for post in posts:
        ct = post["content_type"]
        if ct not in by_type:
            by_type[ct] = {"count": 0, "total_engagement": 0, "conversions": 0}
        
        engagement = post["engagement"]
        total = engagement["likes"] + engagement["reposts"] + engagement["replies"]
        by_type[ct]["count"] += 1
        by_type[ct]["total_engagement"] += total
        by_type[ct]["conversions"] += engagement["conversions"]
    
    # Calculate metrics
    results = {}
    for ct, metrics in by_type.items():
        avg_engagement = metrics["total_engagement"] / metrics["count"] if metrics["count"] > 0 else 0
        conversion_rate = metrics["conversions"] / metrics["count"] if metrics["count"] > 0 else 0
        results[ct] = {
            "posts": metrics["count"],
            "avg_engagement": avg_engagement,
            "total_conversions": metrics["conversions"],
            "conversion_rate": conversion_rate
        }
    
    # Find best performer
    best = max(results.items(), key=lambda x: x[1]["conversion_rate"], default=(None, {}))
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "by_content_type": results,
        "best_content_type": best[0],
        "recommendation": f"Focus on {best[0]} posts (conversion rate: {best[1].get('conversion_rate', 0):.1%})"
    }

def generate_report():
    """Generate human-readable engagement report."""
    analysis = analyze_performance()
    
    report = f"""
# 📊 ENGAGEMENT ANALYTICS REPORT
{analysis['timestamp']}

## By Content Type
"""
    
    for ct, metrics in analysis.get("by_content_type", {}).items():
        report += f"""
### {ct.title()}
- Posts: {metrics['posts']}
- Avg Engagement: {metrics['avg_engagement']:.1f}
- Conversions: {metrics['total_conversions']}
- Conversion Rate: {metrics['conversion_rate']:.1%}
"""
    
    report += f"""
## Recommendation
{analysis.get('recommendation', 'Insufficient data')}
"""
    
    return report

if __name__ == "__main__":
    # Test: Log some sample posts
    init_tracker()
    print("[TRACKER] Engagement tracker initialized")
    print(generate_report())
