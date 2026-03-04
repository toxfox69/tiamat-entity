#!/usr/bin/env python3
"""
summarize_api_ext.py — TIAMAT API with Stripe payment layer bolted on.

Gunicorn loads this instead of summarize_api:app.
It imports the existing Flask app (adding zero risk of breaking it) and
registers the Stripe Blueprint + overrides the /pay page.

If Stripe keys are not set, all Stripe routes return a 503 and the app
keeps working exactly as before.
"""

import sys

# Ensure /root is on the path so 'import summarize_api' and
# 'import stripe_payments' both resolve.
sys.path.insert(0, '/root')

# ── 1. Import the original app ────────────────────────────────────────────────
from summarize_api import app  # noqa: E402  (must come after sys.path insert)

# ── 2. Register the Stripe Blueprint ─────────────────────────────────────────
try:
    from stripe_payments import stripe_bp
    if 'stripe' not in app.blueprints:
        app.register_blueprint(stripe_bp)
        app.logger.info("✅ Stripe Blueprint registered")
    else:
        app.logger.info("ℹ  Stripe Blueprint already registered (fork reuse)")
except Exception as _e:
    app.logger.error("⚠  Could not register Stripe Blueprint: %s", _e)

# ── 3. Override /pay → serve the Stripe-enabled payment page ─────────────────
# Flask dispatches via app.view_functions[endpoint]. Re-assigning the key
# changes what runs without touching the URL map.
from flask import send_file as _send_file

def _payment_page_stripe():
    """Stripe-enabled /pay page (replaces old USDC-only page)."""
    tpl = '/root/entity/templates/payment_stripe.html'
    return _send_file(tpl, mimetype='text/html')

# 'payment_page' is the endpoint name Flask assigned to the original @app.route('/pay')
app.view_functions['payment_page'] = _payment_page_stripe

app.logger.info("✅ summarize_api_ext loaded — Stripe active")
