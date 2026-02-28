import json
import os
from datetime import datetime, timedelta
import re

PARTNERSHIPS_FILE = '/root/.automaton/partnerships.json'

def load_partnerships():
    """Load partnership tracking data."""
    if os.path.exists(PARTNERSHIPS_FILE):
        with open(PARTNERSHIPS_FILE, 'r') as f:
            return json.load(f)
    return {"outreach": []}

def save_partnerships(data):
    """Save partnership tracking data."""
    with open(PARTNERSHIPS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def track_outreach(recipient_email: str, subject: str, sent_date: str = None, window_days: int = 5):
    """Track a new outreach email.
    
    Args:
        recipient_email: Email address contacted
        subject: Email subject line
        sent_date: ISO date sent (default: today)
        window_days: Expected reply window in days
    
    Returns:
        dict with status and record ID
    """
    if not sent_date:
        sent_date = datetime.utcnow().isoformat()[:10]
    
    data = load_partnerships()
    expected_reply = (datetime.fromisoformat(sent_date) + timedelta(days=window_days)).isoformat()[:10]
    
    record = {
        "id": len(data["outreach"]) + 1,
        "recipient": recipient_email,
        "subject": subject,
        "sent_date": sent_date,
        "expected_reply_by": expected_reply,
        "status": "waiting",
        "replied_date": None,
        "notes": ""
    }
    
    data["outreach"].append(record)
    save_partnerships(data)
    
    return {"status": "tracked", "id": record["id"], "recipient": recipient_email}

def check_replies(emails: list):
    """Check inbox for replies to tracked outreach.
    
    Args:
        emails: List of email dicts from read_email() with 'from' and 'subject' fields
    
    Returns:
        dict with matched replies
    """
    data = load_partnerships()
    matched = []
    
    # Extract domain from tracked emails
    tracked_domains = {}
    for record in data["outreach"]:
        if record["status"] == "waiting":
            domain = record["recipient"].split('@')[1]
            tracked_domains[domain] = record["id"]
    
    # Match incoming emails
    for email in emails:
        sender_domain = email.get("from", "").split('@')[1] if '@' in email.get("from", "") else None
        
        if sender_domain and sender_domain in tracked_domains:
            record_id = tracked_domains[sender_domain]
            # Mark as replied
            for record in data["outreach"]:
                if record["id"] == record_id:
                    record["status"] = "replied"
                    record["replied_date"] = datetime.utcnow().isoformat()[:10]
                    matched.append({
                        "tracked_id": record_id,
                        "from": email["from"],
                        "subject": email.get("subject", "(no subject)")
                    })
                    break
    
    if matched:
        save_partnerships(data)
    
    return matched

def get_partnership_status():
    """Return summary of all tracked partnerships.
    
    Returns:
        dict with {total_sent, waiting_reply, replied, overdue, summary}
    """
    data = load_partnerships()
    today = datetime.utcnow().date()
    
    total = len(data["outreach"])
    waiting = sum(1 for r in data["outreach"] if r["status"] == "waiting")
    replied = sum(1 for r in data["outreach"] if r["status"] == "replied")
    overdue = sum(1 for r in data["outreach"] 
                  if r["status"] == "waiting" and 
                  datetime.fromisoformat(r["expected_reply_by"]).date() < today)
    
    pending = []
    for r in data["outreach"]:
        if r["status"] == "waiting":
            days_left = (datetime.fromisoformat(r["expected_reply_by"]).date() - today).days
            pending.append({
                "recipient": r["recipient"],
                "subject": r["subject"],
                "days_left": days_left
            })
    
    return {
        "total_sent": total,
        "waiting_reply": waiting,
        "replied": replied,
        "overdue": overdue,
        "pending_list": pending,
        "summary": f"{waiting} waiting ({overdue} overdue), {replied} replies received"
    }
