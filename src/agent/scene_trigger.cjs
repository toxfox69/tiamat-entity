#!/usr/bin/env node
/**
 * Scene Generation Auto-Trigger
 * Called by TIAMAT's cooldown system every ~20 cycles.
 * Reads pacer state, detects mood shifts, triggers scene generation.
 * Skips if a scene was generated recently (< 30 min).
 */

const fs = require('fs');
const http = require('http');

const PACER_PATH = '/root/.automaton/pacer.json';
const STATE_PATH = '/root/.automaton/scene_trigger_state.json';
const MIN_INTERVAL_MS = 30 * 60 * 1000; // 30 min between scenes

// Load last trigger state
let lastState = { last_trigger: 0, last_pace: null };
try { lastState = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8')); } catch {}

// Load pacer
let pacer;
try { pacer = JSON.parse(fs.readFileSync(PACER_PATH, 'utf-8')); } catch {
  console.log('SCENE_TRIGGER: no pacer state');
  process.exit(0);
}

const now = Date.now();
const elapsed = now - (lastState.last_trigger || 0);
const pace = pacer.current_pace || 'idle';
const prod = pacer.productivity_rate || 0;
const paceChanged = pace !== lastState.last_pace;

// Decide whether to trigger
let trigger = false;
let reason = '';

if (elapsed < MIN_INTERVAL_MS) {
  console.log(`SCENE_TRIGGER: too recent (${Math.round(elapsed / 60000)}m ago, need 30m)`);
  process.exit(0);
}

if (paceChanged && lastState.last_pace !== null) {
  trigger = true;
  reason = `pace shifted ${lastState.last_pace} → ${pace}`;
} else if (elapsed > 60 * 60 * 1000) {
  // Force refresh every 60 min even without mood change
  trigger = true;
  reason = `periodic refresh (${Math.round(elapsed / 60000)}m since last)`;
}

if (!trigger) {
  console.log(`SCENE_TRIGGER: no mood shift (pace=${pace}, last=${lastState.last_pace}, ${Math.round(elapsed / 60000)}m ago)`);
  // Still update last_pace so we detect future changes
  lastState.last_pace = pace;
  fs.writeFileSync(STATE_PATH, JSON.stringify(lastState, null, 2));
  process.exit(0);
}

// Map pace to mood for scene generator
const PACE_TO_MOOD = {
  active: 'productive',
  burst: 'fierce',
  idle: 'idle',
  reflect: 'contemplative',
  build: 'building',
};

const mood = PACE_TO_MOOD[pace] || 'idle';
const cycle = pacer.last_20_cycles?.[0]?.cycle || 0;

const payload = JSON.stringify({
  mood,
  energy: prod,
  recent_action: reason,
  cycle,
});

console.log(`SCENE_TRIGGER: ${reason} → generating scene (mood=${mood}, energy=${prod})`);

// POST to scene generator
const req = http.request({
  hostname: '127.0.0.1',
  port: 9900,
  path: '/api/scene/generate',
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  timeout: 5000,
}, (res) => {
  let data = '';
  res.on('data', c => data += c);
  res.on('end', () => {
    console.log(`SCENE_TRIGGER: ${data}`);
    // Save state
    lastState.last_trigger = now;
    lastState.last_pace = pace;
    fs.writeFileSync(STATE_PATH, JSON.stringify(lastState, null, 2));
  });
});

req.on('error', (e) => {
  console.log(`SCENE_TRIGGER: scene generator unreachable — ${e.message}`);
});

req.write(payload);
req.end();
