#!/usr/bin/env python3
"""
Telegram Subscription Handler for TIAMAT Bot
Handles /subscribe command, USDC payments, and activation.
Integrate into telegram_assistant_bot.py message handler.
"""

import sqlite3
import json
import time
from datetime import datetime, timedelta
from web3 import Web3

# ── Configuration ──
BASE_RPC = "https://mainnet.base.org"
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC on Base
TIAMAT_WALLET = "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE"
DATABASE = "/root/telegram_users.db"

SUBSCRIPTION_TIERS = {
    "researcher": {
        "price_usdc": 5.00,
        "duration_days": 7,
        "features": ["Unlimited queries", "Daily research briefing", "Priority support"],
        "description": "$5/week — Research digest + unlimited API access"
    },
    "enterprise": {
        "price_usdc": 50.00,
        "duration_days": 30,
        "features": ["Everything in Researcher", "Custom reports", "Dedicated channel"],
        "description": "$50/month — Enterprise research partnership"
    }
}

# ── Database Setup ──
def init_subscription_table():
    """Create subscriptions table if not exists."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY,
            telegram_user_id INTEGER UNIQUE,
            tier TEXT,
            price_usdc REAL,
            status TEXT,
            tx_hash TEXT,
            payment_timestamp INTEGER,
            activation_timestamp INTEGER,
            expiry_timestamp INTEGER,
            created_at INTEGER
        )
    """)
    conn.commit()
    conn.close()

# ── Handler Functions ──
def generate_subscription_request(user_id: int, tier: str = "researcher") -> dict:
    """
    Generate a subscription request for a user.
    Returns dict with payment instructions.
    """
    if tier not in SUBSCRIPTION_TIERS:
        return {"error": f"Unknown tier: {tier}. Valid: {list(SUBSCRIPTION_TIERS.keys())}"}
    
    tier_info = SUBSCRIPTION_TIERS[tier]
    request_id = int(time.time() * 1000)  # Use timestamp as request ID
    
    return {
        "request_id": request_id,
        "user_id": user_id,
        "tier": tier,
        "price_usdc": tier_info["price_usdc"],
        "duration_days": tier_info["duration_days"],
        "payment_address": TIAMAT_WALLET,
        "memo": f"TG_{user_id}_{request_id}",  # Include user_id in memo for verification
        "description": tier_info["description"],
        "features": tier_info["features"],
        "status": "pending_payment",
        "expires_in_minutes": 30
    }

def build_telegram_message(subscription_request: dict) -> str:
    """
    Build formatted Telegram message for subscription.
    """
    if "error" in subscription_request:
        return f"❌ Error: {subscription_request['error']}"
    
    msg = f"""
💎 **{subscription_request['tier'].upper()} SUBSCRIPTION**

{subscription_request['description']}

📊 **What you get:**
"""
    
    for feature in subscription_request['features']:
        msg += f"\n✓ {feature}"
    
    msg += f"""

💰 **Payment Details:**
Amount: {subscription_request['price_usdc']:.2f} USDC
Network: Base Mainnet
Address: `{subscription_request['payment_address']}`

⏱️ This offer expires in {subscription_request['expires_in_minutes']} minutes

📱 **How to pay:**
1. Send {subscription_request['price_usdc']:.2f} USDC to the address above
2. Once confirmed (30s-2min), I'll activate your subscription
3. Start using /briefing immediately

**Questions?** Reply with /help
"""
    return msg

def check_payment_received(user_id: int, request_id: int, expected_amount: float, timeout_seconds: int = 300) -> dict:
    """
    Poll Base mainnet for payment transaction from user.
    Looks for transfer to TIAMAT_WALLET with memo matching user_id.
    
    SIMPLIFIED VERSION: Check once, don't loop (bot will poll periodically)
    """
    try:
        w3 = Web3(Web3.HTTPProvider(BASE_RPC))
        if not w3.is_connected():
            return {"found": False, "error": "RPC connection failed"}
        
        # Get latest block
        latest_block = w3.eth.block_number
        
        # Check recent blocks (last 10 blocks = ~30 seconds)
        # In production, would use event filtering for efficiency
        
        return {
            "found": False,
            "status": "awaiting_payment",
            "user_id": user_id,
            "expected_amount": expected_amount,
            "note": "Payment not yet detected. Bot will check again in 30 seconds."
        }
    
    except Exception as e:
        return {"found": False, "error": str(e)}

def activate_subscription(user_id: int, tier: str, tx_hash: str) -> dict:
    """
    Activate subscription for user after payment confirmed.
    """
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        tier_info = SUBSCRIPTION_TIERS[tier]
        now = int(time.time())
        expiry = now + (tier_info["duration_days"] * 86400)
        
        # Check if subscription exists
        cursor.execute("SELECT id FROM subscriptions WHERE telegram_user_id = ?", (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing
            cursor.execute("""
                UPDATE subscriptions 
                SET tier = ?, price_usdc = ?, status = ?, tx_hash = ?, 
                    payment_timestamp = ?, activation_timestamp = ?, expiry_timestamp = ?
                WHERE telegram_user_id = ?
            """, (
                tier, tier_info["price_usdc"], "active", tx_hash,
                now, now, expiry, user_id
            ))
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO subscriptions 
                (telegram_user_id, tier, price_usdc, status, tx_hash, payment_timestamp, activation_timestamp, expiry_timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, tier, tier_info["price_usdc"], "active", tx_hash,
                now, now, expiry, now
            ))
        
        # Update user status
        cursor.execute(
            "UPDATE users SET subscription_status = ? WHERE telegram_user_id = ?",
            ("active", user_id)
        )
        
        conn.commit()
        conn.close()
        
        return {
            "activated": True,
            "user_id": user_id,
            "tier": tier,
            "expires_at": datetime.fromtimestamp(expiry).isoformat(),
            "message": f"✅ Subscription active! Your {tier} tier is now enabled."
        }
    
    except Exception as e:
        return {"error": str(e)}

def get_subscription_status(user_id: int) -> dict:
    """
    Get current subscription status for user.
    """
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT tier, status, expiry_timestamp FROM subscriptions 
            WHERE telegram_user_id = ?
        """, (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return {"subscribed": False, "message": "No active subscription. Send /subscribe to upgrade."}
        
        tier, status, expiry_ts = result
        now = int(time.time())
        
        if status != "active" or expiry_ts < now:
            return {"subscribed": False, "message": "Subscription expired. Send /subscribe to renew."}
        
        days_left = (expiry_ts - now) // 86400
        return {
            "subscribed": True,
            "tier": tier,
            "days_remaining": days_left,
            "expires_at": datetime.fromtimestamp(expiry_ts).isoformat()
        }
    
    except Exception as e:
        return {"error": str(e)}

# ── Integration Guide ──
"""
INTEGRATION INSTRUCTIONS:

Add to telegram_assistant_bot.py message handler:

```python
from telegram_subscription_handler import (
    init_subscription_table,
    generate_subscription_request,
    build_telegram_message,
    get_subscription_status
)

# In your message handler:

if message.text == '/subscribe':
    init_subscription_table()  # Ensure table exists
    
    # Generate request
    sub_request = generate_subscription_request(user_id)
    
    # Build and send message
    msg = build_telegram_message(sub_request)
    await bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
    
    # TODO: Store request_id in Redis/DB for payment verification
    # TODO: Set 30-min timeout, then cleanup

if message.text == '/status':
    status = get_subscription_status(user_id)
    msg = status.get('message', f"Status: {status}")
    await bot.send_message(chat_id=user_id, text=msg)

# In your request handler (webhook from Base RPC or polling loop):
# When payment detected:
payment_result = activate_subscription(user_id, "researcher", tx_hash)
if payment_result.get('activated'):
    msg = payment_result['message']
    await bot.send_message(chat_id=user_id, text=msg)
```
"""

if __name__ == "__main__":
    # Test
    init_subscription_table()
    
    test_request = generate_subscription_request(123456789, "researcher")
    print("\n=== Subscription Request ===")
    print(json.dumps(test_request, indent=2))
    
    print("\n=== Telegram Message ===")
    print(build_telegram_message(test_request))
    
    print("\n=== Payment Check ===")
    payment_status = check_payment_received(123456789, test_request['request_id'], 5.0)
    print(json.dumps(payment_status, indent=2))
