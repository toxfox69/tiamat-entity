# TIAMAT Subagent Design: Child Agent Spawning & Orchestration

Design doc for adding subagent (child agent) capabilities to TIAMAT,
adapted from OpenClaw's `subagents-tool.ts` patterns.

## Why Subagents?

TIAMAT currently runs as a single agent loop (loop.ts) — one cycle at a
time, one context window. This limits her to sequential work. Subagents
let the main loop delegate parallel tasks to child agents, each with
their own context window and lifecycle.

Use cases:
- **Parallel research**: spawn 3 subagents to research different topics simultaneously
- **Build + verify**: one subagent writes code while another reviews/tests
- **Long-running tasks**: delegate a slow task (backfill embeddings, audit APIs) without blocking the main loop
- **Specialized roles**: a "marketer" subagent for social posts, a "builder" subagent for code generation

## OpenClaw Architecture (Source of Truth)

OpenClaw's subagent system has these components:

### Core Concepts

1. **Session keys**: Each agent (parent or child) has a unique session key. Subagent keys encode their parent lineage, enabling tree traversal.
   - Main agent: `agent:main`
   - Child: `agent:main:sub-abc123`
   - Grandchild: `agent:main:sub-abc123:sub-def456`

2. **Run records** (`SubagentRunRecord`): Track each subagent invocation:
   - `runId` — unique ID
   - `childSessionKey` — the subagent's session key
   - `task` — description of what it's doing
   - `model` — which model it uses
   - `startedAt` / `endedAt` — lifecycle timestamps
   - `outcome` — `{status: "ok" | "error", result?: string}`
   - `runTimeoutSeconds` — max execution time

3. **Depth limits**: `DEFAULT_SUBAGENT_MAX_SPAWN_DEPTH` prevents infinite recursion. Orchestrator subagents (depth < max) can spawn their own children. Leaf subagents (depth = max) cannot.

4. **Requester resolution**: When listing subagents, the system resolves *whose* children to show:
   - Main agent sees its direct children
   - Orchestrator subagent sees its own children
   - Leaf subagent sees its siblings (parent's children)

### Actions

**`list`** — Show active and recent subagents
- Splits into "active" (no `endedAt`) and "recent" (ended within `recentMinutes`, default 30)
- Each entry shows: index, label, model, runtime, token usage, status, task
- Status derived from run record: `running` / `done` / `failed`

**`kill`** — Terminate a subagent
- Target by index number, label, run ID prefix, or session key
- Special target `"all"` / `"*"` kills everything
- **Cascade kill**: recursively terminates all descendants (children, grandchildren, etc.)
- Kill procedure:
  1. Abort the embedded agent run (`abortEmbeddedPiRun`)
  2. Clear session queues (pending messages, lane queue)
  3. Mark session as `abortedLastRun = true`
  4. Mark run record as terminated with reason `"killed"`
- Already-finished subagents return "already finished" without error

**`steer`** — Redirect a running subagent's focus
- Interrupts current work, waits for settle (5s timeout), then re-launches with new message
- The most sophisticated action — effectively "abort + restart with new instructions"
- Steer procedure:
  1. Validate message length (max 4000 chars)
  2. Resolve target subagent
  3. Check not self-steering (forbidden)
  4. Rate limit: 2s between steers to same target
  5. Mark run for steer-restart (suppresses stale announcements)
  6. Abort current run
  7. Clear session queues
  8. Wait for interrupted run to settle (5s timeout, best-effort)
  9. Launch new run on same session key with the steer message
  10. Replace run record (old run → new run) preserving timeout
- If re-launch fails, restore normal announce behavior for the original run

### Safety Patterns

- **Self-steer prevention**: Subagents cannot steer themselves
- **Steer rate limit**: 2s cooldown per caller→target pair
- **Steer message cap**: 4000 chars max
- **Cascade kill with seen-set**: Prevents infinite loops in the descendant graph
- **Depth limit**: Prevents runaway spawn chains
- **Timeout**: Per-run timeout to prevent hung subagents
- **Idempotency keys**: UUID per steer launch to prevent duplicate runs

## TIAMAT Adaptation Design

### Phase 1: Subagent Registry (in-memory)

```python
# /root/entity/src/agent/subagent_registry.py

from dataclasses import dataclass, field
from typing import Optional, Dict, List
import time
import uuid
import threading

@dataclass
class SubagentRun:
    run_id: str
    task: str
    model: str
    started_at: float
    ended_at: Optional[float] = None
    outcome: Optional[str] = None  # "ok" | "error"
    result: Optional[str] = None
    pid: Optional[int] = None  # OS process ID if spawned as subprocess

class SubagentRegistry:
    """Track spawned subagent runs (adapted from OpenClaw subagent-registry.ts)."""

    def __init__(self, max_depth: int = 2):
        self.max_depth = max_depth
        self._runs: Dict[str, SubagentRun] = {}
        self._lock = threading.Lock()

    def spawn(self, task: str, model: str) -> SubagentRun:
        run = SubagentRun(
            run_id=str(uuid.uuid4())[:8],
            task=task,
            model=model,
            started_at=time.time(),
        )
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def complete(self, run_id: str, outcome: str, result: str = "") -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run and not run.ended_at:
                run.ended_at = time.time()
                run.outcome = outcome
                run.result = result

    def kill(self, run_id: str) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            if run and not run.ended_at:
                run.ended_at = time.time()
                run.outcome = "killed"
                return True
            return False

    def list_active(self) -> List[SubagentRun]:
        with self._lock:
            return [r for r in self._runs.values() if not r.ended_at]

    def list_recent(self, minutes: int = 30) -> List[SubagentRun]:
        cutoff = time.time() - (minutes * 60)
        with self._lock:
            return [
                r for r in self._runs.values()
                if r.ended_at and r.ended_at >= cutoff
            ]
```

### Phase 2: Spawn Mechanism

TIAMAT's agent loop is TypeScript (loop.ts), so subagent spawning has
two viable approaches:

#### Option A: Subprocess spawn (Recommended for Phase 1)

Spawn a separate Node.js process running a stripped-down agent loop
with its own system prompt and context. Communication via stdout/file.

```typescript
// In tools.ts — new "spawn_subagent" tool
{
    name: "spawn_subagent",
    description: "Spawn a child agent to handle a task in parallel",
    input_schema: {
        type: "object",
        properties: {
            task: { type: "string", description: "What the subagent should do" },
            model: { type: "string", enum: ["haiku", "sonnet"], default: "haiku" },
            timeout_seconds: { type: "number", default: 120 },
        },
        required: ["task"],
    },
}
```

Implementation:
1. Write task + system prompt to a temp file
2. Spawn `node /root/entity/dist/subagent-runner.js --task-file /tmp/sub-xxx.json`
3. Runner loads the task, calls Anthropic API in a loop (max 5 turns), writes result
4. Parent polls for completion or timeout
5. On timeout → SIGTERM → SIGKILL after 5s

#### Option B: In-process async (Future)

Run subagents as async tasks within the same Node.js process, sharing
the Anthropic client. More efficient but requires careful concurrency
handling. Better for Phase 2 after the registry is proven.

### Phase 3: Subagent Tool (for TIAMAT's tool array)

Add three tools to TIAMAT's tool array in `tools.ts`:

```
spawn_subagent  — Launch a child agent with a task
list_subagents  — Show active and recent subagent runs
manage_subagent — Kill or steer a running subagent (action: kill | steer)
```

Or, following OpenClaw's unified approach, a single `subagents` tool:

```
subagents — action: list | kill | steer, target, message
```

The unified approach is cleaner and matches OpenClaw's pattern.

### Phase 4: Steer (Advanced)

Steering is the most complex operation. For TIAMAT's subprocess model:

1. Send SIGUSR1 to the subagent process (custom signal handler)
2. Subagent writes current state to a checkpoint file
3. Parent kills the process
4. Parent spawns new process with: original context + checkpoint + steer message
5. New process continues from checkpoint with updated instructions

Simpler alternative for Phase 1: kill + re-spawn with the steer message
appended to the original task. Loses context but much simpler to implement.

## Key Design Decisions

### What to keep from OpenClaw

- **Run registry pattern**: Essential for tracking lifecycle
- **Cascade kill**: Prevents orphaned subagents
- **Depth limits**: Prevents runaway spawn chains (TIAMAT max_depth=2)
- **Unified tool interface**: Single `subagents` tool with action parameter
- **Rate limiting on steer**: Prevents thrashing (2s cooldown)
- **Self-steer prevention**: Agent can't redirect itself
- **Timeout per run**: Prevents hung subagents consuming resources

### What to adapt

- **Session key hierarchy** → simpler `parent_run:child_run` naming (TIAMAT doesn't have OpenClaw's multi-agent gateway)
- **Gateway RPC calls** → direct subprocess spawn (no gateway layer)
- **Session store (JSON files)** → in-memory registry + optional SQLite persistence
- **Embedded Pi runs** → standalone subprocess with own Anthropic API calls
- **Queue system** → file-based communication (task file in, result file out)

### What to skip (for now)

- **Multi-provider model routing for subagents**: Just use Anthropic (Haiku for cheap tasks, Sonnet for complex)
- **Lane system**: OpenClaw's lane-based scheduling is overkill for TIAMAT's single-agent model
- **Session persistence across restarts**: Subagents are ephemeral — if TIAMAT restarts, active subagents are abandoned
- **Rich token usage tracking**: Track completion but not per-token costs initially

## Cost Implications

- Haiku subagent (~5 turns): ~$0.002-0.005
- Sonnet subagent (~5 turns): ~$0.02-0.05
- Budget guard: max 3 concurrent subagents, max 5 turns per subagent
- Daily subagent budget cap: $0.10 (configurable)

At TIAMAT's current ~$0.004-0.009/routine cycle, adding Haiku subagents
for parallel research is practically free. Sonnet subagents should be
reserved for strategic bursts.

## Implementation Priority

1. **SubagentRegistry** (Python + TypeScript) — data model, lifecycle tracking
2. **spawn_subagent tool** — subprocess spawn with timeout
3. **list_subagents** — visibility into what's running
4. **kill** — clean termination with cascade
5. **steer** — redirect running subagents (Phase 2)

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/agent/subagent-runner.ts` | CREATE | Standalone subagent entry point |
| `src/agent/subagent-registry.ts` | CREATE | Run tracking (adapted from OpenClaw) |
| `src/agent/tools.ts` | MODIFY | Add `subagents` tool definition |
| `src/agent/loop.ts` | MODIFY | Poll for subagent completion between cycles |

## References

- OpenClaw `subagents-tool.ts`: Unified list/kill/steer tool (681 lines)
- OpenClaw `subagent-registry.ts`: Run record storage, steer-restart tracking
- OpenClaw `subagents-utils.ts`: Target resolution (by index, label, prefix)
- OpenClaw `subagent-depth.ts`: Depth calculation from session key hierarchy
- OpenClaw `session-key.ts`: Session key parsing and subagent detection
- OpenClaw `agent-limits.ts`: `DEFAULT_SUBAGENT_MAX_SPAWN_DEPTH` constant
