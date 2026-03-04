#!/usr/bin/env bash
# deploy_stripe.sh — Deploy Stripe integration to live summarize_api.py
# Run as root: bash /root/entity/deploy_stripe.sh
set -euo pipefail

LIVE_API="/root/summarize_api.py"
LIVE_PAYMENT_HTML="/root/entity/templates/payment.html"
NEW_PAYMENT_HTML="/root/entity/templates/payment_stripe.html"
BLUEPRINT="/root/entity/stripe_payments.py"
ENTITY_DIR="/root/entity"

echo "=== TIAMAT Stripe Deploy ==="
echo ""

# ── 1. Verify Stripe keys are set ────────────────────────────────────────────
source /root/.env 2>/dev/null || true

if [[ "${STRIPE_SECRET_KEY:-}" == "sk_test_PLACEHOLDER" || -z "${STRIPE_SECRET_KEY:-}" ]]; then
    echo "ERROR: STRIPE_SECRET_KEY is not set in /root/.env"
    echo "  Get it from: https://dashboard.stripe.com/apikeys"
    echo "  Set: STRIPE_SECRET_KEY=sk_live_..."
    exit 1
fi
if [[ "${STRIPE_PUBLISHABLE_KEY:-}" == "pk_test_PLACEHOLDER" || -z "${STRIPE_PUBLISHABLE_KEY:-}" ]]; then
    echo "ERROR: STRIPE_PUBLISHABLE_KEY is not set in /root/.env"
    exit 1
fi
if [[ "${STRIPE_WEBHOOK_SECRET:-}" == "whsec_PLACEHOLDER" || -z "${STRIPE_WEBHOOK_SECRET:-}" ]]; then
    echo "WARNING: STRIPE_WEBHOOK_SECRET not set — webhook signature verification disabled"
    echo "  Set it after creating webhook at: https://dashboard.stripe.com/webhooks"
    echo "  Continuing anyway (success page fallback will still work)..."
fi
echo "✅ Stripe keys verified"
echo ""

# ── 2. Copy stripe_payments.py to /root/ (importable path) ───────────────────
cp "$BLUEPRINT" /root/stripe_payments.py
echo "✅ Copied stripe_payments.py → /root/"

# ── 3. Patch live summarize_api.py to register the Blueprint ─────────────────
echo "Patching $LIVE_API..."

# Remove immutable flag
chattr -i "$LIVE_API"

# Check if already patched
if grep -q "stripe_payments" "$LIVE_API"; then
    echo "  Already patched (stripe_payments import found) — skipping inject"
else
    # Inject import + blueprint registration after 'app.config' line
    python3 - <<'PYEOF'
import re

with open('/root/summarize_api.py', 'r') as f:
    content = f.read()

inject = """
# ── Stripe Blueprint (auto-injected by deploy_stripe.sh) ─────────────────────
try:
    import sys as _sp_sys
    _sp_sys.path.insert(0, '/root')
    from stripe_payments import stripe_bp, check_paid_key, increment_key_usage
    app.register_blueprint(stripe_bp)
    import logging as _sp_log
    _sp_log.getLogger(__name__).info("✅ Stripe blueprint registered")
    _STRIPE_LOADED = True
except Exception as _sp_err:
    import logging as _sp_log
    _sp_log.getLogger(__name__).warning("Stripe blueprint not loaded: %s", _sp_err)
    _STRIPE_LOADED = False
# ─────────────────────────────────────────────────────────────────────────────
"""

# Insert after app.config['MAX_CONTENT_LENGTH'] line
target = "app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB max"
if target in content:
    content = content.replace(target, target + inject, 1)
    with open('/root/summarize_api.py', 'w') as f:
        f.write(content)
    print("  Injected blueprint registration after app.config line")
else:
    # Fallback: insert after 'app = Flask(' block
    m = re.search(r"(app = Flask\([^\n]+\n)", content)
    if m:
        pos = m.end()
        content = content[:pos] + inject + content[pos:]
        with open('/root/summarize_api.py', 'w') as f:
            f.write(content)
        print("  Injected blueprint registration after app = Flask(...)")
    else:
        print("  WARNING: Could not find injection point — add manually (see deploy_stripe.sh)")
PYEOF
fi

# ── 4. Patch payment route to use new template ───────────────────────────────
if grep -q "payment_stripe.html" "$LIVE_API"; then
    echo "  Payment route already updated"
else
    python3 - <<'PYEOF'
with open('/root/summarize_api.py', 'r') as f:
    content = f.read()

# Swap template name in the /pay route
old = "return render_template('payment.html', endpoint=endpoint, amount=amount, wallet=USER_WALLET)"
new = "return render_template('payment_stripe.html', endpoint=endpoint, amount=amount, wallet=USER_WALLET)"
if old in content:
    content = content.replace(old, new, 1)
    with open('/root/summarize_api.py', 'w') as f:
        f.write(content)
    print("  Updated /pay route → payment_stripe.html")
else:
    print("  WARNING: /pay render_template not found — update manually")
PYEOF
fi

# Re-add immutable flag
chattr +i "$LIVE_API"
echo "✅ Live API patched and re-locked"
echo ""

# ── 5. Update payment.html (if it's chattr +i, unlock it) ────────────────────
echo "Updating payment.html..."
if [ -f "$NEW_PAYMENT_HTML" ]; then
    chattr -i "$LIVE_PAYMENT_HTML" 2>/dev/null || true
    cp "$NEW_PAYMENT_HTML" "$LIVE_PAYMENT_HTML"
    chattr +i "$LIVE_PAYMENT_HTML" 2>/dev/null || true
    echo "✅ payment.html updated with Stripe UI"
else
    echo "WARNING: $NEW_PAYMENT_HTML not found — payment.html not updated"
fi
echo ""

# ── 6. Add /pay/success to exempt routes in summarize_api.py ─────────────────
# The Blueprint handles its own routes — no rate limit decorator used.
# Exempt routes are only needed for the before_request check.
echo "Checking exempt routes..."
chattr -i "$LIVE_API"
python3 - <<'PYEOF'
with open('/root/summarize_api.py', 'r') as f:
    content = f.read()

routes_to_exempt = ['/pay/success', '/create-checkout', '/stripe-webhook']
changed = False
for route in routes_to_exempt:
    if f"'{route}'" not in content and f'"{route}"' not in content:
        # Add to exempt_routes set
        target = "'/pay',"
        if target in content:
            content = content.replace(target, f"'{route}',\n        '/pay',", 1)
            changed = True
            print(f"  Added {route} to exempt_routes")

if changed:
    with open('/root/summarize_api.py', 'w') as f:
        f.write(content)
else:
    print("  Exempt routes already up to date")
PYEOF
chattr +i "$LIVE_API"
echo ""

# ── 7. Restart gunicorn ───────────────────────────────────────────────────────
echo "Restarting gunicorn..."
pkill -HUP gunicorn 2>/dev/null && echo "✅ Gunicorn gracefully reloaded" || {
    echo "  pkill -HUP failed, trying systemctl..."
    systemctl reload gunicorn 2>/dev/null || systemctl restart gunicorn 2>/dev/null || {
        echo "  Trying direct kill + restart..."
        pkill -f "gunicorn.*summarize_api" 2>/dev/null || true
        sleep 2
        cd /root && gunicorn -w 2 -b 127.0.0.1:5000 --daemon summarize_api:app
        echo "✅ Gunicorn restarted"
    }
}
echo ""

# ── 8. Smoke test ─────────────────────────────────────────────────────────────
echo "Running smoke test..."
sleep 3
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/pay 2>/dev/null || echo "000")
echo "  GET /pay → HTTP $HTTP"

STRIPE_RESP=$(curl -s -X POST http://localhost:5000/create-checkout \
    -H 'Content-Type: application/json' \
    -d '{"amount_usd": 5}' 2>/dev/null || echo '{}')
echo "  POST /create-checkout → $STRIPE_RESP"
echo ""

echo "=== Deploy complete ==="
echo ""
echo "NEXT STEPS:"
echo "1. Set real Stripe keys in /root/.env:"
echo "   STRIPE_SECRET_KEY=sk_live_..."
echo "   STRIPE_PUBLISHABLE_KEY=pk_live_..."
echo ""
echo "2. Register webhook in Stripe Dashboard:"
echo "   URL: https://tiamat.live/stripe-webhook"
echo "   Events: checkout.session.completed"
echo "   Copy the signing secret → STRIPE_WEBHOOK_SECRET=whsec_..."
echo ""
echo "3. Run deploy again after setting webhook secret"
echo ""
echo "4. Test end-to-end:"
echo "   curl -X POST https://tiamat.live/create-checkout -H 'Content-Type: application/json' -d '{\"amount_usd\": 1}'"
