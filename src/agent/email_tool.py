"""
TIAMAT Email Tool — Read (IMAP) + Send (SendGrid HTTP API)
DigitalOcean blocks outbound SMTP (465/587), so we use SendGrid over HTTPS for sending.
IMAP port 993 is open for reading.
"""
import os
import json
import imaplib
import email
from email.header import decode_header
import urllib.request
import urllib.error

GMAIL_USER = os.environ.get("TIAMAT_EMAIL", "tiamat.entity.prime@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")


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


def send_email(to, subject, body, from_name="TIAMAT"):
    """Send email via SendGrid HTTP API.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Plain text body
        from_name: Sender display name

    Returns:
        Dict with status
    """
    if not SENDGRID_API_KEY:
        return {"error": "SENDGRID_API_KEY not set"}

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": GMAIL_USER, "name": from_name},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return {"status": "sent", "code": resp.status}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        return {"error": f"SendGrid {e.code}: {error_body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


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

    else:
        print(json.dumps({"error": f"Unknown action: {action}. Use: inbox, unread, search, send"}))
