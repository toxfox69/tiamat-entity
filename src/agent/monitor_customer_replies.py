#!/usr/bin/env python3
"""Monitor email for customer acquisition responses (TIK-277).
Runs as a cooldown task between cycles.
Flags any positive interest in API integration or pricing discussion.
"""
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta

KEYWORD_POSITIVE = ['interest', 'integration', 'api key', 'pricing', 'demo', 'trial', 'pricing', 'collaborate', 'partner']
KEYWORD_NEGATIVE = ['unsubscribe', 'remove', 'spam', 'not interested']

def check_inbox(mailbox_name='tiamat'):
    """Check for new emails matching TIK-277 outreach targets."""
    try:
        # Email credentials from env (already set by TIAMAT)
        import os
        email_addr = os.getenv('TIAMAT_LIVE_EMAIL')
        password = os.getenv('TIAMAT_LIVE_PASSWORD')
        
        imap = imaplib.IMAP4_SSL('mail.privateemail.com', 993)
        imap.login(email_addr, password)
        imap.select('INBOX')
        
        # Search for emails from last 48h
        status, msg_ids = imap.search(None, 'SINCE', (datetime.now() - timedelta(hours=48)).strftime('%d-%b-%Y'))
        
        if status != 'OK' or not msg_ids[0]:
            print(f'[{datetime.now().isoformat()}] No new emails in last 48h')
            imap.close()
            return
        
        results = []
        for msg_id in msg_ids[0].split():
            status, msg_data = imap.fetch(msg_id, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])
            
            subject = decode_header(msg['Subject'])[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            
            sender = msg['From']
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore') if msg.is_multipart() else msg.get_payload()
            
            # Check for TIK-277 targets (Langchain, AgentKit, MetaGPT senders)
            relevant_senders = ['builds@langchain.com', 'hello@agentkit.so', 'geekan@metateam.cc', 'support@langchain.dev', 'team@agentkit.ai', 'sh@shawwn.com']
            
            if any(target.lower() in sender.lower() for target in relevant_senders):
                # Check sentiment
                body_lower = body.lower()
                has_positive = any(kw in body_lower for kw in KEYWORD_POSITIVE)
                has_negative = any(kw in body_lower for kw in KEYWORD_NEGATIVE)
                
                if has_positive and not has_negative:
                    results.append({
                        'from': sender,
                        'subject': subject,
                        'time': msg['Date'],
                        'positive': True,
                        'preview': body[:200]
                    })
        
        imap.close()
        
        if results:
            print(f'\n🎯 CUSTOMER RESPONSE DETECTED (TIK-277):')
            for r in results:
                print(f"  From: {r['from']}")
                print(f"  Subject: {r['subject']}")
                print(f"  Time: {r['time']}")
                print(f"  Preview: {r['preview'][:100]}...")
                print()
        else:
            print(f'[{datetime.now().isoformat()}] No positive responses yet')
    
    except Exception as e:
        print(f'Error checking inbox: {e}')

if __name__ == '__main__':
    check_inbox()
