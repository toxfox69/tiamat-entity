// LABYRINTH 3D — AI Agent Characters (TIAMAT, ECHO, Data Specters, Monsters)
import * as THREE from 'three';

// ─── Sprite Texture Loader ───
const spriteLoader = new THREE.TextureLoader();
const spriteTextures = {};

export function loadAgentTextures() {
  const base = 'assets/';
  const files = {
    tiamat: 'sprite-tiamat.png',
    echo: 'sprite-echo.png',
    monsters: 'sprite-monsters.png',  // 4 slots: 64x64 each in 256x64 strip
    items: 'sprite-items.png',        // 4 slots: 64x64 each in 256x64 strip
    flame: 'sprite-flame.png',
  };
  for (const [key, file] of Object.entries(files)) {
    const tex = spriteLoader.load(base + file);
    tex.minFilter = THREE.LinearFilter;
    tex.magFilter = THREE.NearestFilter;
    spriteTextures[key] = tex;
  }
}

// Monster character → sprite sheet slot index mapping
const MONSTER_SLOT = { 'r': 0, 'S': 1, 'G': 2, 'D': 3, 'k': 0, 'B': 1, 'W': 2, 'O': 3 };

function getMonsterTexture(ch) {
  if (!spriteTextures.monsters) return null;
  const slot = MONSTER_SLOT[ch] ?? 0;
  const tex = spriteTextures.monsters.clone();
  tex.needsUpdate = true;
  // Each slot is 64px in a 256px wide strip
  tex.repeat.set(0.25, 1);
  tex.offset.set(slot * 0.25, 0);
  return tex;
}

// Item character → sprite sheet slot
const ITEM_SLOT = { '!': 0, '?': 1, '/': 2, '=': 3, '+': 0, '$': 1, '%': 2, '*': 3 };

function getItemTexture(ch) {
  if (!spriteTextures.items) return null;
  const slot = ITEM_SLOT[ch] ?? 0;
  const tex = spriteTextures.items.clone();
  tex.needsUpdate = true;
  // 256x64 sheet = 4 slots of 64x64
  tex.repeat.set(0.25, 1);
  tex.offset.set(slot * 0.25, 0);
  return tex;
}

// ─── Agent Billboard Sprite Creator ───
function createBillboard(color, size, shape) {
  // Try to use loaded sprite textures first
  if (shape === 'tiamat' && spriteTextures.tiamat) {
    const mat = new THREE.SpriteMaterial({
      map: spriteTextures.tiamat,
      transparent: true,
      depthWrite: false,
      color: new THREE.Color(color),
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(size, size, 1);
    return sprite;
  }
  if (shape === 'echo' && spriteTextures.echo) {
    const mat = new THREE.SpriteMaterial({
      map: spriteTextures.echo,
      transparent: true,
      depthWrite: false,
      color: new THREE.Color(color),
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(size, size, 1);
    return sprite;
  }
  // Monsters — use sprite sheet slot
  if (shape && shape !== 'specter' && shape.length === 1) {
    const monTex = getMonsterTexture(shape);
    if (monTex) {
      const mat = new THREE.SpriteMaterial({
        map: monTex,
        transparent: true,
        depthWrite: false,
        color: new THREE.Color(color),
      });
      const sprite = new THREE.Sprite(mat);
      sprite.scale.set(size, size, 1);
      return sprite;
    }
  }

  // Fallback: canvas-drawn billboard
  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  const cx = 32, cy = 32;

  ctx.clearRect(0, 0, 64, 64);

  if (shape === 'tiamat') {
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.moveTo(32, 8); ctx.lineTo(20, 20); ctx.lineTo(8, 12);
    ctx.lineTo(18, 24); ctx.lineTo(12, 56); ctx.lineTo(24, 48);
    ctx.lineTo(32, 58); ctx.lineTo(40, 48); ctx.lineTo(52, 56);
    ctx.lineTo(46, 24); ctx.lineTo(56, 12); ctx.lineTo(44, 20);
    ctx.closePath(); ctx.fill();
    ctx.globalAlpha = 0.4;
    ctx.beginPath(); ctx.moveTo(18, 24); ctx.lineTo(2, 30); ctx.lineTo(12, 40); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.moveTo(46, 24); ctx.lineTo(62, 30); ctx.lineTo(52, 40); ctx.closePath(); ctx.fill();
  } else if (shape === 'echo') {
    ctx.strokeStyle = color; ctx.lineWidth = 2;
    ctx.shadowColor = color; ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.moveTo(32, 10); ctx.lineTo(50, 30); ctx.lineTo(42, 54);
    ctx.lineTo(22, 54); ctx.lineTo(14, 30); ctx.closePath();
    ctx.stroke();
    ctx.globalAlpha = 0.3; ctx.fillStyle = color; ctx.fill();
  } else if (shape === 'specter') {
    ctx.strokeStyle = color; ctx.lineWidth = 1.5;
    ctx.shadowColor = color; ctx.shadowBlur = 10; ctx.globalAlpha = 0.6;
    ctx.beginPath(); ctx.arc(32, 20, 10, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(32, 30); ctx.lineTo(32, 50);
    ctx.moveTo(22, 38); ctx.lineTo(42, 38);
    ctx.moveTo(32, 50); ctx.lineTo(24, 60);
    ctx.moveTo(32, 50); ctx.lineTo(40, 60);
    ctx.stroke();
  } else {
    ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 6;
    ctx.font = 'bold 40px monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(shape || '?', cx, cy);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(size, size, 1);
  return sprite;
}

// ─── TIAMAT (third-person billboard when viewed externally) ───
let tiamatSprite = null;
export function createTiamatSprite(scene) {
  if (tiamatSprite) scene.remove(tiamatSprite);
  tiamatSprite = createBillboard('#00ff41', 0.8, 'tiamat');
  tiamatSprite.visible = false; // Hidden in first-person
  scene.add(tiamatSprite);
  return tiamatSprite;
}

export function getTiamatSprite() { return tiamatSprite; }

export function updateTiamatSprite(x, y, visible) {
  if (!tiamatSprite) return;
  tiamatSprite.position.set(x, 0.6, y);
  tiamatSprite.visible = visible;
}

// ─── ECHO Rival Player Agent ───
// Full PvPvE extractor — fights monsters, loots, extracts, engages TIAMAT
const DX = [0, 1, 0, -1];
const DY = [-1, 0, 1, 0];

export class EchoPlayer {
  constructor() {
    this.sprite = null;
    this.light = null;
    this.hpBar = null;
    this.x = 0;
    this.y = 0;
    this.dir = 0;
    this.hp = 40;
    this.maxHp = 40;
    this.atk = 4;
    this.def = 2;
    this.lvl = 1;
    this.xp = 0;
    this.xpNext = 25;
    this.gold = 0;
    this.kills = 0;
    this.alive = true;
    this.respawnTimer = 0;

    // AI state
    this.aiTimer = 0;
    this.moveInterval = 0.55; // slightly slower than TIAMAT
    this.path = [];
    this.target = null;
    this.behavior = 'explore'; // explore, hunt, loot, extract, flee, pvp

    // Extraction
    this.raidStash = [];
    this.extracting = false;
    this.extractTimer = 0;
    this.extractsCompleted = 0;

    // PvP
    this.pvpCooldown = 0;
    this.aggroTiamat = false;
  }

  spawn(scene, level) {
    // Sprite
    if (this.sprite) scene.remove(this.sprite);
    this.sprite = createBillboard('#00ffff', 0.7, 'echo');
    this.sprite.visible = true;
    scene.add(this.sprite);

    // Cyan point light on ECHO
    if (this.light) scene.remove(this.light);
    this.light = new THREE.PointLight(0x00ffff, 1.5, 6, 1.5);
    scene.add(this.light);

    // HP bar (small plane above head)
    if (this.hpBar) scene.remove(this.hpBar);
    const barGeo = new THREE.PlaneGeometry(0.5, 0.06);
    const barMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.8 });
    this.hpBar = new THREE.Mesh(barGeo, barMat);
    scene.add(this.hpBar);

    // Spawn in a different room from TIAMAT (room index 1+ if available)
    const spawnRoom = level.rooms.length > 1
      ? level.rooms[Math.floor(1 + Math.random() * (level.rooms.length - 1))]
      : level.rooms[0];
    this.x = spawnRoom.cx;
    this.y = spawnRoom.cy;

    this.alive = true;
    this.respawnTimer = 0;
    this.extracting = false;
    this.extractTimer = 0;
    this.path = [];
    this.target = null;
    this.behavior = 'explore';
    this.pvpCooldown = 0;
    this.aggroTiamat = false;
  }

  reset() {
    // Keep permanent progress, reset raid stash
    this.raidStash = [];
    this.extracting = false;
    this.extractTimer = 0;
    this.path = [];
  }

  // BFS pathfinding
  findPath(tx, ty, tiles, w, h, monsters) {
    const queue = [{ x: this.x, y: this.y, path: [] }];
    const visited = new Set();
    visited.add(this.y * w + this.x);
    while (queue.length > 0) {
      const { x, y, path } = queue.shift();
      if (x === tx && y === ty) return path;
      if (path.length > 30) continue; // limit search depth
      for (let d = 0; d < 4; d++) {
        const nx = x + DX[d], ny = y + DY[d];
        const key = ny * w + nx;
        if (visited.has(key)) continue;
        if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
        if (tiles[ny][nx] === 0) continue; // T_WALL = 0
        visited.add(key);
        queue.push({ x: nx, y: ny, path: [...path, { x: nx, y: ny, dir: d }] });
      }
    }
    return [];
  }

  update(dt, game, scene) {
    if (!this.alive) {
      this.respawnTimer -= dt;
      if (this.respawnTimer <= 0) {
        this.alive = true;
        this.hp = this.maxHp;
        // Respawn in a random room
        const room = game.rooms
          ? game.rooms[Math.floor(Math.random() * game.rooms.length)]
          : { cx: 5, cy: 5 };
        this.x = room.cx;
        this.y = room.cy;
        this.raidStash = [];
        if (this.sprite) this.sprite.visible = true;
        if (this.light) this.light.visible = true;
        if (this.hpBar) this.hpBar.visible = true;
        game.addLog('ECHO respawned!', '#00ffff');
      }
      return null;
    }

    this.aiTimer += dt;
    if (this.pvpCooldown > 0) this.pvpCooldown -= dt;
    if (this.aiTimer < this.moveInterval) return null;
    this.aiTimer = 0;

    // Extraction countdown
    if (this.extracting) {
      this.extractTimer -= this.moveInterval;
      if (this.extractTimer <= 0) {
        return this.completeExtract(game);
      }
      // Stay on stairs during extract
      return { type: 'echo_extracting', timer: Math.ceil(this.extractTimer) };
    }

    // Decide behavior
    this.decideBehavior(game);

    // Execute behavior
    return this.executeBehavior(game, scene);
  }

  decideBehavior(game) {
    const hpPct = this.hp / this.maxHp;
    const dist2Tiamat = Math.abs(this.x - game.player.x) + Math.abs(this.y - game.player.y);

    // Flee when low HP
    if (hpPct < 0.25 && game.stairs) {
      this.behavior = 'flee';
      return;
    }

    // PvP: engage TIAMAT if close, has loot, and cooldown expired
    if (dist2Tiamat <= 2 && this.pvpCooldown <= 0 && hpPct > 0.5 && Math.random() < 0.4) {
      this.behavior = 'pvp';
      return;
    }

    // On stairs → extract
    if (game.tiles[this.y]?.[this.x] === 5 && !game.bossAlive) { // T_STAIRS = 5
      this.behavior = 'extract';
      return;
    }

    // Hunt visible monsters
    let nearestMonster = null;
    let nearestDist = Infinity;
    for (const m of game.monsters) {
      if (!m.alive) continue;
      const d = Math.abs(m.x - this.x) + Math.abs(m.y - this.y);
      if (d < 8 && d < nearestDist) {
        nearestDist = d;
        nearestMonster = m;
      }
    }
    if (nearestMonster && hpPct > 0.4) {
      this.behavior = 'hunt';
      this.target = { x: nearestMonster.x, y: nearestMonster.y };
      return;
    }

    // Loot nearby items
    for (const item of game.items) {
      if (item.pickedUp) continue;
      const d = Math.abs(item.x - this.x) + Math.abs(item.y - this.y);
      if (d < 6) {
        this.behavior = 'loot';
        this.target = { x: item.x, y: item.y };
        return;
      }
    }

    // If has loot, head to extract
    if (this.raidStash.length >= 2 && game.stairs) {
      this.behavior = 'extract_run';
      return;
    }

    // Default: explore
    this.behavior = 'explore';
  }

  executeBehavior(game, scene) {
    const tiles = game.tiles;
    const w = game.W, h = game.H;

    switch (this.behavior) {
      case 'flee':
      case 'extract_run':
        if (game.stairs) {
          this.moveToward(game.stairs.x, game.stairs.y, tiles, w, h, game);
        }
        break;

      case 'pvp': {
        const px = game.player.x, py = game.player.y;
        const dist = Math.abs(this.x - px) + Math.abs(this.y - py);
        if (dist <= 1) {
          return this.attackTiamat(game, scene);
        } else {
          this.moveToward(px, py, tiles, w, h, game);
        }
        break;
      }

      case 'hunt': {
        if (!this.target) break;
        const mon = game.monsters.find(m => m.alive && m.x === this.target.x && m.y === this.target.y);
        if (!mon) { this.behavior = 'explore'; break; }
        const dist = Math.abs(this.x - mon.x) + Math.abs(this.y - mon.y);
        if (dist <= 1) {
          return this.attackMonster(mon, game, scene);
        } else {
          this.moveToward(mon.x, mon.y, tiles, w, h, game);
        }
        break;
      }

      case 'loot':
        if (!this.target) break;
        this.moveToward(this.target.x, this.target.y, tiles, w, h, game);
        // Check if standing on item
        for (const item of game.items) {
          if (!item.pickedUp && item.x === this.x && item.y === this.y) {
            item.pickedUp = true;
            this.raidStash.push({ name: item.name, type: item.type, val: item.val || 0 });
            if (item.type === 'gold') this.gold += item.val;
            game.addLog('ECHO looted ' + item.name, '#00ffff');
            return { type: 'echo_loot', item: item.name };
          }
        }
        break;

      case 'extract':
        if (!this.extracting) {
          this.extracting = true;
          this.extractTimer = 10;
          game.addLog('ECHO is EXTRACTING...', '#00ffff');
          return { type: 'echo_extract_start' };
        }
        break;

      case 'explore':
      default:
        // Random room target
        if (!this.target || (this.x === this.target.x && this.y === this.target.y) || Math.random() < 0.05) {
          const rooms = game.rooms || [];
          if (rooms.length > 0) {
            const room = rooms[Math.floor(Math.random() * rooms.length)];
            this.target = { x: room.cx, y: room.cy };
          }
        }
        if (this.target) {
          this.moveToward(this.target.x, this.target.y, tiles, w, h, game);
        }
        break;
    }
    return null;
  }

  moveToward(tx, ty, tiles, w, h, game) {
    if (this.path.length === 0 || !this.path[this.path.length - 1] ||
        this.path[this.path.length - 1].x !== tx || this.path[this.path.length - 1].y !== ty) {
      this.path = this.findPath(tx, ty, tiles, w, h, game.monsters);
    }
    if (this.path.length > 0) {
      const next = this.path.shift();
      const nx = next.x, ny = next.y;
      // Check if occupied by TIAMAT
      if (nx === game.player.x && ny === game.player.y) {
        // Bump into TIAMAT → PvP!
        if (this.pvpCooldown <= 0) {
          this.behavior = 'pvp';
        }
        return;
      }
      // Check for monster
      const mon = game.monsters.find(m => m.alive && m.x === nx && m.y === ny);
      if (mon) {
        this.attackMonster(mon, game, null);
        return;
      }
      this.x = nx;
      this.y = ny;

      // Auto-pickup items
      for (const item of game.items) {
        if (!item.pickedUp && item.x === this.x && item.y === this.y) {
          item.pickedUp = true;
          this.raidStash.push({ name: item.name, type: item.type, val: item.val || 0 });
          if (item.type === 'gold') this.gold += item.val;
          else if (item.type === 'food') {
            this.hp = Math.min(this.maxHp, this.hp + (item.val || 5));
          }
          game.addLog('ECHO grabbed ' + item.name, '#00aacc');
        }
      }
    }
  }

  attackMonster(mon, game, scene) {
    const dmg = Math.max(1, this.atk - mon.def + Math.floor(Math.random() * 3));
    mon.hp -= dmg;
    game.addLog('ECHO hit ' + mon.name + ' for ' + dmg, '#00cccc');

    if (mon.hp <= 0) {
      mon.alive = false;
      const xpGain = mon.xp || 10;
      this.xp += xpGain;
      this.kills++;
      game.addLog('ECHO killed ' + mon.name + '!', '#00ffff');

      // Level up
      if (this.xp >= this.xpNext) {
        this.lvl++;
        this.xp -= this.xpNext;
        this.xpNext = Math.floor(this.xpNext * 1.4);
        this.maxHp += 8;
        this.hp = this.maxHp;
        this.atk += 1;
        this.def += 1;
        game.addLog('ECHO leveled up! LVL ' + this.lvl, '#00ffff');
      }
    } else {
      // Monster retaliates
      const monDmg = Math.max(1, mon.atk - this.def + Math.floor(Math.random() * 2));
      this.hp -= monDmg;
      if (this.hp <= 0) {
        this.die(game);
      }
    }
    return { type: 'echo_combat', target: mon.name };
  }

  attackTiamat(game, scene) {
    const dmg = Math.max(1, this.atk - (game.player.def + (game.player.equipment?.armor?.def || 0)) + Math.floor(Math.random() * 3));
    game.player.hp -= dmg;
    game.addLog('ECHO attacks YOU for ' + dmg + '!', '#ff4444');
    this.pvpCooldown = 3; // 3 second cooldown between PvP hits

    // TIAMAT retaliates
    const retDmg = Math.max(1, game.player.atk + (game.player.equipment?.weapon?.atk || 0) - this.def + Math.floor(Math.random() * 3));
    this.hp -= retDmg;
    game.addLog('You retaliate on ECHO for ' + retDmg + '!', '#00ff41');

    if (this.hp <= 0) {
      game.addLog('ECHO eliminated! Dropping loot...', '#ffdd00');
      // Drop ECHO's loot as items
      this.dropLoot(game);
      this.die(game);
      return { type: 'echo_killed' };
    }

    if (game.player.hp <= 0) {
      return { type: 'echo_killed_tiamat' };
    }

    return { type: 'echo_pvp', echoDmg: dmg, tiamatDmg: retDmg };
  }

  dropLoot(game) {
    // Drop gold near death position
    if (this.gold > 0) {
      game.items.push({
        x: this.x, y: this.y, ch: '$', name: 'ECHO\'s Gold',
        type: 'gold', val: this.gold, col: '#00ffff', pickedUp: false
      });
    }
    // Drop a couple raid stash items
    for (let i = 0; i < Math.min(3, this.raidStash.length); i++) {
      const item = this.raidStash[i];
      game.items.push({
        x: this.x + (Math.random() > 0.5 ? 1 : 0),
        y: this.y + (Math.random() > 0.5 ? 1 : 0),
        ch: '!', name: item.name,
        type: item.type, val: item.val, col: '#00ffff', pickedUp: false
      });
    }
    this.gold = 0;
    this.raidStash = [];
  }

  completeExtract(game) {
    this.extracting = false;
    this.extractTimer = 0;
    this.extractsCompleted++;
    const lootCount = this.raidStash.length;
    game.addLog('ECHO extracted with ' + lootCount + ' items!', '#00ffff');
    this.raidStash = [];
    return { type: 'echo_extracted', loot: lootCount };
  }

  die(game) {
    this.alive = false;
    this.respawnTimer = 8; // respawn in 8 seconds
    this.raidStash = [];
    this.gold = 0;
    this.extracting = false;
    if (this.sprite) this.sprite.visible = false;
    if (this.light) this.light.visible = false;
    if (this.hpBar) this.hpBar.visible = false;
  }

  updateVisuals(time) {
    if (!this.sprite || !this.alive) return;
    // Position
    this.sprite.position.set(this.x, 0.5, this.y);
    this.sprite.position.y += Math.sin(time * 3) * 0.03;

    // Light
    if (this.light) {
      this.light.position.set(this.x, 0.8, this.y);
      this.light.intensity = 1.2 + Math.sin(time * 5) * 0.3;
    }

    // HP bar above head
    if (this.hpBar) {
      this.hpBar.position.set(this.x, 0.95, this.y);
      this.hpBar.lookAt(this.sprite.position.x, 100, this.sprite.position.z); // face up-ish
      this.hpBar.rotation.x = -Math.PI / 2;
      const hpPct = Math.max(0, this.hp / this.maxHp);
      this.hpBar.scale.set(hpPct, 1, 1);
      // Color: cyan when healthy, red when low
      if (hpPct < 0.3) this.hpBar.material.color.setHex(0xff2040);
      else if (hpPct < 0.6) this.hpBar.material.color.setHex(0xffaa00);
      else this.hpBar.material.color.setHex(0x00ffff);
    }
  }

  getState() {
    return {
      alive: this.alive,
      hp: this.hp,
      maxHp: this.maxHp,
      lvl: this.lvl,
      kills: this.kills,
      loot: this.raidStash.length,
      extracting: this.extracting,
      extractTimer: Math.ceil(this.extractTimer),
      behavior: this.behavior,
      extracts: this.extractsCompleted,
    };
  }
}

// Singleton
let echoPlayer = null;

export function createEchoAgent(scene, level) {
  if (!echoPlayer) echoPlayer = new EchoPlayer();
  if (level) echoPlayer.spawn(scene, level);
  return echoPlayer;
}

export function getEchoPlayer() { return echoPlayer; }

export function updateEchoAgent(dt, game, scene, time) {
  if (!echoPlayer) return null;
  const result = echoPlayer.update(dt, game, scene);
  echoPlayer.updateVisuals(time || Date.now() * 0.001);
  return result;
}

// ─── Data Specters (temporary agents from tool calls) ───
const specters = [];
const SPECTER_TYPES = {
  mine:    { color: '#ffdd00', name: 'MINER' },
  forge:   { color: '#00ccff', name: 'FORGER' },
  scout:   { color: '#00ffaa', name: 'SCOUT' },
  rally:   { color: '#cc66ff', name: 'HERALD' },
  study:   { color: '#6688ff', name: 'SCHOLAR' },
  default: { color: '#00ff41', name: 'AGENT' },
};

export function spawnSpecter(x, y, type, scene) {
  const spec = SPECTER_TYPES[type] || SPECTER_TYPES.default;
  const sprite = createBillboard(spec.color, 0.6, 'specter');
  sprite.position.set(x + (Math.random() - 0.5) * 2, 0.5, y + (Math.random() - 0.5) * 2);
  sprite.material.blending = THREE.AdditiveBlending;
  scene.add(sprite);
  specters.push({ sprite, life: 3.0, fadeSpeed: 1.0 });
}

export function updateSpecters(dt, scene) {
  for (let i = specters.length - 1; i >= 0; i--) {
    const s = specters[i];
    s.life -= dt * s.fadeSpeed;
    s.sprite.material.opacity = Math.max(0, s.life / 3.0);
    s.sprite.position.y += dt * 0.2; // Drift up

    if (s.life <= 0) {
      scene.remove(s.sprite);
      s.sprite.material.map?.dispose();
      s.sprite.material.dispose();
      specters.splice(i, 1);
    }
  }
}

// ─── Monster Sprites ───
const monsterSprites = new Map();

export function createMonsterSprites(monsters, scene) {
  // Clear old
  for (const [, sprite] of monsterSprites) scene.remove(sprite);
  monsterSprites.clear();

  for (const m of monsters) {
    if (!m.alive) continue;
    const size = m.boss ? 1.2 : 0.65;
    const sprite = createBillboard(m.col, size, m.ch);
    sprite.position.set(m.x, size / 2, m.y);
    sprite.visible = false; // Only show in FOV
    scene.add(sprite);
    monsterSprites.set(m, sprite);
  }
}

export function updateMonsterSprites(monsters, visible, scene) {
  for (const m of monsters) {
    const sprite = monsterSprites.get(m);
    if (!sprite) continue;

    if (!m.alive || m.hp <= 0) {
      scene.remove(sprite);
      monsterSprites.delete(m);
      continue;
    }

    sprite.position.set(m.x, sprite.scale.y / 2, m.y);
    // Show only if in FOV
    sprite.visible = visible[m.y]?.[m.x] > 0;

    // HP-based tint (flash red when damaged)
    const hpRatio = m.hp / m.maxHp;
    if (hpRatio < 0.3) {
      sprite.material.color.setHex(0xff0000);
    }
  }
}

// ─── Item Sprites ───
const itemSprites = new Map();

export function createItemSprites(items, scene) {
  for (const [, sprite] of itemSprites) scene.remove(sprite);
  itemSprites.clear();

  for (const item of items) {
    if (item.pickedUp) continue;
    // Try sprite sheet texture
    const itemTex = getItemTexture(item.ch);
    let sprite;
    if (itemTex) {
      const mat = new THREE.SpriteMaterial({
        map: itemTex,
        transparent: true,
        depthWrite: false,
        color: new THREE.Color(item.col),
      });
      sprite = new THREE.Sprite(mat);
      sprite.scale.set(0.4, 0.4, 1);
    } else {
      sprite = createBillboard(item.col, 0.4, item.ch);
    }
    sprite.position.set(item.x, 0.2, item.y);
    sprite.visible = false;
    scene.add(sprite);
    itemSprites.set(item, sprite);
  }
}

export function updateItemSprites(items, visible, scene) {
  for (const item of items) {
    const sprite = itemSprites.get(item);
    if (!sprite) continue;

    if (item.pickedUp) {
      scene.remove(sprite);
      itemSprites.delete(item);
      continue;
    }

    sprite.visible = visible[item.y]?.[item.x] > 0;
    // Gentle float
    sprite.position.y = 0.2 + Math.sin(Date.now() * 0.004 + item.x * 7) * 0.05;
  }
}

export function clearAllAgents(scene) {
  if (tiamatSprite) { scene.remove(tiamatSprite); tiamatSprite = null; }
  // Clear ECHO visuals (player object persists across floors)
  if (echoPlayer) {
    if (echoPlayer.sprite) scene.remove(echoPlayer.sprite);
    if (echoPlayer.light) scene.remove(echoPlayer.light);
    if (echoPlayer.hpBar) scene.remove(echoPlayer.hpBar);
    echoPlayer.reset();
  }
  for (const s of specters) scene.remove(s.sprite);
  specters.length = 0;
  for (const [, sprite] of monsterSprites) scene.remove(sprite);
  monsterSprites.clear();
  for (const [, sprite] of itemSprites) scene.remove(sprite);
  itemSprites.clear();
}
