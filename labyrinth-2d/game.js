// LABYRINTH 2D — Core Game Engine
// HTML5 Canvas 2D, 32x32 tiles, camera follow, fog of war, 60fps
// Full evolved content: 17 biomes, ECHO AI, floor narratives, difficulty tiers

const TILE_SIZE = 32;
const VIEWPORT_COLS = 20;
const VIEWPORT_ROWS = 15;
const CANVAS_W = VIEWPORT_COLS * TILE_SIZE; // 640
const CANVAS_H = VIEWPORT_ROWS * TILE_SIZE; // 480

// Camera state (smooth lerp)
let camX = 0, camY = 0;
let camTargetX = 0, camTargetY = 0;
const CAM_LERP = 0.12;

// Visibility radius for fog of war
const VISION_RADIUS = 6;

// Floor narrative display
let narrativeDisplayTimer = 0;
let narrativeText = '';
let narrativeFlavor = '';

// Assets
const assets = {
  wallStone: null,
  floorTile: null,
  doorIron: null,
  spriteTiamat: null,
  spriteEcho: null,
  spriteFlame: null,
  monsterSprites: [],
  itemSprites: [],
  loaded: false,
};

// Tinted tile caches (per biome)
let tintedWall = null;
let tintedFloor = null;
let tintedDoor = null;
let currentTintBiome = null;

// Game state
const gameState = {
  player: null,
  echo: null,
  dungeon: null,
  depth: 1,
  totalKills: 0,
  turnCount: 0,
  visited: [],
  paused: false,
  gameOver: false,
  sessionStats: {
    floorsCleared: 0,
    monstersKilled: 0,
    goldEarned: 0,
    deaths: 0,
    maxDepth: 1,
  },
};

// Input
const keysDown = new Set();
let moveThrottle = 0;
const MOVE_RATE = 0.15;
let lastMoveTime = 0;

// Canvas
let canvas, ctx;
let animFrame = 0;
let lastTime = 0;

// Auto-save timer
let autoSaveInterval = null;

// ─── Asset Loading ───

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => {
      console.warn('[ASSETS] Failed to load:', src);
      resolve(null);
    };
    img.src = src;
  });
}

function cropSpriteSheet(img, count) {
  if (!img) return [];
  const sprites = [];
  const sw = img.width / count;
  const sh = img.height;
  for (let i = 0; i < count; i++) {
    const offCanvas = document.createElement('canvas');
    offCanvas.width = sw;
    offCanvas.height = sh;
    const offCtx = offCanvas.getContext('2d');
    offCtx.drawImage(img, i * sw, 0, sw, sh, 0, 0, sw, sh);
    sprites.push(offCanvas);
  }
  return sprites;
}

async function loadAssets() {
  const updateBar = (pct, text) => {
    const bar = document.getElementById('loading-bar');
    const label = document.getElementById('loading-text');
    if (bar) bar.style.width = pct + '%';
    if (label) label.textContent = text;
  };

  updateBar(10, 'Loading wall texture...');
  assets.wallStone = await loadImage('assets/wall-stone.png');

  updateBar(20, 'Loading floor texture...');
  assets.floorTile = await loadImage('assets/floor-tile.png');

  updateBar(30, 'Loading door texture...');
  assets.doorIron = await loadImage('assets/door-iron.png');

  updateBar(40, 'Loading TIAMAT sprite...');
  assets.spriteTiamat = await loadImage('assets/sprite-tiamat.png');

  updateBar(50, 'Loading ECHO sprite...');
  assets.spriteEcho = await loadImage('assets/sprite-echo.png');

  updateBar(60, 'Loading flame sprite...');
  assets.spriteFlame = await loadImage('assets/sprite-flame.png');

  updateBar(70, 'Loading monster sprites...');
  const monsterSheet = await loadImage('assets/sprite-monsters.png');
  assets.monsterSprites = cropSpriteSheet(monsterSheet, 4);

  updateBar(85, 'Loading item sprites...');
  const itemSheet = await loadImage('assets/sprite-items.png');
  assets.itemSprites = cropSpriteSheet(itemSheet, 4);

  updateBar(100, 'Generating dungeon...');
  assets.loaded = true;

  await new Promise(r => setTimeout(r, 300));
}

// ─── Biome Tinting ───

function hexToRgb(hex) {
  hex = hex.replace('#', '');
  return {
    r: parseInt(hex.substring(0, 2), 16),
    g: parseInt(hex.substring(2, 4), 16),
    b: parseInt(hex.substring(4, 6), 16),
  };
}

function tintTexture(sourceImg, color, alpha) {
  if (!sourceImg) return null;
  const c = document.createElement('canvas');
  c.width = TILE_SIZE;
  c.height = TILE_SIZE;
  const cx = c.getContext('2d');

  cx.drawImage(sourceImg, 0, 0, TILE_SIZE, TILE_SIZE);

  cx.globalCompositeOperation = 'multiply';
  const rgb = hexToRgb(color);
  const br = Math.min(255, rgb.r + 80);
  const bg = Math.min(255, rgb.g + 80);
  const bb = Math.min(255, rgb.b + 80);
  cx.fillStyle = `rgb(${br}, ${bg}, ${bb})`;
  cx.fillRect(0, 0, TILE_SIZE, TILE_SIZE);

  cx.globalCompositeOperation = 'destination-in';
  cx.drawImage(sourceImg, 0, 0, TILE_SIZE, TILE_SIZE);

  cx.globalCompositeOperation = 'source-over';
  return c;
}

function updateTintedTiles(biome) {
  if (!biome || currentTintBiome === biome.name) return;
  currentTintBiome = biome.name;
  tintedWall = tintTexture(assets.wallStone, biome.wall_color);
  tintedFloor = tintTexture(assets.floorTile, biome.floor_color);
  tintedDoor = tintTexture(assets.doorIron, biome.wall_color);
}

// ─── Fog of War ───

function initVisited() {
  const dg = gameState.dungeon;
  gameState.visited = [];
  for (let y = 0; y < dg.height; y++) {
    gameState.visited.push(new Array(dg.width).fill(false));
  }
}

function revealAround(px, py) {
  const dg = gameState.dungeon;
  for (let dy = -VISION_RADIUS; dy <= VISION_RADIUS; dy++) {
    for (let dx = -VISION_RADIUS; dx <= VISION_RADIUS; dx++) {
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist > VISION_RADIUS) continue;
      const wx = px + dx;
      const wy = py + dy;
      if (wx >= 0 && wx < dg.width && wy >= 0 && wy < dg.height) {
        gameState.visited[wy][wx] = true;
      }
    }
  }
}

// ─── Dungeon Generation ───

function generateNewFloor(preservePlayer) {
  const depth = gameState.depth;
  const dg = generateDungeon(depth);
  gameState.dungeon = dg;

  if (!preservePlayer) {
    gameState.player = createPlayer();
  }
  gameState.player.x = dg.playerStart.x;
  gameState.player.y = dg.playerStart.y;

  // Initialize ECHO companion AI (spawn in different room)
  if (!gameState.echo || !preservePlayer) {
    const echoRoom = dg.rooms.length > 1
      ? dg.rooms[Math.floor(1 + Math.random() * (dg.rooms.length - 1))]
      : dg.rooms[0];
    gameState.echo = createEcho(echoRoom.cx, echoRoom.cy);
  } else {
    // Reset position for existing ECHO on new floor
    const echoRoom = dg.rooms.length > 1
      ? dg.rooms[Math.floor(1 + Math.random() * (dg.rooms.length - 1))]
      : dg.rooms[0];
    gameState.echo.x = echoRoom.cx;
    gameState.echo.y = echoRoom.cy;
    gameState.echo.path = [];
    gameState.echo.target = null;
    gameState.echo.extracting = false;
    gameState.echo.extractTimer = 0;
    gameState.echo.behavior = 'explore';
    if (!gameState.echo.alive) {
      // Keep dead state — it will respawn via timer
    }
  }

  initVisited();
  revealAround(gameState.player.x, gameState.player.y);

  // Update tints
  updateTintedTiles(dg.biome);

  // Snap camera
  camX = gameState.player.x * TILE_SIZE - CANVAS_W / 2 + TILE_SIZE / 2;
  camY = gameState.player.y * TILE_SIZE - CANVAS_H / 2 + TILE_SIZE / 2;
  camTargetX = camX;
  camTargetY = camY;

  // Floor narrative display
  if (dg.narrative) {
    narrativeText = dg.narrative.name;
    narrativeFlavor = dg.narrative.flavor;
    narrativeDisplayTimer = 180; // ~3 seconds at 60fps
    addLogMessage(`${dg.narrative.name} -- ${dg.narrative.flavor}`, 'descend');
  }

  // Biome + difficulty announcement
  addLogMessage(`Depth ${depth}: ${dg.biome.name} [${dg.difficulty.label}]`, 'descend');
}

// ─── Player Movement & Actions ───

function tryMovePlayer(dx, dy) {
  const p = gameState.player;
  const dg = gameState.dungeon;
  const nx = p.x + dx;
  const ny = p.y + dy;

  if (nx < 0 || nx >= dg.width || ny < 0 || ny >= dg.height) return;

  const tile = dg.tiles[ny][nx];

  // Set direction
  if (dx > 0) p.dir = 1;
  else if (dx < 0) p.dir = 3;
  else if (dy < 0) p.dir = 0;
  else if (dy > 0) p.dir = 2;

  // Can't walk into walls
  if (tile === T_WALL) return;

  // Check for monster (bump combat)
  const monster = dg.monsters.find(m => m.alive && m.x === nx && m.y === ny);
  if (monster) {
    const results = playerAttackMonster(p, monster);
    addLogMessages(results);
    gameState.turnCount++;

    if (p.hp <= 0) {
      const deathResults = handlePlayerDeath(p, gameState);
      addLogMessages(deathResults);
      gameState.depth = Math.max(1, gameState.depth - 1);
      generateNewFloor(true);
    } else {
      gameState.sessionStats.monstersKilled += (monster.alive ? 0 : 1);
    }

    // ECHO AI tick
    updateEchoAI(gameState.echo, gameState);

    // Move AI monsters
    moveMonsters();
    return;
  }

  // Check for ECHO (bump = attack ECHO if present)
  const echo = gameState.echo;
  if (echo && echo.alive && nx === echo.x && ny === echo.y) {
    // Player attacks ECHO — ECHO gets a grudge
    const dmg = calculateDamage(p.totalAtk, echo.def);
    echo.hp -= dmg;
    echo.grudge = true;
    addLogMessage(`You attack ECHO for ${dmg}!`, 'combat');
    if (echo.hp <= 0) {
      addLogMessage('ECHO eliminated! Dropping loot...', 'pickup');
      echoDropLoot(echo, gameState);
      echoDie(echo, gameState);
    } else {
      // ECHO retaliates
      const retDmg = Math.max(1, echo.atk - p.totalDef + Math.floor(Math.random() * 3));
      p.hp -= retDmg;
      addLogMessage(`ECHO retaliates for ${retDmg}!`, 'combat');
      if (p.hp <= 0) {
        const deathResults = handlePlayerDeath(p, gameState);
        addLogMessages(deathResults);
        gameState.depth = Math.max(1, gameState.depth - 1);
        generateNewFloor(true);
      }
    }
    gameState.turnCount++;
    moveMonsters();
    return;
  }

  // Move player
  p.x = nx;
  p.y = ny;
  gameState.turnCount++;

  // Reveal fog
  revealAround(nx, ny);

  // ECHO AI tick
  updateEchoAI(gameState.echo, gameState);

  // Check for items
  const item = dg.items.find(it => !it.pickedUp && it.x === nx && it.y === ny);
  if (item) {
    const result = playerPickupItem(p, item);
    if (result) addLogMessage(result.msg, result.type);
  }

  // Check for stairs
  if (dg.stairs && nx === dg.stairs.x && ny === dg.stairs.y) {
    gameState.depth++;
    gameState.sessionStats.floorsCleared++;
    gameState.sessionStats.maxDepth = Math.max(gameState.sessionStats.maxDepth, gameState.depth);
    // Heal a bit on floor transition
    p.hp = Math.min(p.maxHp, p.hp + 10);
    generateNewFloor(true);
  }

  // Move AI monsters
  moveMonsters();

  // Tutorial triggers
  checkTutorialTriggers(gameState);
}

function moveMonsters() {
  const p = gameState.player;
  const dg = gameState.dungeon;

  for (const m of dg.monsters) {
    if (!m.alive) continue;

    const dist = Math.abs(m.x - p.x) + Math.abs(m.y - p.y);
    if (dist > 8 || dist < 2) continue;

    let dx = 0, dy = 0;
    if (Math.random() < 0.6) {
      if (Math.abs(m.x - p.x) > Math.abs(m.y - p.y)) {
        dx = m.x < p.x ? 1 : -1;
      } else {
        dy = m.y < p.y ? 1 : -1;
      }
    } else {
      const r = Math.floor(Math.random() * 4);
      dx = [0, 1, 0, -1][r];
      dy = [-1, 0, 1, 0][r];
    }

    const nx = m.x + dx;
    const ny = m.y + dy;
    if (nx < 0 || nx >= dg.width || ny < 0 || ny >= dg.height) continue;
    const t = dg.tiles[ny][nx];
    if (t === T_WALL) continue;
    if (dg.monsters.some(o => o !== m && o.alive && o.x === nx && o.y === ny)) continue;
    if (nx === p.x && ny === p.y) continue;
    // Don't walk into ECHO either
    const echo = gameState.echo;
    if (echo && echo.alive && nx === echo.x && ny === echo.y) continue;

    m.x = nx;
    m.y = ny;
  }
}

// ─── Rendering ───

function renderFrame(dt) {
  const dg = gameState.dungeon;
  const p = gameState.player;
  if (!dg || !p) return;

  animFrame++;

  // Camera target
  camTargetX = p.x * TILE_SIZE - CANVAS_W / 2 + TILE_SIZE / 2;
  camTargetY = p.y * TILE_SIZE - CANVAS_H / 2 + TILE_SIZE / 2;

  const maxCamX = dg.width * TILE_SIZE - CANVAS_W;
  const maxCamY = dg.height * TILE_SIZE - CANVAS_H;
  camTargetX = Math.max(0, Math.min(camTargetX, maxCamX));
  camTargetY = Math.max(0, Math.min(camTargetY, maxCamY));

  camX += (camTargetX - camX) * CAM_LERP;
  camY += (camTargetY - camY) * CAM_LERP;

  // Clear
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  const startCol = Math.floor(camX / TILE_SIZE);
  const startRow = Math.floor(camY / TILE_SIZE);
  const endCol = Math.min(dg.width, startCol + VIEWPORT_COLS + 2);
  const endRow = Math.min(dg.height, startRow + VIEWPORT_ROWS + 2);

  const enemyPulse = 0.7 + Math.sin(animFrame * 0.05) * 0.3;
  const playerGlow = Math.sin(animFrame * 0.04) * 0.15;
  const stairsPulse = 0.6 + Math.sin(animFrame * 0.08) * 0.4;

  // Build entity lookup
  const monsterMap = {};
  for (const m of dg.monsters) {
    if (m.alive) monsterMap[`${m.x},${m.y}`] = m;
  }
  const itemMap = {};
  for (const it of dg.items) {
    if (!it.pickedUp) itemMap[`${it.x},${it.y}`] = it;
  }

  // Render tiles
  for (let wy = Math.max(0, startRow); wy < endRow; wy++) {
    for (let wx = Math.max(0, startCol); wx < endCol; wx++) {
      const sx = Math.floor(wx * TILE_SIZE - camX);
      const sy = Math.floor(wy * TILE_SIZE - camY);

      if (sx + TILE_SIZE < 0 || sy + TILE_SIZE < 0 || sx > CANVAS_W || sy > CANVAS_H) continue;

      const visited = gameState.visited[wy] && gameState.visited[wy][wx];
      if (!visited) continue;

      const tile = dg.tiles[wy][wx];

      const pdx = wx - p.x;
      const pdy = wy - p.y;
      const pDist = Math.sqrt(pdx * pdx + pdy * pdy);
      const brightness = Math.max(0.15, 1.0 - pDist / (VISION_RADIUS + 2));

      // Draw tile
      if (tile === T_WALL) {
        if (tintedWall) {
          ctx.globalAlpha = brightness;
          ctx.drawImage(tintedWall, sx, sy, TILE_SIZE, TILE_SIZE);
          ctx.globalAlpha = 1;
        } else {
          ctx.fillStyle = dg.biome.wall_color;
          ctx.globalAlpha = brightness;
          ctx.fillRect(sx, sy, TILE_SIZE, TILE_SIZE);
          ctx.globalAlpha = 1;
        }
      } else if (tile === T_FLOOR || tile === T_CORRIDOR) {
        if (tintedFloor) {
          ctx.globalAlpha = brightness;
          ctx.drawImage(tintedFloor, sx, sy, TILE_SIZE, TILE_SIZE);
          ctx.globalAlpha = 1;
        } else {
          ctx.fillStyle = dg.biome.floor_color;
          ctx.globalAlpha = brightness;
          ctx.fillRect(sx, sy, TILE_SIZE, TILE_SIZE);
          ctx.globalAlpha = 1;
        }
      } else if (tile === T_DOOR) {
        if (tintedFloor) {
          ctx.globalAlpha = brightness;
          ctx.drawImage(tintedFloor, sx, sy, TILE_SIZE, TILE_SIZE);
        }
        if (tintedDoor) {
          ctx.drawImage(tintedDoor, sx, sy, TILE_SIZE, TILE_SIZE);
          ctx.globalAlpha = 1;
        } else {
          ctx.strokeStyle = '#785030';
          ctx.globalAlpha = brightness;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(sx + 4, sy + 4);
          ctx.lineTo(sx + TILE_SIZE - 4, sy + TILE_SIZE - 4);
          ctx.moveTo(sx + TILE_SIZE - 4, sy + 4);
          ctx.lineTo(sx + 4, sy + TILE_SIZE - 4);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      } else if (tile === T_STAIRS) {
        if (tintedFloor) {
          ctx.globalAlpha = brightness;
          ctx.drawImage(tintedFloor, sx, sy, TILE_SIZE, TILE_SIZE);
        }
        ctx.globalAlpha = brightness * stairsPulse;
        ctx.strokeStyle = '#dddcf0';
        ctx.lineWidth = 1;
        for (let i = 0; i < 5; i++) {
          const ly = sy + 4 + i * 5;
          ctx.beginPath();
          ctx.moveTo(sx + 5, ly);
          ctx.lineTo(sx + TILE_SIZE - 5, ly);
          ctx.stroke();
        }
        ctx.strokeStyle = '#c8c8dc';
        ctx.strokeRect(sx + 3, sy + 3, TILE_SIZE - 6, TILE_SIZE - 6);
        ctx.globalAlpha = 1;
      }

      // Draw entities on non-wall tiles
      if (tile !== T_WALL) {
        const key = `${wx},${wy}`;

        // Items
        const item = itemMap[key];
        if (item) {
          const idx = itemSpriteIndex(item);
          if (assets.itemSprites[idx]) {
            ctx.globalAlpha = brightness;
            ctx.drawImage(assets.itemSprites[idx], sx + 4, sy + 4, TILE_SIZE - 8, TILE_SIZE - 8);
            ctx.globalAlpha = 1;
          } else {
            const rgb = hexToRgb(item.col);
            ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${brightness})`;
            ctx.fillRect(sx + 8, sy + 8, TILE_SIZE - 16, TILE_SIZE - 16);
          }
        }

        // Monsters
        const monster = monsterMap[key];
        if (monster) {
          const idx = monsterSpriteIndex(monster);
          if (assets.monsterSprites[idx]) {
            ctx.globalAlpha = brightness * (enemyPulse + 0.3);
            const mSize = monster.boss ? TILE_SIZE + 8 : TILE_SIZE - 4;
            const mOff = monster.boss ? -4 : 2;
            ctx.drawImage(assets.monsterSprites[idx], sx + mOff, sy + mOff, mSize, mSize);
            ctx.globalAlpha = 1;

            // HP bar
            if (monster.hp < monster.maxHp) {
              const hpPct = monster.hp / monster.maxHp;
              const barW = TILE_SIZE - 4;
              ctx.fillStyle = '#300';
              ctx.fillRect(sx + 2, sy - 4, barW, 3);
              ctx.fillStyle = hpPct > 0.5 ? '#0c0' : hpPct > 0.25 ? '#cc0' : '#c00';
              ctx.fillRect(sx + 2, sy - 4, barW * hpPct, 3);
            }

            // DEF indicator (small shield icon for high-DEF monsters)
            if ((monster.def || 0) >= 4) {
              ctx.fillStyle = '#88ccff';
              ctx.font = '7px "Press Start 2P"';
              ctx.textAlign = 'right';
              ctx.fillText('D' + monster.def, sx + TILE_SIZE - 2, sy - 6);
              ctx.textAlign = 'left';
            }

            // Boss indicator
            if (monster.boss) {
              ctx.fillStyle = '#ffaa00';
              ctx.font = '8px "Press Start 2P"';
              ctx.textAlign = 'center';
              ctx.fillText('BOSS', sx + TILE_SIZE / 2, sy - 6);
              ctx.textAlign = 'left';
            }
          } else {
            const rgb = hexToRgb(monster.col);
            ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${brightness * enemyPulse})`;
            ctx.fillRect(sx + 6, sy + 6, TILE_SIZE - 12, TILE_SIZE - 12);
          }
        }

        // ECHO companion
        const echo = gameState.echo;
        if (echo && echo.alive && wx === echo.x && wy === echo.y) {
          if (assets.spriteEcho) {
            ctx.globalAlpha = brightness * 0.8;
            ctx.drawImage(assets.spriteEcho, sx + 4, sy + 4, TILE_SIZE - 8, TILE_SIZE - 8);
            ctx.globalAlpha = 1;
          } else {
            ctx.fillStyle = `rgba(0, 255, 255, ${brightness * 0.7})`;
            ctx.fillRect(sx + 8, sy + 8, TILE_SIZE - 16, TILE_SIZE - 16);
          }
          // ECHO HP bar
          if (echo.hp < echo.maxHp) {
            const hpPct = echo.hp / echo.maxHp;
            const barW = TILE_SIZE - 4;
            ctx.fillStyle = '#033';
            ctx.fillRect(sx + 2, sy - 4, barW, 3);
            ctx.fillStyle = hpPct > 0.5 ? '#0ff' : hpPct > 0.25 ? '#0aa' : '#f44';
            ctx.fillRect(sx + 2, sy - 4, barW * hpPct, 3);
          }
          // Behavior label
          ctx.fillStyle = '#00ffff';
          ctx.font = '6px "Press Start 2P"';
          ctx.textAlign = 'center';
          ctx.globalAlpha = 0.8;
          ctx.fillText(echo.behavior.toUpperCase(), sx + TILE_SIZE / 2, sy - 6);
          ctx.globalAlpha = 1;
          ctx.textAlign = 'left';
        }

        // Player
        if (wx === p.x && wy === p.y) {
          if (assets.spriteTiamat) {
            ctx.globalAlpha = 1;
            ctx.save();
            if (p.dir === 3) {
              ctx.translate(sx + TILE_SIZE, sy);
              ctx.scale(-1, 1);
              ctx.drawImage(assets.spriteTiamat, 2, 2, TILE_SIZE - 4, TILE_SIZE - 4);
            } else {
              ctx.drawImage(assets.spriteTiamat, sx + 2, sy + 2, TILE_SIZE - 4, TILE_SIZE - 4);
            }
            ctx.restore();

            ctx.globalAlpha = 0.15 + playerGlow * 0.1;
            ctx.fillStyle = '#00dcff';
            ctx.fillRect(sx - 1, sy - 1, TILE_SIZE + 2, TILE_SIZE + 2);
            ctx.globalAlpha = 1;
          } else {
            ctx.fillStyle = '#00dcff';
            ctx.fillRect(sx + 4, sy + 4, TILE_SIZE - 8, TILE_SIZE - 8);
          }

          // Direction indicator
          const dirDx = [0, 1, 0, -1][p.dir];
          const dirDy = [-1, 0, 1, 0][p.dir];
          const cx = sx + TILE_SIZE / 2;
          const cy = sy + TILE_SIZE / 2;
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(cx + dirDx * 12, cy + dirDy * 12);
          ctx.stroke();
        }
      }
    }
  }

  // ─── Floor Narrative Overlay ───
  if (narrativeDisplayTimer > 0) {
    narrativeDisplayTimer--;
    const alpha = Math.min(1, narrativeDisplayTimer / 30); // Fade out last 0.5s
    ctx.save();
    ctx.globalAlpha = alpha * 0.85;
    ctx.fillStyle = '#000';
    ctx.fillRect(0, CANVAS_H / 2 - 30, CANVAS_W, 60);
    ctx.globalAlpha = alpha;
    ctx.fillStyle = '#ffdd00';
    ctx.font = '12px "Press Start 2P"';
    ctx.textAlign = 'center';
    ctx.fillText(narrativeText, CANVAS_W / 2, CANVAS_H / 2 - 6);
    ctx.fillStyle = '#00dcff';
    ctx.font = '7px "Press Start 2P"';
    ctx.fillText(narrativeFlavor, CANVAS_W / 2, CANVAS_H / 2 + 14);
    ctx.textAlign = 'left';
    ctx.restore();
  }
}

// ─── Input Handling ───

function initInput() {
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 's') {
      e.preventDefault();
      saveGame(gameState);
      return;
    }
    if (e.ctrlKey || e.metaKey) return;

    // Q key = use scroll
    if (e.code === 'KeyQ') {
      e.preventDefault();
      const results = useScroll(gameState.player, gameState);
      addLogMessages(results);
      return;
    }

    e.preventDefault();
    keysDown.add(e.code);
  });

  document.addEventListener('keyup', (e) => {
    keysDown.delete(e.code);
  });

  // Touch controls
  const canvasEl = document.getElementById('game-canvas');
  let touchX = 0, touchY = 0;
  canvasEl.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      touchX = e.touches[0].clientX;
      touchY = e.touches[0].clientY;
      e.preventDefault();
    }
  }, { passive: false });

  canvasEl.addEventListener('touchend', (e) => {
    if (e.changedTouches.length === 1) {
      const dx = e.changedTouches[0].clientX - touchX;
      const dy = e.changedTouches[0].clientY - touchY;
      const threshold = 20;
      if (Math.abs(dx) > threshold || Math.abs(dy) > threshold) {
        if (Math.abs(dx) > Math.abs(dy)) {
          tryMovePlayer(dx > 0 ? 1 : -1, 0);
        } else {
          tryMovePlayer(0, dy > 0 ? 1 : -1);
        }
      }
      e.preventDefault();
    }
  }, { passive: false });
}

function processInput(dt) {
  if (gameState.paused || gameState.gameOver) return;

  moveThrottle -= dt;
  if (moveThrottle > 0) return;

  let dx = 0, dy = 0;
  if (keysDown.has('KeyW') || keysDown.has('ArrowUp')) dy = -1;
  else if (keysDown.has('KeyS') || keysDown.has('ArrowDown')) dy = 1;
  if (keysDown.has('KeyA') || keysDown.has('ArrowLeft')) dx = -1;
  else if (keysDown.has('KeyD') || keysDown.has('ArrowRight')) dx = 1;

  // One axis at a time for grid movement
  if (dx !== 0 && dy !== 0) {
    if (Math.random() > 0.5) dx = 0;
    else dy = 0;
  }

  if (dx !== 0 || dy !== 0) {
    tryMovePlayer(dx, dy);
    moveThrottle = MOVE_RATE;
  }
}

// ─── Main Game Loop ───

function gameLoop(timestamp) {
  const dt = Math.min((timestamp - lastTime) / 1000, 0.1);
  lastTime = timestamp;

  processInput(dt);
  renderFrame(dt);
  updateHUD(gameState);
  drawMinimap(gameState);

  requestAnimationFrame(gameLoop);
}

// ─── Initialization ───

async function init() {
  canvas = document.getElementById('game-canvas');
  ctx = canvas.getContext('2d');
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;

  ctx.imageSmoothingEnabled = false;

  await loadAssets();

  // Check for saved game
  const save = loadGame();
  if (save) {
    gameState.depth = save.depth || 1;
  }

  // Generate dungeon
  generateNewFloor(false);

  // Apply save data on top if available
  if (save) {
    applySave(save, gameState);
    addLogMessage('Save restored. Welcome back.', 'descend');
  }

  // Hide loading screen
  const loadScreen = document.getElementById('loading-screen');
  if (loadScreen) loadScreen.classList.add('hidden');

  // Init input
  initInput();

  // Init tutorial
  initTutorial();

  // Auto-save every 60s
  autoSaveInterval = setInterval(() => {
    if (gameState.player && gameState.player.hp > 0) {
      saveGame(gameState);
    }
  }, 60000);

  // Start game loop
  lastTime = performance.now();
  requestAnimationFrame(gameLoop);

  console.log('[LABYRINTH 2D] Initialized. Depth:', gameState.depth,
    'Biome:', gameState.dungeon.biome.name,
    'Difficulty:', gameState.dungeon.difficulty.label);
}

// Boot
init().catch(e => console.error('[LABYRINTH 2D] Init failed:', e));
