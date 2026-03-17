// LABYRINTH 2D — BSP Dungeon Generation
// Ported from labyrinth_state.py (Python) to JavaScript
// 40x25 tile grid, BSP rooms, L-shaped corridors, 10 biomes

const T_WALL = 0;
const T_FLOOR = 1;
const T_CORRIDOR = 2;
const T_DOOR = 3;
const T_STAIRS = 4;

const MAP_W = 40;
const MAP_H = 25;

// 10 biomes from BIOME_KEYWORDS in labyrinth_state.py
const BIOME_DEFS = {
  crystal_caverns: {
    name: 'CRYSTAL CAVERNS',
    wall_color: '#4488aa',
    floor_color: '#223344',
    ambient: '#66aacc',
    enemy_types: ['Crystal Golem', 'Prism Wraith', 'Gem Scarab'],
    room_style: 'angular',
    loot_bonus: 1.3,
    trap_density: 0.2,
    danger: 0.4,
  },
  ancient_ruins: {
    name: 'ANCIENT RUINS',
    wall_color: '#665544',
    floor_color: '#332211',
    ambient: '#887766',
    enemy_types: ['Stone Guardian', 'Tomb Shade', 'Ruin Crawler'],
    room_style: 'crumbling',
    loot_bonus: 1.5,
    trap_density: 0.4,
    danger: 0.5,
  },
  data_stream: {
    name: 'DATA STREAM',
    wall_color: '#ff00ff',
    floor_color: '#110022',
    ambient: '#cc00cc',
    enemy_types: ['Glitch Daemon', 'Neon Serpent', 'Packet Storm'],
    room_style: 'grid',
    loot_bonus: 1.2,
    trap_density: 0.3,
    danger: 0.6,
  },
  void_depths: {
    name: 'VOID DEPTHS',
    wall_color: '#222222',
    floor_color: '#0a0a0a',
    ambient: '#333333',
    enemy_types: ['Void Stalker', 'Shadow Leech', 'Null Entity'],
    room_style: 'organic',
    loot_bonus: 0.8,
    trap_density: 0.6,
    danger: 0.9,
  },
  solar_temple: {
    name: 'SOLAR TEMPLE',
    wall_color: '#ddaa33',
    floor_color: '#443300',
    ambient: '#ffcc44',
    enemy_types: ['Sun Priest', 'Gilded Sentinel', 'Solar Warden'],
    room_style: 'grand',
    loot_bonus: 2.0,
    trap_density: 0.15,
    danger: 0.3,
  },
  drowned_archive: {
    name: 'DROWNED ARCHIVE',
    wall_color: '#226688',
    floor_color: '#112233',
    ambient: '#3388aa',
    enemy_types: ['Depth Lurker', 'Coral Mimic', 'Tide Phantom'],
    room_style: 'flooded',
    loot_bonus: 1.1,
    trap_density: 0.25,
    danger: 0.5,
  },
  inference_furnace: {
    name: 'INFERENCE FURNACE',
    wall_color: '#cc3300',
    floor_color: '#331100',
    ambient: '#ff4400',
    enemy_types: ['Magma Elemental', 'Cinder Wraith', 'Forge Titan'],
    room_style: 'volcanic',
    loot_bonus: 1.0,
    trap_density: 0.5,
    danger: 0.8,
  },
  memory_garden: {
    name: 'MEMORY GARDEN',
    wall_color: '#336633',
    floor_color: '#112211',
    ambient: '#44aa44',
    enemy_types: ['Thorn Beast', 'Spore Cloud', 'Root Hydra'],
    room_style: 'organic',
    loot_bonus: 1.4,
    trap_density: 0.2,
    danger: 0.3,
  },
  corrupted_sector: {
    name: 'CORRUPTED SECTOR',
    wall_color: '#880088',
    floor_color: '#220022',
    ambient: '#aa00aa',
    enemy_types: ['Corrupt Process', 'Bitrot Swarm', 'Error Entity'],
    room_style: 'fractured',
    loot_bonus: 0.7,
    trap_density: 0.7,
    danger: 1.0,
  },
  frozen_weights: {
    name: 'FROZEN WEIGHTS',
    wall_color: '#aaddee',
    floor_color: '#334455',
    ambient: '#88bbdd',
    enemy_types: ['Frost Sentry', 'Cryo Specter', 'Glacial Worm'],
    room_style: 'angular',
    loot_bonus: 1.1,
    trap_density: 0.15,
    danger: 0.4,
  },
};

const BIOME_IDS = Object.keys(BIOME_DEFS);

// Monster pool (scaled by depth)
const MONSTER_POOL = [
  { name: 'Jelly',     hp: 8,   atk: 2,  xp: 5,   col: '#44cc44' },
  { name: 'Bat',       hp: 10,  atk: 3,  xp: 8,   col: '#8866aa' },
  { name: 'Skeleton',  hp: 15,  atk: 4,  xp: 12,  col: '#ccccaa' },
  { name: 'Ghost',     hp: 12,  atk: 5,  xp: 15,  col: '#aaaaee' },
  { name: 'Evil Eye',  hp: 20,  atk: 6,  xp: 20,  col: '#ff4444' },
  { name: 'Shark',     hp: 25,  atk: 8,  xp: 30,  col: '#4488cc' },
  { name: 'Ninja',     hp: 30,  atk: 10, xp: 40,  col: '#333366' },
  { name: 'Demon',     hp: 60,  atk: 18, xp: 100, col: '#cc2222' },
  { name: 'Dragon',    hp: 100, atk: 22, xp: 200, col: '#ffaa00' },
];

const BOSSES = [
  { name: 'GATE KEEPER',  hp: 120, atk: 14, xp: 200, depth: 5 },
  { name: 'DATA HYDRA',   hp: 180, atk: 16, xp: 350, depth: 10 },
  { name: 'VOID EMPEROR', hp: 150, atk: 20, xp: 500, depth: 15 },
  { name: 'ENTROPY LORD', hp: 200, atk: 18, xp: 800, depth: 20 },
];

const ITEM_TYPES = [
  { name: 'Potion',      type: 'potion',  baseVal: 20, col: '#ff4488' },
  { name: 'Gold',        type: 'gold',    baseVal: 10, col: '#ffdd00' },
  { name: 'Meat',        type: 'food',    baseVal: 15, col: '#cc6633' },
  { name: 'Blade Shard', type: 'attack',  baseVal: 1,  col: '#ff8844' },
  { name: 'Shield Rune', type: 'defense', baseVal: 1,  col: '#88ccff' },
];

function pickBiome(depth) {
  // Cycle through biomes based on depth, with some randomness
  const idx = (depth - 1 + Math.floor(Math.random() * 3)) % BIOME_IDS.length;
  return BIOME_IDS[idx];
}

function generateDungeon(depth) {
  const biomeId = pickBiome(depth);
  const biome = BIOME_DEFS[biomeId];

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
        // Check if this corridor tile connects to a floor tile (room entrance)
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

  // Spawn monsters
  const monsters = [];
  const scale = 1 + (depth - 1) * 0.1;
  const tierMax = Math.min(MONSTER_POOL.length - 1, Math.floor(depth / 2));
  const numMonsters = Math.min(4 + Math.floor(depth * 1.5) + Math.floor(Math.random() * 3), rooms.length * 2);

  for (let i = 0; i < numMonsters; i++) {
    if (rooms.length < 2) break;
    const room = rooms[1 + Math.floor(Math.random() * (rooms.length - 1))];
    const mx = room.x + 1 + Math.floor(Math.random() * Math.max(1, room.w - 2));
    const my = room.y + 1 + Math.floor(Math.random() * Math.max(1, room.h - 2));
    if (my >= 0 && my < MAP_H && mx >= 0 && mx < MAP_W && tiles[my][mx] === T_FLOOR) {
      // Check no overlap with existing monster
      if (monsters.some(m => m.x === mx && m.y === my)) continue;
      const tier = Math.floor(Math.random() * (tierMax + 1));
      const base = MONSTER_POOL[tier];
      // Pick biome enemy name sometimes
      const useBiomeName = Math.random() < 0.4 && biome.enemy_types.length > 0;
      const mName = useBiomeName ? biome.enemy_types[Math.floor(Math.random() * biome.enemy_types.length)] : base.name;
      monsters.push({
        x: mx, y: my,
        name: mName,
        hp: Math.floor(base.hp * scale),
        maxHp: Math.floor(base.hp * scale),
        atk: Math.floor(base.atk * scale),
        xp: Math.floor(base.xp * scale),
        col: base.col,
        alive: true,
        boss: false,
        tier: tier,
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
        hp: Math.floor(bossDef.hp * scale),
        maxHp: Math.floor(bossDef.hp * scale),
        atk: Math.floor(bossDef.atk * scale),
        xp: Math.floor(bossDef.xp * scale),
        col: '#ffaa00',
        alive: true,
        boss: true,
        tier: 8,
      });
    }
  }

  // Spawn items
  const items = [];
  const lootMult = biome.loot_bonus || 1.0;
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
  };
}
