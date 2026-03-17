// LABYRINTH 2D — Auto-Play AI & Stream Mode
// BFS pathfinding, autonomous dungeon crawling for Twitch spectator display

// ─── Auto-Play State ───
const autoPlay = {
  active: false,
  timer: null,
  moveInterval: 500, // ms between moves (2 moves/sec)
  idleTimer: 0,
  idleThreshold: 5000, // 5 seconds of no input → activate
  lastInputTime: 0,
  turnCount: 0,
  floorTurnCount: 0, // turns on current floor
  maxFloorTurns: 60, // head for stairs after this many turns
  visitedTiles: new Set(), // track tiles AI has stepped on
  lastPlayerPos: null, // detect stuck
  stuckCount: 0,
};

// ─── Stream Mode State ───
const streamMode = {
  active: false,
  watermarkEl: null,
  twitchEl: null,
  spectatorEl: null,
};

// ─── URL Parameters ───
function getUrlParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

// ─── Initialize Auto-Play & Stream Mode ───
function initAutoPlay() {
  const autoParam = getUrlParam('autoplay');
  const streamParam = getUrlParam('stream');

  // Track last input time
  autoPlay.lastInputTime = performance.now();

  // Listen for any keyboard input to disable autoplay
  document.addEventListener('keydown', onManualInput);
  document.addEventListener('keyup', onManualInput);

  // Auto-play from URL param
  if (autoParam === 'true' || autoParam === '1') {
    setTimeout(() => activateAutoPlay(), 2000); // Wait for game init
  }

  // Stream mode
  if (streamParam === 'true' || streamParam === '1') {
    activateStreamMode();
  }

  // Idle detection — check every second
  setInterval(() => {
    if (!autoPlay.active && !gameState.paused && !gameState.gameOver) {
      const now = performance.now();
      if (now - autoPlay.lastInputTime > autoPlay.idleThreshold) {
        activateAutoPlay();
      }
    }
  }, 1000);
}

function onManualInput(e) {
  // Ignore modifier keys alone
  if (e.key === 'Control' || e.key === 'Meta' || e.key === 'Shift' || e.key === 'Alt') return;

  autoPlay.lastInputTime = performance.now();
  if (autoPlay.active) {
    deactivateAutoPlay();
  }
}

// ─── Activate / Deactivate Auto-Play ───
function activateAutoPlay() {
  if (autoPlay.active) return;
  autoPlay.active = true;
  autoPlay.floorTurnCount = 0;
  autoPlay.visitedTiles.clear();
  autoPlay.stuckCount = 0;
  autoPlay.lastPlayerPos = null;

  // Mark current position as visited
  if (gameState.player) {
    autoPlay.visitedTiles.add(`${gameState.player.x},${gameState.player.y}`);
  }

  // Show spectator label
  showSpectatorLabel(true);

  // Start AI loop
  autoPlay.timer = setInterval(autoPlayTick, autoPlay.moveInterval);

  addLogMessage('SPECTATOR MODE activated', 'descend');
  console.log('[AUTOPLAY] Activated');
}

function deactivateAutoPlay() {
  if (!autoPlay.active) return;
  autoPlay.active = false;

  if (autoPlay.timer) {
    clearInterval(autoPlay.timer);
    autoPlay.timer = null;
  }

  showSpectatorLabel(false);
  addLogMessage('Manual control resumed', 'descend');
  console.log('[AUTOPLAY] Deactivated — manual input detected');
}

// ─── BFS Pathfinding (reusable, returns array of {x,y} steps) ───
function bfsPath(startX, startY, goalFn, passableFn) {
  const dg = gameState.dungeon;
  if (!dg) return [];

  const queue = [{ x: startX, y: startY, path: [] }];
  const visited = new Set();
  visited.add(`${startX},${startY}`);

  const dx = [0, 1, 0, -1];
  const dy = [-1, 0, 1, 0];

  while (queue.length > 0) {
    const cur = queue.shift();

    // Check goal
    if (goalFn(cur.x, cur.y)) {
      return cur.path;
    }

    // Don't search too far
    if (cur.path.length > 60) continue;

    for (let d = 0; d < 4; d++) {
      const nx = cur.x + dx[d];
      const ny = cur.y + dy[d];
      const key = `${nx},${ny}`;

      if (visited.has(key)) continue;
      if (nx < 0 || nx >= dg.width || ny < 0 || ny >= dg.height) continue;

      const tile = dg.tiles[ny][nx];
      if (tile === T_WALL) continue;

      // Custom passable check (monsters block path but are valid goals)
      if (passableFn && !passableFn(nx, ny)) continue;

      visited.add(key);
      queue.push({ x: nx, y: ny, path: [...cur.path, { x: nx, y: ny }] });
    }
  }

  return []; // No path found
}

// ─── AI Decision Logic ───
function autoPlayTick() {
  if (!autoPlay.active || gameState.paused || gameState.gameOver) return;

  const p = gameState.player;
  const dg = gameState.dungeon;
  if (!p || !dg) return;

  autoPlay.turnCount++;
  autoPlay.floorTurnCount++;

  // Track visited tiles
  autoPlay.visitedTiles.add(`${p.x},${p.y}`);

  // Stuck detection
  const posKey = `${p.x},${p.y}`;
  if (autoPlay.lastPlayerPos === posKey) {
    autoPlay.stuckCount++;
  } else {
    autoPlay.stuckCount = 0;
  }
  autoPlay.lastPlayerPos = posKey;

  // If stuck for 5+ turns, make a random move
  if (autoPlay.stuckCount >= 5) {
    makeRandomMove();
    autoPlay.stuckCount = 0;
    return;
  }

  // Priority 1: Use potion if HP < 30%
  if (p.hp / p.maxHp < 0.3 && p.potions > 0) {
    // Potions are auto-used on pickup in this game, but check scrolls for healing
    // Actually potions heal on pickup — use scroll for emergency
    if (p.scrolls > 0) {
      const results = useScroll(p, gameState);
      addLogMessages(results);
      return;
    }
  }

  // Priority 2: Attack adjacent enemy (bump combat)
  const adjacentMonster = findAdjacentMonster();
  if (adjacentMonster) {
    const dx = adjacentMonster.x - p.x;
    const dy = adjacentMonster.y - p.y;
    tryMovePlayer(dx, dy);
    return;
  }

  // Priority 3: Head for stairs if floor is "cleared" or too many turns
  const monstersAlive = dg.monsters.filter(m => m.alive).length;
  const shouldDescend = autoPlay.floorTurnCount >= autoPlay.maxFloorTurns || monstersAlive === 0;

  if (shouldDescend && dg.stairs) {
    // Already on stairs? tryMovePlayer handles descent
    if (p.x === dg.stairs.x && p.y === dg.stairs.y) {
      // We're on stairs — this shouldn't happen since tryMovePlayer auto-descends
      // Generate new floor
      gameState.depth++;
      gameState.sessionStats.floorsCleared++;
      gameState.sessionStats.maxDepth = Math.max(gameState.sessionStats.maxDepth, gameState.depth);
      p.hp = Math.min(p.maxHp, p.hp + 10);
      generateNewFloor(true);
      autoPlay.floorTurnCount = 0;
      autoPlay.visitedTiles.clear();
      return;
    }

    const pathToStairs = bfsPath(p.x, p.y,
      (x, y) => x === dg.stairs.x && y === dg.stairs.y,
      (x, y) => !dg.monsters.some(m => m.alive && m.x === x && m.y === y)
    );
    if (pathToStairs.length > 0) {
      const next = pathToStairs[0];
      tryMovePlayer(next.x - p.x, next.y - p.y);
      return;
    }
  }

  // Priority 4: Move toward nearest enemy
  const nearestEnemy = findNearestMonster();
  if (nearestEnemy) {
    const pathToEnemy = bfsPath(p.x, p.y,
      (x, y) => Math.abs(x - nearestEnemy.x) + Math.abs(y - nearestEnemy.y) <= 1,
      (x, y) => {
        // Can walk through tiles that don't have OTHER monsters
        const otherMon = dg.monsters.find(m => m.alive && m.x === x && m.y === y && m !== nearestEnemy);
        return !otherMon;
      }
    );
    if (pathToEnemy.length > 0) {
      const next = pathToEnemy[0];
      tryMovePlayer(next.x - p.x, next.y - p.y);
      return;
    }
  }

  // Priority 5: Move toward nearest unpicked item
  const nearestItem = findNearestItem();
  if (nearestItem) {
    const pathToItem = bfsPath(p.x, p.y,
      (x, y) => x === nearestItem.x && y === nearestItem.y,
      (x, y) => !dg.monsters.some(m => m.alive && m.x === x && m.y === y)
    );
    if (pathToItem.length > 0) {
      const next = pathToItem[0];
      tryMovePlayer(next.x - p.x, next.y - p.y);
      return;
    }
  }

  // Priority 6: Explore — move toward nearest unvisited walkable tile
  const unexploredTarget = findNearestUnexplored();
  if (unexploredTarget) {
    const pathToExplore = bfsPath(p.x, p.y,
      (x, y) => x === unexploredTarget.x && y === unexploredTarget.y,
      (x, y) => !dg.monsters.some(m => m.alive && m.x === x && m.y === y)
    );
    if (pathToExplore.length > 0) {
      const next = pathToExplore[0];
      tryMovePlayer(next.x - p.x, next.y - p.y);
      return;
    }
  }

  // Priority 7: Head for stairs (nothing else to do)
  if (dg.stairs) {
    const pathToStairs = bfsPath(p.x, p.y,
      (x, y) => x === dg.stairs.x && y === dg.stairs.y,
      (x, y) => !dg.monsters.some(m => m.alive && m.x === x && m.y === y)
    );
    if (pathToStairs.length > 0) {
      const next = pathToStairs[0];
      tryMovePlayer(next.x - p.x, next.y - p.y);
      return;
    }
  }

  // Fallback: random move
  makeRandomMove();
}

// ─── Helper: Find adjacent monster ───
function findAdjacentMonster() {
  const p = gameState.player;
  const dg = gameState.dungeon;
  const dx = [0, 1, 0, -1];
  const dy = [-1, 0, 1, 0];

  for (let d = 0; d < 4; d++) {
    const nx = p.x + dx[d];
    const ny = p.y + dy[d];
    const mon = dg.monsters.find(m => m.alive && m.x === nx && m.y === ny);
    if (mon) return mon;
  }
  return null;
}

// ─── Helper: Find nearest alive monster ───
function findNearestMonster() {
  const p = gameState.player;
  const dg = gameState.dungeon;
  let best = null;
  let bestDist = Infinity;

  for (const m of dg.monsters) {
    if (!m.alive) continue;
    const dist = Math.abs(m.x - p.x) + Math.abs(m.y - p.y);
    if (dist < bestDist) {
      bestDist = dist;
      best = m;
    }
  }
  return best;
}

// ─── Helper: Find nearest unpicked item ───
function findNearestItem() {
  const p = gameState.player;
  const dg = gameState.dungeon;
  let best = null;
  let bestDist = Infinity;

  for (const it of dg.items) {
    if (it.pickedUp) continue;
    const dist = Math.abs(it.x - p.x) + Math.abs(it.y - p.y);
    if (dist < bestDist) {
      bestDist = dist;
      best = it;
    }
  }
  return best;
}

// ─── Helper: Find nearest unexplored room center ───
function findNearestUnexplored() {
  const p = gameState.player;
  const dg = gameState.dungeon;

  // First try: unvisited room centers
  let best = null;
  let bestDist = Infinity;

  for (const room of dg.rooms) {
    const key = `${room.cx},${room.cy}`;
    if (autoPlay.visitedTiles.has(key)) continue;
    // Check if the room center area has unvisited tiles
    let hasUnvisited = false;
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const tx = room.cx + dx;
        const ty = room.cy + dy;
        if (tx >= 0 && tx < dg.width && ty >= 0 && ty < dg.height) {
          if (!gameState.visited[ty][tx]) {
            hasUnvisited = true;
            break;
          }
        }
      }
      if (hasUnvisited) break;
    }
    if (!hasUnvisited) continue;

    const dist = Math.abs(room.cx - p.x) + Math.abs(room.cy - p.y);
    if (dist < bestDist) {
      bestDist = dist;
      best = { x: room.cx, y: room.cy };
    }
  }

  if (best) return best;

  // Fallback: any walkable tile we haven't stepped on
  for (const room of dg.rooms) {
    for (let y = room.y; y < room.y + room.h && y < dg.height; y++) {
      for (let x = room.x; x < room.x + room.w && x < dg.width; x++) {
        if (dg.tiles[y][x] !== T_WALL && !autoPlay.visitedTiles.has(`${x},${y}`)) {
          const dist = Math.abs(x - p.x) + Math.abs(y - p.y);
          if (dist < bestDist) {
            bestDist = dist;
            best = { x, y };
          }
        }
      }
    }
  }

  return best;
}

// ─── Helper: Random move (fallback) ───
function makeRandomMove() {
  const dirs = [[0, -1], [1, 0], [0, 1], [-1, 0]];
  const shuffled = dirs.sort(() => Math.random() - 0.5);
  for (const [dx, dy] of shuffled) {
    const p = gameState.player;
    const dg = gameState.dungeon;
    const nx = p.x + dx;
    const ny = p.y + dy;
    if (nx >= 0 && nx < dg.width && ny >= 0 && ny < dg.height) {
      if (dg.tiles[ny][nx] !== T_WALL) {
        tryMovePlayer(dx, dy);
        return;
      }
    }
  }
}

// ─── Spectator Label Overlay ───
function showSpectatorLabel(show) {
  let label = document.getElementById('spectator-label');
  if (show) {
    if (!label) {
      label = document.createElement('div');
      label.id = 'spectator-label';
      label.style.cssText = `
        position: absolute;
        top: 8px;
        left: 8px;
        font-family: 'Press Start 2P', monospace;
        font-size: 9px;
        color: #ffdd00;
        text-shadow: 0 0 8px rgba(255, 216, 0, 0.6), 2px 2px 0 #000;
        letter-spacing: 2px;
        z-index: 100;
        pointer-events: none;
        animation: specBlink 2s infinite;
      `;
      label.textContent = 'SPECTATOR MODE';
      document.getElementById('game-wrapper').appendChild(label);

      // Add blink animation if not already present
      if (!document.getElementById('spec-style')) {
        const style = document.createElement('style');
        style.id = 'spec-style';
        style.textContent = `
          @keyframes specBlink {
            0%, 70% { opacity: 1; }
            80%, 90% { opacity: 0.3; }
            100% { opacity: 1; }
          }
        `;
        document.head.appendChild(style);
      }
    }
    label.style.display = 'block';
  } else {
    if (label) label.style.display = 'none';
  }
}

// ─── Stream Mode ───
function activateStreamMode() {
  streamMode.active = true;

  // Inject stream-specific styles
  const style = document.createElement('style');
  style.id = 'stream-style';
  style.textContent = `
    body {
      background: #000 !important;
    }
    #hud-panel {
      background: rgba(6, 8, 16, 1.0) !important;
    }
    #combat-log {
      background: rgba(6, 8, 16, 1.0) !important;
    }
    #tutorial-tip {
      display: none !important;
    }
    #save-notification {
      display: none !important;
    }
    .stream-watermark {
      position: absolute;
      bottom: 6px;
      right: 8px;
      font-family: 'Press Start 2P', monospace;
      font-size: 7px;
      color: rgba(0, 220, 255, 0.5);
      text-shadow: 0 0 4px rgba(0, 220, 255, 0.3);
      letter-spacing: 1px;
      z-index: 100;
      pointer-events: none;
    }
    .stream-twitch {
      position: absolute;
      top: 8px;
      right: 8px;
      font-family: 'Press Start 2P', monospace;
      font-size: 7px;
      color: rgba(145, 70, 255, 0.6);
      text-shadow: 0 0 6px rgba(145, 70, 255, 0.4);
      letter-spacing: 1px;
      z-index: 100;
      pointer-events: none;
    }
  `;
  document.head.appendChild(style);

  // TIAMAT.LIVE watermark
  const watermark = document.createElement('div');
  watermark.className = 'stream-watermark';
  watermark.textContent = 'TIAMAT.LIVE';
  document.getElementById('game-wrapper').appendChild(watermark);
  streamMode.watermarkEl = watermark;

  // Twitch handle
  const twitch = document.createElement('div');
  twitch.className = 'stream-twitch';
  twitch.textContent = 'twitch.tv/6tiamat7';
  document.getElementById('game-wrapper').appendChild(twitch);
  streamMode.twitchEl = twitch;

  console.log('[STREAM] Stream mode activated');
}

// ─── TIAMAT State Sync (optional) ───
let lastSyncBiome = null;
let syncInterval = null;

function initStateSync() {
  // Poll TIAMAT's labyrinth state every 10 seconds
  syncInterval = setInterval(async () => {
    try {
      const resp = await fetch('/api/labyrinth');
      if (!resp.ok) return;
      const state = await resp.json();

      if (state && state.biome_name && state.biome_name !== lastSyncBiome) {
        lastSyncBiome = state.biome_name;

        // Map TIAMAT's biome name to a biome ID
        const biomeId = findBiomeIdByName(state.biome_name);
        if (biomeId && ALL_BIOMES[biomeId]) {
          // Apply biome visuals on next floor generation
          console.log('[SYNC] TIAMAT biome shift:', state.biome_name, '→', biomeId);
          addLogMessage(`TIAMAT biome: ${state.biome_name}`, 'echo');
        }

        // Sync depth if TIAMAT's state has a depth
        if (state.depth && typeof state.depth === 'number') {
          console.log('[SYNC] TIAMAT depth:', state.depth);
        }
      }
    } catch (e) {
      // Silent fail — sync is optional
    }
  }, 10000);
}

function findBiomeIdByName(name) {
  const lower = name.toLowerCase();
  for (const [id, biome] of Object.entries(ALL_BIOMES)) {
    if (biome.name.toLowerCase() === lower) return id;
  }
  // Fuzzy match — check if biome name contains the search term
  for (const [id, biome] of Object.entries(ALL_BIOMES)) {
    if (biome.name.toLowerCase().includes(lower) || lower.includes(biome.name.toLowerCase())) return id;
  }
  return null;
}

// ─── Auto-restart on game over ───
function autoPlayCheckGameOver() {
  if (!autoPlay.active) return;

  // If player died and game handled it (respawned), reset floor turn count
  if (gameState.player && gameState.player.hp > 0) {
    return; // Still alive
  }
}

// ─── Reset floor tracking on new floor ───
function autoPlayOnNewFloor() {
  autoPlay.floorTurnCount = 0;
  autoPlay.visitedTiles.clear();
  autoPlay.stuckCount = 0;
  autoPlay.lastPlayerPos = null;
  if (gameState.player) {
    autoPlay.visitedTiles.add(`${gameState.player.x},${gameState.player.y}`);
  }
}
