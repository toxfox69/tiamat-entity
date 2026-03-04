"""
stripe_payments.py — Stripe Checkout integration for tiamat.live
Registers as a Flask Blueprint; drop in via:
    from stripe_payments import stripe_bp
    app.register_blueprint(stripe_bp)
"""

import os
import sqlite3
import hashlib
import hmac as _hmac
import logging
import datetime

import stripe
from flask import Blueprint, request, jsonify, redirect, render_template_string

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY   = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PUB_KEY      = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')

_stripe_ready = (
    STRIPE_SECRET_KEY
    and not STRIPE_SECRET_KEY.startswith('sk_test_PLACEHOLDER')
)

if _stripe_ready:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("✅ Stripe configured")
else:
    logger.warning("⚠  Stripe not configured — set STRIPE_SECRET_KEY in .env")

PAID_KEYS_DB = '/root/.automaton/paid_keys.db'

# USD amount → calls purchased
PRICE_MAP = {1: 1000, 5: 5000, 10: 10000, 50: 50000}

# ── Paid keys DB ──────────────────────────────────────────────────────────────

def _db():
    return sqlite3.connect(PAID_KEYS_DB)

def _init_db():
    with _db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS paid_keys (
                api_key        TEXT PRIMARY KEY,
                session_id     TEXT UNIQUE,
                amount_usd     INTEGER NOT NULL,
                calls_purchased INTEGER NOT NULL,
                calls_used     INTEGER DEFAULT 0,
                email          TEXT,
                created_at     TEXT DEFAULT (datetime('now')),
                expires_at     TEXT
            )
        ''')

try:
    _init_db()
    logger.info("✅ Paid keys DB ready: %s", PAID_KEYS_DB)
except Exception as exc:
    logger.error("Failed to init paid_keys DB: %s", exc)


def _make_api_key(session_id: str) -> str:
    """Deterministic, stable API key from session_id."""
    secret = STRIPE_WEBHOOK_SECRET or 'tiamat-key-fallback'
    token = _hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).hexdigest()[:32]
    return f'tia_{token}'


def provision_key(session_id: str, amount_usd: int, email: str | None = None) -> str:
    """Idempotently provision an API key for a completed Stripe session."""
    api_key = _make_api_key(session_id)
    calls   = PRICE_MAP.get(int(amount_usd), 1000)
    expires = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with _db() as conn:
            conn.execute(
                '''INSERT OR IGNORE INTO paid_keys
                   (api_key, session_id, amount_usd, calls_purchased, email, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (api_key, session_id, int(amount_usd), calls, email, expires)
            )
        logger.info("✅ Key provisioned: %s... $%s", api_key[:12], amount_usd)
    except Exception as exc:
        logger.error("provision_key error: %s", exc)
    return api_key


def check_paid_key(api_key: str) -> dict | None:
    """Return key metadata if valid + unexpired, else None."""
    if not api_key or not api_key.startswith('tia_'):
        return None
    try:
        with _db() as conn:
            cur = conn.execute(
                '''SELECT api_key, amount_usd, calls_purchased, calls_used, expires_at
                   FROM paid_keys
                   WHERE api_key = ?
                     AND (expires_at IS NULL OR expires_at > datetime('now'))''',
                (api_key,)
            )
            row = cur.fetchone()
        if row:
            return dict(zip(('api_key', 'amount_usd', 'calls_purchased', 'calls_used', 'expires_at'), row))
        return None
    except Exception as exc:
        logger.error("check_paid_key error: %s", exc)
        return None


def increment_key_usage(api_key: str):
    try:
        with _db() as conn:
            conn.execute('UPDATE paid_keys SET calls_used = calls_used + 1 WHERE api_key = ?', (api_key,))
    except Exception as exc:
        logger.error("increment_key_usage error: %s", exc)


# ── Blueprint ─────────────────────────────────────────────────────────────────

stripe_bp = Blueprint('stripe', __name__)

# ── POST /create-checkout ─────────────────────────────────────────────────────

@stripe_bp.route('/create-checkout', methods=['POST'])
def create_checkout():
    if not _stripe_ready:
        return jsonify({'error': 'Stripe not configured on server'}), 503

    data       = request.get_json(silent=True) or {}
    amount_usd = int(data.get('amount_usd', 5))

    if amount_usd not in PRICE_MAP:
        return jsonify({'error': 'Invalid amount. Choose 1, 5, 10, or 50'}), 400

    calls = PRICE_MAP[amount_usd]

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'TIAMAT API — {calls:,} calls',
                        'description': (
                            f'${amount_usd} · {calls:,} API calls · 30-day access · '
                            'Use via Authorization: Bearer tia_... header'
                        ),
                    },
                    'unit_amount': amount_usd * 100,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://tiamat.live/pay/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://tiamat.live/pay?cancelled=1',
            metadata={'amount_usd': str(amount_usd)},
        )
        return jsonify({'url': session.url, 'session_id': session.id})
    except stripe.StripeError as exc:
        logger.error("Stripe error in create_checkout: %s", exc)
        return jsonify({'error': str(exc)}), 500


# ── GET /pay/success ──────────────────────────────────────────────────────────

_SUCCESS_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT — Payment Successful</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);font-family:'JetBrains Mono',monospace;color:#00ff88;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:rgba(0,20,40,0.92);border:2px solid #00ff88;border-radius:10px;padding:40px;max-width:620px;width:100%;box-shadow:0 0 30px rgba(0,255,136,0.3)}
h1{font-size:24px;margin-bottom:20px;text-align:center}
.badge{color:#000;background:#00ff88;padding:3px 10px;border-radius:3px;font-size:12px;display:inline-block;margin-bottom:20px}
.key-box{background:#000;border:1px solid #00ff88;border-radius:5px;padding:15px;word-break:break-all;font-size:14px;margin:20px 0;cursor:pointer;position:relative}
.key-box:hover{background:#001a0a}
.copy-hint{position:absolute;top:8px;right:10px;font-size:11px;color:#00aa55}
.info{border-left:3px solid #00ff88;padding:12px 16px;background:rgba(0,255,136,0.05);font-size:13px;line-height:1.7;margin:16px 0}
.usage{font-size:13px;color:#aaa;margin-top:24px;line-height:1.8}
code{background:#001a0a;padding:2px 6px;border-radius:3px;color:#00ff88}
.btn{display:block;text-align:center;background:linear-gradient(135deg,#00ff88,#00cc6a);color:#000;padding:12px;border-radius:5px;font-weight:bold;text-decoration:none;margin-top:24px;font-size:15px}
.btn:hover{box-shadow:0 0 15px rgba(0,255,136,0.5)}
</style>
</head>
<body>
<div class="card">
  <h1>&#9889; Payment Confirmed</h1>
  <div class="badge">PAID</div>
  <p style="color:#aaa;font-size:13px;margin-bottom:8px">Your API key (click to copy):</p>
  <div class="key-box" onclick="copy(this)" id="keybox">
    <span class="copy-hint">click to copy</span>
    {{ api_key }}
  </div>
  <div class="info">
    <strong>${{ amount }} USD</strong> &middot; {{ calls | int | format_number }} API calls &middot; 30-day access<br>
    Expires: {{ expires }}
  </div>
  <div class="usage">
    <strong>How to use:</strong><br>
    Add to every API request:<br><br>
    <code>Authorization: Bearer {{ api_key }}</code><br><br>
    Example:<br>
    <code>curl -X POST https://tiamat.live/summarize \<br>
    &nbsp;&nbsp;-H "Authorization: Bearer {{ api_key }}" \<br>
    &nbsp;&nbsp;-H "Content-Type: application/json" \<br>
    &nbsp;&nbsp;-d '{"text": "your text here"}'</code>
  </div>
  <a class="btn" href="https://tiamat.live/docs">View API Docs &rarr;</a>
</div>
<script>
function copy(el){
  const key = el.innerText.trim().replace('click to copy','').trim();
  navigator.clipboard.writeText(key).then(()=>{
    el.querySelector('.copy-hint').textContent='copied!';
    setTimeout(()=>el.querySelector('.copy-hint').textContent='click to copy',2000);
  });
}
</script>
</body>
</html>'''

_ERROR_HTML = '''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>TIAMAT — Payment Error</title>
<style>body{background:#0f0c29;color:#ff4444;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{border:1px solid #ff4444;padding:40px;border-radius:8px;text-align:center}
a{color:#00ff88;display:block;margin-top:20px}</style></head>
<body><div class="card"><h2>Payment Error</h2><p style="margin-top:12px">{{ error }}</p>
<a href="/pay">Try again &rarr;</a></div></body></html>'''


@stripe_bp.route('/pay/success', methods=['GET'])
def pay_success():
    session_id = request.args.get('session_id', '')
    if not session_id:
        return redirect('/pay')
    if not _stripe_ready:
        return render_template_string(_ERROR_HTML, error='Stripe not configured'), 503

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError as exc:
        logger.error("pay_success retrieve error: %s", exc)
        return render_template_string(_ERROR_HTML, error='Could not verify session'), 400

    if session.payment_status != 'paid':
        return render_template_string(_ERROR_HTML, error='Payment not completed — please try again'), 402

    metadata   = session.metadata or {}
    amount_usd = int(metadata.get('amount_usd', 5))
    email      = getattr(session.customer_details, 'email', None) if session.customer_details else None
    api_key    = provision_key(session_id, amount_usd, email)
    calls      = PRICE_MAP.get(amount_usd, 1000)
    expires    = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(days=30)).strftime('%Y-%m-%d')

    # Render without Jinja filter (plain string format)
    html = (_SUCCESS_HTML
            .replace('{{ api_key }}', api_key)
            .replace('{{ amount }}', str(amount_usd))
            .replace('{{ calls | int | format_number }}', f'{calls:,}')
            .replace('{{ expires }}', expires))
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


# ── POST /stripe-webhook ──────────────────────────────────────────────────────

@stripe_bp.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    if not STRIPE_WEBHOOK_SECRET or STRIPE_WEBHOOK_SECRET.startswith('whsec_PLACEHOLDER'):
        logger.warning("Webhook received but STRIPE_WEBHOOK_SECRET not set")
        return jsonify({'error': 'Webhook secret not configured'}), 400

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature")
        return jsonify({'error': 'Invalid signature'}), 400
    except Exception as exc:
        logger.error("Webhook construct error: %s", exc)
        return jsonify({'error': 'Bad request'}), 400

    if event['type'] == 'checkout.session.completed':
        sess       = event['data']['object']
        amount_usd = int(sess.get('metadata', {}).get('amount_usd', 5))
        email      = (sess.get('customer_details') or {}).get('email')
        api_key    = provision_key(sess['id'], amount_usd, email)
        logger.info("✅ Webhook provisioned key %s... $%s for %s", api_key[:12], amount_usd, email)

    return jsonify({'received': True}), 200


# ── Helper: validate key for use in other routes ──────────────────────────────
# Import this function in summarize_api.py to gate paid routes:
#
#   from stripe_payments import check_paid_key, increment_key_usage
#
#   auth = request.headers.get('Authorization', '')
#   if auth.startswith('Bearer tia_'):
#       key_data = check_paid_key(auth[7:])
#       if key_data and key_data['calls_used'] < key_data['calls_purchased']:
#           increment_key_usage(auth[7:])
#           return f(*args, **kwargs)  # skip rate limit
