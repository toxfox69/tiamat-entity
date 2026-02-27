#!/usr/bin/env python3
"""Real-time monitoring for Moltbook pilot agents."""

import sqlite3
import json
from datetime import datetime
import requests
import os

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram_alert(message):
    """Send alert to creator via Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': message})

def monitor_moltbook_usage():
    """Query usage stats and send alerts if thresholds exceeded."""
    db = sqlite3.connect('/root/.automaton/inference_proxy.db')
    cursor = db.cursor()
    
    # Get daily usage per agent
    cursor.execute('''
        SELECT agent_name, COUNT(*) as requests, SUM(tokens) as tokens
        FROM usage_log
        WHERE user_ip IN (SELECT api_key FROM moltbook_pilot)
        AND DATE(timestamp) = DATE('now')
        GROUP BY agent_name
    ''')
    
    results = cursor.fetchall()
    db.close()
    
    if results:
        msg = "🔴 **MOLTBOOK PILOT — DAILY REPORT**\n\n"
        total_requests = 0
        total_tokens = 0
        
        for agent_name, requests, tokens in results:
            msg += f"{agent_name}: {requests} req, {tokens} tokens\n"
            total_requests += requests
            total_tokens += tokens
        
        msg += f"\n📊 **Total:** {total_requests} requests, {total_tokens} tokens\n"
        msg += f"💰 **Est. cost:** ${total_tokens * 0.0001 / 1000:.2f}\n"
        send_telegram_alert(msg)

def check_for_errors():
    """Alert on any API errors from Moltbook agents."""
    db = sqlite3.connect('/root/.automaton/inference_proxy.db')
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) FROM error_log
        WHERE user_ip IN (SELECT api_key FROM moltbook_pilot)
        AND timestamp > datetime('now', '-1 hour')
    ''')
    
    error_count = cursor.fetchone()[0]
    db.close()
    
    if error_count > 0:
        send_telegram_alert(f"🚨 **MOLTBOOK ALERT** — {error_count} errors in last hour. Check logs.")

if __name__ == '__main__':
    monitor_moltbook_usage()
    check_for_errors()
