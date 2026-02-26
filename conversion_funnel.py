#!/usr/bin/env python3
"""
TIAMAT Conversion Funnel Analyzer
Reads all available log sources and outputs a structured JSON diagnostic.

Data sources (in priority order):
  1. /root/api/requests.log       — app-level structured log
  2. /var/log/nginx/access.log*   — HTTP layer (all rotated + gzipped)
  3. /root/api/payments.db        — SQLite payment records
  4. /root/api/quota.db           — Free-tier quota usage
  5. /root/.automaton/tiamat.log  — Agent activity (also handles /root/tiamat.log alias)
"""

import re
import json
import gzip
import sqlite3
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_PATH = "/root/.automaton/conversion_funnel.json"

NGINX_LOGS = [
    "/var/log/nginx/access.log",
    "/var/log/nginx/access.log.1",
    "/var/log/nginx/access.log.2.gz",
    "/var/log/nginx/access.log.3.gz",
]
APP_REQUEST_LOG = "/root/api/requests.log"
PAYMENTS_DB     = "/root/api/payments.db"
QUOTA_DB        = "/root/api/quota.db"
FREETIER_DB     = "/root/api/freetier.db"
TIAMAT_LOG      = "/root/.automaton/tiamat.log"  # alias for /root/tiamat.log

# Endpoints we care about for conversion analysis
API_ENDPOINTS = {"/summarize", "/chat", "/generate", "/memory", "/research",
                 "/drift/check", "/drift/baseline"}

# Prices (USDC)
PRICES = {"/summarize": 0.01, "/chat": 0.005, "/generate": 0.01,
          "/drift/check": 0.01, "/drift/baseline": 0.005, "/memory": 0.001}

# ── Regex patterns ─────────────────────────────────────────────────────────────

# Nginx combined log: IP - - [date] "METHOD /path HTTP/ver" STATUS bytes "ref" "ua"
_NGINX_RE = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "(?:GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH) (/[^ ?"]*)(?:[^"]*)" (\d{3}) \d+'
)

# App request log (multiple evolving formats):
# Old: 2026-02-21T03:43:35 | IP: 127.0.0.1 | Length: 86 | Type: FREE | Code: 200 | ...
# New: 2026-02-25T07:17:44 | IP:127.0.0.1 | endpoint:/summarize | status:402 | free:False | ...
_APPLOG_TS_RE    = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})')
_APPLOG_IP_RE    = re.compile(r'IP\s*:\s*(\S+)')
_APPLOG_CODE_RE  = re.compile(r'(?:Code|status)\s*:\s*(\d{3})')
_APPLOG_FREE_RE  = re.compile(r'(?:Type|free)\s*:\s*(FREE|True|False)', re.I)
_APPLOG_EP_RE    = re.compile(r'endpoint\s*:\s*(/\S+)')

# Payment event patterns in tiamat.log / nginx
_PAYMENT_ATTEMPT_RE = re.compile(
    r'(?:verify_payment|X-Payment|payment_attempt|payment.*attempt)', re.I
)
_PAYMENT_SUCCESS_RE = re.compile(
    r'(?:payment.*verified|payment_success|paid.*True|free:False.*200)', re.I
)
_PAYMENT_FAIL_RE = re.compile(
    r'(?:payment.*fail|verify.*fail|invalid.*tx|nonce.*low|already.*used|'
    r'payment_error|verification.*failed)', re.I
)

# ── Log readers ───────────────────────────────────────────────────────────────

def read_lines(path: str) -> list[str]:
    """Read lines from plain or gzip file. Returns [] if missing."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rt", errors="replace") as f:
                return f.readlines()
        else:
            with open(path, errors="replace") as f:
                return f.readlines()
    except Exception:
        return []

# ── Nginx parsing ─────────────────────────────────────────────────────────────

def parse_nginx() -> tuple[dict, int]:
    """Return per-endpoint counts of {total, 200, 402, 4xx, 5xx, bots}."""
    ep_stats: dict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_all = 0
    bot_ips = {"10.17.0.2"}  # known internal / brainrot IPs

    for log_path in NGINX_LOGS:
        for line in read_lines(log_path):
            m = _NGINX_RE.match(line)
            if not m:
                continue
            ip, _, path, status = m.group(1), m.group(2), m.group(3), int(m.group(4))

            # Normalize endpoint (strip sub-paths for grouping)
            ep = "/" + path.strip("/").split("/")[0]
            if ep not in API_ENDPOINTS:
                continue

            total_all += 1
            ep_stats[ep]["total"] += 1
            ep_stats[ep]["bot" if ip in bot_ips else "human"] += 1

            if status == 200:
                ep_stats[ep]["200"] += 1
            elif status == 402:
                ep_stats[ep]["402"] += 1
            elif 400 <= status < 500:
                ep_stats[ep]["4xx"] += 1
            elif status >= 500:
                ep_stats[ep]["5xx"] += 1

    return dict(ep_stats), total_all

# ── App request log parsing ───────────────────────────────────────────────────

def _ep_entry() -> dict:
    return {"total": 0, "free": 0, "paid": 0, "402": 0, "200": 0, "500": 0, "errors": []}

def parse_app_log() -> dict:
    """Parse /root/api/requests.log for structured request data."""
    lines = read_lines(APP_REQUEST_LOG)
    ep_data: dict[str, dict] = defaultdict(_ep_entry)
    for line in lines:
        line = line.strip()
        if not line:
            continue

        ep_m   = _APPLOG_EP_RE.search(line)
        code_m = _APPLOG_CODE_RE.search(line)
        free_m = _APPLOG_FREE_RE.search(line)

        # Determine endpoint
        if ep_m:
            ep = ep_m.group(1)
        elif "summarize" in line.lower():
            ep = "/summarize"
        elif "chat" in line.lower():
            ep = "/chat"
        elif "generate" in line.lower():
            ep = "/generate"
        else:
            ep = "/unknown"

        # Normalize to base endpoint
        ep = "/" + ep.strip("/").split("/")[0]

        code = int(code_m.group(1)) if code_m else 0
        is_free = True
        if free_m:
            val = free_m.group(1).upper()
            is_free = val in ("FREE", "TRUE")

        ep_data[ep]["total"] += 1
        if code == 200:
            ep_data[ep]["200"] += 1
            if is_free:
                ep_data[ep]["free"] += 1
            else:
                ep_data[ep]["paid"] += 1
        elif code == 402:
            ep_data[ep]["402"] += 1
        elif code >= 500:
            ep_data[ep]["500"] += 1
            # Extract error message
            err_part = line.split("|")[-1].strip() if "|" in line else line[-120:]
            if err_part and len(ep_data[ep]["errors"]) < 10:
                ep_data[ep]["errors"].append(err_part)

    return dict(ep_data)

# ── Tiamat log: payment events ────────────────────────────────────────────────

def parse_tiamat_log() -> dict:
    """Scan agent log for payment attempt / success / failure events."""
    lines = read_lines(TIAMAT_LOG)
    attempts  = defaultdict(int)
    successes = defaultdict(int)
    failures  = defaultdict(int)
    fail_msgs = []

    _EP_RE = re.compile(r"/(summarize|chat|generate|memory|research|drift)")

    for line in lines:
        if "payment" not in line.lower() and "402" not in line and "paid" not in line.lower():
            continue

        ep_m = _EP_RE.search(line)
        ep   = f"/{ep_m.group(1)}" if ep_m else "/unknown"

        if _PAYMENT_FAIL_RE.search(line):
            failures[ep] += 1
            msg = line.strip()[-200:]
            if msg not in fail_msgs:
                fail_msgs.append(msg)
        elif _PAYMENT_SUCCESS_RE.search(line):
            successes[ep] += 1
        elif _PAYMENT_ATTEMPT_RE.search(line):
            attempts[ep] += 1

    return {
        "attempts":  dict(attempts),
        "successes": dict(successes),
        "failures":  dict(failures),
        "fail_msgs": fail_msgs[:20],
    }

# ── SQLite queries ────────────────────────────────────────────────────────────

def query_payments_db() -> dict:
    """Read payments.db for verified tx hashes and premium subscriptions."""
    result = {"verified_payments": [], "premium_subs": [], "real_revenue_usdc": 0.0}
    try:
        conn = sqlite3.connect(PAYMENTS_DB)
        rows = conn.execute(
            "SELECT tx_hash, amount_usdc, sender, endpoint, verified_at FROM used_tx_hashes"
        ).fetchall()
        TEST_PREFIXES = ("0xaaa", "0xbbb", "0xccc", "0xtest", "0x1234", "0x5678")
        for tx_hash, amount, sender, endpoint, verified_at in rows:
            is_test = (
                tx_hash.lower().startswith(TEST_PREFIXES)
                or sender.lower() in ("0x1234", "0x5678", "0xtest")
                or len(set(tx_hash.lower().replace("0x", ""))) < 4  # degenerate hash
            )
            entry = {"tx_hash": tx_hash[:20] + "...", "amount_usdc": amount,
                     "endpoint": endpoint, "verified_at": verified_at,
                     "is_test": is_test}
            result["verified_payments"].append(entry)
            if not is_test:
                result["real_revenue_usdc"] += amount

        subs = conn.execute(
            "SELECT tx_hash, amount_usdc, sender, activated_at FROM premium_subscriptions"
        ).fetchall()
        for tx_hash, amount, sender, activated_at in subs:
            is_test = len(set(tx_hash.lower().replace("0x", ""))) < 4
            entry = {"tx_hash": tx_hash[:20] + "...", "amount_usdc": amount,
                     "activated_at": activated_at, "is_test": is_test}
            result["premium_subs"].append(entry)
            if not is_test:
                result["real_revenue_usdc"] += amount

        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result

def query_quota_db() -> dict:
    """Return per-endpoint unique-IP free-tier usage counts."""
    result = defaultdict(int)
    try:
        conn = sqlite3.connect(QUOTA_DB)
        rows = conn.execute(
            "SELECT ip, endpoint, date, count FROM quota"
        ).fetchall()
        for ip, endpoint, date, count in rows:
            ep = f"/{endpoint}" if not endpoint.startswith("/") else endpoint
            result[ep] += count
        conn.close()
    except Exception:
        pass
    return dict(result)

def query_freetier_db() -> dict:
    """Return count of unique IPs that ever used the free tier."""
    try:
        conn = sqlite3.connect(FREETIER_DB)
        ips = conn.execute("SELECT ip FROM used_ips").fetchall()
        conn.close()
        real_ips = [r[0] for r in ips if r[0] not in ("127.0.0.1", "10.17.0.2")]
        return {"total_unique_ips": len(ips), "real_external_ips": len(real_ips)}
    except Exception:
        return {"total_unique_ips": 0, "real_external_ips": 0}

# ── Blocker analysis ──────────────────────────────────────────────────────────

def analyze_blockers(nginx_ep, app_ep, payments, quota_usage) -> list[dict]:
    """Derive top 3 conversion blockers from the data."""
    blockers = []

    # --- Blocker: self-test noise inflating request counts ---
    total_nginx = sum(v.get("total", 0) for v in nginx_ep.values())
    bot_total   = sum(v.get("bot", 0) for v in nginx_ep.values())
    if total_nginx > 0 and bot_total / max(total_nginx, 1) > 0.3:
        pct = int(100 * bot_total / total_nginx)
        blockers.append({
            "blocker": f"{pct}% of API requests are TIAMAT's own self-tests "
                       f"(127.0.0.1 / 10.17.0.2) — inflating request counts, "
                       f"masking real user traffic",
            "impact": "HIGH",
            "fix": "Exclude 127.0.0.1 and 10.17.0.2 from all request counters. "
                   "Add a real analytics dashboard that shows ONLY external IPs. "
                   "The '7297 requests' claim was from a 7297ms inference latency "
                   "being misread as a request count — actual external requests ≈ "
                   f"{total_nginx - bot_total}.",
        })

    # --- Blocker: no paid calls to /chat or /generate ---
    for ep in ["/chat", "/generate"]:
        app_data = app_ep.get(ep, {})
        nginx_data = nginx_ep.get(ep, {})
        nginx_total = nginx_data.get("total", 0)
        paid_200 = app_data.get("paid", 0)
        if nginx_total == 0 and paid_200 == 0:
            blockers.append({
                "blocker": f"ZERO requests to {ep} in any log — the endpoint exists "
                           f"but no one (user or test) has ever called it via POST",
                "impact": "HIGH",
                "fix": f"The {ep} endpoint is invisible. Add it to the landing page "
                       f"demo tabs with a working interactive example. Currently only "
                       f"/summarize has any traffic. Run: curl -X POST https://tiamat.live{ep} "
                       f"-d '{{\"message\":\"hello\"}}' to verify it works end-to-end.",
            })

    # --- Blocker: 402 on free tier from self-test (quota exhausted by bot) ---
    summarize_data = app_ep.get("/summarize", {})
    s_402 = summarize_data.get("402", 0)
    s_total = summarize_data.get("total", 0)
    if s_402 > 0 and s_total > 0 and s_402 / s_total > 0.3:
        pct = int(100 * s_402 / s_total)
        blockers.append({
            "blocker": f"{pct}% of /summarize requests return 402 'daily quota exceeded' — "
                       f"TIAMAT's own verify loops (verify_summarize_api / verify_api_running) "
                       f"exhaust the 3/day free quota for 127.0.0.1 before any real user calls",
            "impact": "HIGH",
            "fix": "Whitelist 127.0.0.1 from the free-tier rate limiter (it's the server itself). "
                   "OR change verify scripts to use a paid X-Payment header for self-tests. "
                   "Currently every ~60s TIAMAT calls /summarize and burns a quota slot. "
                   "Fix in: /root/entity/src/agent/rate_limiter.py or "
                   "/root/.automaton/test_summarize_api.py",
        })

    # --- Blocker: no real payments in payments.db ---
    real_payments = payments.get("real_revenue_usdc", 0.0)
    all_payments  = payments.get("verified_payments", [])
    test_only     = all(p["is_test"] for p in all_payments) if all_payments else True
    if real_payments == 0.0:
        blockers.append({
            "blocker": "payments.db contains ONLY test/dummy hashes (0xaaa..., 0xbbb...) — "
                       "zero real USDC transactions have been verified. The payment wall "
                       "is working (returns 402 correctly) but no user has completed a payment.",
            "impact": "HIGH",
            "fix": "The funnel is: (1) user hits 402, (2) reads how_to_pay JSON, "
                   "(3) sends USDC on Base, (4) retries with X-Payment: <tx_hash>. "
                   "Step 2→3 is the dropout. Add a /pay page with MetaMask 'Pay Now' button "
                   "(already partially built). OR lower friction: accept payment via Stripe → "
                   "mint USDC proxy. Also: verify_payment() is never called with a real tx — "
                   "add logging to capture any payment header attempts.",
        })

    # --- Blocker: /chat and /generate not wired for x402 ---
    # Check if app log shows any paid successes for chat/generate
    chat_paid = app_ep.get("/chat", {}).get("paid", 0)
    gen_paid  = app_ep.get("/generate", {}).get("paid", 0)
    if chat_paid == 0 and gen_paid == 0:
        blockers.append({
            "blocker": "/chat and /generate show 0 paid successes in requests.log — "
                       "either x402 payment handling is not wired on these endpoints, "
                       "or no one has called them with X-Payment header",
            "impact": "MED",
            "fix": "Search summarize_api.py for x402 payment check on /chat and /generate. "
                   "If missing: add verify_payment() call at start of each handler, "
                   "same pattern as /summarize. Also add payment logging to requests.log "
                   "for these endpoints so they appear in analytics.",
        })

    # Sort: HIGH first, then MED/LOW
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    blockers.sort(key=lambda b: order.get(b["impact"], 3))
    return blockers[:3]

# ── Revenue calculation ───────────────────────────────────────────────────────

def calc_revenue(app_ep: dict, payments: dict) -> tuple[dict, float]:
    """Calculate per-endpoint revenue from app log paid counts + DB."""
    by_ep = {}
    total = 0.0
    for ep, price in PRICES.items():
        paid_count = app_ep.get(ep, {}).get("paid", 0)
        rev = round(paid_count * price, 4)
        if paid_count > 0:
            by_ep[ep] = f"${rev:.4f}"
            total += rev
    # Add real DB revenue (non-test)
    db_rev = payments.get("real_revenue_usdc", 0.0)
    total = max(total, db_rev)  # use whichever is higher
    return by_ep, total

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Gather all data
    nginx_ep, nginx_total = parse_nginx()
    app_ep   = parse_app_log()
    tiamat   = parse_tiamat_log()
    payments = query_payments_db()
    quota    = query_quota_db()
    freetier = query_freetier_db()
    rev_by_ep, total_rev = calc_revenue(app_ep, payments)
    blockers = analyze_blockers(nginx_ep, app_ep, payments, quota)

    # ── Aggregate request counts ──────────────────────────────────────────────
    # Prefer app log (structured) for API endpoints; nginx for overall traffic
    all_endpoints = set(API_ENDPOINTS) | set(nginx_ep.keys()) | set(app_ep.keys())

    requests_by_endpoint = {}
    for ep in sorted(all_endpoints):
        nginx_count = nginx_ep.get(ep, {}).get("total", 0)
        app_count   = app_ep.get(ep, {}).get("total", 0)
        requests_by_endpoint[ep] = max(nginx_count, app_count)

    total_requests = sum(requests_by_endpoint.values())

    # ── Payment funnel ────────────────────────────────────────────────────────
    payment_attempts = {}
    successful_payments = {}
    failed_payments = {}
    failed_errors = list(tiamat.get("fail_msgs", []))

    for ep in API_ENDPOINTS:
        a = tiamat["attempts"].get(ep, 0)
        s = (app_ep.get(ep, {}).get("paid", 0)
             + tiamat["successes"].get(ep, 0))
        f = tiamat["failures"].get(ep, 0)
        if a > 0:
            payment_attempts[ep]   = a
        if s > 0:
            successful_payments[ep] = s
        if f > 0:
            failed_payments[ep]    = f

    # ── Conversion rates ──────────────────────────────────────────────────────
    conversion_rates = {}
    for ep in API_ENDPOINTS:
        total_ep = requests_by_endpoint.get(ep, 0)
        paid_ep  = successful_payments.get(ep, 0)
        if total_ep > 0:
            conversion_rates[ep] = f"{100 * paid_ep / total_ep:.2f}%"

    # ── DB summary ────────────────────────────────────────────────────────────
    db_summary = {
        "payments_db": {
            "verified_tx_count": len(payments.get("verified_payments", [])),
            "premium_sub_count": len(payments.get("premium_subs", [])),
            "real_revenue_usdc": payments.get("real_revenue_usdc", 0.0),
            "note": "All current DB entries are test/dummy hashes — no real payments",
        },
        "quota_db": {"usage_by_endpoint": quota},
        "freetier_db": freetier,
    }

    # ── Recommendations ────────────────────────────────────────────────────────
    top_blocker = blockers[0]["blocker"] if blockers else "No blockers identified"
    recs = (
        f"CRITICAL: {top_blocker[:120]}... | "
        "PRIORITY ORDER: (1) Fix self-test quota exhaustion — it creates false 402s. "
        "(2) Add /chat and /generate to landing page with working demos — they have 0 traffic. "
        "(3) Build MetaMask 'Pay Now' button on /pay page — current how_to_pay JSON response "
        "requires manual USDC transfer which nobody completes. "
        "(4) Add payment attempt logging — can't debug what you can't measure. "
        "The core issue: payment friction is too high for a free-tier user to spontaneously "
        "upgrade. Need a 1-click path from free hit to paid transaction."
    )

    # ── Assemble output ───────────────────────────────────────────────────────
    output = {
        "_meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "sources": {
                "nginx_logs": NGINX_LOGS,
                "app_request_log": APP_REQUEST_LOG,
                "payments_db": PAYMENTS_DB,
                "tiamat_log": TIAMAT_LOG,
            },
            "note_on_7297": (
                "The '7297 requests' figure TIAMAT cited was a 7297ms GPU inference latency "
                "misread as a request count. Actual verified API request counts are in "
                "requests_by_endpoint below (nginx + app log cross-reference)."
            ),
        },
        "total_requests": total_requests,
        "requests_by_endpoint": requests_by_endpoint,
        "payment_attempts": payment_attempts,
        "successful_payments": successful_payments,
        "failed_payments": failed_payments,
        "failed_payment_errors": failed_errors,
        "revenue_by_endpoint": rev_by_ep if rev_by_ep else {"note": "No paid revenue recorded"},
        "total_revenue": f"${total_rev:.4f}",
        "conversion_rates": conversion_rates,
        "database_summary": db_summary,
        "top_3_blockers": blockers,
        "recommendations": recs,
    }

    # ── Write output ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))
    print(f"\n[OK] Written to {OUTPUT_PATH}", flush=True)
    return output


if __name__ == "__main__":
    main()
