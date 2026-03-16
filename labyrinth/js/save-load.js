// LABYRINTH — Save/Load System
// Persists game state to localStorage (browser) or Steam Cloud (Electron)

const SAVE_KEY = 'labyrinth_save_v1';
const AUTO_SAVE_INTERVAL = 30000; // 30 seconds

let autoSaveTimer = null;

export function saveGame(gameState) {
  const saveData = {
    version: 1,
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
      equipment: gameState.player.equipment,
    },
    depth: gameState.depth,
    totalKills: gameState.totalKills,
    sessionStats: { ...gameState.sessionStats },
    permanentStash: gameState.permanentStash || [],
  };

  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify(saveData));
    console.log('[SAVE] Game saved at depth', saveData.depth);
    return true;
  } catch (e) {
    console.error('[SAVE] Failed:', e);
    return false;
  }
}

export function loadGame() {
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data.version !== 1) return null;
    console.log('[LOAD] Restored save from', new Date(data.timestamp).toISOString());
    return data;
  } catch (e) {
    console.error('[LOAD] Failed:', e);
    return null;
  }
}

export function deleteSave() {
  localStorage.removeItem(SAVE_KEY);
  console.log('[SAVE] Save deleted');
}

export function hasSave() {
  return localStorage.getItem(SAVE_KEY) !== null;
}

export function startAutoSave(getStateFn) {
  stopAutoSave();
  autoSaveTimer = setInterval(() => {
    const state = getStateFn();
    if (state) saveGame(state);
  }, AUTO_SAVE_INTERVAL);
}

export function stopAutoSave() {
  if (autoSaveTimer) {
    clearInterval(autoSaveTimer);
    autoSaveTimer = null;
  }
}

// Apply loaded save data to game state
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
  if (p.equipment) gameState.player.equipment = p.equipment;

  gameState.depth = saveData.depth || 1;
  gameState.totalKills = saveData.totalKills || 0;
  if (saveData.sessionStats) {
    Object.assign(gameState.sessionStats, saveData.sessionStats);
  }

  return true;
}
