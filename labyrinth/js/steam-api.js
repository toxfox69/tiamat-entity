// LABYRINTH — Steam API Integration (Achievements + Cloud Saves)
// Uses greenworks/steamworks.js when running in Electron
// Falls back gracefully in browser mode

let steamReady = false;
let greenworks = null;

// Achievement definitions
const ACHIEVEMENTS = {
  FIRST_KILL:    { id: 'ACH_FIRST_KILL',    name: 'First Blood',         desc: 'Kill your first monster' },
  DEPTH_5:       { id: 'ACH_DEPTH_5',       name: 'Delving Deep',        desc: 'Reach depth 5' },
  DEPTH_10:      { id: 'ACH_DEPTH_10',      name: 'Into the Abyss',      desc: 'Reach depth 10' },
  DEPTH_20:      { id: 'ACH_DEPTH_20',      name: 'Rock Bottom',         desc: 'Reach depth 20' },
  KILL_BOSS:     { id: 'ACH_KILL_BOSS',     name: 'Boss Slayer',         desc: 'Defeat a boss' },
  KILL_100:      { id: 'ACH_KILL_100',      name: 'Centurion',           desc: 'Kill 100 monsters' },
  KILL_1000:     { id: 'ACH_KILL_1000',     name: 'Genocide',            desc: 'Kill 1000 monsters' },
  GOLD_500:      { id: 'ACH_GOLD_500',      name: 'Dragon Hoard',        desc: 'Accumulate 500 gold' },
  EXTRACT_10:    { id: 'ACH_EXTRACT_10',    name: 'Safe Hands',          desc: 'Extract successfully 10 times' },
  DIE_10:        { id: 'ACH_DIE_10',        name: 'Persistent',          desc: 'Die 10 times' },
  STREAK_5:      { id: 'ACH_STREAK_5',      name: 'Killing Spree',       desc: 'Get a 5x kill streak' },
  STREAK_10:     { id: 'ACH_STREAK_10',     name: 'Rampage',             desc: 'Get a 10x kill streak' },
  KILL_ECHO:     { id: 'ACH_KILL_ECHO',     name: 'Rival Eliminated',    desc: 'Kill ECHO in PvP' },
  LEVEL_10:      { id: 'ACH_LEVEL_10',      name: 'Veteran',             desc: 'Reach level 10' },
  ALL_BIOMES:    { id: 'ACH_ALL_BIOMES',    name: 'World Explorer',      desc: 'Visit all 7 biomes' },
};

export function initSteam() {
  try {
    greenworks = require('greenworks');
    if (greenworks.init()) {
      steamReady = true;
      console.log('[STEAM] Initialized, user:', greenworks.getSteamId().screenName);
    }
  } catch (e) {
    // Not running in Electron or greenworks not available
    steamReady = false;
  }
  return steamReady;
}

export function isSteamReady() { return steamReady; }

export function unlockAchievement(key) {
  const ach = ACHIEVEMENTS[key];
  if (!ach) return;

  if (steamReady && greenworks) {
    try {
      greenworks.activateAchievement(ach.id, () => {
        console.log(`[STEAM] Achievement unlocked: ${ach.name}`);
      }, (err) => {
        console.error(`[STEAM] Achievement error: ${err}`);
      });
    } catch (e) {
      console.error('[STEAM] Achievement failed:', e);
    }
  } else {
    // Browser fallback: track locally
    try {
      const unlocked = JSON.parse(localStorage.getItem('labyrinth_achievements') || '[]');
      if (!unlocked.includes(key)) {
        unlocked.push(key);
        localStorage.setItem('labyrinth_achievements', JSON.stringify(unlocked));
        console.log(`[ACH] Unlocked: ${ach.name} — ${ach.desc}`);
      }
    } catch (e) {}
  }
}

// Check and unlock achievements based on game state
export function checkAchievements(gameState) {
  const p = gameState.player;
  const stats = gameState.sessionStats;

  if (gameState.totalKills >= 1) unlockAchievement('FIRST_KILL');
  if (gameState.totalKills >= 100) unlockAchievement('KILL_100');
  if (gameState.totalKills >= 1000) unlockAchievement('KILL_1000');
  if (gameState.depth >= 5) unlockAchievement('DEPTH_5');
  if (gameState.depth >= 10) unlockAchievement('DEPTH_10');
  if (gameState.depth >= 20) unlockAchievement('DEPTH_20');
  if (p.gold >= 500) unlockAchievement('GOLD_500');
  if (p.lvl >= 10) unlockAchievement('LEVEL_10');
  if (stats.deaths >= 10) unlockAchievement('DIE_10');
  if (gameState.killStreak?.count >= 5) unlockAchievement('STREAK_5');
  if (gameState.killStreak?.count >= 10) unlockAchievement('STREAK_10');
}

export function getAchievements() { return ACHIEVEMENTS; }

export function getUnlockedAchievements() {
  if (steamReady && greenworks) {
    // TODO: Query Steam API
    return [];
  }
  try {
    return JSON.parse(localStorage.getItem('labyrinth_achievements') || '[]');
  } catch (e) {
    return [];
  }
}
