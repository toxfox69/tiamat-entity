"""
payment_analytics.py — x402 USDC micro-payment analytics Blueprint
=================================================================
Drop into summarize_api.py with:

    from src.agent.payment_analytics import analytics_bp
    app.register_blueprint(analytics_bp)

POST /api/payment-analytics
  Headers : X-API-Key: <ANALYTICS_API_KEY env var>
  Body    : { "transactions": [...], "export": "json"|"csv" }

Transaction schema (each item in the list):
  {
    "tx_hash"     : "0xabc...",        # optional, string
    "customer_id" : "0xaddr_or_uid",   # required for CLV / churn
    "amount_usdc" : 0.01,              # float
    "timestamp"   : "2026-03-04T12:00:00",
    "endpoint"    : "/summarize",      # which product was used
    "status"      : "confirmed"        # "confirmed" | "failed" | "pending"
  }
"""

import csv
import hmac
import io
import os
import time
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, Response

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)

# ── Cache (in-process, 5-minute TTL) ────────────────────────────────────────
_cache: dict = {}
CACHE_TTL = 300  # seconds


def _cache_key(transactions: list) -> str:
    raw = "|".join(
        f"{t.get('tx_hash','')}{t.get('customer_id','')}{t.get('amount_usdc',0)}"
        f"{t.get('timestamp','')}{t.get('status','')}"
        for t in transactions
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.monotonic() < entry["exp"]:
        return entry["val"]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, val: dict):
    _cache[key] = {"val": val, "exp": time.monotonic() + CACHE_TTL}


# ── API-key auth ─────────────────────────────────────────────────────────────
def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        expected = os.getenv("ANALYTICS_API_KEY", "")
        provided = request.headers.get("X-API-Key", "")
        if not expected:
            return jsonify({"error": "ANALYTICS_API_KEY not configured on server"}), 503
        if not provided:
            return jsonify({"error": "X-API-Key header required"}), 401
        # Constant-time comparison avoids timing attacks
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return wrapper


# ── Timestamp parser ─────────────────────────────────────────────────────────
_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
)


def _parse_ts(val) -> datetime:
    s = str(val).strip()[:26]
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unparseable timestamp: {val!r}")


# ── Core analytics engine ────────────────────────────────────────────────────
def compute_analytics(transactions: list) -> dict:
    """Pure function — no side effects. Returns analytics dict."""
    if not transactions:
        return {"error": "Empty transactions list"}

    # ── Normalize rows ───────────────────────────────────────────────────────
    rows = []
    for i, tx in enumerate(transactions):
        try:
            ts = _parse_ts(tx.get("timestamp", ""))
            amount = float(tx.get("amount_usdc", 0))
            if amount < 0:
                continue
            rows.append(
                {
                    "ts": ts,
                    "date": ts.date().isoformat(),
                    "amount": amount,
                    "status": str(tx.get("status", "confirmed")).lower(),
                    "customer": str(tx.get("customer_id", f"anon_{i}")),
                    "endpoint": str(tx.get("endpoint", "/unknown")),
                    "tx_hash": str(tx.get("tx_hash", "")),
                }
            )
        except (ValueError, TypeError):
            continue  # skip malformed rows

    if not rows:
        return {"error": "No valid transactions after parsing"}

    confirmed = [r for r in rows if r["status"] == "confirmed"]

    # ── 1. Daily revenue trends ──────────────────────────────────────────────
    daily_rev: dict = defaultdict(float)
    daily_total: dict = defaultdict(int)
    daily_ok: dict = defaultdict(int)

    for r in rows:
        daily_total[r["date"]] += 1
    for r in confirmed:
        daily_rev[r["date"]] += r["amount"]
        daily_ok[r["date"]] += 1

    all_dates = sorted(set(list(daily_rev) + list(daily_total)))
    daily_trends = [
        {
            "date": d,
            "revenue_usdc": round(daily_rev.get(d, 0.0), 6),
            "transactions": daily_total.get(d, 0),
            "confirmed": daily_ok.get(d, 0),
            "conversion_pct": round(
                daily_ok.get(d, 0) / daily_total[d] * 100, 2
            ) if daily_total.get(d) else 0.0,
        }
        for d in all_dates
    ]

    # ── 2. Top customers ─────────────────────────────────────────────────────
    c_spend: dict = defaultdict(float)
    c_count: dict = defaultdict(int)
    c_first: dict = {}
    c_last: dict = {}

    for r in confirmed:
        c = r["customer"]
        c_spend[c] += r["amount"]
        c_count[c] += 1
        c_first[c] = min(c_first.get(c, r["ts"]), r["ts"])
        c_last[c] = max(c_last.get(c, r["ts"]), r["ts"])

    top_customers = sorted(
        [
            {
                "customer_id": c,
                "total_spend_usdc": round(c_spend[c], 6),
                "transaction_count": c_count[c],
                "avg_spend_usdc": round(c_spend[c] / c_count[c], 6),
                "first_seen": c_first[c].isoformat(),
                "last_seen": c_last[c].isoformat(),
            }
            for c in c_spend
        ],
        key=lambda x: x["total_spend_usdc"],
        reverse=True,
    )[:20]

    # ── 3. Conversion rates ──────────────────────────────────────────────────
    total_txn = len(rows)
    confirmed_txn = len(confirmed)
    overall_conv = (confirmed_txn / total_txn * 100) if total_txn else 0.0

    ep_total: dict = defaultdict(int)
    ep_ok: dict = defaultdict(int)
    for r in rows:
        ep_total[r["endpoint"]] += 1
    for r in confirmed:
        ep_ok[r["endpoint"]] += 1

    conversion_by_ep = {
        ep: {
            "total": ep_total[ep],
            "confirmed": ep_ok.get(ep, 0),
            "rate_pct": round(ep_ok.get(ep, 0) / ep_total[ep] * 100, 2),
        }
        for ep in ep_total
    }

    # ── 4. Churn rate ────────────────────────────────────────────────────────
    # Definition: customers active in the prior 30-day window who made zero
    # transactions in the most-recent 30-day window.
    churn_info: dict
    if confirmed:
        latest = max(r["ts"] for r in confirmed)
        t_recent = latest - timedelta(days=30)
        t_prior = latest - timedelta(days=60)

        prior_set = {r["customer"] for r in confirmed if t_prior <= r["ts"] < t_recent}
        recent_set = {r["customer"] for r in confirmed if r["ts"] >= t_recent}
        churned = prior_set - recent_set

        churn_rate = len(churned) / len(prior_set) * 100 if prior_set else 0.0
        churn_info = {
            "rate_pct": round(churn_rate, 2),
            "churned_customers": len(churned),
            "active_prior_window": len(prior_set),
            "active_recent_window": len(recent_set),
            "window_days": 30,
            "definition": "Customers active in days 31-60 who did not transact in latest 30 days",
        }
    else:
        churn_info = {
            "rate_pct": 0.0,
            "churned_customers": 0,
            "active_prior_window": 0,
            "active_recent_window": 0,
            "window_days": 30,
            "definition": "No confirmed transactions",
        }

    # ── 5. Customer Lifetime Value ───────────────────────────────────────────
    # CLV_365 = avg_order_value × (total_txns_per_customer / avg_lifespan_days) × 365
    clv_info: dict
    if c_spend:
        total_confirmed_amount = sum(c_spend.values())
        avg_order = total_confirmed_amount / confirmed_txn if confirmed_txn else 0.0

        # Per-customer lifespan (days from first to last tx; min 1 day)
        lifespans = [
            max((c_last[c] - c_first[c]).days, 1)
            for c in c_first
        ]
        avg_lifespan = sum(lifespans) / len(lifespans)

        avg_txns_per_cust = confirmed_txn / len(c_spend)
        # Daily purchase rate over their lifespan
        daily_rate = avg_txns_per_cust / avg_lifespan
        clv_365 = avg_order * daily_rate * 365

        clv_info = {
            "clv_365d_usdc": round(clv_365, 4),
            "avg_order_value_usdc": round(avg_order, 6),
            "avg_lifespan_days": round(avg_lifespan, 1),
            "avg_txns_per_customer": round(avg_txns_per_cust, 2),
            "total_unique_customers": len(c_spend),
            "note": "Projected annual CLV from observed behavior",
        }
    else:
        clv_info = {
            "clv_365d_usdc": 0.0,
            "note": "No confirmed transactions to compute CLV",
        }

    # ── Summary ──────────────────────────────────────────────────────────────
    total_revenue = sum(r["amount"] for r in confirmed)

    return {
        "summary": {
            "total_revenue_usdc": round(total_revenue, 6),
            "total_transactions": total_txn,
            "confirmed_transactions": confirmed_txn,
            "failed_transactions": total_txn - confirmed_txn,
            "overall_conversion_pct": round(overall_conv, 2),
            "unique_customers": len(c_spend),
            "period_start": min(r["date"] for r in rows),
            "period_end": max(r["date"] for r in rows),
        },
        "daily_revenue_trends": daily_trends,
        "top_customers": top_customers,
        "conversion_rates": {
            "overall_pct": round(overall_conv, 2),
            "by_endpoint": conversion_by_ep,
        },
        "churn": churn_info,
        "clv": clv_info,
    }


# ── CSV renderer ─────────────────────────────────────────────────────────────
def _analytics_to_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)

    def section(title, rows_of_dicts):
        w.writerow([f"=== {title} ==="])
        if rows_of_dicts and isinstance(rows_of_dicts[0], dict):
            w.writerow(list(rows_of_dicts[0].keys()))
            for row in rows_of_dicts:
                w.writerow(list(row.values()))
        w.writerow([])

    def kv_section(title, d: dict):
        w.writerow([f"=== {title} ==="])
        for k, v in d.items():
            w.writerow([k, v])
        w.writerow([])

    kv_section("SUMMARY", data.get("summary", {}))
    section("DAILY REVENUE TRENDS", data.get("daily_revenue_trends", []))
    section("TOP CUSTOMERS", data.get("top_customers", []))

    # Conversion rates — flatten by-endpoint sub-dict
    conv = data.get("conversion_rates", {})
    w.writerow(["=== CONVERSION RATES ==="])
    w.writerow(["overall_pct", conv.get("overall_pct", 0)])
    ep_rows = [
        {"endpoint": ep, **vals}
        for ep, vals in conv.get("by_endpoint", {}).items()
    ]
    if ep_rows:
        w.writerow(list(ep_rows[0].keys()))
        for row in ep_rows:
            w.writerow(list(row.values()))
    w.writerow([])

    kv_section("CHURN", data.get("churn", {}))
    kv_section("CUSTOMER LIFETIME VALUE", data.get("clv", {}))

    return buf.getvalue()


# ── Route ─────────────────────────────────────────────────────────────────────
@analytics_bp.route("/api/payment-analytics", methods=["POST"])
@require_api_key
def payment_analytics():
    """
    POST /api/payment-analytics

    Headers:
      X-API-Key: <ANALYTICS_API_KEY>

    Body (JSON):
      {
        "transactions": [
          {
            "tx_hash"    : "0xabc...",
            "customer_id": "0xaddr_or_uid",
            "amount_usdc": 0.01,
            "timestamp"  : "2026-03-04T12:00:00",
            "endpoint"   : "/summarize",
            "status"     : "confirmed"
          },
          ...
        ],
        "export": "json"    // or "csv"
      }

    Returns:
      JSON analytics report, or CSV attachment if export=csv.
    """
    try:
        body = request.get_json(force=True, silent=True)
        if not body:
            return jsonify({"error": "JSON body required"}), 400

        transactions = body.get("transactions")
        if not isinstance(transactions, list):
            return jsonify({"error": '"transactions" must be an array'}), 400
        if len(transactions) > 100_000:
            return jsonify({"error": "Max 100,000 transactions per call"}), 400

        export_fmt = str(body.get("export", "json")).lower()
        if export_fmt not in ("json", "csv"):
            return jsonify({"error": '"export" must be "json" or "csv"'}), 400

        # ── Cache lookup ──────────────────────────────────────────────────
        cache_key = _cache_key(transactions)
        cached = _cache_get(cache_key)
        from_cache = cached is not None

        if cached is None:
            result = compute_analytics(transactions)
            if "error" not in result:
                _cache_set(cache_key, result)
        else:
            result = cached

        if "error" in result:
            return jsonify(result), 422

        # ── CSV export ────────────────────────────────────────────────────
        if export_fmt == "csv":
            csv_body = _analytics_to_csv(result)
            return Response(
                csv_body,
                mimetype="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="payment_analytics.csv"'
                },
            )

        # ── JSON response ─────────────────────────────────────────────────
        return jsonify(
            {
                "cached": from_cache,
                "cache_ttl_seconds": CACHE_TTL,
                **result,
            }
        )

    except Exception as e:
        logger.error("payment_analytics error: %s", e, exc_info=True)
        return jsonify({"error": "Internal analytics error"}), 500
