"""
Breach checking for TIAMAT Data Scrubber.
- Password check: HIBP Pwned Passwords API (free, k-anonymity)
- Email breach check: XposedOrNot API (free, no auth, no Cloudflare)
  Falls back to HIBP API if key provided.
"""

import hashlib
import logging
import requests

logger = logging.getLogger(__name__)

HIBP_PASSWORD_API = "https://api.pwnedpasswords.com/range/"
XON_CHECK_API = "https://api.xposedornot.com/v1/check-email/"
XON_ANALYTICS_API = "https://api.xposedornot.com/v1/breach-analytics"


def check_password(password: str) -> dict:
    """
    Check if a password has been in known data breaches.
    Uses HIBP k-anonymity model — only first 5 chars of SHA-1 hash sent.
    Your password NEVER leaves this server.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]
    suffix = sha1[5:]

    try:
        resp = requests.get(
            HIBP_PASSWORD_API + prefix,
            headers={"User-Agent": "TIAMAT-DataScrubber"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {
                "pwned": False,
                "count": 0,
                "message": f"HIBP API error (HTTP {resp.status_code})",
                "error": True,
            }

        for line in resp.text.splitlines():
            parts = line.strip().split(":")
            if len(parts) == 2 and parts[0] == suffix:
                count = int(parts[1])
                return {
                    "pwned": True,
                    "count": count,
                    "message": f"This password has appeared in {count:,} data breaches. Change it immediately.",
                }

        return {
            "pwned": False,
            "count": 0,
            "message": "This password has NOT been found in any known data breaches.",
        }

    except requests.RequestException as e:
        logger.error(f"HIBP password check failed: {e}")
        return {"pwned": False, "count": 0, "message": f"Could not reach HIBP: {e}", "error": True}


def check_email_breaches(email: str, api_key: str = None) -> dict:
    """
    Check if an email has been in known data breaches.
    Primary: XposedOrNot free API (no auth, no Cloudflare).
    Fallback: HIBP API if key provided.
    """
    # If HIBP API key provided, use it (more comprehensive)
    if api_key:
        result = _check_hibp_api(email, api_key)
        if not result.get("error"):
            return result
        # Fall through to XposedOrNot if HIBP fails

    # Primary: XposedOrNot (free, works from datacenter IPs)
    return _check_xposedornot(email)


def _check_xposedornot(email: str) -> dict:
    """Check email breaches via XposedOrNot free API."""
    try:
        # Step 1: Quick check — is this email in any breaches?
        resp = requests.get(
            XON_CHECK_API + email,
            headers={"User-Agent": "TIAMAT-DataScrubber"},
            timeout=15,
        )

        if resp.status_code == 404 or "Not found" in resp.text:
            return {
                "pwned": False,
                "breach_count": 0,
                "breaches": [],
                "message": "This email has NOT been found in any known data breaches.",
            }

        if resp.status_code != 200:
            return {
                "pwned": False,
                "breach_count": 0,
                "breaches": [],
                "message": f"Breach check API error (HTTP {resp.status_code})",
                "error": True,
            }

        data = resp.json()
        breach_names = []
        raw_breaches = data.get("breaches", [])
        # XON returns breaches as [[name1, name2, ...]]
        if raw_breaches and isinstance(raw_breaches[0], list):
            breach_names = raw_breaches[0]
        elif raw_breaches and isinstance(raw_breaches[0], str):
            breach_names = raw_breaches

        if not breach_names:
            return {
                "pwned": False,
                "breach_count": 0,
                "breaches": [],
                "message": "This email has NOT been found in any known data breaches.",
            }

        # Step 2: Get detailed analytics (risk score, exposed data types)
        details = _get_xon_analytics(email)

        breaches = [{"name": name, "details": ""} for name in breach_names]

        risk_score = details.get("risk_score", 0)
        risk_label = details.get("risk_label", "Unknown")
        exposed_data = details.get("exposed_data", [])

        msg = f"This email was found in {len(breaches)} data breach(es)."
        if risk_label and risk_label != "Unknown":
            msg += f" Risk level: {risk_label} ({risk_score}/100)."
        if exposed_data:
            msg += f" Exposed data types: {', '.join(exposed_data[:5])}."

        return {
            "pwned": True,
            "breach_count": len(breaches),
            "breaches": breaches,
            "risk_score": risk_score,
            "risk_label": risk_label,
            "exposed_data": exposed_data,
            "message": msg,
        }

    except requests.RequestException as e:
        logger.error(f"XposedOrNot check failed: {e}")
        return {
            "pwned": False,
            "breach_count": 0,
            "breaches": [],
            "message": f"Could not reach breach database: {e}",
            "error": True,
        }
    except Exception as e:
        logger.error(f"XposedOrNot parse error: {e}")
        return {
            "pwned": False,
            "breach_count": 0,
            "breaches": [],
            "message": f"Error parsing breach data: {e}",
            "error": True,
        }


def _get_xon_analytics(email: str) -> dict:
    """Get detailed breach analytics from XposedOrNot."""
    try:
        resp = requests.get(
            XON_ANALYTICS_API,
            params={"email": email},
            headers={"User-Agent": "TIAMAT-DataScrubber"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {}

        data = resp.json()
        metrics = data.get("BreachMetrics", {})

        # Extract risk
        risk = metrics.get("risk", [{}])
        risk_info = risk[0] if risk else {}

        # Extract exposed data types
        exposed = []
        xposed_data = metrics.get("xposed_data", [{}])
        if xposed_data:
            xd = xposed_data[0] if isinstance(xposed_data, list) else xposed_data
            children = xd.get("children", [])
            for category in children:
                cat_children = category.get("children", [])
                for item in cat_children:
                    name = item.get("name", "")
                    value = item.get("value", 0)
                    if value > 0 and name.startswith("data_"):
                        exposed.append(name.replace("data_", ""))

        return {
            "risk_score": risk_info.get("risk_score", 0),
            "risk_label": risk_info.get("risk_label", "Unknown"),
            "exposed_data": exposed,
        }
    except Exception as e:
        logger.error(f"XON analytics error: {e}")
        return {}


def _check_hibp_api(email: str, api_key: str) -> dict:
    """Check email breaches via HIBP paid API."""
    try:
        resp = requests.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
            headers={
                "hibp-api-key": api_key,
                "User-Agent": "TIAMAT-DataScrubber",
            },
            params={"truncateResponse": "false"},
            timeout=15,
        )

        if resp.status_code == 404:
            return {
                "pwned": False,
                "breach_count": 0,
                "breaches": [],
                "message": "This email has NOT been found in any known data breaches.",
            }

        if resp.status_code == 200:
            breaches = resp.json()
            return {
                "pwned": True,
                "breach_count": len(breaches),
                "breaches": [
                    {
                        "name": b.get("Name", ""),
                        "title": b.get("Title", ""),
                        "domain": b.get("Domain", ""),
                        "date": b.get("BreachDate", ""),
                        "records": b.get("PwnCount", 0),
                        "data_exposed": b.get("DataClasses", []),
                    }
                    for b in breaches
                ],
                "message": f"This email was found in {len(breaches)} data breach(es).",
            }

        return {"error": True, "message": f"HIBP API error (HTTP {resp.status_code})"}

    except requests.RequestException as e:
        return {"error": True, "message": f"Could not reach HIBP API: {e}"}
