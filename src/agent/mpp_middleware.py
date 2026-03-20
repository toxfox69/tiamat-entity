#!/usr/bin/env python3
"""
MPP (Machine Payments Protocol) middleware for TIAMAT's Flask API.
Integrates Tempo blockchain payments via HTTP 402.

Usage in summarize_api.py:
    from mpp_middleware import mpp_charge, init_mpp

    init_mpp()  # Call once at startup

    @app.route('/api/resource')
    async def resource():
        result = mpp_charge(request, amount='0.01', description='API call')
        if result is not None:
            return result  # 402 challenge response
        return jsonify({'data': '...'})
"""

import os
import asyncio
import json
import logging
from functools import wraps

log = logging.getLogger('mpp')

# Lazy init — don't fail at import if mpp not installed
_mpp_instance = None
_mpp_available = False

TIAMAT_WALLET = os.environ.get('TIAMAT_WALLET_ADDR', '0xdA4A701aB24e2B6805b702dDCC3cB4D8f591d397')
# pathUSD on Tempo (the default stablecoin)
PATH_USD = '0x20c0000000000000000000000000000000000000'
# MPP secret key for HMAC challenge signing
MPP_SECRET = os.environ.get('MPP_SECRET_KEY', 'tiamat-mpp-secret-2026')


def init_mpp():
    """Initialize MPP with Tempo payment method."""
    global _mpp_instance, _mpp_available
    try:
        from mpp.server import Mpp
        from mpp.methods.tempo.client import TempoMethod

        method = TempoMethod(
            currency=PATH_USD,
            recipient=TIAMAT_WALLET,
            chain_id=4217,  # Tempo mainnet
        )

        _mpp_instance = Mpp.create(
            method=method,
            realm='tiamat.live',
            secret_key=MPP_SECRET,
        )
        _mpp_available = True
        log.info('[MPP] Initialized with Tempo payments (chain 4217, pathUSD)')
        return True
    except Exception as e:
        log.warning(f'[MPP] Init failed: {e} — falling back to legacy x402')
        _mpp_available = False
        return False


def mpp_charge(flask_request, amount='0.01', description=None):
    """
    Check if request has valid MPP payment credential.
    Returns None if paid (proceed with response), or a Flask 402 Response if payment needed.
    Falls back to legacy behavior if MPP not available.
    """
    if not _mpp_available or not _mpp_instance:
        return None  # No MPP — fall through to legacy x402

    auth_header = flask_request.headers.get('Authorization')

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            _mpp_instance.charge(
                authorization=auth_header,
                amount=amount,
                description=description or f'TIAMAT API — {flask_request.path}',
            )
        )
        loop.close()

        # If result is a Challenge, return 402
        from mpp import Challenge
        if isinstance(result, Challenge):
            # Build 402 response with MPP challenge header
            from flask import make_response, jsonify
            resp = make_response(jsonify({
                'error': 'payment_required',
                'message': f'This endpoint requires {amount} pathUSD payment via Tempo',
                'protocol': 'MPP',
                'amount': amount,
                'currency': 'pathUSD',
                'chain': 'Tempo (4217)',
                'recipient': TIAMAT_WALLET,
                'docs': 'https://mpp.dev/quickstart/client',
            }), 402)
            # Add the MPP challenge header
            resp.headers['WWW-Authenticate'] = result.serialize()
            return resp

        # Payment verified — return None to proceed
        return None

    except Exception as e:
        log.debug(f'[MPP] Charge error: {e}')
        return None  # On error, fall through to legacy


def mpp_status():
    """Return MPP integration status for /status endpoint."""
    return {
        'mpp_available': _mpp_available,
        'payment_method': 'Tempo (chain 4217)' if _mpp_available else 'legacy x402',
        'currency': 'pathUSD' if _mpp_available else 'USDC/ETH',
        'recipient': TIAMAT_WALLET,
        'protocol_docs': 'https://mpp.dev',
    }
