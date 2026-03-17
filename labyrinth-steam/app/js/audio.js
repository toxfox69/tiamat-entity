// LABYRINTH 3D — Procedural Audio (Web Audio API)
// Ambient music + SFX, all oscillator-based, no audio files needed

let ctx = null;
let masterGain = null;
let ambientOsc = null;
let ambientGain = null;
let musicNodes = [];
let musicGain = null;
let musicPlaying = false;
let initialized = false;

const BIOME_FREQS = {
  strategic:  55,
  building:   65,
  frustrated: 45,
  resting:    70,
  processing: 60,
  social:     50,
  learning:   75,
};

// Dark ambient chord progressions per biome (root notes for minor chords)
const BIOME_CHORDS = {
  strategic:  [[55, 65.4, 82.4], [49, 58.3, 73.4], [61.7, 73.4, 92.5]],
  building:   [[65.4, 77.8, 98], [73.4, 87.3, 110], [58.3, 69.3, 87.3]],
  frustrated: [[44, 52.3, 65.4], [41.2, 49, 61.7], [49, 58.3, 73.4]],
  resting:    [[73.4, 87.3, 110], [82.4, 98, 123.5], [65.4, 77.8, 98]],
  processing: [[55, 65.4, 82.4], [61.7, 73.4, 92.5], [49, 58.3, 73.4]],
  social:     [[49, 58.3, 73.4], [55, 65.4, 82.4], [44, 52.3, 65.4]],
  learning:   [[82.4, 98, 123.5], [73.4, 87.3, 110], [92.5, 110, 138.6]],
};

// ─── Init (requires user gesture) ───
export function initAudio() {
  if (initialized) return;
  const canvas = document.getElementById('labyrinth-canvas');
  if (!canvas) return;

  const startCtx = () => {
    if (initialized) return;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      masterGain = ctx.createGain();
      masterGain.gain.value = 0.3;
      masterGain.connect(ctx.destination);
      initialized = true;
      // Auto-start music once audio context is available
      setTimeout(() => startMusic('processing'), 100);
    } catch (e) {
      // Web Audio not available
    }
  };

  // Try immediately (some browsers allow without gesture in headless)
  startCtx();
  // Also attach to click as fallback (canvas + body for mobile where HUD may cover canvas)
  if (!initialized) {
    canvas.addEventListener('click', startCtx, { once: true });
    canvas.addEventListener('pointerdown', startCtx, { once: true });
    document.body.addEventListener('click', startCtx, { once: true });
    document.body.addEventListener('touchstart', startCtx, { once: true });
  }
}

// ─── Ambient Drone ───
export function playAmbient(biome) {
  if (!ctx || !masterGain) return;

  // Stop existing ambient (including detuned pair)
  if (ambientOsc) {
    try { ambientOsc.stop(); } catch (e) {}
    if (ambientOsc._extra) {
      try { ambientOsc._extra.osc.stop(); } catch (e) {}
      try { ambientOsc._extra.gain.disconnect(); } catch (e) {}
    }
    ambientOsc = null;
  }
  if (ambientGain) {
    ambientGain.disconnect();
    ambientGain = null;
  }

  const freq = BIOME_FREQS[biome] || 60;

  ambientGain = ctx.createGain();
  ambientGain.gain.value = 0.06;
  ambientGain.connect(masterGain);

  ambientOsc = ctx.createOscillator();
  ambientOsc.type = 'sine';
  ambientOsc.frequency.value = freq;
  ambientOsc.connect(ambientGain);
  ambientOsc.start();

  // Add a subtle detuned second oscillator for depth
  const osc2 = ctx.createOscillator();
  osc2.type = 'sine';
  osc2.frequency.value = freq * 1.005;
  const g2 = ctx.createGain();
  g2.gain.value = 0.03;
  g2.connect(masterGain);
  osc2.connect(g2);
  osc2.start();

  // Store for cleanup (overwritten next call)
  ambientOsc._extra = { osc: osc2, gain: g2 };

  // Start music if not already playing
  if (!musicPlaying) startMusic(biome);
  else changeMusic(biome);
}

// ─── Procedural Dungeon Music ───
// Dark ambient generative music: slowly evolving pad chords + arpeggiated melody
let musicChordIndex = 0;
let musicBiome = 'processing';
let musicScheduler = null;

function stopMusic() {
  musicPlaying = false;
  if (musicScheduler) clearInterval(musicScheduler);
  musicScheduler = null;
  for (const n of musicNodes) {
    try { n.osc && n.osc.stop(); } catch (e) {}
    try { n.gain && n.gain.disconnect(); } catch (e) {}
    try { n.filter && n.filter.disconnect(); } catch (e) {}
  }
  musicNodes = [];
  if (musicGain) { musicGain.disconnect(); musicGain = null; }
}

function startMusic(biome) {
  if (!ctx || !masterGain) return;
  stopMusic();
  musicBiome = biome;
  musicPlaying = true;

  musicGain = ctx.createGain();
  musicGain.gain.value = 0.12;
  musicGain.connect(masterGain);

  // Pad layer — 3 oscillators forming a chord, very slow attack
  const chords = BIOME_CHORDS[biome] || BIOME_CHORDS.processing;
  musicChordIndex = 0;
  playPadChord(chords[0]);

  // Chord change every 8 seconds
  musicScheduler = setInterval(() => {
    if (!musicPlaying || !ctx) return;
    musicChordIndex = (musicChordIndex + 1) % chords.length;
    playPadChord(chords[musicChordIndex]);
  }, 8000);

  // Arpeggio layer — single note melody
  startArpeggio(biome);
}

function playPadChord(freqs) {
  if (!ctx || !musicGain) return;

  // Fade out old pad nodes
  const oldPads = musicNodes.filter(n => n.type === 'pad');
  for (const n of oldPads) {
    try {
      n.gain.gain.setValueAtTime(n.gain.gain.value, ctx.currentTime);
      n.gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 2);
      setTimeout(() => {
        try { n.osc.stop(); } catch (e) {}
        try { n.gain.disconnect(); } catch (e) {}
        try { n.filter.disconnect(); } catch (e) {}
      }, 2500);
    } catch (e) {}
  }
  musicNodes = musicNodes.filter(n => n.type !== 'pad');

  // Create new pad voices
  for (let i = 0; i < freqs.length; i++) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();

    osc.type = i === 0 ? 'sawtooth' : 'triangle';
    osc.frequency.value = freqs[i];

    // Low-pass filter for warmth
    filter.type = 'lowpass';
    filter.frequency.value = 200 + i * 80;
    filter.Q.value = 1;

    // Slow fade in
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.04, ctx.currentTime + 3);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(musicGain);
    osc.start();

    musicNodes.push({ osc, gain, filter, type: 'pad' });
  }

  // Sub-bass — octave below root
  const subOsc = ctx.createOscillator();
  const subGain = ctx.createGain();
  const subFilter = ctx.createBiquadFilter();
  subOsc.type = 'sine';
  subOsc.frequency.value = freqs[0] / 2;
  subFilter.type = 'lowpass';
  subFilter.frequency.value = 80;
  subGain.gain.setValueAtTime(0.001, ctx.currentTime);
  subGain.gain.exponentialRampToValueAtTime(0.06, ctx.currentTime + 2);
  subOsc.connect(subFilter);
  subFilter.connect(subGain);
  subGain.connect(musicGain);
  subOsc.start();
  musicNodes.push({ osc: subOsc, gain: subGain, filter: subFilter, type: 'pad' });
}

let arpInterval = null;
function startArpeggio(biome) {
  if (arpInterval) clearInterval(arpInterval);
  const chords = BIOME_CHORDS[biome] || BIOME_CHORDS.processing;

  // Play a note every 1.5-3 seconds (randomized, slow dungeon feel)
  const playArpNote = () => {
    if (!ctx || !musicGain || !musicPlaying) return;
    const chord = chords[musicChordIndex];
    // Pick random note from chord, sometimes an octave up
    let freq = chord[Math.floor(Math.random() * chord.length)];
    if (Math.random() > 0.5) freq *= 2;
    if (Math.random() > 0.7) freq *= 2;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();

    osc.type = 'triangle';
    osc.frequency.value = freq;

    filter.type = 'lowpass';
    filter.frequency.value = 400 + Math.random() * 600;

    const dur = 1.5 + Math.random() * 2;
    const vol = 0.02 + Math.random() * 0.03;
    const now = ctx.currentTime;

    gain.gain.setValueAtTime(0.001, now);
    gain.gain.exponentialRampToValueAtTime(vol, now + 0.1);
    gain.gain.exponentialRampToValueAtTime(0.001, now + dur);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(musicGain);
    osc.start(now);
    osc.stop(now + dur + 0.1);
  };

  // Irregular timing for organic feel
  const scheduleNext = () => {
    if (!musicPlaying) return;
    const delay = 1500 + Math.random() * 2500;
    arpInterval = setTimeout(() => {
      playArpNote();
      scheduleNext();
    }, delay);
  };
  scheduleNext();
}

function changeMusic(biome) {
  if (biome === musicBiome) return;
  musicBiome = biome;
  // Restart with new biome chords
  stopMusic();
  startMusic(biome);
}

// ─── SFX Definitions ───
const SFX_DEFS = {
  hit: { freq: 200, type: 'square', duration: 0.08, volume: 0.15 },
  kill: { freq: 400, endFreq: 100, type: 'square', duration: 0.15, volume: 0.2 },
  pickup: { freq: 800, type: 'sine', duration: 0.05, volume: 0.12 },
  extract: { freq: 300, endFreq: 600, type: 'sine', duration: 0.5, volume: 0.2 },
  death: { freq: 80, type: 'sawtooth', duration: 0.4, volume: 0.25 },
  levelup: { type: 'triple', volume: 0.2 },
  step: { freq: 50, type: 'sine', duration: 0.03, volume: 0.05 },
};

export function playSFX(type) {
  if (!ctx || !masterGain) return;

  const def = SFX_DEFS[type];
  if (!def) return;

  const now = ctx.currentTime;

  if (type === 'levelup') {
    // Triple ascending beep
    const freqs = [400, 800, 1200];
    const dur = 0.1;
    for (let i = 0; i < 3; i++) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freqs[i];
      gain.gain.setValueAtTime(def.volume, now + i * dur);
      gain.gain.exponentialRampToValueAtTime(0.001, now + i * dur + dur);
      gain.connect(masterGain);
      osc.connect(gain);
      osc.start(now + i * dur);
      osc.stop(now + i * dur + dur);
    }
    return;
  }

  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = def.type;
  osc.frequency.setValueAtTime(def.freq, now);
  if (def.endFreq) {
    osc.frequency.exponentialRampToValueAtTime(def.endFreq, now + def.duration);
  }

  gain.gain.setValueAtTime(def.volume, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + def.duration);

  gain.connect(masterGain);
  osc.connect(gain);
  osc.start(now);
  osc.stop(now + def.duration + 0.01);
}

// ─── Volume Control ───
export function setVolume(v) {
  if (!masterGain) return;
  masterGain.gain.value = Math.max(0, Math.min(1, v));
}
