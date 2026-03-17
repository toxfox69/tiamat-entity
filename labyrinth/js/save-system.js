// LABYRINTH: TIAMAT'S DESCENT — Save/Load System
// Serializes game state to localStorage + filesystem (via preload bridge)
// Auto-saves every 60 seconds, manual save on Ctrl+S

const SAVE_KEY = 'labyrinth_save_v2';
const SETTINGS_KEY = 'labyrinth_settings_v1';
const AUTO_SAVE_INTERVAL = 60000; // 60 seconds

let autoSaveTimer = null;
let getGameStateFn = null;
let lastSaveTime = 0;

// ─── Save Game ───
export function saveGame(gameState) {
  if (!gameState) return false;

  const saveData = {
    version: 2,
    timestamp: Date.now(),
    player: {
      hp: gameState.player.hp,
      maxHp: gameState.player.maxHp,
      atk: gameState.player.atk,
      def: gameState.player.def,
      lvl: gameState.player.lvl,
      xp: gameState.player.xp,
      xpNext: gameState.player.xpNext,
      gold: gameState.player.gold,
      kills: gameState.player.kills,
      potions: gameState.player.potions || 0,
      equipment: gameState.player.equipment || {},
      x: gameState.player.x,
      y: gameState.player.y,
      dir: gameState.player.dir,
    },
    depth: gameState.depth || 1,
    totalKills: gameState.totalKills || 0,
    turnCount: gameState.turnCount || 0,
    sessionStats: {
      floorsCleared: gameState.sessionStats?.floorsCleared || 0,
      monstersKilled: gameState.sessionStats?.monstersKilled || 0,
      goldEarned: gameState.sessionStats?.goldEarned || 0,
      deaths: gameState.sessionStats?.deaths || 0,
      maxDepth: gameState.sessionStats?.maxDepth || 1,
    },
    achievements: getLocalAchievements(),
    tutorialComplete: localStorage.getItem('labyrinth_tutorial_complete') === 'true',
  };

  try {
    const json = JSON.stringify(saveData);
    localStorage.setItem(SAVE_KEY, json);

    // Also save via Electron preload bridge (filesystem)
    if (window.labyrinth && window.labyrinth.saveState) {
      window.labyrinth.saveState('save_v2', saveData);
    }

    lastSaveTime = Date.now();
    console.log('[SAVE] Game saved — depth', saveData.depth, 'lvl', saveData.player.lvl);
    return true;
  } catch (e) {
    console.error('[SAVE] Failed:', e);
    return false;
  }
}

// ─── Load Game ───
export function loadGame() {
  try {
    // Try localStorage first
    let raw = localStorage.getItem(SAVE_KEY);

    // Try Electron filesystem fallback
    if (!raw && window.labyrinth && window.labyrinth.loadState) {
      const fsData = window.labyrinth.loadState('save_v2');
      if (fsData) {
        raw = JSON.stringify(fsData);
      }
    }

    if (!raw) return null;

    const data = JSON.parse(raw);
    if (!data.version || data.version < 2) {
      // Migrate v1 saves
      return migrateV1(data);
    }

    console.log('[LOAD] Restored save from', new Date(data.timestamp).toISOString(),
      '— depth', data.depth, 'lvl', data.player.lvl);
    return data;
  } catch (e) {
    console.error('[LOAD] Failed:', e);
    return null;
  }
}

// ─── Migrate v1 save to v2 ───
function migrateV1(data) {
  if (!data || !data.player) return null;
  data.version = 2;
  data.player.x = data.player.x || 0;
  data.player.y = data.player.y || 0;
  data.player.dir = data.player.dir || 0;
  data.player.potions = data.player.potions || 0;
  data.achievements = [];
  data.tutorialComplete = false;
  console.log('[LOAD] Migrated v1 save to v2');
  return data;
}

// ─── Apply loaded save to game state ───
export function applySave(saveData, gameState) {
  if (!saveData || !gameState) return false;

  const p = saveData.player;
  gameState.player.hp = p.hp;
  gameState.player.maxHp = p.maxHp;
  gameState.player.atk = p.atk;
  gameState.player.def = p.def;
  gameState.player.lvl = p.lvl;
  gameState.player.xp = p.xp;
  gameState.player.xpNext = p.xpNext;
  gameState.player.gold = p.gold;
  gameState.player.kills = p.kills;
  gameState.player.potions = p.potions || 0;
  if (p.equipment) gameState.player.equipment = p.equipment;

  gameState.depth = saveData.depth || 1;
  gameState.totalKills = saveData.totalKills || 0;
  gameState.turnCount = saveData.turnCount || 0;

  if (saveData.sessionStats) {
    Object.assign(gameState.sessionStats, saveData.sessionStats);
  }

  // Restore achievements
  if (saveData.achievements && saveData.achievements.length > 0) {
    localStorage.setItem('labyrinth_achievements', JSON.stringify(saveData.achievements));
  }

  if (saveData.tutorialComplete) {
    localStorage.setItem('labyrinth_tutorial_complete', 'true');
  }

  return true;
}

// ─── Delete Save ───
export function deleteSave() {
  localStorage.removeItem(SAVE_KEY);
  if (window.labyrinth && window.labyrinth.saveState) {
    window.labyrinth.saveState('save_v2', null);
  }
  console.log('[SAVE] Save deleted — new game');
}

// ─── Check if save exists ───
export function hasSave() {
  if (localStorage.getItem(SAVE_KEY)) return true;
  if (window.labyrinth && window.labyrinth.loadState) {
    return window.labyrinth.loadState('save_v2') !== null;
  }
  return false;
}

// ─── Auto-save system ───
export function startAutoSave(getStateFn) {
  getGameStateFn = getStateFn;
  stopAutoSave();
  autoSaveTimer = setInterval(() => {
    const state = getGameStateFn();
    if (state && state.player && state.player.hp > 0) {
      saveGame(state);
    }
  }, AUTO_SAVE_INTERVAL);

  // Ctrl+S manual save
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      if (getGameStateFn) {
        const state = getGameStateFn();
        if (state) {
          saveGame(state);
          showSaveNotification();
        }
      }
    }
  });

  console.log('[SAVE] Auto-save started (every 60s)');
}

export function stopAutoSave() {
  if (autoSaveTimer) {
    clearInterval(autoSaveTimer);
    autoSaveTimer = null;
  }
}

// ─── Save notification flash ───
function showSaveNotification() {
  let notif = document.getElementById('save-notification');
  if (!notif) {
    notif = document.createElement('div');
    notif.id = 'save-notification';
    notif.style.cssText = `
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      font-family: 'Press Start 2P', monospace;
      font-size: 14px;
      color: #00ff41;
      text-shadow: 0 0 10px #00ff41;
      background: rgba(0, 0, 0, 0.7);
      padding: 12px 24px;
      border: 1px solid #00ff41;
      z-index: 10000;
      pointer-events: none;
      transition: opacity 0.5s;
    `;
    document.body.appendChild(notif);
  }
  notif.textContent = 'GAME SAVED';
  notif.style.opacity = '1';
  setTimeout(() => { notif.style.opacity = '0'; }, 1500);
}

// ─── Steam Cloud Save sync ───
export function syncCloudSave() {
  // If Steam cloud is available via greenworks, sync
  if (window.labyrinth && window.labyrinth.steam && window.labyrinth.steam.available) {
    try {
      const localSave = localStorage.getItem(SAVE_KEY);
      if (localSave) {
        // Write to Steam cloud
        window.labyrinth.steam.cloudWrite('save_v2.json', localSave);
        console.log('[CLOUD] Save synced to Steam Cloud');
      }

      // Read cloud save for conflict resolution
      const cloudSave = window.labyrinth.steam.cloudRead('save_v2.json');
      if (cloudSave) {
        const cloudData = JSON.parse(cloudSave);
        const localData = localSave ? JSON.parse(localSave) : null;

        // Newest timestamp wins
        if (localData && cloudData.timestamp > localData.timestamp) {
          localStorage.setItem(SAVE_KEY, cloudSave);
          console.log('[CLOUD] Cloud save is newer — using cloud version');
          return JSON.parse(cloudSave);
        }
      }
    } catch (e) {
      console.warn('[CLOUD] Sync failed:', e);
    }
  }
  return null;
}

// ─── Helper: get local achievements ───
function getLocalAchievements() {
  try {
    return JSON.parse(localStorage.getItem('labyrinth_achievements') || '[]');
  } catch (e) {
    return [];
  }
}

export function getLastSaveTime() { return lastSaveTime; }
