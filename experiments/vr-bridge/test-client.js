#!/usr/bin/env node
/**
 * Quick test client — connects to the VR bridge and prints events.
 * Usage: node test-client.js [ws://localhost:8765]
 */
const { WebSocket } = require("ws");
const url = process.argv[2] || "ws://localhost:8765";

console.log(`Connecting to ${url}...`);
const ws = new WebSocket(url);

ws.on("open", () => console.log("Connected!\n"));

ws.on("message", (data) => {
  const msg = JSON.parse(data.toString());
  const ts = msg.timestamp?.slice(11, 19) || "";

  switch (msg.type) {
    case "initial_state":
      console.log(`[INIT] Cycle ${msg.cycle}, model: ${msg.data?.currentModel}, cache: ${msg.data?.cacheRate}%`);
      console.log(`       ${msg.data?.costHistory?.length || 0} cost records loaded`);
      break;
    case "initial_thoughts":
      console.log(`[INIT] ${msg.data?.events?.length || 0} recent thought events loaded`);
      break;
    case "heartbeat":
      process.stdout.write(`\r[HEARTBEAT] cycle:${msg.cycle} clients:${msg.clients} ${ts}`);
      break;
    case "thought":
      console.log(`\n[${ts}] THOUGHT: ${msg.data?.text?.slice(0, 80)}`);
      break;
    case "tool_call":
      console.log(`\n[${ts}] TOOL: ${msg.data?.name}(${msg.data?.args?.slice(0, 60)})`);
      break;
    case "cost_update":
    case "cost_record":
      const d = msg.data;
      const phase = d?.isStrategic ? ` BURST-${d.burstPhase}` : "";
      console.log(`\n[${ts}] COST: $${d?.cost?.toFixed(4)} ${d?.label}${phase} cache:${d?.cacheRate}%`);
      break;
    case "cycle_complete":
      console.log(`\n[${ts}] CYCLE DONE → next in ${msg.data?.nextDelayS}s ${msg.data?.nightMode ? "(night)" : ""}`);
      break;
    case "inference":
      console.log(`\n[${ts}] INFERENCE: in:${msg.data?.input} out:${msg.data?.output} cache:${msg.data?.cacheRate}%`);
      break;
    case "memory_snapshot":
      console.log(`\n[${ts}] MEMORY: ${msg.data?.total} memories, ${msg.data?.memories?.length} sent`);
      break;
    case "error":
      console.log(`\n[${ts}] ERROR: ${msg.data?.text}`);
      break;
    default:
      console.log(`\n[${ts}] ${msg.type}: ${JSON.stringify(msg.data).slice(0, 100)}`);
  }
});

ws.on("close", () => { console.log("\nDisconnected"); process.exit(0); });
ws.on("error", (e) => { console.error("Error:", e.message); process.exit(1); });
