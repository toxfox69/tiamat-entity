// LABYRINTH: TIAMAT'S DESCENT — Settings Menu
// Overlay with volume, graphics, keybinds, resume/quit

const SETTINGS_KEY = 'labyrinth_settings_v1';

const DEFAULTS = {
  masterVolume: 0.3,
  musicVolume: 0.5,
  sfxVolume: 0.7,
  muteAll: false,
  postProcessing: true,
  particles: true,
  resolutionScale: 1.0,
  showMinimap: true,
  showTutorial: true,
  screenShake: true,
};

let current = { ...DEFAULTS };
let menuElement = null;
let isOpen = false;
let onResumeFn = null;
let onQuitFn = null;
let onSettingChangeFn = null;

// ─── Load settings from localStorage ───
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
  return { ...current };
}

// ─── Save settings ───
function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(current));
  } catch (e) {
    console.error('[SETTINGS] Save failed:', e);
  }
}

// ─── Get/Set ───
export function getSetting(key) { return current[key] ?? DEFAULTS[key]; }

export function setSetting(key, value) {
  if (!(key in DEFAULTS)) return;
  current[key] = value;
  saveSettings();
  if (onSettingChangeFn) onSettingChangeFn(key, value);
}

export function getAllSettings() { return { ...current }; }

// ─── Initialize Menu ───
export function initSettingsMenu(callbacks) {
  if (callbacks) {
    onResumeFn = callbacks.onResume || null;
    onQuitFn = callbacks.onQuit || null;
    onSettingChangeFn = callbacks.onSettingChange || null;
  }

  loadSettings();
  createMenuDOM();
  injectCSS();
}

// ─── Toggle menu open/closed ───
export function toggleSettingsMenu() {
  if (isOpen) closeSettings();
  else openSettings();
}

export function openSettings() {
  if (!menuElement) createMenuDOM();
  updateMenuValues();
  menuElement.style.display = 'flex';
  isOpen = true;
}

export function closeSettings() {
  if (menuElement) menuElement.style.display = 'none';
  isOpen = false;
  if (onResumeFn) onResumeFn();
}

export function isSettingsOpen() { return isOpen; }

// ─── Create the DOM structure ───
function createMenuDOM() {
  if (menuElement) return;

  menuElement = document.createElement('div');
  menuElement.id = 'settings-overlay';
  menuElement.innerHTML = `
    <div class="settings-panel">
      <div class="settings-title">SETTINGS</div>

      <div class="settings-section">
        <div class="settings-section-title">AUDIO</div>

        <div class="settings-row">
          <label>Master Volume</label>
          <input type="range" min="0" max="100" value="${current.masterVolume * 100}" id="set-master-vol" class="settings-slider">
          <span id="set-master-vol-val">${Math.round(current.masterVolume * 100)}%</span>
        </div>

        <div class="settings-row">
          <label>Music Volume</label>
          <input type="range" min="0" max="100" value="${current.musicVolume * 100}" id="set-music-vol" class="settings-slider">
          <span id="set-music-vol-val">${Math.round(current.musicVolume * 100)}%</span>
        </div>

        <div class="settings-row">
          <label>SFX Volume</label>
          <input type="range" min="0" max="100" value="${current.sfxVolume * 100}" id="set-sfx-vol" class="settings-slider">
          <span id="set-sfx-vol-val">${Math.round(current.sfxVolume * 100)}%</span>
        </div>

        <div class="settings-row">
          <label>Mute All</label>
          <input type="checkbox" id="set-mute" ${current.muteAll ? 'checked' : ''} class="settings-checkbox">
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-section-title">GRAPHICS</div>

        <div class="settings-row">
          <label>Post-Processing</label>
          <input type="checkbox" id="set-postfx" ${current.postProcessing ? 'checked' : ''} class="settings-checkbox">
        </div>

        <div class="settings-row">
          <label>Particles</label>
          <input type="checkbox" id="set-particles" ${current.particles ? 'checked' : ''} class="settings-checkbox">
        </div>

        <div class="settings-row">
          <label>Screen Shake</label>
          <input type="checkbox" id="set-shake" ${current.screenShake ? 'checked' : ''} class="settings-checkbox">
        </div>

        <div class="settings-row">
          <label>Resolution Scale</label>
          <select id="set-resolution" class="settings-select">
            <option value="0.5" ${current.resolutionScale === 0.5 ? 'selected' : ''}>0.5x (Performance)</option>
            <option value="0.75" ${current.resolutionScale === 0.75 ? 'selected' : ''}>0.75x (Balanced)</option>
            <option value="1" ${current.resolutionScale === 1.0 ? 'selected' : ''}>1.0x (Native)</option>
          </select>
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-section-title">GAMEPLAY</div>

        <div class="settings-row">
          <label>Show Minimap</label>
          <input type="checkbox" id="set-minimap" ${current.showMinimap ? 'checked' : ''} class="settings-checkbox">
        </div>

        <div class="settings-row">
          <label>Show Tutorial Tips</label>
          <input type="checkbox" id="set-tutorial" ${current.showTutorial ? 'checked' : ''} class="settings-checkbox">
        </div>
      </div>

      <div class="settings-section">
        <div class="settings-section-title">KEYBINDS</div>
        <div class="keybind-row"><span class="keybind-key">WASD / Arrows</span><span class="keybind-action">Move</span></div>
        <div class="keybind-row"><span class="keybind-key">Space / Enter</span><span class="keybind-action">Interact / Attack</span></div>
        <div class="keybind-row"><span class="keybind-key">E</span><span class="keybind-action">Extract</span></div>
        <div class="keybind-row"><span class="keybind-key">Tab / I</span><span class="keybind-action">Inventory</span></div>
        <div class="keybind-row"><span class="keybind-key">M</span><span class="keybind-action">Toggle Minimap</span></div>
        <div class="keybind-row"><span class="keybind-key">Escape</span><span class="keybind-action">Pause / Settings</span></div>
        <div class="keybind-row"><span class="keybind-key">Ctrl+S</span><span class="keybind-action">Quick Save</span></div>
        <div class="keybind-row"><span class="keybind-key">F11</span><span class="keybind-action">Toggle Fullscreen</span></div>
        <div class="keybind-row"><span class="keybind-key">P</span><span class="keybind-action">Performance Stats</span></div>
        <div class="keybind-row"><span class="keybind-key">T</span><span class="keybind-action">Agent Telemetry</span></div>
      </div>

      <div class="settings-buttons">
        <button id="set-resume" class="settings-btn settings-btn-resume">RESUME</button>
        <button id="set-quit" class="settings-btn settings-btn-quit">QUIT GAME</button>
      </div>
    </div>
  `;

  document.body.appendChild(menuElement);

  // Wire up events
  wireSlider('set-master-vol', 'set-master-vol-val', 'masterVolume');
  wireSlider('set-music-vol', 'set-music-vol-val', 'musicVolume');
  wireSlider('set-sfx-vol', 'set-sfx-vol-val', 'sfxVolume');

  wireCheckbox('set-mute', 'muteAll');
  wireCheckbox('set-postfx', 'postProcessing');
  wireCheckbox('set-particles', 'particles');
  wireCheckbox('set-shake', 'screenShake');
  wireCheckbox('set-minimap', 'showMinimap');
  wireCheckbox('set-tutorial', 'showTutorial');

  const resSelect = document.getElementById('set-resolution');
  if (resSelect) {
    resSelect.addEventListener('change', () => {
      setSetting('resolutionScale', parseFloat(resSelect.value));
    });
  }

  const resumeBtn = document.getElementById('set-resume');
  if (resumeBtn) resumeBtn.addEventListener('click', closeSettings);

  const quitBtn = document.getElementById('set-quit');
  if (quitBtn) {
    quitBtn.addEventListener('click', () => {
      if (onQuitFn) onQuitFn();
      else if (window.close) window.close();
    });
  }

  // Close on overlay background click
  menuElement.addEventListener('click', (e) => {
    if (e.target === menuElement) closeSettings();
  });

  menuElement.style.display = 'none';
}

function wireSlider(sliderId, valId, settingKey) {
  const slider = document.getElementById(sliderId);
  const valEl = document.getElementById(valId);
  if (slider) {
    slider.addEventListener('input', () => {
      const val = parseInt(slider.value) / 100;
      setSetting(settingKey, val);
      if (valEl) valEl.textContent = Math.round(val * 100) + '%';
    });
  }
}

function wireCheckbox(checkId, settingKey) {
  const check = document.getElementById(checkId);
  if (check) {
    check.addEventListener('change', () => {
      setSetting(settingKey, check.checked);
    });
  }
}

function updateMenuValues() {
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) {
      if (el.type === 'range') el.value = val;
      else if (el.type === 'checkbox') el.checked = val;
      else if (el.tagName === 'SELECT') el.value = val;
    }
  };
  const setTxt = (id, txt) => {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  };

  setVal('set-master-vol', current.masterVolume * 100);
  setTxt('set-master-vol-val', Math.round(current.masterVolume * 100) + '%');
  setVal('set-music-vol', current.musicVolume * 100);
  setTxt('set-music-vol-val', Math.round(current.musicVolume * 100) + '%');
  setVal('set-sfx-vol', current.sfxVolume * 100);
  setTxt('set-sfx-vol-val', Math.round(current.sfxVolume * 100) + '%');
  setVal('set-mute', current.muteAll);
  setVal('set-postfx', current.postProcessing);
  setVal('set-particles', current.particles);
  setVal('set-shake', current.screenShake);
  setVal('set-minimap', current.showMinimap);
  setVal('set-tutorial', current.showTutorial);
  setVal('set-resolution', current.resolutionScale.toString());
}

// ─── CSS injection ───
function injectCSS() {
  if (document.getElementById('settings-css')) return;

  const style = document.createElement('style');
  style.id = 'settings-css';
  style.textContent = `
    #settings-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.85);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9000;
      backdrop-filter: blur(4px);
    }

    .settings-panel {
      background: rgba(5, 10, 5, 0.95);
      border: 1px solid rgba(0, 255, 65, 0.3);
      padding: 24px 32px;
      max-width: 500px;
      width: 90vw;
      max-height: 85vh;
      overflow-y: auto;
      font-family: 'JetBrains Mono', 'Courier New', monospace;
      color: #00ff41;
    }

    .settings-title {
      font-family: 'Press Start 2P', monospace;
      font-size: 18px;
      text-align: center;
      color: #00ff41;
      text-shadow: 0 0 15px #00ff41;
      letter-spacing: 6px;
      margin-bottom: 24px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(0, 255, 65, 0.2);
    }

    .settings-section {
      margin-bottom: 20px;
    }

    .settings-section-title {
      font-family: 'Press Start 2P', monospace;
      font-size: 10px;
      color: #00aa2a;
      letter-spacing: 3px;
      margin-bottom: 10px;
    }

    .settings-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 0;
      font-size: 12px;
      gap: 10px;
    }

    .settings-row label {
      color: #aaa;
      flex-shrink: 0;
      min-width: 140px;
    }

    .settings-slider {
      -webkit-appearance: none;
      appearance: none;
      flex: 1;
      height: 4px;
      background: #222;
      border-radius: 2px;
      outline: none;
      cursor: pointer;
    }

    .settings-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 14px;
      height: 14px;
      background: #00ff41;
      border-radius: 50%;
      cursor: pointer;
      box-shadow: 0 0 6px #00ff41;
    }

    .settings-slider::-moz-range-thumb {
      width: 14px;
      height: 14px;
      background: #00ff41;
      border-radius: 50%;
      cursor: pointer;
      border: none;
      box-shadow: 0 0 6px #00ff41;
    }

    .settings-row span {
      color: #00ff41;
      font-size: 11px;
      min-width: 40px;
      text-align: right;
    }

    .settings-checkbox {
      width: 16px;
      height: 16px;
      accent-color: #00ff41;
      cursor: pointer;
    }

    .settings-select {
      background: #111;
      color: #00ff41;
      border: 1px solid #333;
      padding: 4px 8px;
      font-family: inherit;
      font-size: 11px;
      cursor: pointer;
    }

    .keybind-row {
      display: flex;
      justify-content: space-between;
      padding: 3px 0;
      font-size: 11px;
    }

    .keybind-key {
      color: #00ff41;
      font-weight: bold;
    }

    .keybind-action {
      color: #666;
    }

    .settings-buttons {
      display: flex;
      gap: 16px;
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid rgba(0, 255, 65, 0.2);
    }

    .settings-btn {
      flex: 1;
      padding: 10px 16px;
      font-family: 'Press Start 2P', monospace;
      font-size: 11px;
      cursor: pointer;
      border: 1px solid;
      background: transparent;
      letter-spacing: 2px;
      transition: background 0.2s, box-shadow 0.2s;
    }

    .settings-btn-resume {
      color: #00ff41;
      border-color: #00ff41;
    }
    .settings-btn-resume:hover {
      background: rgba(0, 255, 65, 0.15);
      box-shadow: 0 0 12px rgba(0, 255, 65, 0.3);
    }

    .settings-btn-quit {
      color: #ff0040;
      border-color: #ff0040;
    }
    .settings-btn-quit:hover {
      background: rgba(255, 0, 64, 0.15);
      box-shadow: 0 0 12px rgba(255, 0, 64, 0.3);
    }

    /* Scrollbar styling */
    .settings-panel::-webkit-scrollbar {
      width: 4px;
    }
    .settings-panel::-webkit-scrollbar-track {
      background: #111;
    }
    .settings-panel::-webkit-scrollbar-thumb {
      background: #00ff41;
      border-radius: 2px;
    }
  `;
  document.head.appendChild(style);
}
