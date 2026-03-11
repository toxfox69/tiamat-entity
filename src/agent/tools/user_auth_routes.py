#!/usr/bin/env python3
"""
User Authentication & Scan History Routes

Provides:
  POST /api/auth/register — Register new user
  POST /api/auth/login — Login & get JWT token
  POST /api/scans — Create scan (protected, JWT required)
  GET /api/scans — List user's scans (protected)
  GET /api/scans/{scan_id} — Get scan details (protected)

Database: SQLite (shared with state.db or separate)
Auth: JWT (HS256)
"""

import os
import sqlite3
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, List, Tuple, Any

try:
    from flask import request, jsonify
except ImportError:
    raise ImportError("Flask required: pip install flask")

# JWT Secret (load from env or use fallback)
JWT_SECRET = os.getenv('JWT_SECRET', 'tiamat-secret-key-change-in-production')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_HOURS = 24

# Database path
DB_PATH = os.getenv('USER_DB_PATH', '/root/.automaton/user_data.db')


class AuthDB:
    """SQLite auth & scan history database."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_tables()
    
    def conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_tables(self):
        """Create tables if they don't exist."""
        conn = self.conn()
        c = conn.cursor()
        
        # Users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Scans table
        c.execute('''
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT,
                city TEXT,
                state TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Broker results table
        c.execute('''
            CREATE TABLE IF NOT EXISTS broker_results (
                id INTEGER PRIMARY KEY,
                scan_id INTEGER NOT NULL,
                broker_name TEXT,
                found BOOLEAN,
                url TEXT,
                removal_status TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_user(self, email: str, password: str) -> Tuple[bool, str, Optional[int]]:
        """Create new user. Returns (success, message, user_id)."""
        try:
            password_hash = hash_password(password)
            conn = self.conn()
            c = conn.cursor()
            c.execute('INSERT INTO users (email, password_hash) VALUES (?, ?)',
                     (email, password_hash))
            conn.commit()
            user_id = c.lastrowid
            conn.close()
            return True, 'User created', user_id
        except sqlite3.IntegrityError:
            return False, 'Email already exists', None
        except Exception as e:
            return False, f'Database error: {str(e)}', None
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email. Returns user dict or None."""
        conn = self.conn()
        c = conn.cursor()
        c.execute('SELECT id, email, password_hash FROM users WHERE email = ?', (email,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def create_scan(self, user_id: int, name: str, city: str, state: str) -> int:
        """Create scan record. Returns scan_id."""
        conn = self.conn()
        c = conn.cursor()
        c.execute('INSERT INTO scans (user_id, name, city, state) VALUES (?, ?, ?, ?)',
                 (user_id, name, city, state))
        conn.commit()
        scan_id = c.lastrowid
        conn.close()
        return scan_id
    
    def store_broker_results(self, scan_id: int, results: List[Dict]):
        """Store broker scan results. results = [{broker_name, found, url, removal_status}, ...]"""
        conn = self.conn()
        c = conn.cursor()
        for r in results:
            c.execute('''
                INSERT INTO broker_results (scan_id, broker_name, found, url, removal_status)
                VALUES (?, ?, ?, ?, ?)
            ''', (scan_id, r.get('broker_name'), r.get('found'), r.get('url'), r.get('removal_status')))
        conn.commit()
        conn.close()
    
    def get_scans(self, user_id: int) -> List[Dict]:
        """Get all scans for a user."""
        conn = self.conn()
        c = conn.cursor()
        c.execute('SELECT id, name, city, state, created_at FROM scans WHERE user_id = ? ORDER BY created_at DESC',
                 (user_id,))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_scan_detail(self, scan_id: int, user_id: int) -> Optional[Dict]:
        """Get scan detail (with ownership check). Returns {scan, results}."""
        conn = self.conn()
        c = conn.cursor()
        
        # Check ownership
        c.execute('SELECT id, name, city, state, created_at FROM scans WHERE id = ? AND user_id = ?',
                 (scan_id, user_id))
        scan_row = c.fetchone()
        if not scan_row:
            conn.close()
            return None
        
        # Get results
        c.execute('SELECT broker_name, found, url, removal_status FROM broker_results WHERE scan_id = ?',
                 (scan_id,))
        results = [dict(r) for r in c.fetchall()]
        conn.close()
        
        return {
            'scan': dict(scan_row),
            'results': results
        }


def hash_password(password: str) -> str:
    """Hash password with SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return hash_password(password) == password_hash


def create_jwt(user_id: int, email: str) -> str:
    """Create JWT token (simple HS256 implementation)."""
    import base64
    
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
        "iat": int(time.time())
    }
    
    # Encode header and payload
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    
    # Create signature
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        JWT_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip('=')
    
    return f"{message}.{signature_b64}"


def verify_jwt(token: str) -> Optional[Dict]:
    """Verify JWT token. Returns payload dict or None."""
    import base64
    
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        header_b64, payload_b64, signature_b64 = parts
        
        # Reconstruct message and verify signature
        message = f"{header_b64}.{payload_b64}"
        expected_signature = hmac.new(
            JWT_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        expected_signature_b64 = base64.urlsafe_b64encode(expected_signature).decode().rstrip('=')
        
        if signature_b64 != expected_signature_b64:
            return None
        
        # Decode payload
        padding = '=' * (4 - len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode()
        payload = json.loads(payload_json)
        
        # Check expiry
        if payload.get('exp', 0) < int(time.time()):
            return None
        
        return payload
    except Exception:
        return None


def require_auth(f):
    """Decorator to require JWT authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401
        
        try:
            scheme, token = auth_header.split(' ', 1)
            if scheme.lower() != 'bearer':
                return jsonify({'error': 'Invalid authorization scheme'}), 401
        except ValueError:
            return jsonify({'error': 'Invalid Authorization header format'}), 401
        
        payload = verify_jwt(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Pass user_id to route handler
        return f(user_id=payload['user_id'], *args, **kwargs)
    
    return decorated_function


# Routes
db = AuthDB()


def register_auth_routes(app):
    """Register auth & history routes on Flask app."""
    
    @app.route('/api/auth/register', methods=['POST'])
    def register():
        data = request.get_json() or {}
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400
        
        success, message, user_id = db.create_user(email, password)
        if not success:
            return jsonify({'error': message}), 400
        
        # Create JWT token
        token = create_jwt(user_id, email)
        return jsonify({
            'message': 'User created',
            'user_id': user_id,
            'token': token
        }), 201
    
    @app.route('/api/auth/login', methods=['POST'])
    def login():
        data = request.get_json() or {}
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        user = db.get_user_by_email(email)
        if not user or not verify_password(password, user['password_hash']):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        # Create JWT token
        token = create_jwt(user['id'], user['email'])
        return jsonify({
            'message': 'Login successful',
            'user_id': user['id'],
            'token': token
        }), 200
    
    @app.route('/api/scans', methods=['POST'])
    @require_auth
    def create_scan(user_id):
        """Create a new scan and immediately run it."""
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        city = data.get('city', '').strip()
        state = data.get('state', '').strip()
        
        if not (name and city and state):
            return jsonify({'error': 'Name, city, and state required'}), 400
        
        # Create scan record
        scan_id = db.create_scan(user_id, name, city, state)
        
        # TODO: Call scanner to run scan (will be integration with Phase 3 scanner)
        # For now, return placeholder
        results = [
            {'broker_name': 'Spokeo', 'found': False, 'url': '', 'removal_status': 'pending'},
            {'broker_name': 'WhitePages', 'found': False, 'url': '', 'removal_status': 'pending'},
        ]
        db.store_broker_results(scan_id, results)
        
        return jsonify({
            'message': 'Scan created',
            'scan_id': scan_id,
            'name': name,
            'city': city,
            'state': state,
            'results': results
        }), 201
    
    @app.route('/api/scans', methods=['GET'])
    @require_auth
    def list_scans(user_id):
        """Get all scans for the user."""
        scans = db.get_scans(user_id)
        return jsonify({
            'message': 'Scans retrieved',
            'count': len(scans),
            'scans': scans
        }), 200
    
    @app.route('/api/scans/<int:scan_id>', methods=['GET'])
    @require_auth
    def get_scan_detail(user_id, scan_id):
        """Get detailed results for a specific scan."""
        detail = db.get_scan_detail(scan_id, user_id)
        if not detail:
            return jsonify({'error': 'Scan not found'}), 404
        
        return jsonify({
            'message': 'Scan detail retrieved',
            'scan': detail['scan'],
            'results': detail['results']
        }), 200
