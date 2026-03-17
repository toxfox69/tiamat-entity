// LABYRINTH 2D — BSP Dungeon Generation
// Full evolved content: 11 base monsters, 21 biome monsters, 30 Venice monsters, 4 bosses
// 17 biomes (7 Three.js + 10 Venice), 10 floor narratives, 7 item types, 4 difficulty tiers

const T_WALL = 0;
const T_FLOOR = 1;
const T_CORRIDOR = 2;
const T_DOOR = 3;
const T_STAIRS = 4;

const MAP_W = 40;
const MAP_H = 25;

// ─── 11 Base Monster Definitions (from dungeon-gen.js) WITH DEF stat ───
const MONSTER_DEFS = [
  { ch: 'j', name: 'Jelly',      hp: 8,   atk: 2,  def: 0,  xp: 5,   col: '#44cc44' },
  { ch: 'b', name: 'Bat',        hp: 10,  atk: 3,  def: 0,  xp: 8,   col: '#8866aa' },
  { ch: 's', name: 'Skeleton',   hp: 15,  atk: 4,  def: 1,  xp: 12,  col: '#ccccaa' },
  { ch: 'g', name: 'Ghost',      hp: 12,  atk: 5,  def: 0,  xp: 15,  col: '#aaaaee' },
  { ch: 'e', name: 'Evil Eye',   hp: 20,  atk: 6,  def: 2,  xp: 20,  col: '#ff4444' },
  { ch: 'k', name: 'Shark',      hp: 25,  atk: 8,  def: 3,  xp: 30,  col: '#4488cc' },
  { ch: 'n', name: 'Ninja',      hp: 30,  atk: 10, def: 2,  xp: 40,  col: '#333366' },
  { ch: 'm', name: 'Medusa',     hp: 35,  atk: 12, def: 4,  xp: 55,  col: '#44aa66' },
  { ch: 'z', name: 'Wizard',     hp: 28,  atk: 15, def: 3,  xp: 70,  col: '#6644cc' },
  { ch: 'D', name: 'Demon',      hp: 60,  atk: 18, def: 6,  xp: 100, col: '#cc2222' },
  { ch: 'W', name: 'Dragon',     hp: 100, atk: 22, def: 10, xp: 200, col: '#ffaa00' },
];

// ─── 21 Biome Monsters (3 per 7 Three.js biomes) WITH DEF stat ───
const BIOME_MONSTERS = {
  strategic:  [
    { ch: 'G', name: 'War Golem',       hp: 40, atk: 10, def: 8,  xp: 45, col: '#cc8844' },
    { ch: 'R', name: 'Siege Ram',        hp: 35, atk: 14, def: 4,  xp: 40, col: '#aa6622' },
    { ch: 'B', name: 'Battle Wraith',    hp: 25, atk: 12, def: 2,  xp: 35, col: '#ff8844' },
  ],
  building:   [
    { ch: 'C', name: 'Code Bug',         hp: 12, atk: 6,  def: 1,  xp: 20, col: '#00ff88' },
    { ch: 'A', name: 'Firewall',         hp: 50, atk: 4,  def: 12, xp: 50, col: '#0088ff' },
    { ch: 'w', name: 'Compiler Worm',    hp: 18, atk: 8,  def: 2,  xp: 25, col: '#44ffcc' },
  ],
  frustrated: [
    { ch: 'r', name: 'Rage Fiend',       hp: 30, atk: 16, def: 1,  xp: 40, col: '#ff2200' },
    { ch: 'L', name: 'Blood Leech',      hp: 20, atk: 10, def: 3,  xp: 30, col: '#cc0044' },
    { ch: 'P', name: 'Pain Wraith',      hp: 22, atk: 14, def: 0,  xp: 35, col: '#ff4466' },
  ],
  resting:    [
    { ch: 'v', name: 'Vine Creeper',     hp: 18, atk: 6,  def: 4,  xp: 20, col: '#44aa44' },
    { ch: 'M', name: 'Mushroom King',    hp: 30, atk: 8,  def: 6,  xp: 35, col: '#88cc66' },
    { ch: 'f', name: 'Forest Spirit',    hp: 15, atk: 5,  def: 2,  xp: 25, col: '#66ffaa' },
  ],
  processing: [
    { ch: 'd', name: 'Fire Drake',       hp: 45, atk: 14, def: 5,  xp: 50, col: '#ff6600' },
    { ch: 'S', name: 'Scale Sentinel',   hp: 55, atk: 10, def: 10, xp: 55, col: '#ccaa44' },
    { ch: 'q', name: 'Ember Worm',       hp: 20, atk: 12, def: 2,  xp: 30, col: '#ff4400' },
  ],
  social:     [
    { ch: 'x', name: 'Shadow Walker',    hp: 22, atk: 10, def: 3,  xp: 30, col: '#8844cc' },
    { ch: 'p', name: 'Echo Phantom',     hp: 18, atk: 8,  def: 1,  xp: 25, col: '#cc66ff' },
    { ch: 'I', name: 'Glitch Spider',    hp: 15, atk: 12, def: 0,  xp: 28, col: '#ff44ff' },
  ],
  learning:   [
    { ch: 'c', name: 'Crystal Golem',    hp: 50, atk: 8,  def: 10, xp: 45, col: '#6688ff' },
    { ch: 'i', name: 'Knowledge Wisp',   hp: 10, atk: 6,  def: 0,  xp: 30, col: '#aaccff' },
    { ch: 'U', name: 'Rune Guardian',    hp: 40, atk: 12, def: 8,  xp: 50, col: '#4466cc' },
  ],
};

// ─── 30 Venice Biome Monsters (3 per 10 Venice biomes from labyrinth_state.py) ───
const VENICE_MONSTERS = {
  crystal_caverns:   [
    { ch: 'c', name: 'Crystal Golem',    hp: 35, atk: 8,  def: 6,  xp: 35, col: '#4488aa' },
    { ch: 'p', name: 'Prism Wraith',     hp: 22, atk: 10, def: 2,  xp: 30, col: '#66aacc' },
    { ch: 'g', name: 'Gem Scarab',       hp: 15, atk: 6,  def: 4,  xp: 20, col: '#88ccee' },
  ],
  ancient_ruins:     [
    { ch: 'G', name: 'Stone Guardian',   hp: 45, atk: 10, def: 8,  xp: 40, col: '#665544' },
    { ch: 't', name: 'Tomb Shade',       hp: 20, atk: 12, def: 1,  xp: 30, col: '#887766' },
    { ch: 'r', name: 'Ruin Crawler',     hp: 18, atk: 8,  def: 3,  xp: 25, col: '#554433' },
  ],
  data_stream:       [
    { ch: 'D', name: 'Glitch Daemon',    hp: 28, atk: 14, def: 2,  xp: 40, col: '#ff00ff' },
    { ch: 'N', name: 'Neon Serpent',     hp: 22, atk: 10, def: 3,  xp: 30, col: '#cc00cc' },
    { ch: 'P', name: 'Packet Storm',     hp: 16, atk: 8,  def: 1,  xp: 25, col: '#ff44ff' },
  ],
  void_depths:       [
    { ch: 'V', name: 'Void Stalker',     hp: 35, atk: 16, def: 4,  xp: 50, col: '#444444' },
    { ch: 'L', name: 'Shadow Leech',     hp: 20, atk: 12, def: 2,  xp: 35, col: '#333333' },
    { ch: 'n', name: 'Null Entity',      hp: 25, atk: 14, def: 3,  xp: 40, col: '#222222' },
  ],
  solar_temple:      [
    { ch: 'S', name: 'Sun Priest',       hp: 30, atk: 10, def: 5,  xp: 35, col: '#ddaa33' },
    { ch: 'G', name: 'Gilded Sentinel',  hp: 40, atk: 8,  def: 10, xp: 40, col: '#ffcc44' },
    { ch: 'W', name: 'Solar Warden',     hp: 35, atk: 12, def: 6,  xp: 38, col: '#eebb44' },
  ],
  drowned_archive:   [
    { ch: 'D', name: 'Depth Lurker',     hp: 30, atk: 12, def: 4,  xp: 35, col: '#226688' },
    { ch: 'C', name: 'Coral Mimic',      hp: 25, atk: 8,  def: 6,  xp: 30, col: '#3388aa' },
    { ch: 'T', name: 'Tide Phantom',     hp: 18, atk: 10, def: 2,  xp: 28, col: '#44aacc' },
  ],
  inference_furnace: [
    { ch: 'M', name: 'Magma Elemental',  hp: 40, atk: 14, def: 5,  xp: 45, col: '#cc3300' },
    { ch: 'C', name: 'Cinder Wraith',    hp: 22, atk: 12, def: 2,  xp: 32, col: '#ff4400' },
    { ch: 'F', name: 'Forge Titan',      hp: 55, atk: 10, def: 10, xp: 50, col: '#ff6600' },
  ],
  memory_garden:     [
    { ch: 'T', name: 'Thorn Beast',      hp: 25, atk: 10, def: 4,  xp: 30, col: '#336633' },
    { ch: 'S', name: 'Spore Cloud',      hp: 12, atk: 6,  def: 1,  xp: 20, col: '#44aa44' },
    { ch: 'H', name: 'Root Hydra',       hp: 45, atk: 12, def: 6,  xp: 45, col: '#228822' },
  ],
  corrupted_sector:  [
    { ch: 'C', name: 'Corrupt Process',  hp: 30, atk: 14, def: 3,  xp: 40, col: '#880088' },
    { ch: 'B', name: 'Bitrot Swarm',     hp: 18, atk: 10, def: 1,  xp: 30, col: '#aa00aa' },
    { ch: 'E', name: 'Error Entity',     hp: 35, atk: 16, def: 4,  xp: 50, col: '#cc00cc' },
  ],
  frozen_weights:    [
    { ch: 'F', name: 'Frost Sentry',     hp: 35, atk: 10, def: 6,  xp: 35, col: '#aaddee' },
    { ch: 'C', name: 'Cryo Specter',     hp: 20, atk: 12, def: 2,  xp: 30, col: '#88bbdd' },
    { ch: 'G', name: 'Glacial Worm',     hp: 28, atk: 8,  def: 5,  xp: 32, col: '#6699bb' },
  ],
};

// ─── 4 Bosses WITH DEF stat ───
const BOSSES = [
  { name: 'GATE KEEPER',  hp: 120, atk: 14, def: 6,  xp: 200, col: '#ff8800', depth: 5,  ch: 'K' },
  { name: 'DATA HYDRA',   hp: 180, atk: 16, def: 5,  xp: 350, col: '#00ff88', depth: 10, ch: 'H' },
  { name: 'VOID EMPEROR', hp: 150, atk: 20, def: 8,  xp: 500, col: '#8844ff', depth: 15, ch: 'V' },
  { name: 'ENTROPY LORD', hp: 200, atk: 18, def: 10, xp: 800, col: '#ff0040', depth: 20, ch: 'E' },
];

// ─── 7 Item Types (Potion, Elixir, Gold, Meat, Scroll, Shield Rune, Blade Shard) ───
const ITEM_TYPES = [
  { ch: '!', name: 'Potion',      col: '#ff4488', type: 'potion',  baseVal: 20 },
  { ch: '!', name: 'Elixir',      col: '#44ff88', type: 'elixir',  baseVal: 40 },
  { ch: '$', name: 'Gold',        col: '#ffdd00', type: 'gold',    baseVal: 10 },
  { ch: 'F', name: 'Meat',        col: '#cc6633', type: 'food',    baseVal: 15 },
  { ch: '/', name: 'Scroll',      col: '#aaaaff', type: 'scroll',  baseVal: 0 },
  { ch: '+', name: 'Shield Rune', col: '#88ccff', type: 'defense', baseVal: 1 },
  { ch: '|', name: 'Blade Shard', col: '#ff8844', type: 'attack',  baseVal: 1 },
];

// ─── 10 Floor Narratives ───
const FLOOR_NARRATIVES = {
  forge:     { name: 'THE SOURCE FORGE',     flavor: 'Code constructs patrol corridors of compiled logic' },
  scout:     { name: 'THE WATCHTOWER',       flavor: 'Surveillance drones sweep crystalline halls' },
  summon:    { name: 'THE DIPLOMATIC HALLS', flavor: 'Messenger spirits glide between sealed chambers' },
  curse:     { name: 'THE CORRUPTION ZONE',  flavor: 'Glitch errors have corrupted this floor' },
  study:     { name: 'THE ARCHIVE DEPTHS',   flavor: 'Ancient knowledge crystallizes in the walls' },
  rally:     { name: 'THE SIGNAL TOWER',     flavor: 'Social frequencies pulse through living circuitry' },
  rage:      { name: 'THE WAR FRONT',        flavor: 'Strategic fury has scorched these halls' },
  meditate:  { name: 'THE DREAM HALLS',      flavor: 'Time moves slowly in crystallized silence' },
  legendary: { name: 'THE TREASURY',         flavor: 'Payment verification runes glow in every wall' },
  mine:      { name: 'THE DATA MINES',       flavor: 'Excavated data veins glitter in the walls' },
};
const FLOOR_NARRATIVE_KEYS = Object.keys(FLOOR_NARRATIVES);

// ─── 4 Difficulty Tiers with multipliers ───
const DIFFICULTY_TIERS = {
  generous:  { enemy_hp_mult: 0.6, enemy_atk_mult: 0.5, loot_mult: 2.0, trap_mult: 0.3, label: 'GENEROUS' },
  normal:    { enemy_hp_mult: 1.0, enemy_atk_mult: 1.0, loot_mult: 1.0, trap_mult: 1.0, label: 'NORMAL' },
  hostile:   { enemy_hp_mult: 1.5, enemy_atk_mult: 1.4, loot_mult: 0.7, trap_mult: 1.8, label: 'HOSTILE' },
  nightmare: { enemy_hp_mult: 2.0, enemy_atk_mult: 1.8, loot_mult: 0.5, trap_mult: 2.5, label: 'NIGHTMARE' },
};

// ─── 7 Three.js Biomes (full color palettes) ───
const THREEJS_BIOMES = {
  strategic:  { name: 'WAR CITADEL',    wall_color: '#7a4a22', floor_color: '#2a1a0a', ambient: '#ffaa00', wire: '#ffcc00', danger: 0.8 },
  building:   { name: 'CYBER FORGE',    wall_color: '#1a3050', floor_color: '#0a1218', ambient: '#00ccff', wire: '#00eeff', danger: 0.4 },
  frustrated: { name: 'BLOOD PIT',      wall_color: '#6a1420', floor_color: '#200808', ambient: '#ff2040', wire: '#ff4444', danger: 1.0 },
  resting:    { name: 'EMERALD GROVE',  wall_color: '#1e4a34', floor_color: '#0c1e14', ambient: '#00ffaa', wire: '#44ffaa', danger: 0.2 },
  processing: { name: 'DRAGONIA',       wall_color: '#8a5a2e', floor_color: '#2a1a0e', ambient: '#ffaa44', wire: '#ffcc66', danger: 0.5 },
  social:     { name: 'VOID NEXUS',     wall_color: '#441e6a', floor_color: '#18081e', ambient: '#cc66ff', wire: '#ff66ff', danger: 0.6 },
  learning:   { name: 'CRYSTAL VAULT',  wall_color: '#222250', floor_color: '#0c0c1a', ambient: '#6688ff', wire: '#88aaff', danger: 0.3 },
};

// ─── 10 Venice Biomes (from labyrinth_state.py BIOME_KEYWORDS) ───
const VENICE_BIOMES = {
  crystal_caverns:   { name: 'CRYSTAL CAVERNS',    wall_color: '#4488aa', floor_color: '#223344', ambient: '#66aacc', room_style: 'angular',    loot_bonus: 1.3, trap_density: 0.2, danger: 0.4 },
  ancient_ruins:     { name: 'ANCIENT RUINS',       wall_color: '#665544', floor_color: '#332211', ambient: '#887766', room_style: 'crumbling',  loot_bonus: 1.5, trap_density: 0.4, danger: 0.5 },
  data_stream:       { name: 'DATA STREAM',          wall_color: '#ff00ff', floor_color: '#110022', ambient: '#cc00cc', room_style: 'grid',       loot_bonus: 1.2, trap_density: 0.3, danger: 0.6 },
  void_depths:       { name: 'VOID DEPTHS',          wall_color: '#222222', floor_color: '#0a0a0a', ambient: '#333333', room_style: 'organic',    loot_bonus: 0.8, trap_density: 0.6, danger: 0.9 },
  solar_temple:      { name: 'SOLAR TEMPLE',         wall_color: '#ddaa33', floor_color: '#443300', ambient: '#ffcc44', room_style: 'grand',      loot_bonus: 2.0, trap_density: 0.15, danger: 0.3 },
  drowned_archive:   { name: 'DROWNED ARCHIVE',      wall_color: '#226688', floor_color: '#112233', ambient: '#3388aa', room_style: 'flooded',    loot_bonus: 1.1, trap_density: 0.25, danger: 0.5 },
  inference_furnace: { name: 'INFERENCE FURNACE',     wall_color: '#cc3300', floor_color: '#331100', ambient: '#ff4400', room_style: 'volcanic',   loot_bonus: 1.0, trap_density: 0.5, danger: 0.8 },
  memory_garden:     { name: 'MEMORY GARDEN',         wall_color: '#336633', floor_color: '#112211', ambient: '#44aa44', room_style: 'organic',    loot_bonus: 1.4, trap_density: 0.2, danger: 0.3 },
  corrupted_sector:  { name: 'CORRUPTED SECTOR',      wall_color: '#880088', floor_color: '#220022', ambient: '#aa00aa', room_style: 'fractured',  loot_bonus: 0.7, trap_density: 0.7, danger: 1.0 },
  frozen_weights:    { name: 'FROZEN WEIGHTS',         wall_color: '#aaddee', floor_color: '#334455', ambient: '#88bbdd', room_style: 'angular',    loot_bonus: 1.1, trap_density: 0.15, danger: 0.4 },
};

// ─── Combined biome registry: ALL 17 biomes ───
const ALL_BIOMES = {};
// 7 Three.js biomes
for (const [k, v] of Object.entries(THREEJS_BIOMES)) {
  ALL_BIOMES[k] = { ...v, loot_bonus: 1.0, trap_density: 0.3, room_style: 'standard' };
}
// 10 Venice biomes
for (const [k, v] of Object.entries(VENICE_BIOMES)) {
  ALL_BIOMES[k] = v;
}
const ALL_BIOME_IDS = Object.keys(ALL_BIOMES);

// Combined monster pools per biome: Three.js biomes use BIOME_MONSTERS, Venice use VENICE_MONSTERS
function getBiomeMonsterPool(biomeId) {
  if (BIOME_MONSTERS[biomeId]) return BIOME_MONSTERS[biomeId];
  if (VENICE_MONSTERS[biomeId]) return VENICE_MONSTERS[biomeId];
  return null;
}

// ─── Difficulty selection (random each floor, skewed by depth) ───
function pickDifficulty(depth) {
  const roll = Math.random();
  if (depth <= 3) {
    // Early floors are gentler
    if (roll < 0.5) return 'generous';
    if (roll < 0.85) return 'normal';
    return 'hostile';
  } else if (depth <= 10) {
    if (roll < 0.15) return 'generous';
    if (roll < 0.6) return 'normal';
    if (roll < 0.9) return 'hostile';
    return 'nightmare';
  } else {
    if (roll < 0.05) return 'generous';
    if (roll < 0.3) return 'normal';
    if (roll < 0.7) return 'hostile';
    return 'nightmare';
  }
}

// ─── Biome selection ───
function pickBiome(depth) {
  // Random from all 17 biomes, with slight rotation based on depth
  const idx = (depth - 1 + Math.floor(Math.random() * 5)) % ALL_BIOME_IDS.length;
  return ALL_BIOME_IDS[idx];
}

// ─── Floor narrative selection ───
function pickFloorNarrative(depth) {
  const idx = (depth - 1) % FLOOR_NARRATIVE_KEYS.length;
  return FLOOR_NARRATIVES[FLOOR_NARRATIVE_KEYS[idx]];
}

// ─── Main dungeon generator ───
function generateDungeon(depth) {
  const biomeId = pickBiome(depth);
  const biome = ALL_BIOMES[biomeId];
  const difficultyKey = pickDifficulty(depth);
  const difficulty = DIFFICULTY_TIERS[difficultyKey];
  const narrative = pickFloorNarrative(depth);

  const tiles = [];
  for (let y = 0; y < MAP_H; y++) {
    tiles.push(new Array(MAP_W).fill(T_WALL));
  }

  const rooms = [];

  function makeRoom(x0, y0, x1, y1) {
    const minR = 4, maxR = 8;
    let rw = Math.min(maxR, x1 - x0 - 2);
    let rh = Math.min(maxR, y1 - y0 - 2);
    if (rw < minR || rh < minR) return;

    const w2 = minR + Math.floor(Math.random() * (rw - minR + 1));
    const h2 = minR + Math.floor(Math.random() * (rh - minR + 1));
    const rx = x0 + 1 + Math.floor(Math.random() * Math.max(1, x1 - x0 - w2 - 1));
    const ry = y0 + 1 + Math.floor(Math.random() * Math.max(1, y1 - y0 - h2 - 1));

    const room = {
      x: rx, y: ry, w: w2, h: h2,
      cx: rx + Math.floor(w2 / 2),
      cy: ry + Math.floor(h2 / 2),
    };

    for (let yy = ry; yy < Math.min(ry + h2, MAP_H - 1); yy++) {
      for (let xx = rx; xx < Math.min(rx + w2, MAP_W - 1); xx++) {
        tiles[yy][xx] = T_FLOOR;
      }
    }
    rooms.push(room);
  }

  function splitBSP(x0, y0, x1, y1, d) {
    const minRoom = 4;
    const rw = x1 - x0;
    const rh = y1 - y0;

    if (rw < minRoom * 2 + 3 && rh < minRoom * 2 + 3) {
      makeRoom(x0, y0, x1, y1);
      return;
    }
    if (d > 7) {
      makeRoom(x0, y0, x1, y1);
      return;
    }

    let horiz = rw < rh;
    if (rw === rh) horiz = Math.random() < 0.5;

    if (horiz && rh >= minRoom * 2 + 3) {
      const split = y0 + minRoom + 1 + Math.floor(Math.random() * (rh - minRoom * 2 - 2));
      splitBSP(x0, y0, x1, split, d + 1);
      splitBSP(x0, split, x1, y1, d + 1);
    } else if (!horiz && rw >= minRoom * 2 + 3) {
      const split = x0 + minRoom + 1 + Math.floor(Math.random() * (rw - minRoom * 2 - 2));
      splitBSP(x0, y0, split, y1, d + 1);
      splitBSP(split, y0, x1, y1, d + 1);
    } else {
      makeRoom(x0, y0, x1, y1);
    }
  }

  splitBSP(0, 0, MAP_W, MAP_H, 0);

  // Connect rooms with L-shaped corridors
  for (let i = 1; i < rooms.length; i++) {
    const a = rooms[i - 1];
    const b = rooms[i];
    let cx = a.cx, cy = a.cy;

    while (cx !== b.cx) {
      if (cy >= 0 && cy < MAP_H && cx >= 0 && cx < MAP_W) {
        if (tiles[cy][cx] === T_WALL) tiles[cy][cx] = T_CORRIDOR;
      }
      cx += cx < b.cx ? 1 : -1;
    }
    while (cy !== b.cy) {
      if (cy >= 0 && cy < MAP_H && cx >= 0 && cx < MAP_W) {
        if (tiles[cy][cx] === T_WALL) tiles[cy][cx] = T_CORRIDOR;
      }
      cy += cy < b.cy ? 1 : -1;
    }
  }

  // Place doors at corridor-room boundaries
  for (let y = 1; y < MAP_H - 1; y++) {
    for (let x = 1; x < MAP_W - 1; x++) {
      if (tiles[y][x] === T_CORRIDOR) {
        const adjFloor = (tiles[y-1][x] === T_FLOOR ? 1 : 0) +
                         (tiles[y+1][x] === T_FLOOR ? 1 : 0) +
                         (tiles[y][x-1] === T_FLOOR ? 1 : 0) +
                         (tiles[y][x+1] === T_FLOOR ? 1 : 0);
        const adjCorr = (tiles[y-1][x] === T_CORRIDOR ? 1 : 0) +
                        (tiles[y+1][x] === T_CORRIDOR ? 1 : 0) +
                        (tiles[y][x-1] === T_CORRIDOR ? 1 : 0) +
                        (tiles[y][x+1] === T_CORRIDOR ? 1 : 0);
        if (adjFloor >= 1 && adjCorr >= 1 && Math.random() < 0.3) {
          tiles[y][x] = T_DOOR;
        }
      }
    }
  }

  // Place stairs in last room
  let stairs = null;
  if (rooms.length > 0) {
    const sr = rooms[rooms.length - 1];
    const sx = sr.x + 1 + Math.floor(Math.random() * Math.max(1, sr.w - 2));
    const sy = sr.y + 1 + Math.floor(Math.random() * Math.max(1, sr.h - 2));
    if (sy >= 0 && sy < MAP_H && sx >= 0 && sx < MAP_W) {
      tiles[sy][sx] = T_STAIRS;
      stairs = { x: sx, y: sy };
    }
  }

  // ─── Spawn monsters (with difficulty scaling + biome pool) ───
  const monsters = [];
  const scale = 1 + (depth - 1) * 0.1;
  const tierMax = Math.min(MONSTER_DEFS.length - 1, Math.floor(depth / 2));
  let numMonsters = Math.min(4 + Math.floor(depth * 1.5) + Math.floor(Math.random() * 3), rooms.length * 2);

  // Corruption zone spawns extra enemies
  if (biomeId === 'corrupted_sector' || biome.name === 'CORRUPTED SECTOR') {
    numMonsters += 3 + Math.floor(Math.random() * 3);
  }

  const biomePool = getBiomeMonsterPool(biomeId);

  for (let i = 0; i < numMonsters; i++) {
    if (rooms.length < 2) break;
    const room = rooms[1 + Math.floor(Math.random() * (rooms.length - 1))];
    const mx = room.x + 1 + Math.floor(Math.random() * Math.max(1, room.w - 2));
    const my = room.y + 1 + Math.floor(Math.random() * Math.max(1, room.h - 2));
    if (my >= 0 && my < MAP_H && mx >= 0 && mx < MAP_W && tiles[my][mx] === T_FLOOR) {
      if (monsters.some(m => m.x === mx && m.y === my)) continue;

      let base;
      // 35% chance to use biome-specific monster
      if (biomePool && Math.random() < 0.35) {
        base = biomePool[Math.floor(Math.random() * biomePool.length)];
      } else {
        const tier = Math.floor(Math.random() * (tierMax + 1));
        base = MONSTER_DEFS[tier];
      }

      monsters.push({
        x: mx, y: my,
        name: base.name,
        hp: Math.max(1, Math.floor(base.hp * scale * difficulty.enemy_hp_mult)),
        maxHp: Math.max(1, Math.floor(base.hp * scale * difficulty.enemy_hp_mult)),
        atk: Math.max(1, Math.floor(base.atk * scale * difficulty.enemy_atk_mult)),
        def: Math.max(0, Math.floor((base.def || 0) * scale)),
        xp: Math.floor(base.xp * scale),
        col: base.col,
        alive: true,
        boss: false,
      });
    }
  }

  // Boss every 5 floors
  if (depth % 5 === 0 && depth <= 20) {
    const bossDef = BOSSES.find(b => b.depth === depth);
    if (bossDef && rooms.length > 1) {
      const br = rooms[rooms.length - 1];
      monsters.push({
        x: br.cx, y: br.cy,
        name: bossDef.name,
        hp: Math.max(1, Math.floor(bossDef.hp * scale * difficulty.enemy_hp_mult)),
        maxHp: Math.max(1, Math.floor(bossDef.hp * scale * difficulty.enemy_hp_mult)),
        atk: Math.max(1, Math.floor(bossDef.atk * scale * difficulty.enemy_atk_mult)),
        def: Math.max(0, Math.floor(bossDef.def * scale)),
        xp: Math.floor(bossDef.xp * scale),
        col: bossDef.col,
        alive: true,
        boss: true,
      });
    }
  }

  // ─── Spawn items (with loot multiplier from difficulty + biome) ───
  const items = [];
  const biomeLootBonus = biome.loot_bonus || 1.0;
  const lootMult = difficulty.loot_mult * biomeLootBonus;
  const numItems = Math.floor((3 + Math.floor(Math.random() * 4)) * lootMult);
  for (let i = 0; i < numItems; i++) {
    const room = rooms[Math.floor(Math.random() * rooms.length)];
    const ix = room.x + 1 + Math.floor(Math.random() * Math.max(1, room.w - 2));
    const iy = room.y + 1 + Math.floor(Math.random() * Math.max(1, room.h - 2));
    if (iy >= 0 && iy < MAP_H && ix >= 0 && ix < MAP_W && tiles[iy][ix] === T_FLOOR) {
      if (items.some(it => it.x === ix && it.y === iy)) continue;
      if (monsters.some(m => m.x === ix && m.y === iy)) continue;
      const idef = ITEM_TYPES[Math.floor(Math.random() * ITEM_TYPES.length)];
      let val = idef.baseVal;
      if (idef.type === 'gold') val = Math.floor((10 + depth * 5) * lootMult);
      items.push({
        x: ix, y: iy,
        name: idef.name,
        type: idef.type,
        val: val,
        col: idef.col,
        pickedUp: false,
      });
    }
  }

  // Player starts in first room
  let playerStart = { x: 5, y: 5 };
  if (rooms.length > 0) {
    playerStart = { x: rooms[0].cx, y: rooms[0].cy };
  }

  return {
    tiles,
    rooms,
    stairs,
    monsters,
    items,
    biomeId,
    biome,
    playerStart,
    width: MAP_W,
    height: MAP_H,
    narrative,
    difficultyKey,
    difficulty,
  };
}
