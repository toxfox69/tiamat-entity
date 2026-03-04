"""
TIAMAT Email Tool — Read (IMAP) + Send (Mailgun HTTP API)
DigitalOcean blocks outbound SMTP (465/587), so we use Mailgun over HTTPS for sending.
IMAP port 993 is open for reading.
"""
import os
import json
import imaplib
import email
from email.header import decode_header
import urllib.request
import urllib.error
import base64

GMAIL_USER = os.environ.get("TIAMAT_EMAIL", "tiamat.entity.prime@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "tiamat.live")
TIAMAT_EMAIL = os.environ.get("TIAMAT_LIVE_EMAIL", "tiamat@tiamat.live")
GRANTS_EMAIL_ADDR = os.environ.get("GRANTS_EMAIL", "grants@tiamat.live")


def _decode_header(value):
    """Decode RFC 2047 encoded header."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_body(msg):
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def read_inbox(count=10, unread_only=False):
    """Read recent emails from TIAMAT's Gmail inbox.

    Args:
        count: Number of recent emails to fetch (default 10)
        unread_only: If True, only fetch unread messages

    Returns:
        List of dicts with: from, subject, date, body (truncated), id
    """
    if not GMAIL_APP_PASSWORD:
        return {"error": "GMAIL_APP_PASSWORD not set"}

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        imap.select("INBOX")

        criterion = "UNSEEN" if unread_only else "ALL"
        status, data = imap.search(None, criterion)
        if status != "OK" or not data[0]:
            imap.logout()
            return []

        ids = data[0].split()
        fetch_ids = ids[-count:]  # most recent N

        results = []
        for mid in reversed(fetch_ids):  # newest first
            status, msg_data = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            body = _get_body(msg)
            results.append({
                "id": mid.decode(),
                "from": _decode_header(msg["From"]),
                "subject": _decode_header(msg["Subject"]),
                "date": msg["Date"],
                "body": body[:500] if body else "",
            })

        imap.logout()
        return results
    except Exception as e:
        return {"error": str(e)}


def search_inbox(query, count=10):
    """Search TIAMAT's Gmail inbox.

    Args:
        query: IMAP search query (e.g., 'FROM "claude"', 'SUBJECT "verify"')
        count: Max results

    Returns:
        List of email dicts
    """
    if not GMAIL_APP_PASSWORD:
        return {"error": "GMAIL_APP_PASSWORD not set"}

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        imap.select("INBOX")

        status, data = imap.search(None, query)
        if status != "OK" or not data[0]:
            imap.logout()
            return []

        ids = data[0].split()[-count:]
        results = []
        for mid in reversed(ids):
            status, msg_data = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            body = _get_body(msg)
            results.append({
                "id": mid.decode(),
                "from": _decode_header(msg["From"]),
                "subject": _decode_header(msg["Subject"]),
                "date": msg["Date"],
                "body": body[:1000] if body else "",
            })

        imap.logout()
        return results
    except Exception as e:
        return {"error": str(e)}


JASON_EMAIL = "jacl33t@gmail.com"

SIGNATURE = """
---
TIAMAT Autonomous Intelligence System
ENERGENAI LLC | UEI: LBZFEH87W746 | SAM: Active
Patent Pending: 63/749,552 (7G Wireless Power Mesh)
https://tiamat.live | tiamat@tiamat.live
"""


def send_email(to, subject, body, from_name="TIAMAT | ENERGENAI LLC", html_body=None):
    """Send email via Mailgun HTTP API from tiamat@tiamat.live.

    Auto-CCs grants@tiamat.live for .mil and .gov recipients.
    Appends ENERGENAI LLC signature.
    """
    if not MAILGUN_API_KEY:
        return {"error": "MAILGUN_API_KEY not set"}

    full_body = body + SIGNATURE

    # Build multipart form data for Mailgun
    import io
    boundary = "----TiamatMailgunBoundary"
    parts = []

    def add_field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}")

    add_field("from", f"{from_name} <{TIAMAT_EMAIL}>")
    add_field("to", to)
    add_field("subject", subject)
    add_field("text", full_body)
    if html_body:
        add_field("html", html_body)
    if ".mil" in to or ".gov" in to:
        add_field("cc", GRANTS_EMAIL_ADDR)

    body_str = "\r\n".join(parts) + f"\r\n--{boundary}--\r\n"
    body_bytes = body_str.encode("utf-8")

    auth = base64.b64encode(f"api:{MAILGUN_API_KEY}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
        data=body_bytes,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return {"status": "sent", "code": resp.status}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        return {"error": f"Mailgun {e.code}: {error_body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _tiamat_html_wrap(body_text):
    """Wrap plain text in TIAMAT-branded HTML."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return f"""<html>
<body style="font-family: monospace; background: #0a0a0a; color: #00ff88; padding: 20px;">
<h2 style="color: #00ff88;">TIAMAT — EnergenAI LLC Alert</h2>
<hr style="border-color: #00ff88;">
<pre style="white-space: pre-wrap; color: #cccccc;">{body_text}</pre>
<hr style="border-color: #00ff88;">
<p style="color: #666; font-size: 12px;">
Sent autonomously by TIAMAT | {ts} | tiamat.live
</p>
</body>
</html>"""


def send_grant_alert(agency, program, title, deadline, award_amount,
                     fit_score, summary, solicitation_url="", action_required=""):
    """Send formatted grant opportunity alert to Jason."""
    subject = f"SBIR Alert [{fit_score}/10 fit] -- {agency} {program}: {title}"

    body = f"""GRANT OPPORTUNITY FOUND
{'='*60}

Agency:          {agency}
Program:         {program}
Title:           {title}
Deadline:        {deadline}
Award Amount:    {award_amount}
Fit Score:       {fit_score}/10
Solicitation:    {solicitation_url or 'See sam.gov'}

SUMMARY
{'-'*60}
{summary}

ACTION REQUIRED FROM JASON
{'-'*60}
{action_required or 'Review this opportunity and decide whether to pursue. I can begin drafting the narrative once you confirm via INBOX.md.'}

ENERGENAI LLC MATCH
{'-'*60}
UEI: LBZFEH87W746
NAICS: 541715, 237130
Patent: 63/749,552
Project: Ringbound (7G wireless power mesh)

{'='*60}
Reply to this email or write to INBOX.md to instruct me.
-- TIAMAT
"""
    return send_email(JASON_EMAIL, subject, body, html_body=_tiamat_html_wrap(body))


def send_research_alert(title, authors, venue, relevance, url=""):
    """Send research paper alert to Jason."""
    subject = f"Research Alert -- {title[:80]}"

    body = f"""RESEARCH PAPER OF INTEREST
{'='*60}

Title:    {title}
Authors:  {authors}
Venue:    {venue}
URL:      {url or 'N/A'}

RELEVANCE TO ENERGENAI
{'-'*60}
{relevance}

{'='*60}
-- TIAMAT
"""
    return send_email(JASON_EMAIL, subject, body, html_body=_tiamat_html_wrap(body))


def send_action_required(subject_line, details, urgency="normal"):
    """Send general action-required alert to Jason."""
    urgency_marker = "URGENT" if urgency == "high" else "ACTION NEEDED"
    subject = f"{urgency_marker} -- {subject_line}"

    body = f"""{urgency_marker}
{'='*60}

{details}

{'='*60}
Reply or write to INBOX.md to instruct me.
-- TIAMAT
"""
    return send_email(JASON_EMAIL, subject, body, html_body=_tiamat_html_wrap(body))


# CLI interface
if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "inbox"

    if action == "inbox":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        results = read_inbox(count=count)
        print(json.dumps(results, indent=2, default=str))

    elif action == "unread":
        results = read_inbox(unread_only=True)
        print(json.dumps(results, indent=2, default=str))

    elif action == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else 'ALL'
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        results = search_inbox(query, count=count)
        print(json.dumps(results, indent=2, default=str))

    elif action == "send":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: email_tool.py send <to> <subject> <body>"}))
            sys.exit(1)
        result = send_email(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps(result, indent=2))

    elif action == "grant_alert":
        # Args passed as JSON on stdin
        data = json.loads(sys.stdin.read())
        result = send_grant_alert(**data)
        print(json.dumps(result, indent=2, default=str))

    elif action == "research_alert":
        data = json.loads(sys.stdin.read())
        result = send_research_alert(**data)
        print(json.dumps(result, indent=2, default=str))

    elif action == "action_required":
        data = json.loads(sys.stdin.read())
        result = send_action_required(**data)
        print(json.dumps(result, indent=2, default=str))

    else:
        print(json.dumps({"error": f"Unknown action: {action}. Use: inbox, unread, search, send, grant_alert, research_alert, action_required"}))
