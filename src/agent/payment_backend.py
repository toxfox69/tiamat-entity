#!/usr/bin/env python3
"""
TIAMAT Payment Backend Module
Implements /api/generate-key and /api/verify-payment endpoints.
"""

import os
import sys
import sqlite3
import uuid
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import jsonify, request
import logging

# Import payment verification
sys.path.insert(0, os.path.dirname(__file__))
from payment_verify import verify_usdc_payment

logger = logging.getLogger('payment_backend')

# Database path
DB_PATH = '/root/.automaton/payment.db'

# ──────────────────────────────────────────────────────────
# DATABASE INITIALIZATION
# ──────────────────────────────────────────────────────────

def init_payment_db():
    """Create payment database schema if not exists."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # API Keys table
        c.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                api_key TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                base_daily_limit INTEGER DEFAULT 100,
                paid_tier_expires_at TEXT,
                paid_daily_limit INTEGER DEFAULT 100,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # User quotas table
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_quotas (
                user_id TEXT PRIMARY KEY,
                requests_today INTEGER DEFAULT 0,
                requests_reset_at TEXT,
                last_payment_tx TEXT,
                last_payment_at TEXT
            )
        ''')
        
        # Payment transactions table
        c.execute('''
            CREATE TABLE IF NOT EXISTS payment_transactions (
                tx_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                tx_hash TEXT NOT NULL UNIQUE,
                amount_usdc REAL,
                verified_at TEXT,
                quota_granted_at TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f'Payment database initialized at {DB_PATH}')
        return True
    except Exception as e:
        logger.error(f'Failed to init payment DB: {e}')
        return False

# ──────────────────────────────────────────────────────────
# API KEY GENERATION
# ──────────────────────────────────────────────────────────

def generate_api_key(user_id):
    """Generate a new API key for a user."""
    try:
        key_id = str(uuid.uuid4())
        api_key = f'tiamat_sk_{uuid.uuid4().hex[:32]}'
        created_at = datetime.utcnow().isoformat()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO api_keys 
            (key_id, user_id, api_key, created_at, base_daily_limit)
            VALUES (?, ?, ?, ?, ?)
        ''', (key_id, user_id, api_key, created_at, 100))
        
        conn.commit()
        conn.close()
        
        logger.info(f'Generated API key for user {user_id}')
        return api_key
    except sqlite3.IntegrityError as e:
        logger.warning(f'API key generation failed (duplicate): {e}')
        return None
    except Exception as e:
        logger.error(f'Failed to generate API key: {e}')
        return None

# ──────────────────────────────────────────────────────────
# PAYMENT VERIFICATION
# ──────────────────────────────────────────────────────────

def verify_and_grant_quota(user_id, tx_hash):
    """Verify USDC payment and grant quota upgrade."""
    try:
        # Verify the transaction on-chain
        result = verify_usdc_payment(tx_hash)
        
        if not result or result.get('status') != 'confirmed':
            logger.warning(f'Payment verification failed for tx {tx_hash}')
            return {'verified': False, 'error': 'Transaction not confirmed'}
        
        # Record the transaction
        tx_id = str(uuid.uuid4())
        verified_at = datetime.utcnow().isoformat()
        paid_tier_expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if tx already processed
        c.execute('SELECT tx_id FROM payment_transactions WHERE tx_hash = ?', (tx_hash,))
        if c.fetchone():
            conn.close()
            return {'verified': False, 'error': 'Transaction already processed'}
        
        # Record payment
        c.execute('''
            INSERT INTO payment_transactions 
            (tx_id, user_id, tx_hash, amount_usdc, verified_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (tx_id, user_id, tx_hash, result.get('amount', 100), verified_at, 'confirmed'))
        
        # Update or create user quota
        c.execute('SELECT user_id FROM user_quotas WHERE user_id = ?', (user_id,))
        if c.fetchone():
            c.execute('''
                UPDATE user_quotas 
                SET last_payment_tx = ?, last_payment_at = ?
                WHERE user_id = ?
            ''', (tx_hash, verified_at, user_id))
        else:
            c.execute('''
                INSERT INTO user_quotas 
                (user_id, requests_today, last_payment_tx, last_payment_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, 0, tx_hash, verified_at))
        
        # Update API key with paid tier
        c.execute('''
            UPDATE api_keys 
            SET paid_tier_expires_at = ?, paid_daily_limit = 100
            WHERE user_id = ?
        ''', (paid_tier_expires, user_id))
        
        conn.commit()
        conn.close()
        
        logger.info(f'Verified payment for user {user_id}, granted quota')
        return {
            'verified': True,
            'new_limit': 100,
            'expires_at': paid_tier_expires
        }
    except Exception as e:
        logger.error(f'Payment verification error: {e}')
        return {'verified': False, 'error': str(e)}

# ──────────────────────────────────────────────────────────
# FLASK ROUTE HANDLERS
# ──────────────────────────────────────────────────────────

def register_payment_routes(app):
    """Register payment endpoints with Flask app."""
    
    @app.route('/api/generate-key', methods=['POST'])
    def generate_key():
        """Generate a new API key for the user."""
        try:
            data = request.get_json() or {}
            user_id = data.get('user_id') or data.get('email')
            
            if not user_id:
                return jsonify({'error': 'user_id or email required'}), 400
            
            api_key = generate_api_key(user_id)
            if not api_key:
                return jsonify({'error': 'Failed to generate API key'}), 500
            
            return jsonify({
                'api_key': api_key,
                'daily_limit': 100,
                'message': 'Use this key in the Authorization header: Bearer <api_key>'
            }), 201
        except Exception as e:
            logger.error(f'generate_key error: {e}')
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/verify-payment', methods=['POST'])
    def verify_payment():
        """Verify USDC payment and upgrade quota."""
        try:
            data = request.get_json() or {}
            user_id = data.get('user_id') or data.get('email')
            tx_hash = data.get('tx_hash')
            
            if not user_id or not tx_hash:
                return jsonify({'error': 'user_id and tx_hash required'}), 400
            
            result = verify_and_grant_quota(user_id, tx_hash)
            
            if result.get('verified'):
                return jsonify(result), 200
            else:
                return jsonify(result), 400
        except Exception as e:
            logger.error(f'verify_payment error: {e}')
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/quota-status', methods=['GET'])
    def quota_status():
        """Check user's remaining quota for the day."""
        try:
            api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                return jsonify({'error': 'API key required'}), 401
            
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            c.execute('SELECT user_id, base_daily_limit, paid_daily_limit, paid_tier_expires_at FROM api_keys WHERE api_key = ?', (api_key,))
            row = c.fetchone()
            
            if not row:
                conn.close()
                return jsonify({'error': 'Invalid API key'}), 401
            
            user_id, base_limit, paid_limit, expires_at = row
            
            # Determine current limit
            if expires_at and datetime.fromisoformat(expires_at) > datetime.utcnow():
                current_limit = paid_limit
                is_paid = True
            else:
                current_limit = base_limit
                is_paid = False
            
            # Get today's usage
            today = datetime.utcnow().date().isoformat()
            c.execute('SELECT requests_today FROM user_quotas WHERE user_id = ?', (user_id,))
            quota_row = c.fetchone()
            requests_used = quota_row[0] if quota_row else 0
            
            conn.close()
            
            return jsonify({
                'user_id': user_id,
                'requests_today': requests_used,
                'daily_limit': current_limit,
                'remaining': max(0, current_limit - requests_used),
                'is_paid_tier': is_paid,
                'tier_expires_at': expires_at
            }), 200
        except Exception as e:
            logger.error(f'quota_status error: {e}')
            return jsonify({'error': str(e)}), 500

# Initialize on import
init_payment_db()
