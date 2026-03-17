// LABYRINTH 3D — TIAMAT data feed → dungeon mutations
import { BIOMES, FLOOR_NARRATIVES } from './dungeon-gen.js';
import { emitParticles } from './particles.js';
import { spawnSpecter } from './agents.js';

const DATA_API = '/stream-api/';
const THOUGHTS_API = '/api/thoughts/stream?limit=5';

let lastCycle = 0;
let currentMood = 'processing';
let currentAction = null;
let pollInterval = null;
let boostQueue = [];

// ─── Fetch TIAMAT state ───
async function fetchState() {
  try {
    const res = await fetch(DATA_API + 'state');
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

async function fetchThoughts() {
  try {
    const res = await fetch(THOUGHTS_API);
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// ─── Process state into game events ───
function processState(state) {
  if (!state) return;

  // Mood change → biome shift
  if (state.mood && state.mood !== currentMood) {
    currentMood = state.mood;
    boostQueue.push({ type: 'biome_shift', mood: currentMood, time: Date.now() });
  }

  // Tool calls → game events
  if (state.tool_calls && Array.isArray(state.tool_calls)) {
    for (const tc of state.tool_calls) {
      const action = classifyToolCall(tc);
      if (action) {
        boostQueue.push({ type: action, tool: tc, time: Date.now() });
      }
    }
  }

  // Cycle change → new floor trigger
  if (state.cycle && state.cycle !== lastCycle) {
    lastCycle = state.cycle;
    boostQueue.push({ type: 'new_cycle', cycle: lastCycle, time: Date.now() });
  }
}

function classifyToolCall(tc) {
  const name = (tc.name || tc.tool || '').toLowerCase();
  if (name.includes('write_file') || name.includes('forge') || name.includes('ask_claude')) return 'forge';
  if (name.includes('read') || name.includes('search') || name.includes('scout')) return 'scout';
  if (name.includes('post_') || name.includes('send_') || name.includes('like_')) return 'rally';
  if (name.includes('exec')) return 'mine';
  if (name.includes('study') || name.includes('research')) return 'study';
  return null;
}

// ─── Apply mutations to game state ───
export function processBoostQueue(game, scene) {
  const events = [];
  while (boostQueue.length > 0) {
    const event = boostQueue.shift();
    events.push(event);
    applyMutation(event, game, scene);
  }
  return events;
}

function applyMutation(event, game, scene) {
  const px = game.player?.x || 20;
  const py = game.player?.y || 12;

  switch (event.type) {
    case 'forge':
      // Wall dissolves, equipment materializes
      emitParticles(px + 2, py, 'forge', 12).forEach(m => scene.add(m));
      spawnSpecter(px, py, 'forge', scene);
      game.addLog?.('SOURCE FORGED — new construct materializes', '#00ccff');
      break;

    case 'scout':
      // Fog clears, new torch lights
      emitParticles(px, py, 'scout', 8).forEach(m => scene.add(m));
      spawnSpecter(px, py, 'scout', scene);
      game.addLog?.('WATCHTOWER — area revealed', '#00ffaa');
      break;

    case 'curse':
      // Fog thickens, monsters spawn
      emitParticles(px, py, 'curse', 15).forEach(m => scene.add(m));
      game.addLog?.('CORRUPTION — glitch errors spread', '#ff2040');
      break;

    case 'rage':
      // Lights turn red, player light radius doubles
      emitParticles(px, py, 'rage', 12).forEach(m => scene.add(m));
      game.addLog?.('WAR MODE — fury scorches the halls', '#ff4400');
      break;

    case 'study':
      // Rune patterns, crystal formations
      emitParticles(px, py, 'study', 8).forEach(m => scene.add(m));
      spawnSpecter(px, py, 'study', scene);
      game.addLog?.('ARCHIVE — knowledge crystallizes', '#6688ff');
      break;

    case 'rally':
      // Social frequency pulse
      emitParticles(px, py, 'default', 10).forEach(m => scene.add(m));
      spawnSpecter(px, py, 'rally', scene);
      game.addLog?.('SIGNAL — social frequencies pulse', '#cc66ff');
      break;

    case 'mine':
      // Gold sparkle, data extraction
      emitParticles(px, py, 'mine', 10).forEach(m => scene.add(m));
      spawnSpecter(px, py, 'mine', scene);
      game.addLog?.('DATA MINED — extraction complete', '#ffdd00');
      break;

    case 'legendary':
      // Full layout reveal
      emitParticles(px, py, 'legendary', 20).forEach(m => scene.add(m));
      game.addLog?.('LEGENDARY — the treasury reveals itself', '#ffffff');
      break;

    case 'biome_shift':
      game.addLog?.('BIOME SHIFT: ' + (BIOMES[event.mood]?.name || 'UNKNOWN'), BIOMES[event.mood]?.wire || '#00ff41');
      break;

    case 'new_cycle':
      // Trigger floor narrative
      currentAction = getRandomAction();
      if (FLOOR_NARRATIVES[currentAction]) {
        game.addLog?.(FLOOR_NARRATIVES[currentAction].name, '#ffaa00');
      }
      break;
  }
}

function getRandomAction() {
  const actions = Object.keys(FLOOR_NARRATIVES);
  return actions[Math.floor(Math.random() * actions.length)];
}

// ─── Polling ───
export function startDataPolling(intervalMs) {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    const state = await fetchState();
    processState(state);
  }, intervalMs || 5000);

  // Initial fetch
  fetchState().then(processState);
}

export function stopDataPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

export function getCurrentMood() { return currentMood; }
export function getCurrentAction() { return currentAction; }
export function getBoostQueueLength() { return boostQueue.length; }
