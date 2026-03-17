// LABYRINTH 2D — Entity System
// Player, monsters, items, ECHO companion AI (full 7-state behavior system)

// XP thresholds per level
const XP_TABLE = [0, 30, 70, 130, 220, 350, 520, 740, 1020, 1400, 1900, 2500, 3300, 4300, 5500, 7000, 9000, 11500, 14500, 18000];

// ─── Player ───
function createPlayer() {
  return {
    x: 0,
    y: 0,
    dir: 0, // 0=N, 1=E, 2=S, 3=W
    hp: 50,
    maxHp: 50,
    atk: 5,
    def: 2,
    lvl: 1,
    xp: 0,
    xpNext: 30,
    gold: 0,
    kills: 0,
    potions: 0,
    scrolls: 0,
    equipment: {
      weapon: null,    // { name, atkBonus }
      armor: null,     // { name, defBonus }
      ring: null,      // { name, effect }
    },
    // Computed stats (base + equipment)
    get totalAtk() {
      let a = this.atk;
      if (this.equipment.weapon) a += this.equipment.weapon.atkBonus;
      return a;
    },
    get totalDef() {
      let d = this.def;
      if (this.equipment.armor) d += this.equipment.armor.defBonus;
      return d;
    },
  };
}

function playerGainXp(player, amount) {
  player.xp += amount;
  let leveledUp = false;
  while (player.xp >= player.xpNext) {
    player.xp -= player.xpNext;
    player.lvl++;
    // Stats boost on level up
    player.maxHp += 8 + Math.floor(player.lvl * 1.5);
    player.hp = player.maxHp; // full heal on level up
    player.atk += 1 + Math.floor(player.lvl / 3);
    player.def += 1 + Math.floor(player.lvl / 4);
    // Next threshold
    if (player.lvl - 1 < XP_TABLE.length) {
      player.xpNext = XP_TABLE[player.lvl - 1];
    } else {
      player.xpNext = Math.floor(player.xpNext * 1.4);
    }
    leveledUp = true;
  }
  return leveledUp;
}

function playerPickupItem(player, item) {
  if (item.pickedUp) return null;
  item.pickedUp = true;

  switch (item.type) {
    case 'potion':
      player.potions++;
      player.hp = Math.min(player.maxHp, player.hp + item.val);
      return { msg: `Picked up ${item.name} (+${item.val} HP)`, type: 'pickup' };
    case 'elixir':
      player.potions++;
      player.hp = Math.min(player.maxHp, player.hp + item.val);
      return { msg: `Picked up Elixir (+${item.val} HP)`, type: 'pickup' };
    case 'gold':
      player.gold += item.val;
      return { msg: `Found ${item.val} gold!`, type: 'pickup' };
    case 'food':
      player.hp = Math.min(player.maxHp, player.hp + item.val);
      return { msg: `Ate ${item.name} (+${item.val} HP)`, type: 'pickup' };
    case 'scroll':
      player.scrolls = (player.scrolls || 0) + 1;
      return { msg: `Found a Scroll! (use with Q)`, type: 'pickup' };
    case 'attack':
      // Equip or upgrade weapon
      if (!player.equipment.weapon || player.equipment.weapon.atkBonus < item.val + Math.floor(player.lvl / 2)) {
        player.equipment.weapon = {
          name: item.name,
          atkBonus: item.val + Math.floor(player.lvl / 2),
        };
        return { msg: `Equipped ${item.name} (+${player.equipment.weapon.atkBonus} ATK)`, type: 'pickup' };
      }
      return { msg: `Found ${item.name} (no upgrade)`, type: 'pickup' };
    case 'defense':
      if (!player.equipment.armor || player.equipment.armor.defBonus < item.val + Math.floor(player.lvl / 3)) {
        player.equipment.armor = {
          name: item.name,
          defBonus: item.val + Math.floor(player.lvl / 3),
        };
        return { msg: `Equipped ${item.name} (+${player.equipment.armor.defBonus} DEF)`, type: 'pickup' };
      }
      return { msg: `Found ${item.name} (no upgrade)`, type: 'pickup' };
    default:
      return { msg: `Found ${item.name}`, type: 'pickup' };
  }
}

// ─── ECHO Companion AI (7-state behavior system from agents.js) ───
// States: explore, hunt, loot, extract, flee, pvp, extract_run

const ECHO_DX = [0, 1, 0, -1];
const ECHO_DY = [-1, 0, 1, 0];

function createEcho(spawnX, spawnY) {
  return {
    x: spawnX,
    y: spawnY,
    hp: 40,
    maxHp: 40,
    atk: 4,
    def: 2,
    lvl: 1,
    xp: 0,
    xpNext: 25,
    gold: 0,
    kills: 0,
    alive: true,
    respawnTimer: 0,

    // AI state
    behavior: 'explore',  // explore, hunt, loot, extract, flee, pvp, extract_run
    target: null,         // { x, y }
    path: [],

    // Extraction
    raidStash: [],
    extracting: false,
    extractTimer: 0,
    extractsCompleted: 0,

    // PvP
    pvpCooldown: 0,
    grudge: false,  // becomes true if player attacks ECHO
  };
}

// BFS pathfinding for ECHO
function echoFindPath(echo, tx, ty, tiles, w, h) {
  const queue = [{ x: echo.x, y: echo.y, path: [] }];
  const visited = new Set();
  visited.add(echo.y * w + echo.x);
  while (queue.length > 0) {
    const cur = queue.shift();
    if (cur.x === tx && cur.y === ty) return cur.path;
    if (cur.path.length > 25) continue;
    for (let d = 0; d < 4; d++) {
      const nx = cur.x + ECHO_DX[d];
      const ny = cur.y + ECHO_DY[d];
      const key = ny * w + nx;
      if (visited.has(key)) continue;
      if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
      if (tiles[ny][nx] === T_WALL) continue;
      visited.add(key);
      queue.push({ x: nx, y: ny, path: [...cur.path, { x: nx, y: ny }] });
    }
  }
  return [];
}

// ECHO decides behavior based on game state
function echoDecideBehavior(echo, gameState) {
  const dg = gameState.dungeon;
  const p = gameState.player;
  if (!dg || !p) return;

  const hpPct = echo.hp / echo.maxHp;
  const distToPlayer = Math.abs(echo.x - p.x) + Math.abs(echo.y - p.y);

  // 1. HP < 25% and stairs exist -> flee
  if (hpPct < 0.25 && dg.stairs) {
    echo.behavior = 'flee';
    return;
  }

  // 2. Player nearby + ECHO has grudge -> pvp
  if (distToPlayer <= 2 && echo.grudge && echo.pvpCooldown <= 0 && hpPct > 0.5) {
    echo.behavior = 'pvp';
    return;
  }

  // 3. On stairs -> extract
  if (dg.stairs && echo.x === dg.stairs.x && echo.y === dg.stairs.y) {
    echo.behavior = 'extract';
    return;
  }

  // 4. Gold > threshold + near stairs -> extract_run
  if (echo.raidStash.length >= 3 && dg.stairs) {
    const distToStairs = Math.abs(echo.x - dg.stairs.x) + Math.abs(echo.y - dg.stairs.y);
    if (distToStairs < 12) {
      echo.behavior = 'extract_run';
      return;
    }
  }

  // 5. Monster nearby -> hunt
  let nearestMonster = null;
  let nearestDist = Infinity;
  for (const m of dg.monsters) {
    if (!m.alive) continue;
    const d = Math.abs(m.x - echo.x) + Math.abs(m.y - echo.y);
    if (d < 8 && d < nearestDist) {
      nearestDist = d;
      nearestMonster = m;
    }
  }
  if (nearestMonster && hpPct > 0.4) {
    echo.behavior = 'hunt';
    echo.target = { x: nearestMonster.x, y: nearestMonster.y };
    return;
  }

  // 6. Item nearby -> loot
  for (const item of dg.items) {
    if (item.pickedUp) continue;
    const d = Math.abs(item.x - echo.x) + Math.abs(item.y - echo.y);
    if (d < 6) {
      echo.behavior = 'loot';
      echo.target = { x: item.x, y: item.y };
      return;
    }
  }

  // 7. Has loot, head to extract
  if (echo.raidStash.length >= 2 && dg.stairs) {
    echo.behavior = 'extract_run';
    return;
  }

  // Default: explore (random room target)
  echo.behavior = 'explore';
}

// ECHO moves one step toward target
function echoMoveToward(echo, tx, ty, gameState) {
  const dg = gameState.dungeon;
  const p = gameState.player;
  if (!dg) return;

  // Recompute path if needed
  if (echo.path.length === 0 || !echo.path[echo.path.length - 1] ||
      echo.path[echo.path.length - 1].x !== tx || echo.path[echo.path.length - 1].y !== ty) {
    echo.path = echoFindPath(echo, tx, ty, dg.tiles, dg.width, dg.height);
  }

  if (echo.path.length > 0) {
    const next = echo.path.shift();
    const nx = next.x, ny = next.y;

    // Don't walk into player
    if (nx === p.x && ny === p.y) return;

    // Check for monster at destination
    const mon = dg.monsters.find(m => m.alive && m.x === nx && m.y === ny);
    if (mon) {
      echoAttackMonster(echo, mon, gameState);
      return;
    }

    echo.x = nx;
    echo.y = ny;

    // Auto-pickup items
    for (const item of dg.items) {
      if (!item.pickedUp && item.x === echo.x && item.y === echo.y) {
        item.pickedUp = true;
        echo.raidStash.push({ name: item.name, type: item.type, val: item.val || 0 });
        if (item.type === 'gold') echo.gold += item.val;
        else if (item.type === 'food' || item.type === 'potion' || item.type === 'elixir') {
          echo.hp = Math.min(echo.maxHp, echo.hp + (item.val || 10));
        }
        addLogMessage('ECHO grabbed ' + item.name, 'echo');
      }
    }
  }
}

// ECHO attacks a monster
function echoAttackMonster(echo, mon, gameState) {
  const dmg = Math.max(1, echo.atk - (mon.def || 0) + Math.floor(Math.random() * 3));
  mon.hp -= dmg;
  addLogMessage('ECHO hit ' + mon.name + ' for ' + dmg, 'echo');

  if (mon.hp <= 0) {
    mon.alive = false;
    echo.xp += (mon.xp || 10);
    echo.kills++;
    addLogMessage('ECHO killed ' + mon.name + '!', 'echo');

    // Level up
    if (echo.xp >= echo.xpNext) {
      echo.lvl++;
      echo.xp -= echo.xpNext;
      echo.xpNext = Math.floor(echo.xpNext * 1.4);
      echo.maxHp += 8;
      echo.hp = echo.maxHp;
      echo.atk += 1;
      echo.def += 1;
      addLogMessage('ECHO leveled up! LVL ' + echo.lvl, 'echo');
    }
  } else {
    // Monster retaliates
    const monDmg = Math.max(1, mon.atk - echo.def + Math.floor(Math.random() * 2));
    echo.hp -= monDmg;
    if (echo.hp <= 0) {
      echoDie(echo, gameState);
    }
  }
}

// ECHO attacks player (PvP)
function echoAttackPlayer(echo, gameState) {
  const p = gameState.player;
  const dmg = Math.max(1, echo.atk - p.totalDef + Math.floor(Math.random() * 3));
  p.hp -= dmg;
  addLogMessage('ECHO attacks YOU for ' + dmg + '!', 'combat');
  echo.pvpCooldown = 5;

  // Player retaliates
  const retDmg = Math.max(1, p.totalAtk - echo.def + Math.floor(Math.random() * 3));
  echo.hp -= retDmg;
  addLogMessage('You retaliate on ECHO for ' + retDmg + '!', 'combat');

  if (echo.hp <= 0) {
    addLogMessage('ECHO eliminated! Dropping loot...', 'pickup');
    echoDropLoot(echo, gameState);
    echoDie(echo, gameState);
  }

  if (p.hp <= 0) {
    return 'player_killed';
  }
  return null;
}

// ECHO drops its loot on death
function echoDropLoot(echo, gameState) {
  const dg = gameState.dungeon;
  if (!dg) return;

  if (echo.gold > 0) {
    dg.items.push({
      x: echo.x, y: echo.y, name: "ECHO's Gold",
      type: 'gold', val: echo.gold, col: '#00ffff', pickedUp: false,
    });
  }
  for (let i = 0; i < Math.min(3, echo.raidStash.length); i++) {
    const item = echo.raidStash[i];
    dg.items.push({
      x: echo.x + (Math.random() > 0.5 ? 1 : 0),
      y: echo.y + (Math.random() > 0.5 ? 1 : 0),
      name: item.name, type: item.type, val: item.val,
      col: '#00ffff', pickedUp: false,
    });
  }
  echo.gold = 0;
  echo.raidStash = [];
}

// ECHO dies
function echoDie(echo, gameState) {
  echo.alive = false;
  echo.respawnTimer = 8;
  echo.raidStash = [];
  echo.gold = 0;
  echo.extracting = false;
  echo.path = [];
  addLogMessage('ECHO is down! Respawning in 8 turns...', 'echo');
}

// ECHO completes extraction
function echoCompleteExtract(echo, gameState) {
  echo.extracting = false;
  echo.extractTimer = 0;
  echo.extractsCompleted++;
  const count = echo.raidStash.length;
  addLogMessage('ECHO extracted with ' + count + ' items!', 'echo');
  echo.raidStash = [];
}

// Main ECHO AI tick — called once per player turn
function updateEchoAI(echo, gameState) {
  if (!echo || !echo.alive) {
    // Handle respawn countdown
    if (echo && !echo.alive) {
      echo.respawnTimer--;
      if (echo.respawnTimer <= 0) {
        echo.alive = true;
        echo.hp = echo.maxHp;
        echo.raidStash = [];
        const dg = gameState.dungeon;
        if (dg && dg.rooms.length > 0) {
          const room = dg.rooms[Math.floor(Math.random() * dg.rooms.length)];
          echo.x = room.cx;
          echo.y = room.cy;
        }
        addLogMessage('ECHO respawned!', 'echo');
      }
    }
    return;
  }

  if (echo.pvpCooldown > 0) echo.pvpCooldown--;

  // Extraction countdown
  if (echo.extracting) {
    echo.extractTimer--;
    if (echo.extractTimer <= 0) {
      echoCompleteExtract(echo, gameState);
    }
    return; // Stay put during extraction
  }

  // Decide + execute behavior
  echoDecideBehavior(echo, gameState);

  const dg = gameState.dungeon;
  const p = gameState.player;
  if (!dg || !p) return;

  switch (echo.behavior) {
    case 'flee':
    case 'extract_run':
      if (dg.stairs) {
        echoMoveToward(echo, dg.stairs.x, dg.stairs.y, gameState);
      }
      break;

    case 'pvp': {
      const dist = Math.abs(echo.x - p.x) + Math.abs(echo.y - p.y);
      if (dist <= 1) {
        const result = echoAttackPlayer(echo, gameState);
        if (result === 'player_killed') {
          // Player death handled by caller
        }
      } else {
        echoMoveToward(echo, p.x, p.y, gameState);
      }
      break;
    }

    case 'hunt': {
      if (!echo.target) break;
      const mon = dg.monsters.find(m => m.alive && m.x === echo.target.x && m.y === echo.target.y);
      if (!mon) { echo.behavior = 'explore'; break; }
      const dist = Math.abs(echo.x - mon.x) + Math.abs(echo.y - mon.y);
      if (dist <= 1) {
        echoAttackMonster(echo, mon, gameState);
      } else {
        echoMoveToward(echo, mon.x, mon.y, gameState);
      }
      break;
    }

    case 'loot':
      if (!echo.target) break;
      echoMoveToward(echo, echo.target.x, echo.target.y, gameState);
      break;

    case 'extract':
      if (!echo.extracting) {
        echo.extracting = true;
        echo.extractTimer = 6; // 6 turns to extract
        addLogMessage('ECHO is EXTRACTING...', 'echo');
      }
      break;

    case 'explore':
    default:
      // Pick random room target
      if (!echo.target || (echo.x === echo.target.x && echo.y === echo.target.y) || Math.random() < 0.08) {
        if (dg.rooms.length > 0) {
          const room = dg.rooms[Math.floor(Math.random() * dg.rooms.length)];
          echo.target = { x: room.cx, y: room.cy };
        }
      }
      if (echo.target) {
        echoMoveToward(echo, echo.target.x, echo.target.y, gameState);
      }
      break;
  }
}

// Sprite index helpers
function monsterSpriteIndex(monster) {
  let hash = 0;
  const name = monster.name || '';
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % 4;
}

function itemSpriteIndex(item) {
  let hash = 0;
  hash = ((item.x * 7919) + (item.y * 104729)) | 0;
  return Math.abs(hash) % 4;
}
