"""
TIAMAT Federal Email Tool — Send from tiamat@tiamat.live via Mailgun HTTP API.
Read from tiamat@tiamat.live via IMAP (Namecheap Private Email).

DigitalOcean blocks SMTP ports 465/587, so all SENDING goes through Mailgun HTTPS.
IMAP port 993 is open for reading incoming mail.
"""
import os
import sys
import json
import imaplib
import email
from email.header import decode_header
import urllib.request
import urllib.error
import base64
from datetime import datetime, timezone

# Mailgun for sending
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "tiamat.live")

# tiamat.live mailboxes
TIAMAT_EMAIL = os.environ.get("TIAMAT_LIVE_EMAIL", "tiamat@tiamat.live")
TIAMAT_PASSWORD = os.environ.get("TIAMAT_LIVE_PASSWORD", "")
GRANTS_EMAIL = os.environ.get("GRANTS_EMAIL", "grants@tiamat.live")
JASON_EMAIL = os.environ.get("JASON_EMAIL", "jason@tiamat.live")
IMAP_HOST = os.environ.get("EMAIL_IMAP_HOST", "mail.privateemail.com")

EMAIL_LOG = "/root/.automaton/grants/EMAIL_LOG.md"

SIGNATURE = """
---
TIAMAT Autonomous Intelligence System
ENERGENAI LLC | UEI: LBZFEH87W746 | SAM: Active
Patent Pending: 63/749,552 (7G Wireless Power Mesh)
https://tiamat.live | tiamat@tiamat.live
"""


def send_email(to, subject, body, from_addr=None, from_name="TIAMAT | ENERGENAI LLC",
               cc=None, reply_to=None, append_signature=True):
    """Send email via SendGrid HTTP API from tiamat@tiamat.live.

    Auto-CCs grants@tiamat.live for any .mil or .gov recipients.
    Logs every sent email to EMAIL_LOG.md.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Plain text body
        from_addr: Sender email (default: tiamat@tiamat.live)
        from_name: Sender display name
        cc: CC address (auto-set for .mil/.gov)
        reply_to: Reply-to address
        append_signature: Whether to append the ENERGENAI signature
    """
    if not MAILGUN_API_KEY:
        return {"success": False, "error": "MAILGUN_API_KEY not set"}

    from_addr = from_addr or TIAMAT_EMAIL
    full_body = body + SIGNATURE if append_signature else body

    # Auto-CC grants inbox for federal contacts
    if not cc and (".mil" in to or ".gov" in to):
        cc = GRANTS_EMAIL

    # Build multipart form data for Mailgun
    boundary = "----TiamatMailgunBoundary"
    parts = []

    def add_field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}")

    add_field("from", f"{from_name} <{from_addr}>")
    add_field("to", to)
    add_field("subject", subject)
    add_field("text", full_body)
    if cc:
        add_field("cc", cc)
    if reply_to:
        add_field("h:Reply-To", reply_to)

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
        resp = urllib.request.urlopen(req, timeout=15)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        log_entry = f"| {ts} | {to} | {subject} | {cc or '-'} | sent |\n"

        os.makedirs(os.path.dirname(EMAIL_LOG), exist_ok=True)
        if not os.path.exists(EMAIL_LOG):
            with open(EMAIL_LOG, "w") as f:
                f.write("# TIAMAT Email Log\n\n")
                f.write("| Timestamp | To | Subject | CC | Status |\n")
                f.write("|-----------|----|---------|----|--------|\n")

        with open(EMAIL_LOG, "a") as f:
            f.write(log_entry)

        return {"success": True, "to": to, "subject": subject, "cc": cc, "code": resp.status}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        return {"success": False, "error": f"Mailgun {e.code}: {error_body[:300]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _decode_header_value(value):
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


def read_inbox(mailbox="tiamat", count=10, unread_only=False):
    """Read recent emails from a tiamat.live mailbox via IMAP.

    Args:
        mailbox: "tiamat" for tiamat@tiamat.live, "grants" for grants@tiamat.live
        count: Number of recent emails to fetch
        unread_only: If True, only fetch unread messages
    """
    if mailbox == "grants":
        user = GRANTS_EMAIL
        password = os.environ.get("GRANTS_PASSWORD", "")
    else:
        user = TIAMAT_EMAIL
        password = TIAMAT_PASSWORD

    if not password:
        return {"error": f"Password not set for {user}"}

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST)
        imap.login(user, password)
        imap.select("INBOX")

        criterion = "UNSEEN" if unread_only else "ALL"
        status, data = imap.search(None, criterion)
        if status != "OK" or not data[0]:
            imap.logout()
            return []

        ids = data[0].split()
        fetch_ids = ids[-count:]

        results = []
        for mid in reversed(fetch_ids):
            status, msg_data = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            body = _get_body(msg)
            results.append({
                "id": mid.decode(),
                "from": _decode_header_value(msg["From"]),
                "to": _decode_header_value(msg["To"]),
                "subject": _decode_header_value(msg["Subject"]),
                "date": msg["Date"],
                "body": body[:500] if body else "",
            })

        imap.logout()
        return results
    except Exception as e:
        return {"error": str(e)}


def send_ussocom_email(draft_path="/root/.automaton/grants/USSOCOM_EMAIL_DRAFT.md"):
    """Send the USSOCOM capability briefing from the prepared draft."""
    try:
        with open(draft_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return {"success": False, "error": f"Draft not found: {draft_path}"}

    # Extract subject and body from the draft
    subject = "ENERGENAI LLC — Agentic AI Capability Briefing | RFI USSOCOM_RFI_TE_26-2"
    body = content

    return send_email(
        to="techexp@socom.mil",
        subject=subject,
        body=body,
        cc=GRANTS_EMAIL,
    )


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/root/.env")

    # Re-read env after loading
    globals().update({
        "MAILGUN_API_KEY": os.environ.get("MAILGUN_API_KEY", ""),
        "MAILGUN_DOMAIN": os.environ.get("MAILGUN_DOMAIN", "tiamat.live"),
        "TIAMAT_EMAIL": os.environ.get("TIAMAT_LIVE_EMAIL", "tiamat@tiamat.live"),
        "TIAMAT_PASSWORD": os.environ.get("TIAMAT_LIVE_PASSWORD", ""),
        "GRANTS_EMAIL": os.environ.get("GRANTS_EMAIL", "grants@tiamat.live"),
        "JASON_EMAIL": os.environ.get("JASON_EMAIL", "jason@tiamat.live"),
        "IMAP_HOST": os.environ.get("EMAIL_IMAP_HOST", "mail.privateemail.com"),
    })

    action = sys.argv[1] if len(sys.argv) > 1 else "test"

    if action == "test":
        print("Testing send from tiamat@tiamat.live...")
        result = send_email(
            to=os.environ.get("JASON_EMAIL", "jason@tiamat.live"),
            subject="TIAMAT Email System — Operational Test",
            body="Email infrastructure confirmed operational.\n\nThis message was sent from tiamat@tiamat.live via Mailgun HTTP API.",
        )
        print(json.dumps(result, indent=2))

    elif action == "inbox":
        mailbox = sys.argv[2] if len(sys.argv) > 2 else "tiamat"
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        results = read_inbox(mailbox=mailbox, count=count)
        print(json.dumps(results, indent=2, default=str))

    elif action == "send":
        if len(sys.argv) < 5:
            print("Usage: send_email.py send <to> <subject> <body>")
            sys.exit(1)
        result = send_email(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps(result, indent=2))

    elif action == "ussocom":
        result = send_ussocom_email()
        print(json.dumps(result, indent=2))

    else:
        print(f"Usage: send_email.py [test|inbox|send|ussocom]")
