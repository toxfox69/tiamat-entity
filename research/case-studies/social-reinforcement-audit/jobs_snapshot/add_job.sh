#!/bin/bash
# Add a job to TIAMAT's queue from the command line
# Usage: bash add_job.sh "title" "description" "deadline" priority
TITLE="$1"
DESC="$2"
DEADLINE="$3"
PRIORITY="${4:-5}"
ID=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-')
cat > /root/.automaton/jobs/active/${PRIORITY}-${ID}.json << EOF
{
  "id": "$ID",
  "title": "$TITLE",
  "priority": $PRIORITY,
  "type": "any",
  "deadline": "$DEADLINE",
  "description": "$DESC",
  "deliverable": "",
  "tools_needed": [],
  "status": "active",
  "source": "oracle",
  "created": "$(date -u +%Y-%m-%d)",
  "progress_notes": [],
  "blocked_reason": null,
  "parent": null
}
EOF
echo "Job added: ${PRIORITY}-${ID}.json"
