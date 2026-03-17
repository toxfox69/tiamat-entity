// LABYRINTH: TIAMAT'S DESCENT — Steam Integration
// Achievement unlocks, rich presence, stats tracking
// Falls back to localStorage when Steam is unavailable

let steamAvailable = false;

const ACHIEVEMENTS = {
  FIRST_BLOOD:     { id: 'ACH_FIRST_BLOOD',     name: 'First Blood',         desc: 'Kill your first monster' },
  DUNGEON_DIVER:   { id: 'ACH_DUNGEON_DIVER',   name: 'Dungeon Diver',       desc: 'Reach floor 5' },
  DRAGON_SLAYER:   { id: 'ACH_DRAGON_SLAYER',    name: 'Dragon Slayer',       desc: 'Defeat a boss' },
  HOARDER:         { id: 'ACH_HOARDER',          name: 'Hoarder',             desc: 'Collect 1000 gold' },
  SURVIVOR:        { id: 'ACH_SURVIVOR',         name: 'Survivor',            desc: 'Reach floor 10 without dying' },
  INTO_THE_ABYSS:  { id: 'ACH_INTO_ABYSS',       name: 'Into the Abyss',      desc: 'Reach floor 10' },
  ROCK_BOTTOM:     { id: 'ACH_ROCK_BOTTOM',      name: 'Rock Bottom',         desc: 'Reach floor 20' },
  CENTURION:       { id: 'ACH_CENTURION',        name: 'Centurion',           desc: 'Kill 100 monsters' },
  GENOCIDE:        { id: 'ACH_GENOCIDE',          name: 'Genocide',            desc: 'Kill 1000 monsters' },
  SAFE_HANDS:      { id: 'ACH_SAFE_HANDS',       name: 'Safe Hands',          desc: 'Extract successfully 10 times' },
  PERSISTENT:      { id: 'ACH_PERSISTENT',        name: 'Persistent',          desc: 'Die 10 times' },
  KILLING_SPREE:   { id: 'ACH_KILLING_SPREE',    name: 'Killing Spree',       desc: 'Get a 5x kill streak' },
  RIVAL_ELIMINATED:{ id: 'ACH_RIVAL_ELIMINATED', name: 'Rival Eliminated',    desc: 'Kill ECHO in PvP' },
  VETERAN:         { id: 'ACH_VETERAN',           name: 'Veteran',             desc: 'Reach level 10' },
  WORLD_EXPLORER:  { id: 'ACH_WORLD_EXPLORER',   name: 'World Explorer',      desc: 'Visit all 7 biomes' },
};

// Stats we track locally + sync to Steam
const stats = {
  totalKills: 0,
  totalDeaths: 0,
  totalGold: 0,
  floorsCleared: 0,
  bossKills: 0,
  extractionCount: 0,
  maxFloor: 0,
  maxKillStreak: 0,
  biomesVisited: new Set(),
  deathlessFloors: 0, // Consecutive floors without dying
};

// ─── Init ───
export function initSteamIntegration() {
  // Check for Electron preload bridge
  if (window.labyrinth && window.labyrinth.steam && window.labyrinth.steam.available) {
    steamAvailable = true;
    console.log('[STEAM] Integration active');
  } else {
    steamAvailable = false;
    console.log('[STEAM] Not available — tracking locally');
  }

  // Load local stats
  loadLocalStats();
  return steamAvailable;
}

export function isSteamAvailable() { return steamAvailable; }

// ─── Achievement Unlock ───
export function unlockAchievement(key) {
  const ach = ACHIEVEMENTS[key];
  if (!ach) return;

  // Check if already unlocked
  const unlocked = getUnlockedAchievements();
  if (unlocked.includes(key)) return;

  if (steamAvailable) {
    try {
      window.labyrinth.steam.unlockAchievement(ach.id);
      console.log(`[STEAM] Achievement unlocked: ${ach.name}`);
    } catch (e) {
      console.warn('[STEAM] Achievement error:', e);
    }
  }

  // Always track locally too
  unlocked.push(key);
  localStorage.setItem('labyrinth_achievements', JSON.stringify(unlocked));
  console.log(`[ACH] ${ach.name} — ${ach.desc}`);

  // Show achievement popup
  showAchievementPopup(ach);
}

// ─── Check achievements based on game state ───
export function checkAchievements(gameState) {
  if (!gameState) return;

  const p = gameState.player;
  const s = gameState.sessionStats;

  // Kill-based
  if (gameState.totalKills >= 1) unlockAchievement('FIRST_BLOOD');
  if (gameState.totalKills >= 100) unlockAchievement('CENTURION');
  if (gameState.totalKills >= 1000) unlockAchievement('GENOCIDE');

  // Depth-based
  if (gameState.depth >= 5) unlockAchievement('DUNGEON_DIVER');
  if (gameState.depth >= 10) unlockAchievement('INTO_THE_ABYSS');
  if (gameState.depth >= 20) unlockAchievement('ROCK_BOTTOM');

  // Gold
  if (p.gold >= 1000) unlockAchievement('HOARDER');

  // Level
  if (p.lvl >= 10) unlockAchievement('VETERAN');

  // Kill streak
  if (gameState.killStreak && gameState.killStreak.count >= 5) unlockAchievement('KILLING_SPREE');

  // Deaths
  if (s && s.deaths >= 10) unlockAchievement('PERSISTENT');

  // Survivor (floor 10, 0 deaths) — track deathless floors
  if (stats.deathlessFloors >= 10) unlockAchievement('SURVIVOR');
}

// ─── Event Handlers (wire these into engine.js) ───
export function onMonsterKill(monster, gameState) {
  stats.totalKills++;
  if (monster.boss) {
    stats.bossKills++;
    unlockAchievement('DRAGON_SLAYER');
  }
  saveLocalStats();
  checkAchievements(gameState);
}

export function onPlayerDeath(gameState) {
  stats.totalDeaths++;
  stats.deathlessFloors = 0;
  saveLocalStats();
  checkAchievements(gameState);
}

export function onFloorCleared(depth, gameState) {
  stats.floorsCleared++;
  stats.deathlessFloors++;
  if (depth > stats.maxFloor) stats.maxFloor = depth;
  saveLocalStats();
  checkAchievements(gameState);
  updateRichPresence(gameState);
}

export function onExtraction(gameState) {
  stats.extractionCount++;
  if (stats.extractionCount >= 10) unlockAchievement('SAFE_HANDS');
  saveLocalStats();
}

export function onEchoKilled(gameState) {
  unlockAchievement('RIVAL_ELIMINATED');
}

export function onBiomeVisited(biomeName) {
  stats.biomesVisited.add(biomeName);
  if (stats.biomesVisited.size >= 7) unlockAchievement('WORLD_EXPLORER');
  saveLocalStats();
}

// ─── Rich Presence ───
export function updateRichPresence(gameState) {
  if (!steamAvailable || !gameState) return;

  try {
    const biome = gameState.biome?.name || 'Unknown';
    const floor = gameState.depth || 1;
    const status = `Floor ${floor} — ${biome}`;

    // Steam rich presence update via preload bridge
    if (window.labyrinth.steam.setRichPresence) {
      window.labyrinth.steam.setRichPresence('status', status);
      window.labyrinth.steam.setRichPresence('steam_display', '#StatusFloor');
    }
  } catch (e) {
    // Silently fail — non-critical
  }
}

// ─── Local Stats Persistence ───
function saveLocalStats() {
  try {
    const data = {
      ...stats,
      biomesVisited: Array.from(stats.biomesVisited),
    };
    localStorage.setItem('labyrinth_stats', JSON.stringify(data));
  } catch (e) { /* ignore */ }
}

function loadLocalStats() {
  try {
    const raw = localStorage.getItem('labyrinth_stats');
    if (raw) {
      const data = JSON.parse(raw);
      Object.assign(stats, data);
      stats.biomesVisited = new Set(data.biomesVisited || []);
    }
  } catch (e) {
    // Fresh stats
  }
}

// ─── Get unlocked achievements ───
export function getUnlockedAchievements() {
  try {
    return JSON.parse(localStorage.getItem('labyrinth_achievements') || '[]');
  } catch (e) {
    return [];
  }
}

export function getAchievements() { return ACHIEVEMENTS; }
export function getStats() { return { ...stats, biomesVisited: Array.from(stats.biomesVisited) }; }

// ─── Achievement popup ───
function showAchievementPopup(ach) {
  const popup = document.createElement('div');
  popup.style.cssText = `
    position: fixed;
    top: 60px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0, 10, 0, 0.9);
    border: 1px solid #00ff41;
    padding: 12px 24px;
    z-index: 10000;
    text-align: center;
    animation: achievementSlide 0.4s ease-out;
    pointer-events: none;
    font-family: 'JetBrains Mono', monospace;
  `;
  popup.innerHTML = `
    <div style="font-family: 'Press Start 2P', monospace; font-size: 10px; color: #ffdd00; text-shadow: 0 0 8px #ffdd00; letter-spacing: 2px; margin-bottom: 6px;">ACHIEVEMENT UNLOCKED</div>
    <div style="font-size: 14px; color: #00ff41; text-shadow: 0 0 6px #00ff41; font-weight: bold;">${ach.name}</div>
    <div style="font-size: 10px; color: #888; margin-top: 4px;">${ach.desc}</div>
  `;
  document.body.appendChild(popup);

  // Inject animation if not exists
  if (!document.getElementById('achievement-css')) {
    const style = document.createElement('style');
    style.id = 'achievement-css';
    style.textContent = `
      @keyframes achievementSlide {
        from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
        to { opacity: 1; transform: translateX(-50%) translateY(0); }
      }
    `;
    document.head.appendChild(style);
  }

  setTimeout(() => {
    popup.style.transition = 'opacity 0.5s';
    popup.style.opacity = '0';
    setTimeout(() => popup.remove(), 600);
  }, 3000);
}
