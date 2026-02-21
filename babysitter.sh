#!/bin/bash
LOG=/root/.automaton/babysitter.log
TIAMAT_LOG=/root/.automaton/tiamat.log
PROGRESS=/root/.automaton/PROGRESS.md
CHECK_NUM=0
LAST_REPORT=0

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >&2; }

restart_api() {
  log "ACTION: Restarting gunicorn..."
  pkill gunicorn 2>/dev/null; sleep 2
  cd /root && ANTHROPIC_API_KEY=$(python3 -c "import json; print(json.load(open('/root/.automaton/automaton.json'))['anthropicApiKey'])") \
    nohup /root/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --log-file /root/api.log summarize_api:app >> /root/api.log 2>&1 &
  sleep 3
  log "ACTION: Gunicorn restarted, health=$(curl -s http://localhost:5000/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("status","?"))' 2>/dev/null)"
}

check_stuck() {
  # Get last 6 tool calls from log
  local tools=$(grep '\[TOOL\]' "$TIAMAT_LOG" | tail -6 | awk -F'[TOOL] ' '{print $2}' | awk -F'(' '{print $1}')
  local uniq=$(echo "$tools" | sort -u | wc -l)
  local total=$(echo "$tools" | wc -l)
  if [ "$total" -ge 6 ] && [ "$uniq" -le 2 ]; then
    log "WARN: Possible loop — $total recent calls, only $uniq unique tools: $(echo $tools | tr '\n' ' ')"
    return 1
  fi
  return 0
}

check_token_burn() {
  # Sum tokens from last 5 PROGRESS entries
  local tokens=$(grep 'Tokens:' "$PROGRESS" | tail -5 | grep -o 'Tokens: [0-9]*' | awk '{sum+=$2} END{print sum}')
  echo "${tokens:-0}"
}

write_report() {
  local last3=$(grep 'Tokens:' "$PROGRESS" | tail -3)
  local burn=$(check_token_burn)
  local api_health=$(curl -s http://localhost:5000/health 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("status","DOWN"))' 2>/dev/null || echo "DOWN")
  local last_thought=$(grep '\[THOUGHT\]' "$TIAMAT_LOG" | tail -1 | cut -c28-)
  local turn=$(grep 'Tokens:' "$PROGRESS" | tail -1 | grep -o 'Turn [0-9]*')
  log "=== 30-MIN REPORT ==="
  log "Turn: $turn | API: $api_health | Token burn (last 5 turns): $burn"
  log "Last thought: ${last_thought:0:150}"
  log "Last 3 actions:"
  echo "$last3" | while read line; do log "  $line"; done
  log "=== END REPORT ==="
  echo "--- babysitter.log as of $(date -u) ---"
  cat "$LOG"
  echo "---"
}

log "=== BABYSITTER STARTED === TIAMAT PID=$(pgrep -f 'node /root/entity/dist/index.js' | head -1)"

while true; do
  CHECK_NUM=$((CHECK_NUM + 1))
  NOW=$(date +%s)

  # ── API health ──
  HEALTH=$(curl -s --max-time 5 http://localhost:5000/health 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("status","?"))' 2>/dev/null || echo "DOWN")
  if [ "$HEALTH" = "DOWN" ]; then
    log "ALERT: API is DOWN — restarting"
    restart_api
  fi

  # ── TIAMAT process alive ──
  TPID=$(pgrep -f 'node /root/entity/dist/index.js' | head -1)
  if [ -z "$TPID" ]; then
    log "ALERT: TIAMAT process dead! Restarting..."
    source /root/.env && nohup node /root/entity/dist/index.js --run >> "$TIAMAT_LOG" 2>&1 &
    log "ACTION: Restarted TIAMAT PID=$!"
  fi

  # ── Stuck detection ──
  check_stuck

  # ── Token burn check ──
  BURN=$(check_token_burn)
  if [ "$BURN" -gt 75000 ] 2>/dev/null; then
    log "WARN: High token burn in last 5 turns: $BURN tokens"
  fi

  # ── ask_claude_code failure streak ──
  FAILURES=$(grep 'ask_claude_code.*nested session\|ask_claude_code.*ERROR' "$TIAMAT_LOG" | tail -10 | wc -l)
  if [ "$FAILURES" -ge 3 ]; then
    log "WARN: ask_claude_code failing repeatedly ($FAILURES recent failures) — may need env fix"
  fi

  # ── USDC spend check ──
  USDC_SPEND=$(grep 'x402_fetch\|spend.*usdc\|pay.*agent' "$TIAMAT_LOG" | tail -5 | wc -l)
  if [ "$USDC_SPEND" -gt 0 ]; then
    log "ALERT: Possible unauthorized USDC spend detected — check logs"
  fi

  # ── 30-min report ──
  MINS_ELAPSED=$(( (NOW - LAST_REPORT) / 60 ))
  if [ "$LAST_REPORT" -eq 0 ] || [ "$MINS_ELAPSED" -ge 30 ]; then
    write_report
    LAST_REPORT=$NOW
  fi

  log "CHECK #$CHECK_NUM OK — API:$HEALTH TPID:${TPID:-dead} burn5:${BURN}tok"
  sleep 300
done
