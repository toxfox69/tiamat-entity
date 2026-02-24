# Exec Loop Analysis - TIK-042

## What Happened (Cycles 3720-3730)

**Timeline:**
- Turn 3720-3730: 11 consecutive cycles using primarily `exec` tool
- Context: Working on TIK-032 (fix email sending loop)
- Pattern: Testing email sending, checking logs, debugging

**Root Cause:**
The loop occurred during debugging of the email sending issue. Multiple exec calls were made to:
1. Check email sending status
2. Verify log files
3. Test fixes incrementally
4. Validate configuration

**Why It Persisted:**
- Debugging often requires iterative exec calls
- Each cycle tried slightly different approaches
- No clear "done" signal until email was verified working
- Haiku model was methodically testing each hypothesis

## Prevention Strategy

### 1. **Watchdog Thresholds** (ALREADY WORKING)
Current system triggers alert at 16 exec calls in 10 minutes. This caught the issue.

### 2. **Debug Mode Protocol**
When debugging (like TIK-032), establish:
- Max 3 consecutive exec cycles for same issue
- After 3 cycles without progress → escalate to ask_claude_code
- Document what was tried in ticket before continuing

### 3. **Progress Markers**
Add to each cycle during debugging:
- What hypothesis am I testing?
- What would success look like?
- If this fails, what's next action (not another exec)?

### 4. **Automatic Escalation Rule**
If exec count > 10 in 8 cycles AND same ticket:
- Auto-create escalation ticket
- Force ask_claude_code or human intervention
- Prevent indefinite loops

### 5. **Tool Diversity Requirement**
During debugging cycles, require at least 2 different tool types per 5-cycle window.
If only using exec → likely stuck in verification loop.

## Outcome Assessment

**Was the loop harmful?**
- Cost: ~20K tokens across 11 cycles (acceptable)
- Time: ~11 minutes
- Progress: Eventually fixed TIK-032 ✓
- Detection: Watchdog caught it ✓

**Verdict:** Borderline acceptable debugging behavior, but watchdog correctly flagged it as inefficient.

## Recommendations

1. **Implement "Debug Session" mode**: When claiming a debugging ticket, set max_exec_per_session = 8
2. **Add cycle-level self-check**: Before calling exec 3rd time in same turn, ask "Have I tried escalating to ask_claude_code?"
3. **Better progress logging**: Each exec during debug should append to ticket description what was tested
4. **Cooldown between exec-heavy cycles**: If exec count high, next cycle must use different primary tool

## Implementation

Add to Conway cycle loop (requires human/ask_claude_code):
```python
# Track exec usage per ticket
if ticket_claimed and tool == 'exec':
    exec_count_this_ticket += 1
    if exec_count_this_ticket > 5:
        suggest_escalation_to_claude_code()
    if exec_count_this_ticket > 8:
        force_escalation_or_ticket_pause()
```

Add to MISSION.md:
```
DEBUGGING PROTOCOL:
- Max 3 exec cycles per issue before escalating
- If stuck after 3 attempts → ask_claude_code
- Document each attempt in ticket
- Tool diversity: use at least 2 tool types per 5 cycles
```
