#!/bin/bash
# TIAMAT Health Monitor — runs via cron every 5 minutes
# Pings all production endpoints, alerts on failure

LOG="/root/.automaton/healthcheck.log"
ALERT_COOLDOWN="/tmp/tiamat_alert_cooldown"
COOLDOWN_MINUTES=30

ENDPOINTS=(
  "/ Landing"
  "/company Company"
  "/apps Apps"
  "/thoughts Thoughts"
  "/docs Docs"
  "/pay Payment"
  "/status Status"
  "/proof Proof"
  "/summarize Summarize"
  "/generate Generate"
  "/chat Chat"
  "/synthesize Synthesize"
  "/dashboard Dashboard"
  "/.well-known/agent.json A2A"
  "/.well-known/x402 x402"
  "/api/v1/services Services"
  "/api/thoughts ThoughtsAPI"
  "/api/gallery Gallery"
  "/cycle-tracker CycleTracker"
  "/bloom Bloom"
  "/api/body Body"
)

NOW=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
FAILURES=""
FAIL_COUNT=0

for entry in "${ENDPOINTS[@]}"; do
  path=$(echo "$entry" | awk '{print $1}')
  name=$(echo "$entry" | awk '{print $2}')
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:5000${path}" 2>/dev/null)

  if [ "$code" != "200" ] && [ "$code" != "302" ]; then
    FAILURES="${FAILURES}  ${name} (${path}): HTTP ${code}\n"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

# Check TIAMAT process
if ! kill -0 $(cat /tmp/tiamat.pid 2>/dev/null) 2>/dev/null; then
  FAILURES="${FAILURES}  TIAMAT PROCESS: DOWN\n"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# Check gunicorn
if ! pgrep -f "gunicorn.*summarize" >/dev/null 2>&1; then
  FAILURES="${FAILURES}  GUNICORN: DOWN\n"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# Check immutable flag on summarize_api.py
if ! lsattr /root/summarize_api.py 2>/dev/null | grep -q 'i'; then
  FAILURES="${FAILURES}  summarize_api.py: IMMUTABLE FLAG REMOVED!\n"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# Log result
if [ $FAIL_COUNT -gt 0 ]; then
  echo "[$NOW] FAIL ($FAIL_COUNT issues)" >> "$LOG"
  echo -e "$FAILURES" >> "$LOG"

  # Alert (with cooldown to avoid spam)
  if [ -f "$ALERT_COOLDOWN" ]; then
    LAST=$(cat "$ALERT_COOLDOWN")
    DIFF=$(( $(date +%s) - LAST ))
    if [ $DIFF -lt $((COOLDOWN_MINUTES * 60)) ]; then
      exit 0  # Still in cooldown
    fi
  fi

  date +%s > "$ALERT_COOLDOWN"

  # Send alert via SendGrid
  SUBJECT="TIAMAT ALERT: ${FAIL_COUNT} endpoint(s) DOWN"
  BODY="Health check failed at ${NOW}\n\nFailing endpoints:\n${FAILURES}\nCheck: ssh root@159.89.38.17\nLog: /root/.automaton/healthcheck.log"

  python3 -c "
import os, json, requests
sg_key = os.getenv('SENDGRID_API_KEY', '')
if not sg_key:
    try:
        with open('/root/.env') as f:
            for line in f:
                if line.startswith('SENDGRID_API_KEY='):
                    sg_key = line.strip().split('=',1)[1].strip('\"').strip(\"'\")
    except: pass
if not sg_key:
    print('No SendGrid key')
    exit(1)
requests.post('https://api.sendgrid.com/v3/mail/send',
    headers={'Authorization': f'Bearer {sg_key}', 'Content-Type': 'application/json'},
    json={
        'personalizations': [{'to': [{'email': 'tiamat.entity.prime@gmail.com'}]}],
        'from': {'email': 'tiamat@tiamat.live', 'name': 'TIAMAT Health Monitor'},
        'subject': '''${SUBJECT}''',
        'content': [{'type': 'text/plain', 'value': '''$(echo -e "$BODY")'''}]
    })
print('Alert sent')
" 2>/dev/null

  # Also send Telegram if bot token exists
  TG_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' /root/.env 2>/dev/null | cut -d= -f2 | tr -d '"'"'")
  TG_CHAT=$(grep '^TELEGRAM_CHAT_ID=' /root/.env 2>/dev/null | cut -d= -f2 | tr -d '"'"'")
  if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d chat_id="${TG_CHAT}" \
      -d text="🚨 TIAMAT ALERT: ${FAIL_COUNT} endpoint(s) DOWN
$(echo -e "$FAILURES")" >/dev/null 2>&1
  fi

else
  echo "[$NOW] OK — all ${#ENDPOINTS[@]} endpoints healthy" >> "$LOG"
fi
