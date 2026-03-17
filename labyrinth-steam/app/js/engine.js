// LABYRINTH 3D — Three.js Scene, Renderer, Camera, Lighting, Game Loop
import * as THREE from 'three';
import { DungeonGen, BIOMES, T_WALL, T_STAIRS } from './dungeon-gen.js';
import { buildDungeonMesh, getBiomeMaterials, getBiomeBackgroundColor, lerpBiomeMaterials, updateTorchFlames, loadDungeonTextures } from './dungeon-mesh.js';
import {
  loadSplatTexture, createFogParticles,
  updateFogParticles, updateEventParticles, updateExtractRing,
  clearAllParticles, createDustMotes, updateDustMotes,
  emitParticles, updateExtractProgress, getParticleCount
} from './particles.js';
import {
  createTiamatSprite, getTiamatSprite, createEchoAgent, getEchoPlayer,
  updateEchoAgent, updateSpecters, createMonsterSprites,
  updateMonsterSprites, createItemSprites, updateItemSprites,
  clearAllAgents, loadAgentTextures
} from './agents.js';
import { processBoostQueue, startDataPolling, getCurrentMood } from './data-driver.js';
import { ExtractorLoop } from './extractor.js';
import { HUDOverlay, setOnSpectateSwitch } from './hud-overlay.js';
import { initAudio, playAmbient, playSFX } from './audio.js';
import { preloadAssets, hasModels, addGLTFProps } from './asset-loader.js';
import { PostFX } from './post-fx.js';
import { initDamageSplats, spawnSplat, updateSplats } from './damage-splats.js';

// ─── Constants ───
let RENDER_W = Math.min(960, window.innerWidth);
let RENDER_H = Math.min(540, window.innerHeight);
const FOV = 70;
const FPS_CAP = 20;
const FRAME_TIME = 1000 / FPS_CAP;
const MAP_W = 40, MAP_H = 25;

// ─── Globals ───
let renderer, scene, camera;
let playerLight, playerLight2, ambientLight, hemiLight;
let dungeonGroup = null;
let level = null;
let hud = null;
let extractor = null;
let lastFrameTime = 0;
let gameTime = 0;
let skyDome = null;
let postFX = null;

// Camera state
const camPos = new THREE.Vector3();
const camLookAt = new THREE.Vector3();
const DIR_ANGLES = [0, Math.PI / 2, Math.PI, -Math.PI / 2]; // N, E, S, W
const DX = [0, 1, 0, -1];
const DY = [-1, 0, 1, 0];

// Camera shake state
let shakeIntensity = 0;
let shakeDuration = 0;
let shakeTimer = 0;

function triggerShake(intensity, duration) {
  shakeIntensity = intensity;
  shakeDuration = duration;
  shakeTimer = duration;
}

// Performance tracking
const PERF = { drawCalls: 0, triangles: 0, fps: 0, frameMs: 0 };
let perfOverlayVisible = false;
let perfOverlay = null;

// Boost effect timers
let rageTimer = 0;
let rageSavedIntensity = 0;
let legendaryTimer = 0;
let legendaryFading = false;
let scoutEnergyTimer = 0;
let scoutEnergyOriginal = 0;
let xpMultiplier = 1;
let xpMultiplierTimer = 0;

// Game state
const Game = {
  W: MAP_W, H: MAP_H,
  tiles: null, visible: null, explored: null,
  player: { x: 0, y: 0, dir: 0, hp: 50, maxHp: 50, atk: 5, def: 2, lvl: 1, xp: 0, xpNext: 30, gold: 0, potions: 2, kills: 0, equipment: { weapon: null, armor: null, ring: null } },
  monsters: [], items: [], stairs: null, torches: [],
  depth: 1, turnCount: 0, totalKills: 0, bossAlive: false,
  mood: 'processing', biome: BIOMES.processing,
  log: [], killStreak: { count: 0, timer: 0 },
  sessionStats: { floorsCleared: 0, monstersKilled: 0, goldEarned: 0, deaths: 0, maxDepth: 1 },
  energy: 0.5,

  addLog(text, color) {
    this.log.push({ text, color: color || '#00ff41', time: Date.now() });
    if (this.log.length > 50) this.log.shift();
    if (hud) hud.addLogEntry(text, color);
  },

  computeFov() {
    for (let y = 0; y < this.H; y++) this.visible[y].fill(0);
    const px = this.player.x, py = this.player.y, R = 8 + Math.floor(this.energy * 3);
    this.visible[py][px] = 1; this.explored[py][px] = 1;
    for (let a = 0; a < 360; a += 1.5) {
      const rad = a * Math.PI / 180;
      const dx = Math.cos(rad), dy = Math.sin(rad);
      let rx = px + .5, ry = py + .5;
      for (let d = 0; d < R; d++) {
        rx += dx; ry += dy;
        const ix = Math.floor(rx), iy = Math.floor(ry);
        if (ix < 0 || ix >= this.W || iy < 0 || iy >= this.H) break;
        this.visible[iy][ix] = 1;
        this.explored[iy][ix] = 1;
        if (this.tiles[iy][ix] === T_WALL) break;
      }
    }
  },

  isWalkable(x, y) {
    if (x < 0 || x >= this.W || y < 0 || y >= this.H) return false;
    return this.tiles[y][x] !== T_WALL;
  },

  monsterAt(x, y) {
    return this.monsters.find(m => m.alive && m.x === x && m.y === y) || null;
  },
};

// ─── AI Pathfinding ───
function findPath(sx, sy, tx, ty) {
  const queue = [{ x: sx, y: sy, path: [] }];
  const visited = new Set();
  visited.add(sy * MAP_W + sx);
  while (queue.length > 0) {
    const { x, y, path } = queue.shift();
    if (x === tx && y === ty) return path;
    for (let d = 0; d < 4; d++) {
      const nx = x + DX[d], ny = y + DY[d];
      const key = ny * MAP_W + nx;
      if (visited.has(key)) continue;
      if (!Game.isWalkable(nx, ny)) continue;
      visited.add(key);
      queue.push({ x: nx, y: ny, path: [...path, { x: nx, y: ny, dir: d }] });
    }
  }
  return [];
}

// ─── AI Auto-play ───
let aiPath = [];
let aiTimer = 0;
const AI_MOVE_INTERVAL = 0.45;

function aiTick(dt) {
  aiTimer += dt;
  if (aiTimer < AI_MOVE_INTERVAL) return;
  aiTimer = 0;

  const p = Game.player;

  // On stairs → extract
  if (Game.tiles[p.y]?.[p.x] === T_STAIRS && !Game.bossAlive) {
    if (!extractor.extracting) {
      extractor.startExtract(p.x, p.y);
      Game.addLog('EXTRACTING...', '#ffaa00');
    }
    return;
  }

  // Find target
  let target = null;
  let bestDist = Infinity;

  for (const m of Game.monsters) {
    if (!m.alive) continue;
    if (!Game.visible[m.y]?.[m.x]) continue;
    const d = Math.abs(m.x - p.x) + Math.abs(m.y - p.y);
    if (d < bestDist) { bestDist = d; target = { x: m.x, y: m.y }; }
  }

  if (p.hp < p.maxHp * 0.25 || !target) {
    if (Game.stairs) target = { x: Game.stairs.x, y: Game.stairs.y };
  }

  if (!target) {
    const dirs = [0, 1, 2, 3].filter(d => Game.isWalkable(p.x + DX[d], p.y + DY[d]));
    if (dirs.length > 0) {
      const d = dirs[Math.floor(Math.random() * dirs.length)];
      movePlayer(DX[d], DY[d]);
    }
    return;
  }

  if (aiPath.length === 0 || (aiPath[aiPath.length - 1].x !== target.x || aiPath[aiPath.length - 1].y !== target.y)) {
    aiPath = findPath(p.x, p.y, target.x, target.y);
  }

  if (aiPath.length > 0) {
    const next = aiPath.shift();
    movePlayer(next.x - p.x, next.y - p.y);
  }
}

function movePlayer(dx, dy) {
  const p = Game.player;
  const nx = p.x + dx, ny = p.y + dy;
  if (!Game.isWalkable(nx, ny)) return;

  if (dy < 0) p.dir = 0;
  else if (dx > 0) p.dir = 1;
  else if (dy > 0) p.dir = 2;
  else if (dx < 0) p.dir = 3;

  const mon = Game.monsterAt(nx, ny);
  if (mon) {
    const dmg = Math.max(1, Game.player.atk + (Game.player.equipment.weapon?.atk || 0) - mon.def + Math.floor(Math.random() * 3));
    mon.hp -= dmg;
    Game.addLog('Hit ' + mon.name + ' for ' + dmg + '!', '#ff8844');
    spawnSplat(mon.x, 0.6, mon.y, '-' + dmg, '#ff8844', 'hit');
    triggerShake(0.03, 0.3);
    emitParticles(mon.x, mon.y, 'default', 3).forEach(m => scene.add(m));
    playSFX('hit');

    if (mon.hp <= 0) {
      mon.alive = false;
      const xpGain = Math.ceil(mon.xp * xpMultiplier);
      Game.player.xp += xpGain;
      Game.player.kills++;
      Game.totalKills++;
      Game.killStreak.count++;
      Game.killStreak.timer = 0; // Reset streak timer on each kill
      Game.addLog(mon.name + ' destroyed! +' + xpGain + 'XP', '#ffdd00');
      spawnSplat(mon.x, 0.8, mon.y, '+' + xpGain + 'XP', '#ffdd00', 'xp');
      extractor.addXP(xpGain);
      triggerShake(0.01, 0.15);
      emitParticles(mon.x, mon.y, 'death', 8).forEach(m => scene.add(m));
      playSFX('kill');
      if (hud) hud.updateKillStreak(Game.killStreak.count);

      if (Game.player.xp >= Game.player.xpNext) {
        Game.player.lvl++;
        Game.player.xp -= Game.player.xpNext;
        Game.player.xpNext = Math.floor(Game.player.xpNext * 1.5);
        Game.player.maxHp += 10;
        Game.player.hp = Game.player.maxHp;
        Game.player.atk += 2;
        Game.player.def += 1;
        Game.addLog('LEVEL UP! LVL ' + Game.player.lvl, '#00ff41');
        spawnSplat(Game.player.x, 1.0, Game.player.y, 'LEVEL UP!', '#00ff41', 'crit');
        emitParticles(Game.player.x, Game.player.y, 'legendary', 12).forEach(m => scene.add(m));
        triggerShake(0.04, 0.4);
        playSFX('levelup');
        if (hud) hud.flashLevelUp();
      }
    }
    monstersAttack();
    Game.turnCount++;
    Game.computeFov();
    return;
  }

  p.x = nx; p.y = ny;
  Game.turnCount++;
  playSFX('step');

  const item = Game.items.find(i => !i.pickedUp && i.x === nx && i.y === ny);
  if (item) {
    item.pickedUp = true;
    if (item.type === 'gold') { p.gold += item.val; Game.addLog('+' + item.val + ' gold!', '#ffdd00'); }
    else if (item.type === 'potion') { p.potions++; Game.addLog('Got ' + item.name + '!', item.col); }
    else if (item.type === 'attack') { p.atk += item.val; Game.addLog(item.name + '! +' + item.val + ' ATK', item.col); }
    else if (item.type === 'defense') { p.def += item.val; Game.addLog(item.name + '! +' + item.val + ' DEF', item.col); }
    else if (item.type === 'food') {
      const heal = item.val + Math.floor(Math.random() * 10);
      p.hp = Math.min(p.maxHp, p.hp + heal);
      Game.addLog('Ate ' + item.name + '! +' + heal + 'HP', '#cc6633');
    }
    spawnSplat(item.x, 0.4, item.y, '+' + item.name, item.col, 'heal');
    emitParticles(item.x, item.y, 'mine', 4).forEach(m => scene.add(m));
    playSFX('pickup');
    extractor.addLoot(item);
  }

  if (Game.tiles[ny]?.[nx] === T_STAIRS && !Game.bossAlive) {
    if (!extractor.extracting) {
      extractor.startExtract(nx, ny);
      Game.addLog('EXTRACTING...', '#ffaa00');
    }
  }

  monstersAttack();
  Game.computeFov();
}

function monstersAttack() {
  const p = Game.player;
  for (const m of Game.monsters) {
    if (!m.alive) continue;
    const dist = Math.abs(m.x - p.x) + Math.abs(m.y - p.y);
    if (Game.visible[m.y]?.[m.x]) m.alert = true;
    if (!m.alert || dist > 6) continue;

    if (dist <= 1) {
      const dmg = Math.max(1, m.atk - (p.def + (p.equipment.armor?.def || 0)) + Math.floor(Math.random() * 2));
      p.hp -= dmg;
      spawnSplat(p.x, 0.7, p.y, '-' + dmg, '#ff2040', 'hit');
      emitParticles(p.x, p.y, 'curse', 5).forEach(pm => scene.add(pm));
      if (hud) hud.flashDamage();
      if (p.hp <= 0) {
        Game.addLog('DEATH! Lost all raid loot!', '#ff0040');
        spawnSplat(p.x, 1.0, p.y, 'DEATH!', '#ff0040', 'crit');
        emitParticles(p.x, p.y, 'death', 15).forEach(pm => scene.add(pm));
        triggerShake(0.1, 0.8);
        playSFX('death');
        if (hud) hud.flashDeath();
        Game.sessionStats.deaths++;
        extractor.onDeath();
        p.hp = p.maxHp;
        p.gold = Math.floor(p.gold * 0.7);
        Game.depth = Math.max(1, Game.depth - 1);
        generateNewFloor();
        return;
      }
    } else {
      const mdx = Math.sign(p.x - m.x);
      const mdy = Math.sign(p.y - m.y);
      const mnx = m.x + mdx, mny = m.y + mdy;
      if (Game.isWalkable(mnx, mny) && !Game.monsterAt(mnx, mny)) {
        m.x = mnx; m.y = mny;
      }
    }
  }
}

// ─── Level Generation ───
function generateNewFloor() {
  if (dungeonGroup) {
    scene.remove(dungeonGroup);
    clearAllParticles(scene);
    clearAllAgents(scene);
  }

  const mood = getCurrentMood() || Game.mood;
  level = DungeonGen.generate(MAP_W, MAP_H, Game.depth, mood, null, Game.energy);

  // Density scaling: higher energy = more monsters and items post-gen
  if (Game.energy > 0.6) {
    const extraMonsters = Math.floor((Game.energy - 0.5) * 6);
    for (let em = 0; em < extraMonsters && level.rooms.length > 1; em++) {
      const room = level.rooms[1 + Math.floor(Math.random() * (level.rooms.length - 1))];
      const mx = room.x + 1 + Math.floor(Math.random() * Math.max(1, room.w - 2));
      const my = room.y + 1 + Math.floor(Math.random() * Math.max(1, room.h - 2));
      if (level.tiles[my]?.[mx] === 1) {
        const scale = 1 + (Game.depth - 1) * 0.1;
        level.monsters.push({
          x: mx, y: my, ch: 's', name: 'Skeleton', col: '#ccccaa',
          hp: Math.ceil(15 * scale), maxHp: Math.ceil(15 * scale),
          atk: Math.ceil(4 * scale), def: Math.ceil(1 * scale),
          xp: Math.ceil(12 * scale), alive: true, alert: false
        });
      }
    }
  }

  Game.tiles = level.tiles;
  Game.monsters = level.monsters;
  Game.items = level.items;
  Game.stairs = level.stairs;
  Game.torches = level.torches;
  Game.bossAlive = level.monsters.some(m => m.boss);

  Game.visible = [];
  Game.explored = [];
  for (let y = 0; y < MAP_H; y++) {
    Game.visible[y] = new Uint8Array(MAP_W);
    Game.explored[y] = new Uint8Array(MAP_W);
  }

  const spawn = level.rooms[0];
  Game.player.x = spawn.cx;
  Game.player.y = spawn.cy;
  Game.computeFov();

  // Build 3D dungeon — procedural geometry for walls/floors, GLTF props on top
  dungeonGroup = buildDungeonMesh(level, mood);
  scene.add(dungeonGroup);

  // Add GLTF props (barrels, chests, torches, etc.) if models loaded
  if (hasModels()) {
    const biomeForBuild = BIOMES[mood] || BIOMES.processing;
    addGLTFProps(level.tiles, MAP_W, MAP_H, level.torches, dungeonGroup, biomeForBuild.wire);
  }

  // Particles & atmosphere (no wall splats — they create floating billboard artifacts)
  const biome = BIOMES[mood] || BIOMES.processing;
  createFogParticles(level, biome.wire, scene);

  // Agents
  createTiamatSprite(scene);
  createEchoAgent(scene, level);
  createMonsterSprites(level.monsters, scene);
  createItemSprites(level.items, scene);

  // Torch lights (separate from geometry — these are actual light sources)
  createTorchLights(level.torches, biome);

  // Update scene fog
  const fogDensity = 0.04 + Game.depth * 0.003;
  scene.fog = new THREE.FogExp2(new THREE.Color(biome.floor).multiplyScalar(1.3).getHex(), fogDensity);

  // Set scene.background to biome-tinted ceiling color (darkened floor)
  scene.background = getBiomeBackgroundColor(mood);

  // Update sky dome color (ShaderMaterial — use uniforms)
  if (skyDome && skyDome.material.uniforms) {
    skyDome.material.uniforms.bottomColor.value.set(biome.floor);
  }

  // Update lighting colors — keep torch warm, blend 25% biome tint for contrast
  const warmTorch = new THREE.Color(0xffcc66);
  playerLight.color.copy(warmTorch).lerp(new THREE.Color(biome.wire), 0.25);
  playerLight2.color.copy(new THREE.Color(0x996644)).lerp(new THREE.Color(biome.accent || biome.wire), 0.2);
  // Biome-specific ambient light color
  const biomeAmbient = new THREE.Color(biome.wire).multiplyScalar(0.15);
  ambientLight.color.set(0x888888).lerp(biomeAmbient, 0.4);
  hemiLight.color.set(new THREE.Color(biome.wire).multiplyScalar(0.25));
  hemiLight.groundColor.set(biome.floor);

  // Camera snap
  camPos.set(Game.player.x, 0.55, Game.player.y);
  const angle = DIR_ANGLES[Game.player.dir];
  camLookAt.set(Game.player.x + Math.sin(angle), 0.5, Game.player.y - Math.cos(angle));

  aiPath = [];
  extractor.deploy(Game.depth);

  // Audio: ambient drone for new biome
  playAmbient(mood);

  // Reset boost effect timers
  rageTimer = 0;
  legendaryTimer = 0;
  scoutEnergyTimer = 0;
  xpMultiplier = 1;
  xpMultiplierTimer = 0;

  Game.addLog('DEPTH ' + Game.depth + ' — ' + biome.name, biome.wire);
}

// ─── Torch Lights (point lights, separate from geometry) ───
const torchLights = [];
function createTorchLights(torches, biome) {
  for (const tl of torchLights) scene.remove(tl);
  torchLights.length = 0;

  const wireColor = new THREE.Color(biome.wire);
  const maxTorches = 14;
  for (let i = 0; i < Math.min(torches.length, maxTorches); i++) {
    const t = torches[i];
    const light = new THREE.PointLight(wireColor, 2.5, 8, 1.3);
    light.position.set(t.x, 1.2, t.y);
    scene.add(light);
    torchLights.push(light);
  }
}

function updateTorchLights(time) {
  for (let i = 0; i < torchLights.length; i++) {
    torchLights[i].intensity = 1.5 + Math.sin(time * 7 + i * 2.3) * 0.5 + Math.sin(time * 11 + i * 5.1) * 0.3;
  }
}

// ─── Create Sky Dome + Ground Plane ───
let groundPlane = null;

function createSkyDome() {
  // Skybox — gradient sphere with subtle color
  const geo = new THREE.SphereGeometry(48, 24, 16);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    uniforms: {
      topColor: { value: new THREE.Color(0x0a0a14) },
      bottomColor: { value: new THREE.Color(0x1a0e08) },
      offset: { value: 5 },
      exponent: { value: 0.6 },
    },
    vertexShader: `
      varying vec3 vWorldPosition;
      void main() {
        vec4 worldPos = modelMatrix * vec4(position, 1.0);
        vWorldPosition = worldPos.xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform vec3 topColor;
      uniform vec3 bottomColor;
      uniform float offset;
      uniform float exponent;
      varying vec3 vWorldPosition;
      void main() {
        float h = normalize(vWorldPosition + offset).y;
        gl_FragColor = vec4(mix(bottomColor, topColor, max(pow(max(h, 0.0), exponent), 0.0)), 1.0);
      }
    `,
  });
  skyDome = new THREE.Mesh(geo, mat);
  skyDome.position.set(MAP_W / 2, 0, MAP_H / 2);
  scene.add(skyDome);

  // Ground plane — large dark surface under everything so you never see void
  const groundGeo = new THREE.PlaneGeometry(120, 80);
  const groundMat = new THREE.MeshLambertMaterial({ color: 0x0e0a08, side: THREE.DoubleSide });
  groundPlane = new THREE.Mesh(groundGeo, groundMat);
  groundPlane.rotation.x = -Math.PI / 2;
  groundPlane.position.set(MAP_W / 2, -0.01, MAP_H / 2);
  scene.add(groundPlane);
}

// ─── Init ───
export function init() {
  // Renderer
  renderer = new THREE.WebGLRenderer({
    canvas: document.getElementById('labyrinth-canvas'),
    antialias: false,
    alpha: true,
    powerPreference: 'low-power',
  });
  renderer.setSize(RENDER_W, RENDER_H);
  renderer.setPixelRatio(1);
  renderer.setClearColor(0x050505, 1);

  // Scene
  scene = new THREE.Scene();

  // Camera — slightly above floor level for better perspective
  camera = new THREE.PerspectiveCamera(FOV, RENDER_W / RENDER_H, 0.05, 50);
  camera.position.set(20, 0.55, 12);

  // ─── Lighting ───
  // Ambient — visible base so dungeon geometry is always readable (boosted 50%)
  ambientLight = new THREE.AmbientLight(0x888888, 2.25);
  scene.add(ambientLight);

  // Hemisphere light — warm sky/ground bounce for depth (boosted 50%)
  hemiLight = new THREE.HemisphereLight(0x998877, 0x443322, 1.8);
  scene.add(hemiLight);

  // Player torch — primary (warm, moderate range, not blown out)
  playerLight = new THREE.PointLight(0xffcc66, 4.0, 16, 1.0);
  playerLight.position.set(20, 0.7, 12);
  scene.add(playerLight);

  // Player secondary light — warm fill behind player
  playerLight2 = new THREE.PointLight(0x996644, 2.2, 10, 1.2);
  playerLight2.position.set(20, 0.3, 12);
  scene.add(playerLight2);

  // Fog — atmospheric distance fade (moderate)
  scene.fog = new THREE.FogExp2(0x0a0806, 0.05);

  // Post-processing (Bloom + Color Grading + Chromatic Aberration)
  postFX = new PostFX(renderer, scene, camera);

  // Damage splats (floating combat text)
  initDamageSplats();

  // Sky dome (dark background so you never see pure black void)
  createSkyDome();

  // Load assets (GLTF models + textures in parallel)
  preloadAssets().then(() => {
    console.log('KayKit GLTF models loaded');
    // Add GLTF props to current floor
    if (dungeonGroup && level && hasModels()) {
      const biome = BIOMES[Game.mood] || BIOMES.processing;
      addGLTFProps(level.tiles, MAP_W, MAP_H, level.torches, dungeonGroup, biome.wire);
    }
  });
  loadDungeonTextures();
  loadAgentTextures();
  loadSplatTexture();

  // Dust motes (persist across floors)
  createDustMotes(scene);

  // HUD
  hud = new HUDOverlay();
  setOnSpectateSwitch((target) => setSpectateTarget(target));

  // Extractor
  extractor = new ExtractorLoop();

  // Generate first floor
  generateNewFloor();

  // Audio
  initAudio();

  // Start data polling
  startDataPolling(5000);

  // Perf overlay (hidden by default)
  perfOverlay = document.createElement('div');
  perfOverlay.id = 'perf-overlay';
  perfOverlay.style.cssText = 'position:absolute;top:4px;right:160px;color:#00ff41;font:10px monospace;background:rgba(0,0,0,0.7);padding:4px 6px;display:none;z-index:100;pointer-events:none;';
  document.body.appendChild(perfOverlay);

  // Toggle perf overlay with 'P' key, telemetry with 'T' key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'P' || e.key === 'p') {
      perfOverlayVisible = !perfOverlayVisible;
      perfOverlay.style.display = perfOverlayVisible ? 'block' : 'none';
    }
    if (e.key === 'T' || e.key === 't') {
      if (hud) hud.toggleTelemetry();
    }
  });

  // Responsive resize
  window.addEventListener('resize', onResize);
  // Handle orientation change on mobile
  window.addEventListener('orientationchange', () => setTimeout(onResize, 100));

  // Start game loop (setAnimationLoop required for WebXR support)
  renderer.setAnimationLoop((timestamp) => {
    try { gameLoop(timestamp); } catch (e) { console.error('gameLoop error:', e); }
  });
}

function onResize() {
  RENDER_W = Math.min(960, window.innerWidth);
  RENDER_H = Math.min(540, window.innerHeight);
  if (renderer) {
    renderer.setSize(RENDER_W, RENDER_H);
  }
  if (camera) {
    camera.aspect = RENDER_W / RENDER_H;
    camera.updateProjectionMatrix();
  }
  if (postFX) postFX.resize(RENDER_W, RENDER_H);
}

// ─── Getters for external modules (WebXR) ───
export function getRenderer() { return renderer; }
export function getScene() { return scene; }
export function getCamera() { return camera; }

// ─── Spectator Mode ───
let spectateTarget = 'tiamat'; // 'tiamat' | 'echo'
let arFreeRoam = false;
let arYaw = 0, arPitch = 0; // gyroscope angles for AR free-roam

export function setSpectateTarget(target) {
  spectateTarget = target;
  // Make the non-spectated agent visible as third-person sprite
  const ts = getTiamatSprite();
  if (ts) ts.visible = (target !== 'tiamat');
  if (hud) hud.setSpectateTarget(target);
}

export function getSpectateTarget() { return spectateTarget; }

export function cycleSpectateTarget() {
  setSpectateTarget(spectateTarget === 'tiamat' ? 'echo' : 'tiamat');
}

// ─── Game Loop ───
let xrActive = false;
let xrMode = null; // 'vr' | 'ar'

export function setXRActive(active, mode) {
  xrActive = active;
  xrMode = active ? (mode || 'vr') : null;
  arFreeRoam = (xrMode === 'ar');
  if (active && scene) {
    // AR needs transparent background for camera passthrough
    scene.background = null;
    scene.fog = null;
    renderer.setClearColor(0x000000, 0);
    if (skyDome) skyDome.visible = false;
    if (groundPlane) groundPlane.visible = false;
    // AR free-roam: start gyroscope listener
    if (arFreeRoam) startGyroscope();
  } else if (scene) {
    renderer.setClearColor(0x050505, 1);
    scene.fog = new THREE.FogExp2(0x111008, 0.045);
    if (skyDome) skyDome.visible = true;
    if (groundPlane) groundPlane.visible = true;
    arFreeRoam = false;
  }
}

// ─── AR Gyroscope Free-Roam ───
let gyroHandler = null;
function startGyroscope() {
  if (gyroHandler) return;
  // Request permission on iOS
  if (typeof DeviceOrientationEvent !== 'undefined' && DeviceOrientationEvent.requestPermission) {
    DeviceOrientationEvent.requestPermission().then(r => {
      if (r === 'granted') attachGyro();
    }).catch(() => {});
  } else {
    attachGyro();
  }
}

function attachGyro() {
  gyroHandler = (e) => {
    if (e.alpha !== null) arYaw = THREE.MathUtils.degToRad(e.alpha);
    if (e.beta !== null) arPitch = THREE.MathUtils.clamp(THREE.MathUtils.degToRad(e.beta - 90), -1.2, 1.2);
  };
  window.addEventListener('deviceorientation', gyroHandler);
}

function gameLoop(timestamp) {
  if (!timestamp) timestamp = performance.now();
  const elapsed = timestamp - lastFrameTime;
  // Skip frame cap when XR is active — XR manages its own frame rate
  if (!xrActive && elapsed < FRAME_TIME) return;
  lastFrameTime = timestamp;

  const dt = Math.min(elapsed / 1000, 0.1);
  gameTime += dt;

  const frameStart = performance.now();

  // AI
  aiTick(dt);

  // Process TIAMAT data events with rich boost handling
  const boostEvents = processBoostQueue(Game, scene);
  for (const evt of boostEvents) {
    switch (evt.type) {
      case 'forge':
        triggerShake(0.02, 0.3);
        // Add a random torch light nearby
        {
          const tl = new THREE.PointLight(Game.biome?.wire || 0xffaa44, 0.8, 5, 2);
          tl.position.set(Game.player.x + (Math.random() - 0.5) * 4, 1.2, Game.player.y + (Math.random() - 0.5) * 4);
          scene.add(tl);
          torchLights.push(tl);
        }
        break;
      case 'scout':
        // Temporary FOV boost
        scoutEnergyOriginal = Game.energy;
        Game.energy = Math.min(1.0, Game.energy + 0.3);
        scoutEnergyTimer = 5.0;
        break;
      case 'curse':
        triggerShake(0.03, 0.3);
        // Spawn 1-2 extra monsters near player
        {
          const numExtra = 1 + Math.floor(Math.random() * 2);
          for (let ce = 0; ce < numExtra; ce++) {
            const cx = Game.player.x + Math.floor(Math.random() * 5) - 2;
            const cy = Game.player.y + Math.floor(Math.random() * 5) - 2;
            if (Game.isWalkable(cx, cy) && !Game.monsterAt(cx, cy)) {
              const scale = 1 + (Game.depth - 1) * 0.1;
              const m = { x: cx, y: cy, ch: 'g', name: 'Glitch', col: '#ff2040',
                hp: Math.ceil(12 * scale), maxHp: Math.ceil(12 * scale),
                atk: Math.ceil(5 * scale), def: 0, xp: Math.ceil(15 * scale),
                alive: true, alert: true };
              Game.monsters.push(m);
            }
          }
        }
        break;
      case 'rage':
        // Double playerLight intensity for 3s
        rageSavedIntensity = playerLight.intensity;
        rageTimer = 3.0;
        break;
      case 'legendary':
        // Flash ambient light up for 2s then fade
        legendaryTimer = 2.0;
        legendaryFading = false;
        ambientLight.color.set(0x444444);
        triggerShake(0.04, 0.4);
        break;
      case 'mine':
        // Add gold + sparkle
        {
          const goldAmt = 5 + Math.floor(Math.random() * 11);
          Game.player.gold += goldAmt;
          Game.addLog('+' + goldAmt + ' gold from DATA MINE', '#ffdd00');
        }
        break;
      case 'study':
        // Boost XP multiplier for 5s
        xpMultiplier = 2;
        xpMultiplierTimer = 5.0;
        break;
    }
  }

  // ─── Boost effect timers ───
  if (rageTimer > 0) {
    rageTimer -= dt;
    playerLight.intensity = (rageSavedIntensity || 2.5) * 2;
    if (rageTimer <= 0) playerLight.intensity = rageSavedIntensity || 2.5;
  }
  if (legendaryTimer > 0) {
    legendaryTimer -= dt;
    if (legendaryTimer <= 0) {
      ambientLight.color.set(0x1a1a1a);
    } else if (legendaryTimer < 0.5) {
      // Fade back
      ambientLight.color.lerp(new THREE.Color(0x1a1a1a), dt * 4);
    }
  }
  if (scoutEnergyTimer > 0) {
    scoutEnergyTimer -= dt;
    if (scoutEnergyTimer <= 0) {
      Game.energy = scoutEnergyOriginal;
    }
  }
  if (xpMultiplierTimer > 0) {
    xpMultiplierTimer -= dt;
    if (xpMultiplierTimer <= 0) xpMultiplier = 1;
  }

  // Kill streak timer decay
  if (Game.killStreak.count > 0) {
    Game.killStreak.timer += dt;
    if (Game.killStreak.timer > 5) {
      Game.killStreak.count = 0;
      Game.killStreak.timer = 0;
    }
  }

  // Extraction
  const extractResult = extractor.update(dt, Game.player.x, Game.player.y, scene);
  if (extractResult) {
    if (extractResult.type === 'extracting') {
      // Show extract progress in HUD and particles
      if (hud) hud.showExtractProgress(extractResult.progress);
      updateExtractProgress(extractResult.progress);
    } else if (extractResult.type === 'extract_success') {
      Game.addLog('EXTRACTED! +' + extractResult.loot + ' items, +' + extractResult.xp + ' XP banked', '#00ff41');
      Game.depth++;
      Game.sessionStats.floorsCleared++;
      Game.player.hp = Math.min(Game.player.maxHp, Game.player.hp + 10);
      triggerShake(0.06, 0.5);
      playSFX('extract');
      if (hud) hud.showExtractProgress(0);
      generateNewFloor();
    } else if (extractResult.type === 'extract_cancelled') {
      if (hud) hud.showExtractProgress(0);
    }
  } else if (!extractor.extracting && hud) {
    // Not extracting, hide progress
    hud.showExtractProgress(0);
  }

  // Biome transition
  const currentMood = getCurrentMood();
  if (currentMood !== Game.mood && dungeonGroup) {
    Game.mood = currentMood;
    Game.biome = BIOMES[currentMood] || BIOMES.processing;
    lerpBiomeMaterials(dungeonGroup, currentMood, dt * 2);
    playerLight.color.lerp(new THREE.Color(Game.biome.wire), dt * 2);
    scene.fog.color.lerp(new THREE.Color(Game.biome.floor), dt * 2);
    if (skyDome && skyDome.material.uniforms) {
      skyDome.material.uniforms.bottomColor.value.lerp(new THREE.Color(Game.biome.floor), dt * 2);
    }
    playAmbient(currentMood);
  }

  // ─── Camera (follows spectated target) ───
  const echo = getEchoPlayer();
  let camTargetX, camTargetZ, camAngle;

  if (spectateTarget === 'echo' && echo && echo.alive) {
    camTargetX = echo.x;
    camTargetZ = echo.y;
    // ECHO doesn't have a dir — derive from movement or face TIAMAT
    const dx = Game.player.x - echo.x, dz = Game.player.y - echo.y;
    camAngle = Math.atan2(dx, -dz);
  } else {
    camTargetX = Game.player.x;
    camTargetZ = Game.player.y;
    camAngle = DIR_ANGLES[Game.player.dir];
  }

  // Make spectated agent's sprite hidden, other visible
  const tiamatSpr = getTiamatSprite();
  if (tiamatSpr) {
    tiamatSpr.visible = (spectateTarget !== 'tiamat');
    tiamatSpr.position.set(Game.player.x, 0.6, Game.player.y);
  }
  if (echo && echo.sprite) echo.sprite.visible = (spectateTarget !== 'echo' && echo.alive);

  if (arFreeRoam) {
    // AR free-roam: gyroscope controls camera direction, position at dungeon center
    camPos.lerp(new THREE.Vector3(camTargetX, 1.0, camTargetZ), 0.05);
    camera.position.copy(camPos);
    // Gyroscope look direction
    const lookX = camPos.x + Math.sin(arYaw) * 3;
    const lookZ = camPos.z - Math.cos(arYaw) * 3;
    const lookY = camPos.y + Math.sin(arPitch) * 2;
    camera.lookAt(lookX, lookY, lookZ);
  } else if (!xrActive) {
    const lookDist = 2.5;
    const lookX = camTargetX + Math.sin(camAngle) * lookDist;
    const lookZ = camTargetZ - Math.cos(camAngle) * lookDist;

    // Smooth follow with slight bob
    const bob = Math.sin(gameTime * 3) * 0.008;
    camPos.lerp(new THREE.Vector3(camTargetX, 0.55 + bob, camTargetZ), 0.1);
    camLookAt.lerp(new THREE.Vector3(lookX, 0.48, lookZ), 0.07);

    camera.position.copy(camPos);
    camera.lookAt(camLookAt);

    // Camera shake
    if (shakeTimer > 0) {
      shakeTimer -= dt;
      const decay = shakeTimer / shakeDuration;
      const sx = (Math.random() - 0.5) * 2 * shakeIntensity * decay;
      const sy = (Math.random() - 0.5) * 2 * shakeIntensity * decay;
      const sz = (Math.random() - 0.5) * 2 * shakeIntensity * decay;
      camera.position.x += sx;
      camera.position.y += sy;
      camera.position.z += sz;
    }
  } else {
    // VR XR: headset controls camera, position at spectated player
    camPos.set(camTargetX, 0.55, camTargetZ);
  }

  // Player light follows camera (slightly above and behind)
  playerLight.position.set(camPos.x, 0.8, camPos.z);
  if (rageTimer <= 0) {
    playerLight.intensity = 3.8 + Math.sin(gameTime * 4.5) * 0.5 + Math.sin(gameTime * 7.3) * 0.3;
  }

  playerLight2.position.set(
    camPos.x - Math.sin(camAngle) * 0.5,
    0.3,
    camPos.z + Math.cos(camAngle) * 0.5
  );

  // ─── Updates ───
  updateFogParticles(dt);
  updateDustMotes(dt, Game.player.x, Game.player.y);
  updateEventParticles(dt, scene);
  updateExtractRing(gameTime);
  updateTorchLights(gameTime);
  updateTorchFlames(dungeonGroup, gameTime);

  // ECHO rival player — full AI with combat, looting, extraction, PvP
  const echoGame = {
    player: Game.player, tiles: Game.tiles, monsters: Game.monsters,
    items: Game.items, stairs: Game.stairs, bossAlive: Game.bossAlive,
    W: Game.W, H: Game.H, depth: Game.depth, rooms: level ? level.rooms : [],
    addLog: (t, c) => Game.addLog(t, c),
  };
  const echoResult = updateEchoAgent(dt, echoGame, scene, gameTime);
  if (echoResult) {
    if (echoResult.type === 'echo_killed_tiamat') {
      // ECHO killed TIAMAT — death sequence
      Game.addLog('KILLED BY ECHO!', '#ff0040');
      spawnSplat(Game.player.x, 1.0, Game.player.y, 'KILLED BY ECHO!', '#ff0040', 'crit');
      triggerShake(0.1, 0.8);
      playSFX('death');
      if (hud) hud.flashDeath();
      Game.sessionStats.deaths++;
      extractor.onDeath();
      Game.player.hp = Game.player.maxHp;
      Game.player.gold = Math.floor(Game.player.gold * 0.7);
      Game.depth = Math.max(1, Game.depth - 1);
      generateNewFloor();
    } else if (echoResult.type === 'echo_pvp') {
      triggerShake(0.04, 0.3);
      if (hud) hud.flashDamage();
      playSFX('hit');
      spawnSplat(Game.player.x, 0.7, Game.player.y, '-' + (echoResult.echoDmg || '?'), '#ff4444', 'hit');
      if (echoResult.tiamatDmg) {
        const ep = getEchoPlayer();
        if (ep) spawnSplat(ep.x, 0.7, ep.y, '-' + echoResult.tiamatDmg, '#00ffff', 'hit');
      }
      emitParticles(Game.player.x, Game.player.y, 'curse', 4).forEach(m => scene.add(m));
    } else if (echoResult.type === 'echo_killed') {
      // ECHO died — spawn loot particles
      const echo = getEchoPlayer();
      if (echo) emitParticles(echo.x, echo.y, 'mine', 8).forEach(m => scene.add(m));
      // Recreate item sprites to show ECHO's dropped loot
      createItemSprites(Game.items, scene);
      triggerShake(0.02, 0.2);
    } else if (echoResult.type === 'echo_extracted') {
      Game.addLog('ECHO extracted! Racing you...', '#00ffff');
    }
  }
  updateSpecters(dt, scene);
  updateMonsterSprites(Game.monsters, Game.visible, scene);
  updateItemSprites(Game.items, Game.visible, scene);

  // HUD
  if (hud) {
    hud.update(Game, extractor.getState(), Game.mood);
    hud.updateMinimap(Game);
    const echoForTelem = getEchoPlayer();
    hud.updateTelemetry(Game, echoForTelem ? echoForTelem.getState() : null);
  }

  // Update floating damage splats (project 3D → 2D)
  updateSplats(camera, renderer.domElement.clientWidth, renderer.domElement.clientHeight);

  // Render (post-processed: Bloom + Color Grading + Chromatic Aberration)
  if (postFX) {
    postFX.render(gameTime);
  } else {
    renderer.render(scene, camera);
  }

  // Performance tracking
  const frameEnd = performance.now();
  PERF.frameMs = frameEnd - frameStart;
  PERF.fps = Math.round(1000 / Math.max(1, elapsed));
  if (renderer.info) {
    PERF.drawCalls = renderer.info.render.calls || 0;
    PERF.triangles = renderer.info.render.triangles || 0;
  }
  if (perfOverlayVisible && perfOverlay) {
    perfOverlay.textContent = `FPS:${PERF.fps} DC:${PERF.drawCalls} TRI:${PERF.triangles} P:${getParticleCount()} F:${PERF.frameMs.toFixed(1)}ms`;
  }
}
