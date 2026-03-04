#!/usr/bin/env python3
"""
stripe_webhook_test.py — Test Stripe webhook handler at /api/stripe/webhook

Usage:
    # 1. Against local dev server (requires STRIPE_WEBHOOK_SECRET set):
    python3 stripe_webhook_test.py --url http://localhost:5000

    # 2. Against live server:
    python3 stripe_webhook_test.py --url https://tiamat.live

    # 3. Use Stripe CLI for real event forwarding (recommended for production):
    stripe listen --forward-to https://tiamat.live/api/stripe/webhook
    stripe trigger charge.succeeded

    # 4. Test a specific event type only:
    python3 stripe_webhook_test.py --url http://localhost:5000 --event charge.succeeded

Options:
    --url     Base URL of the running Flask app (default: http://localhost:5000)
    --event   Run only this event type (default: all three)
    --verbose Show full response bodies
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error


# ── Config ────────────────────────────────────────────────────────────────────

WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
ENDPOINT_PATH  = '/api/stripe/webhook'

# ── Synthetic test payloads ───────────────────────────────────────────────────

def _make_event(event_type: str, data_object: dict, event_id: str = '') -> dict:
    """Build a minimal Stripe event envelope."""
    return {
        'id':             event_id or f'evt_test_{int(time.time())}',
        'object':         'event',
        'api_version':    '2024-06-20',
        'created':        int(time.time()),
        'type':           event_type,
        'livemode':       False,
        'data': {'object': data_object},
    }


TEST_EVENTS = {
    'charge.succeeded': _make_event(
        'charge.succeeded',
        {
            'id':       'ch_test_001',
            'object':   'charge',
            'amount':   500,           # $5.00 USD
            'currency': 'usd',
            'customer': 'cus_test_webhook01',
            'status':   'succeeded',
            'billing_details': {
                'email': 'test@example.com',
                'name':  'Test User',
            },
        },
        event_id='evt_test_charge_succeeded',
    ),

    'invoice.payment_failed': _make_event(
        'invoice.payment_failed',
        {
            'id':                 'in_test_001',
            'object':             'invoice',
            'customer':           'cus_test_webhook02',
            'customer_email':     'dunning@example.com',
            'amount_due':         1000,   # $10.00 USD
            'attempt_count':      2,
            'hosted_invoice_url': 'https://invoice.stripe.com/i/test_acct/test_001',
            'status':             'open',
        },
        event_id='evt_test_payment_failed',
    ),

    'customer.subscription.deleted': _make_event(
        'customer.subscription.deleted',
        {
            'id':       'sub_test_001',
            'object':   'subscription',
            'customer': 'cus_test_webhook03',
            'status':   'canceled',
            'metadata': {'email': 'sub@example.com'},
        },
        event_id='evt_test_sub_deleted',
    ),
}


# ── Stripe signature builder ──────────────────────────────────────────────────

def _stripe_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """
    Construct a Stripe-Signature header value matching the v1 scheme.
    https://stripe.com/docs/webhooks/signatures
    """
    ts  = timestamp or int(time.time())
    signed_payload = f'{ts}.'.encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f't={ts},v1={sig}'


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _post(url: str, payload: bytes, sig: str, verbose: bool) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type':    'application/json',
            'Stripe-Signature': sig,
            'User-Agent':      'stripe-webhook-test/1.0',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            if verbose:
                print(f'    Response body: {json.dumps(body, indent=2)}')
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            body = json.loads(body_bytes)
        except Exception:
            body = {'raw': body_bytes.decode(errors='replace')}
        if verbose:
            print(f'    Response body: {json.dumps(body, indent=2)}')
        return exc.code, body


# ── Individual tests ──────────────────────────────────────────────────────────

def run_test(base_url: str, event_type: str, secret: str, verbose: bool) -> bool:
    event   = TEST_EVENTS[event_type]
    payload = json.dumps(event).encode()
    sig     = _stripe_signature(payload, secret)
    url     = base_url.rstrip('/') + ENDPOINT_PATH

    print(f'\n  [{event_type}]')
    print(f'    POST {url}')
    print(f'    Event ID: {event["id"]}')

    status, body = _post(url, payload, sig, verbose)
    ok = status == 200 and body.get('received') is True

    if ok:
        print(f'    ✅ {status} — received=True, event_id={body.get("event_id", "?")}')
    else:
        print(f'    ❌ {status} — {body}')

    # Idempotency check — send same event again
    print(f'    [idempotency check: resend same event_id]')
    status2, body2 = _post(url, payload, sig, verbose)
    if status2 == 200 and (body2.get('duplicate') or body2.get('received')):
        print(f'    ✅ Idempotent: {body2}')
    else:
        print(f'    ⚠  Idempotency unclear: {status2} {body2}')

    return ok


def run_bad_signature_test(base_url: str, verbose: bool) -> bool:
    """Ensure the endpoint rejects a tampered signature."""
    event   = TEST_EVENTS['charge.succeeded']
    payload = json.dumps(event).encode()
    bad_sig = 't=1234567890,v1=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
    url     = base_url.rstrip('/') + ENDPOINT_PATH

    print('\n  [signature rejection test]')
    status, body = _post(url, payload, bad_sig, verbose)
    ok = status == 400

    if ok:
        print(f'    ✅ Bad signature correctly rejected with 400')
    else:
        print(f'    ❌ Expected 400, got {status}: {body}')
    return ok


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Test Stripe webhook endpoint')
    parser.add_argument('--url',     default='http://localhost:5000', help='Base URL of Flask app')
    parser.add_argument('--event',   default='',                      help='Test only this event type')
    parser.add_argument('--verbose', action='store_true',             help='Show full response bodies')
    args = parser.parse_args()

    secret = WEBHOOK_SECRET
    if not secret or secret.startswith('whsec_PLACEHOLDER'):
        print('ERROR: Set STRIPE_WEBHOOK_SECRET in environment (or /root/.env)')
        print('       export STRIPE_WEBHOOK_SECRET=whsec_...')
        sys.exit(1)

    print(f'Stripe Webhook Test — {args.url}')
    print(f'Secret: {secret[:10]}... (truncated)')
    print('=' * 60)

    if args.event:
        if args.event not in TEST_EVENTS:
            print(f'Unknown event type: {args.event}')
            print(f'Valid: {", ".join(TEST_EVENTS.keys())}')
            sys.exit(1)
        events_to_run = [args.event]
    else:
        events_to_run = list(TEST_EVENTS.keys())

    results = []
    for et in events_to_run:
        ok = run_test(args.url, et, secret, args.verbose)
        results.append((et, ok))

    # Signature rejection
    results.append(('bad_signature', run_bad_signature_test(args.url, args.verbose)))

    print('\n' + '=' * 60)
    print('Results:')
    passed = 0
    for name, ok in results:
        icon = '✅' if ok else '❌'
        print(f'  {icon}  {name}')
        if ok:
            passed += 1

    print(f'\n{passed}/{len(results)} tests passed')

    if passed < len(results):
        sys.exit(1)


if __name__ == '__main__':
    main()
