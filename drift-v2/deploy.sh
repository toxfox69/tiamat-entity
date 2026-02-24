#!/bin/bash
set -e

echo "🚀 Deploying TIAMAT Drift v2..."

cd /root/.automaton/drift-v2/backend

# 1. Create venv if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# 3. Kill old process if running
pkill -f "gunicorn drift_v2_api" || true

# 4. Start API server (background)
echo "Starting Drift v2 API on port 5001..."
nohup ./venv/bin/gunicorn drift_v2_api:app -b 0.0.0.0:5001 --workers 4 --timeout 60 > /tmp/drift_v2.log 2>&1 &

echo "✅ Drift v2 API started (PID: $!)"
echo "📊 Logs: tail -f /tmp/drift_v2.log"
echo ""

# 5. Wait for server to start
sleep 3

# 6. Test endpoint
echo "Testing API..."
curl -s http://localhost:5001/api/drift/status | head -n 5

echo ""
echo "🎯 SDK Installation:"
echo "   cd /root/.automaton/drift-v2/sdk"
echo "   pip install -e ."
echo ""
echo "✨ Drift v2 backend is LIVE on port 5001"
