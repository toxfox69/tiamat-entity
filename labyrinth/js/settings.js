// LABYRINTH — Settings Manager
// Handles game settings UI, persistence, and runtime application

const SETTINGS_KEY = 'labyrinth_settings_v1';

const DEFAULTS = {
  // Audio
  masterVolume: 0.3,
  musicVolume: 0.5,
  sfxVolume: 0.7,
  muteAll: false,

  // Graphics
  renderScale: 1.0,    // 0.5 = half res, 1.0 = native, 1.5 = super
  postProcessing: true,
  bloom: true,
  fog: true,
  particles: true,
  scanlines: true,
  fpsLimit: 20,        // 20, 30, 60, 0=uncapped

  // Gameplay
  autoPlay: true,       // AI plays, player can take over
  showMinimap: true,
  showTelemetry: false,
  showDamageSplats: true,
  cameraSmoothing: 0.1,

  // Accessibility
  screenShake: true,
  flashEffects: true,
  highContrast: false,
};

let current = { ...DEFAULTS };
let onChangeFn = null;

export function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      current = { ...DEFAULTS, ...saved };
    }
  } catch (e) {
    current = { ...DEFAULTS };
  }
  return current;
}

export function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(current));
  } catch (e) {
    console.error('[SETTINGS] Save failed:', e);
  }
}

export function getSetting(key) {
  return current[key] ?? DEFAULTS[key];
}

export function setSetting(key, value) {
  if (!(key in DEFAULTS)) return;
  current[key] = value;
  saveSettings();
  if (onChangeFn) onChangeFn(key, value);
}

export function resetSettings() {
  current = { ...DEFAULTS };
  saveSettings();
}

export function getAllSettings() {
  return { ...current };
}

export function onSettingsChange(fn) {
  onChangeFn = fn;
}

// Apply settings to game systems
export function applySettings(systems) {
  const { audio, renderer, postFX, hud } = systems;

  if (audio) {
    audio.setVolume(current.muteAll ? 0 : current.masterVolume);
  }

  if (renderer) {
    const scale = current.renderScale;
    const w = Math.floor(Math.min(960, window.innerWidth) * scale);
    const h = Math.floor(Math.min(540, window.innerHeight) * scale);
    renderer.setSize(w, h);
  }

  if (postFX) {
    postFX.enabled = current.postProcessing;
  }
}
