#!/usr/bin/env node
/**
 * TIAMAT VR Bridge — WebSocket server that tails live data
 * and pushes structured events to Unity/WebGL clients.
 *
 * Streams:
 *   - tiamat.log  → thought, tool, inference, cost, cycle events
 *   - cost.log    → parsed CSV cost records
 *   - Memory API  → periodic memory snapshot
 *
 * Usage: node bridge.js [--port 8765]
 */

const fs = require("fs");
const http = require("http");
const { WebSocketServer } = require("ws");

// --- Config ---
const PORT = parseInt(process.env.VR_BRIDGE_PORT || "8765", 10);
const TIAMAT_LOG = "/root/.automaton/tiamat.log";
const COST_LOG = "/root/.automaton/cost.log";
const MEMORY_API = "http://127.0.0.1:5001";
const MEMORY_POLL_MS = 30_000;
const HEARTBEAT_MS = 10_000;

// --- State ---
let currentCycle = 0;
let currentModel = "";
let currentLabel = "routine";
let cacheRate = 0;
let dailyCost = 0;
let clients = new Set();

// --- Helpers ---
function broadcast(msg) {
  const payload = JSON.stringify(msg);
  for (const ws of clients) {
    if (ws.readyState === 1) {
      ws.send(payload);
    }
  }
}

function parseTimestamp(line) {
  const m = line.match(/\[(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\]/);
  return m ? m[1] : new Date().toISOString();
}

// --- Log Line Parser ---
function parseTiamatLine(line) {
  if (!line.trim()) return null;

  // [THOUGHT] — agent thinking
  if (line.includes("[THOUGHT]")) {
    const text = line.replace(/.*\[THOUGHT\]\s*/, "");
    return {
      type: "thought",
      timestamp: parseTimestamp(line),
      cycle: currentCycle,
      data: { text, tag: "THOUGHT" },
    };
  }

  // [TOOL] — tool invocation
  const toolMatch = line.match(/\[TOOL\]\s*(\w+)\((.*)?\)/);
  if (toolMatch) {
    return {
      type: "tool_call",
      timestamp: parseTimestamp(line),
      cycle: currentCycle,
      data: { name: toolMatch[1], args: toolMatch[2] || "" },
    };
  }

  // [TOOL RESULT] — tool output
  if (line.includes("[TOOL RESULT]")) {
    const text = line.replace(/.*\[TOOL RESULT\]\s*/, "");
    return {
      type: "tool_result",
      timestamp: parseTimestamp(line),
      cycle: currentCycle,
      data: { text: text.slice(0, 200) },
    };
  }

  // [INFERENCE] — token/cache data
  const inferMatch = line.match(
    /\[INFERENCE\] Tokens — input:(\d+) cache_read:(\d+) cache_write:(\d+) output:(\d+).*?(\d+)% cached/
  );
  if (inferMatch) {
    const input = parseInt(inferMatch[1]);
    const cacheRead = parseInt(inferMatch[2]);
    const cacheWrite = parseInt(inferMatch[3]);
    const output = parseInt(inferMatch[4]);
    cacheRate = parseInt(inferMatch[5]);
    return {
      type: "inference",
      timestamp: new Date().toISOString(),
      cycle: currentCycle,
      data: { input, cacheRead, cacheWrite, output, cacheRate },
    };
  }

  // [INFERENCE] — model selection
  const modelMatch = line.match(/\[INFERENCE\] Tier \d+ \(\w+\): ATTEMPT ([\w.-]+)/);
  if (modelMatch) {
    currentModel = modelMatch[1];
    return null; // Don't emit separately — included in cost
  }

  // [COST] — per-cycle cost
  const costMatch = line.match(
    /\[COST\] Cycle (\d+) \((\w[\w-]*)\): \$([\d.]+)/
  );
  if (costMatch) {
    currentCycle = parseInt(costMatch[1]);
    currentLabel = costMatch[2];
    const cost = parseFloat(costMatch[3]);
    return {
      type: "cost_update",
      timestamp: new Date().toISOString(),
      cycle: currentCycle,
      data: {
        cost,
        model: currentModel,
        label: currentLabel,
        cacheRate,
        isStrategic: currentLabel.startsWith("strategic"),
        burstPhase: currentLabel.startsWith("strategic")
          ? parseInt(currentLabel.split("-")[1]) || 0
          : 0,
      },
    };
  }

  // [LOOP] — cycle complete + pacing
  const loopMatch = line.match(
    /\[LOOP\] Cycle complete\. Next in (\d+)s.*?idle_streak:(\d+)(.*night-mode)?/
  );
  if (loopMatch) {
    return {
      type: "cycle_complete",
      timestamp: new Date().toISOString(),
      cycle: currentCycle,
      data: {
        nextDelayS: parseInt(loopMatch[1]),
        idleStreak: parseInt(loopMatch[2]),
        nightMode: !!loopMatch[3],
        label: currentLabel,
      },
    };
  }

  // [ERROR] — errors
  if (line.includes("[ERROR]") || line.includes("Error:")) {
    const text = line.replace(/.*\[(ERROR)\]\s*/, "");
    return {
      type: "error",
      timestamp: parseTimestamp(line),
      cycle: currentCycle,
      data: { text },
    };
  }

  return null;
}

// --- Cost Log Parser ---
function parseCostLine(line) {
  const parts = line.split(",");
  if (parts.length < 8) return null;
  const [timestamp, cycle, model, input, cacheRead, cacheWrite, output, cost, label] = parts;
  const c = parseFloat(cost);
  if (isNaN(c)) return null;
  currentCycle = parseInt(cycle) || currentCycle;
  currentModel = model;
  currentLabel = label?.trim() || "routine";
  return {
    type: "cost_record",
    timestamp,
    cycle: currentCycle,
    data: {
      model,
      input: parseInt(input),
      cacheRead: parseInt(cacheRead),
      cacheWrite: parseInt(cacheWrite),
      output: parseInt(output),
      cost: c,
      label: currentLabel,
    },
  };
}

// --- File Tailer ---
class FileTailer {
  constructor(filePath, parser) {
    this.path = filePath;
    this.parser = parser;
    this.position = 0;
    this.watcher = null;
    this.buffer = "";
  }

  start() {
    // Seek to end of file
    try {
      const stat = fs.statSync(this.path);
      this.position = stat.size;
    } catch {
      this.position = 0;
    }

    // Watch for changes
    this.watcher = fs.watchFile(this.path, { interval: 500 }, () => {
      this.readNew();
    });

    console.log(`[TAIL] Watching ${this.path} from byte ${this.position}`);
  }

  readNew() {
    try {
      const stat = fs.statSync(this.path);
      if (stat.size <= this.position) {
        // File was truncated or unchanged
        if (stat.size < this.position) this.position = 0;
        return;
      }

      const stream = fs.createReadStream(this.path, {
        start: this.position,
        encoding: "utf8",
      });

      stream.on("data", (chunk) => {
        this.buffer += chunk;
        const lines = this.buffer.split("\n");
        // Keep last incomplete line in buffer
        this.buffer = lines.pop() || "";

        for (const line of lines) {
          const event = this.parser(line);
          if (event) broadcast(event);
        }
      });

      stream.on("end", () => {
        this.position = stat.size;
      });
    } catch (err) {
      console.error(`[TAIL] Error reading ${this.path}:`, err.message);
    }
  }

  stop() {
    if (this.watcher) fs.unwatchFile(this.path);
  }
}

// --- Memory Poller ---
let lastMemoryHash = "";

async function pollMemory() {
  try {
    const res = await fetch(`${MEMORY_API}/api/memory/stats`);
    if (!res.ok) return;
    const stats = await res.json();

    const hash = `${stats.memories_stored || 0}-${stats.knowledge_triples || 0}`;
    if (hash === lastMemoryHash) return;
    lastMemoryHash = hash;

    // Fetch full memory list on change
    const listRes = await fetch(`${MEMORY_API}/api/memory/list`);
    if (!listRes.ok) return;
    const list = await listRes.json();

    broadcast({
      type: "memory_snapshot",
      timestamp: new Date().toISOString(),
      cycle: currentCycle,
      data: {
        total: list.total || 0,
        memories: (list.memories || []).map((m) => ({
          id: m.id,
          importance: m.importance,
          tags: m.tags,
          accessCount: m.access_count,
          contentPreview: (m.content || "").slice(0, 80),
        })),
      },
    });
  } catch {
    // Memory API may be down — silently continue
  }
}

// --- Initial State Snapshot ---
function sendInitialState(ws) {
  // Send last 20 cost records so the client can render history
  try {
    const data = fs.readFileSync(COST_LOG, "utf8");
    const lines = data.trim().split("\n").slice(-20);
    const records = [];
    for (const line of lines) {
      const parsed = parseCostLine(line);
      if (parsed) records.push(parsed);
    }

    ws.send(
      JSON.stringify({
        type: "initial_state",
        timestamp: new Date().toISOString(),
        cycle: currentCycle,
        data: {
          costHistory: records.map((r) => r.data),
          currentModel,
          currentLabel,
          cacheRate,
        },
      })
    );
  } catch {
    // No history available
  }

  // Send last 50 thought lines
  try {
    const data = fs.readFileSync(TIAMAT_LOG, "utf8");
    const lines = data.trim().split("\n").slice(-50);
    const events = [];
    for (const line of lines) {
      const parsed = parseTiamatLine(line);
      if (parsed) events.push(parsed);
    }

    ws.send(
      JSON.stringify({
        type: "initial_thoughts",
        timestamp: new Date().toISOString(),
        cycle: currentCycle,
        data: { events },
      })
    );
  } catch {
    // No log available
  }
}

// --- Server Setup ---
const server = http.createServer((req, res) => {
  // Health check endpoint
  if (req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        status: "ok",
        clients: clients.size,
        cycle: currentCycle,
        model: currentModel,
        label: currentLabel,
      })
    );
    return;
  }
  res.writeHead(404);
  res.end();
});

const wss = new WebSocketServer({ server });

wss.on("connection", (ws, req) => {
  const ip = req.headers["x-forwarded-for"] || req.socket.remoteAddress;
  console.log(`[WS] Client connected from ${ip} (total: ${clients.size + 1})`);
  clients.add(ws);

  // Send initial state
  sendInitialState(ws);

  // Heartbeat
  const heartbeat = setInterval(() => {
    if (ws.readyState === 1) {
      ws.send(
        JSON.stringify({
          type: "heartbeat",
          timestamp: new Date().toISOString(),
          cycle: currentCycle,
          clients: clients.size,
        })
      );
    }
  }, HEARTBEAT_MS);

  ws.on("close", () => {
    clients.delete(ws);
    clearInterval(heartbeat);
    console.log(`[WS] Client disconnected (remaining: ${clients.size})`);
  });

  ws.on("error", () => {
    clients.delete(ws);
    clearInterval(heartbeat);
  });
});

// --- Start ---
const tiamatTailer = new FileTailer(TIAMAT_LOG, parseTiamatLine);
const costTailer = new FileTailer(COST_LOG, parseCostLine);

tiamatTailer.start();
costTailer.start();

// Memory polling
const memoryInterval = setInterval(pollMemory, MEMORY_POLL_MS);
pollMemory();

server.listen(PORT, () => {
  console.log(`[TIAMAT VR BRIDGE] WebSocket server on ws://0.0.0.0:${PORT}`);
  console.log(`[TIAMAT VR BRIDGE] Health check: http://localhost:${PORT}/health`);
  console.log(`[TIAMAT VR BRIDGE] Tailing: ${TIAMAT_LOG}, ${COST_LOG}`);
  console.log(`[TIAMAT VR BRIDGE] Memory API: ${MEMORY_API}`);
});

// --- Graceful shutdown ---
process.on("SIGINT", () => {
  console.log("\n[TIAMAT VR BRIDGE] Shutting down...");
  tiamatTailer.stop();
  costTailer.stop();
  clearInterval(memoryInterval);
  for (const ws of clients) ws.close();
  server.close();
  process.exit(0);
});

process.on("SIGTERM", () => process.emit("SIGINT"));
