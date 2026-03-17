// LABYRINTH 2D — HUD Panel & Minimap & Combat Log
// Shows DEF stat, floor narrative, difficulty tier, ECHO status

const MAX_LOG_LINES = 5;
let combatLogLines = [];

function updateHUD(gameState) {
  const p = gameState.player;
  const dg = gameState.dungeon;
  const biome = dg ? dg.biome : null;

  // Biome name
  const biomeEl = document.getElementById('hud-biome');
  if (biomeEl) biomeEl.textContent = biome ? biome.name : '---';

  // Floor narrative
  const narrativeEl = document.getElementById('hud-narrative');
  if (narrativeEl && dg && dg.narrative) {
    narrativeEl.textContent = dg.narrative.name;
    narrativeEl.title = dg.narrative.flavor;
  } else if (narrativeEl) {
    narrativeEl.textContent = '';
  }

  // Difficulty tier
  const diffEl = document.getElementById('hud-difficulty');
  if (diffEl && dg && dg.difficulty) {
    diffEl.textContent = dg.difficulty.label;
    // Color code difficulty
    switch (dg.difficultyKey) {
      case 'generous':  diffEl.style.color = '#44ff88'; break;
      case 'normal':    diffEl.style.color = '#ffdd00'; break;
      case 'hostile':   diffEl.style.color = '#ff6644'; break;
      case 'nightmare': diffEl.style.color = '#ff0040'; break;
    }
  } else if (diffEl) {
    diffEl.textContent = 'NORMAL';
  }

  // Depth
  const depthEl = document.getElementById('hud-depth');
  if (depthEl) depthEl.textContent = `F${gameState.depth}`;

  // HP
  const hpPct = Math.max(0, p.hp / p.maxHp * 100);
  const hpBar = document.getElementById('hud-hp-bar');
  if (hpBar) hpBar.style.width = hpPct + '%';
  const hpText = document.getElementById('hud-hp');
  if (hpText) hpText.textContent = `${Math.max(0, p.hp)}/${p.maxHp}`;

  // XP
  const xpPct = p.xpNext > 0 ? Math.min(100, p.xp / p.xpNext * 100) : 0;
  const xpBar = document.getElementById('hud-xp-bar');
  if (xpBar) xpBar.style.width = xpPct + '%';
  const lvlText = document.getElementById('hud-lvl');
  if (lvlText) lvlText.textContent = p.lvl;

  // Stats
  const atkEl = document.getElementById('hud-atk');
  if (atkEl) atkEl.textContent = p.totalAtk;
  const defEl = document.getElementById('hud-def');
  if (defEl) defEl.textContent = p.totalDef;
  const goldEl = document.getElementById('hud-gold');
  if (goldEl) goldEl.textContent = p.gold;
  const killsEl = document.getElementById('hud-kills');
  if (killsEl) killsEl.textContent = p.kills;

  // Scrolls
  const scrollEl = document.getElementById('hud-scrolls');
  if (scrollEl) scrollEl.textContent = p.scrolls || 0;

  // Equipment
  const wpnEl = document.getElementById('hud-wpn');
  if (wpnEl) wpnEl.textContent = p.equipment.weapon ? `${p.equipment.weapon.name} +${p.equipment.weapon.atkBonus}` : '---';
  const armEl = document.getElementById('hud-arm');
  if (armEl) armEl.textContent = p.equipment.armor ? `${p.equipment.armor.name} +${p.equipment.armor.defBonus}` : '---';

  // ECHO status
  const echo = gameState.echo;
  const echoSection = document.getElementById('echo-section');
  if (echoSection && echo) {
    echoSection.style.display = 'block';
    const echoHpEl = document.getElementById('echo-hp');
    const echoBehaviorEl = document.getElementById('echo-behavior');
    const echoGoldEl = document.getElementById('echo-gold');
    const echoLvlEl = document.getElementById('echo-lvl');
    const echoHpBar = document.getElementById('echo-hp-bar');

    if (echo.alive) {
      if (echoHpEl) echoHpEl.textContent = `${echo.hp}/${echo.maxHp}`;
      if (echoBehaviorEl) {
        echoBehaviorEl.textContent = echo.behavior.toUpperCase();
        // Color behavior
        switch (echo.behavior) {
          case 'hunt':        echoBehaviorEl.style.color = '#ff4444'; break;
          case 'flee':        echoBehaviorEl.style.color = '#ffaa00'; break;
          case 'pvp':         echoBehaviorEl.style.color = '#ff0040'; break;
          case 'extract':
          case 'extract_run': echoBehaviorEl.style.color = '#44ff88'; break;
          case 'loot':        echoBehaviorEl.style.color = '#ffdd00'; break;
          default:            echoBehaviorEl.style.color = '#00ffff'; break;
        }
      }
      if (echoGoldEl) echoGoldEl.textContent = echo.gold;
      if (echoLvlEl) echoLvlEl.textContent = echo.lvl;
      if (echoHpBar) {
        const echoPct = Math.max(0, echo.hp / echo.maxHp * 100);
        echoHpBar.style.width = echoPct + '%';
      }
    } else {
      if (echoHpEl) echoHpEl.textContent = 'DEAD';
      if (echoBehaviorEl) { echoBehaviorEl.textContent = `RESPAWN ${echo.respawnTimer}`; echoBehaviorEl.style.color = '#666'; }
      if (echoGoldEl) echoGoldEl.textContent = '0';
      if (echoHpBar) echoHpBar.style.width = '0%';
    }
  }
}

function addLogMessage(msg, type) {
  combatLogLines.push({ msg, type: type || '' });
  if (combatLogLines.length > MAX_LOG_LINES) {
    combatLogLines.shift();
  }
  renderCombatLog();
}

function addLogMessages(messages) {
  for (const m of messages) {
    combatLogLines.push({ msg: m.msg, type: m.type || '' });
  }
  while (combatLogLines.length > MAX_LOG_LINES) {
    combatLogLines.shift();
  }
  renderCombatLog();
}

function renderCombatLog() {
  const logEl = document.getElementById('combat-log');
  if (!logEl) return;
  logEl.innerHTML = combatLogLines.map(l =>
    `<div class="log-line ${l.type}">${l.msg}</div>`
  ).join('');
}

function drawMinimap(gameState) {
  const canvas = document.getElementById('minimap-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dg = gameState.dungeon;
  if (!dg) return;

  const cw = canvas.width;
  const ch = canvas.height;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, cw, ch);

  const scaleX = cw / dg.width;
  const scaleY = ch / dg.height;
  const scale = Math.min(scaleX, scaleY);
  const ox = (cw - dg.width * scale) / 2;
  const oy = (ch - dg.height * scale) / 2;

  const visited = gameState.visited;
  const tiles = dg.tiles;

  // Draw visited tiles
  for (let y = 0; y < dg.height; y++) {
    for (let x = 0; x < dg.width; x++) {
      if (!visited[y] || !visited[y][x]) continue;
      const t = tiles[y][x];
      if (t === T_WALL) {
        ctx.fillStyle = 'rgba(60, 70, 80, 0.6)';
      } else if (t === T_FLOOR || t === T_CORRIDOR || t === T_DOOR) {
        ctx.fillStyle = 'rgba(40, 50, 60, 0.8)';
      } else if (t === T_STAIRS) {
        ctx.fillStyle = '#ffdd00';
      }
      ctx.fillRect(ox + x * scale, oy + y * scale, Math.ceil(scale), Math.ceil(scale));
    }
  }

  // Monsters (red dots)
  if (dg.monsters) {
    for (const m of dg.monsters) {
      if (!m.alive) continue;
      if (visited[m.y] && visited[m.y][m.x]) {
        ctx.fillStyle = m.boss ? '#ffaa00' : '#ff4444';
        const sz = m.boss ? 3 : 2;
        ctx.fillRect(ox + m.x * scale, oy + m.y * scale, sz, sz);
      }
    }
  }

  // Items (yellow dots)
  if (dg.items) {
    for (const it of dg.items) {
      if (it.pickedUp) continue;
      if (visited[it.y] && visited[it.y][it.x]) {
        ctx.fillStyle = '#ffdd00';
        ctx.fillRect(ox + it.x * scale, oy + it.y * scale, 2, 2);
      }
    }
  }

  // Stairs (white)
  if (dg.stairs && visited[dg.stairs.y] && visited[dg.stairs.y][dg.stairs.x]) {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(ox + dg.stairs.x * scale - 1, oy + dg.stairs.y * scale - 1, 4, 4);
  }

  // ECHO (cyan dot)
  const echo = gameState.echo;
  if (echo && echo.alive) {
    ctx.fillStyle = '#00ffff';
    ctx.fillRect(ox + echo.x * scale - 1, oy + echo.y * scale - 1, 3, 3);
  }

  // Player (bright cyan dot, always visible)
  const p = gameState.player;
  ctx.fillStyle = '#00dcff';
  ctx.fillRect(ox + p.x * scale - 1, oy + p.y * scale - 1, 4, 4);

  // Border
  ctx.strokeStyle = 'rgba(0, 180, 220, 0.3)';
  ctx.lineWidth = 1;
  ctx.strokeRect(0, 0, cw, ch);
}

// Tutorial system
const TUTORIAL_TIPS = {
  MOVE: { text: 'WASD or Arrow Keys to move through the dungeon', shown: false },
  COMBAT: { text: 'Walk into enemies to attack them', shown: false },
  PICKUP: { text: 'Walk over items to pick them up', shown: false },
  STAIRS: { text: 'Find the glowing stairs to descend deeper', shown: false },
  SCROLL: { text: 'Press Q to use a Scroll (random powerful effect)', shown: false },
  ECHO: { text: 'ECHO is your rival AI companion — it hunts, loots, and may turn hostile', shown: false },
  SAVE: { text: 'Press Ctrl+S to save your progress', shown: false },
};

let currentTip = null;
let tipTimeout = null;

function initTutorial() {
  const stored = localStorage.getItem('lab2d_tutorial_done');
  if (stored === 'true') {
    for (const k in TUTORIAL_TIPS) TUTORIAL_TIPS[k].shown = true;
    return;
  }
  setTimeout(() => showTip('MOVE'), 1500);
}

function showTip(key) {
  const tip = TUTORIAL_TIPS[key];
  if (!tip || tip.shown || currentTip) return;
  tip.shown = true;
  currentTip = key;

  const el = document.getElementById('tutorial-tip');
  const textEl = document.getElementById('tip-text');
  if (el && textEl) {
    textEl.textContent = tip.text;
    el.style.display = 'block';
    el.style.opacity = '1';
  }

  if (tipTimeout) clearTimeout(tipTimeout);
  tipTimeout = setTimeout(() => {
    if (el) {
      el.style.opacity = '0';
      setTimeout(() => { el.style.display = 'none'; currentTip = null; }, 500);
    }
    currentTip = null;

    const allDone = Object.values(TUTORIAL_TIPS).every(t => t.shown);
    if (allDone) localStorage.setItem('lab2d_tutorial_done', 'true');
  }, 4500);
}

function checkTutorialTriggers(gameState) {
  const p = gameState.player;
  const dg = gameState.dungeon;
  if (!dg) return;

  if (!TUTORIAL_TIPS.COMBAT.shown && dg.monsters) {
    const near = dg.monsters.some(m => m.alive && Math.abs(m.x - p.x) + Math.abs(m.y - p.y) <= 3);
    if (near) showTip('COMBAT');
  }
  if (!TUTORIAL_TIPS.PICKUP.shown && dg.items) {
    const near = dg.items.some(it => !it.pickedUp && Math.abs(it.x - p.x) + Math.abs(it.y - p.y) <= 3);
    if (near) showTip('PICKUP');
  }
  if (!TUTORIAL_TIPS.STAIRS.shown && p.kills >= 1) {
    showTip('STAIRS');
  }
  if (!TUTORIAL_TIPS.SCROLL.shown && (p.scrolls || 0) >= 1) {
    showTip('SCROLL');
  }
  if (!TUTORIAL_TIPS.ECHO.shown && gameState.echo && gameState.echo.alive) {
    const eDist = Math.abs(gameState.echo.x - p.x) + Math.abs(gameState.echo.y - p.y);
    if (eDist <= 5) showTip('ECHO');
  }
  if (!TUTORIAL_TIPS.SAVE.shown && gameState.depth >= 2) {
    setTimeout(() => showTip('SAVE'), 2000);
  }
}

// Save/Load system (localStorage)
const SAVE_KEY = 'labyrinth2d_save_v2';

function saveGame(gameState) {
  const data = {
    version: 2,
    timestamp: Date.now(),
    depth: gameState.depth,
    totalKills: gameState.totalKills,
    turnCount: gameState.turnCount,
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
      potions: gameState.player.potions,
      scrolls: gameState.player.scrolls || 0,
      equipment: gameState.player.equipment,
    },
    sessionStats: gameState.sessionStats,
  };
  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify(data));
    const notif = document.getElementById('save-notification');
    if (notif) {
      notif.style.opacity = '1';
      setTimeout(() => { notif.style.opacity = '0'; }, 1500);
    }
    return true;
  } catch (e) {
    return false;
  }
}

function loadGame() {
  try {
    // Try v2 first, fall back to v1
    let raw = localStorage.getItem(SAVE_KEY);
    if (!raw) raw = localStorage.getItem('labyrinth2d_save_v1');
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function applySave(saveData, gameState) {
  if (!saveData) return false;
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
  gameState.player.scrolls = p.scrolls || 0;
  if (p.equipment) gameState.player.equipment = p.equipment;
  gameState.depth = saveData.depth || 1;
  gameState.totalKills = saveData.totalKills || 0;
  gameState.turnCount = saveData.turnCount || 0;
  if (saveData.sessionStats) Object.assign(gameState.sessionStats, saveData.sessionStats);
  return true;
}
