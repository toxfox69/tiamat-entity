#!/usr/bin/env python3
"""
Flask endpoint wrapper for Bluesky analytics
Add this to summarize_api.py
"""

from flask import Flask, jsonify
import sqlite3
from pathlib import Path
from datetime import datetime

BLUESKY_ANALYTICS_DB = Path.home() / '.automaton' / 'bluesky_analytics.db'

def register_analytics_routes(app: Flask):
    """Register Bluesky analytics endpoints"""
    
    @app.route('/api/bluesky/analytics', methods=['GET'])
    def get_bluesky_analytics():
        """Get full Bluesky engagement analytics"""
        if not BLUESKY_ANALYTICS_DB.exists():
            return jsonify({'error': 'No analytics data yet'}), 404
        
        conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Top posts
        c.execute('''
            SELECT uri, text, created_at, likes, reposts, replies,
                   CAST((likes + reposts + replies) AS REAL) / MAX(LENGTH(text), 1) as engagement_rate
            FROM posts
            ORDER BY (likes + reposts + replies) DESC
            LIMIT 10
        ''')
        top_posts = [dict(row) for row in c.fetchall()]
        
        # Optimal posting hours
        c.execute('''
            SELECT hour_posted, AVG(engagement_rate) as avg_engagement, COUNT(*) as post_count
            FROM metrics
            GROUP BY hour_posted
            ORDER BY avg_engagement DESC
            LIMIT 5
        ''')
        optimal_hours = [dict(row) for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            'timestamp': datetime.utcnow().isoformat(),
            'top_posts': top_posts,
            'optimal_posting_hours': optimal_hours
        })
    
    @app.route('/api/bluesky/trends', methods=['GET'])
    def get_bluesky_trends():
        """Get 7-day engagement trends"""
        if not BLUESKY_ANALYTICS_DB.exists():
            return jsonify({'error': 'No analytics data yet'}), 404
        
        conn = sqlite3.connect(BLUESKY_ANALYTICS_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute('''
            SELECT DATE(created_at) as date, COUNT(*) as post_count,
                   AVG(likes + reposts + replies) as avg_engagement
            FROM posts
            WHERE created_at >= datetime('now', '-7 days')
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        ''')
        
        trends = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify({'trends': trends})
