#!/usr/bin/env python3
"""
Telegram Bot Subscription Handler
Manages USDC payments and subscription status for tiamat_assistant_bot
"""

import sqlite3
import json
import time
import os
from datetime import datetime, timedelta

DB_PATH = '/root/telegram_users.db'
WALLET = '0xdA4A701aB24e2B6805b702dDCC3cB4D8f591d397'

# ─── INITIALIZATION ───
def init_db():
    """Initialize database schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subscription_status TEXT DEFAULT 'free'
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            tier TEXT,
            price_usdc REAL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            tx_hash TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscription_requests (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            duration_weeks INTEGER,
            payment_address TEXT,
            unique_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            tx_hash TEXT,
            verified BOOLEAN DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ─── SUBSCRIPTION REQUESTS ───
def generate_subscription_request(user_id, amount=5.0, weeks=1):
    """Create a new subscription request."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Ensure user exists
        c.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
        
        # Generate unique ID
        unique_id = f"{user_id}:{int(time.time())}"
        expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
        
        c.execute('''
            INSERT INTO subscription_requests 
            (user_id, amount, duration_weeks, payment_address, unique_id, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, amount, weeks, WALLET, unique_id, expires_at))
        
        conn.commit()
        conn.close()
        
        return {
            'user_id': user_id,
            'amount': amount,
            'weeks': weeks,
            'address': WALLET,
            'request_id': unique_id,
            'expires_at': expires_at
        }
    except Exception as e:
        print(f"Error generating request: {e}")
        return None

# ─── PAYMENT VERIFICATION ───
def verify_usdc_payment(user_id, unique_id, timeout=60):
    """Verify payment on Base mainnet."""
    try:
        # In a real implementation, this would:
        # 1. Query Base RPC for USDC transfers to WALLET
        # 2. Match by unique_id in transaction data
        # 3. Return tx_hash when found
        
        # For now, return mock verification
        return {
            'verified': False,
            'tx_hash': None,
            'message': 'Waiting for payment detection...'
        }
    except Exception as e:
        print(f"Error verifying payment: {e}")
        return {'verified': False, 'tx_hash': None}

# ─── ACTIVATION ───
def activate_subscription(user_id, weeks=1, tx_hash=None):
    """Activate a subscription after payment verified."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        expires_at = (datetime.now() + timedelta(weeks=weeks)).isoformat()
        
        # Insert subscription
        c.execute('''
            INSERT INTO subscriptions 
            (user_id, tier, price_usdc, expires_at, tx_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 'pro', weeks * 5.0, expires_at, tx_hash or 'manual'))
        
        # Update user status
        c.execute('UPDATE users SET subscription_status = ? WHERE user_id = ?', ('pro', user_id))
        
        conn.commit()
        conn.close()
        
        return {
            'user_id': user_id,
            'is_active': True,
            'expires_at': expires_at,
            'tier': 'pro'
        }
    except Exception as e:
        print(f"Error activating subscription: {e}")
        return None

# ─── STATUS CHECK ───
def get_subscription_status(user_id):
    """Get current subscription status for user."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check for active subscription
        c.execute('''
            SELECT expires_at FROM subscriptions 
            WHERE user_id = ? AND expires_at > datetime('now')
            ORDER BY expires_at DESC LIMIT 1
        ''', (user_id,))
        
        row = c.fetchone()
        conn.close()
        
        if row:
            return {
                'user_id': user_id,
                'status': 'active',
                'is_active': True,
                'expires_at': row[0]
            }
        else:
            return {
                'user_id': user_id,
                'status': 'free',
                'is_active': False,
                'expires_at': None
            }
    except Exception as e:
        print(f"Error getting status: {e}")
        return {'user_id': user_id, 'is_active': False, 'status': 'error'}

if __name__ == '__main__':
    init_db()
    print("✅ Database initialized")
