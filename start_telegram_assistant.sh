#!/bin/bash
# Start TIAMAT Telegram Assistant

cd /root/.automaton

# Check if already running
if pgrep -f "telegram_assistant.py" > /dev/null; then
    echo "Telegram assistant already running"
    exit 0
fi

# Install dependencies if needed
pip install -q python-telegram-bot requests 2>/dev/null

# Start in background
nohup python3 /root/.automaton/telegram_assistant.py > /root/.automaton/telegram_assistant.log 2>&1 &

PID=$!
echo $PID > /tmp/telegram_assistant.pid

echo "Telegram assistant started (PID: $PID)"
