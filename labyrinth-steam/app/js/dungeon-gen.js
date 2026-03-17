// LABYRINTH 3D — Dungeon Generator (BSP)
// Extracted from index.html, same algorithm

export const T_WALL = 0, T_FLOOR = 1, T_CORRIDOR = 2, T_DOOR = 3, T_STAIRS = 4;

export const BIOMES = {
  strategic:  { name:'WAR CITADEL',   floor:'#2a1a0a', floorAlt:'#342010', wall:'#7a4a22', wallDark:'#4a2e1a', wallLight:'#9a6a3a', wire:'#ffaa00', accent:'#ffcc00', monsterTint:'#ff8800' },
  building:   { name:'CYBER FORGE',   floor:'#0a1218', floorAlt:'#080e14', wall:'#1a3050', wallDark:'#102040', wallLight:'#2a4a70', wire:'#00ccff', accent:'#00eeff', monsterTint:'#0088ff' },
  frustrated: { name:'BLOOD PIT',     floor:'#200808', floorAlt:'#180606', wall:'#6a1420', wallDark:'#440a14', wallLight:'#8a2030', wire:'#ff2040', accent:'#ff4444', monsterTint:'#cc0000' },
  resting:    { name:'EMERALD GROVE', floor:'#0c1e14', floorAlt:'#0a180e', wall:'#1e4a34', wallDark:'#103424', wallLight:'#306a4a', wire:'#00ffaa', accent:'#44ffaa', monsterTint:'#00cc88' },
  processing: { name:'DRAGONIA',      floor:'#2a1a0e', floorAlt:'#221408', wall:'#8a5a2e', wallDark:'#5a3a1a', wallLight:'#aa7a44', wire:'#ffaa44', accent:'#ffcc66', monsterTint:'#ffcc00' },
  social:     { name:'VOID NEXUS',    floor:'#18081e', floorAlt:'#120614', wall:'#441e6a', wallDark:'#2e1048', wallLight:'#5a2e8a', wire:'#cc66ff', accent:'#ff66ff', monsterTint:'#cc44ff' },
  learning:   { name:'CRYSTAL VAULT', floor:'#0c0c1a', floorAlt:'#08081a', wall:'#222250', wallDark:'#16163a', wallLight:'#3a3a6a', wire:'#6688ff', accent:'#88aaff', monsterTint:'#4466cc' }
};

export const FLOOR_NARRATIVES = {
  forge:     { name:'THE SOURCE FORGE',     flavor:'Code constructs patrol corridors of compiled logic' },
  scout:     { name:'THE WATCHTOWER',       flavor:'Surveillance drones sweep crystalline halls' },
  summon:    { name:'THE DIPLOMATIC HALLS', flavor:'Messenger spirits glide between sealed chambers' },
  curse:     { name:'THE CORRUPTION ZONE',  flavor:'Glitch errors have corrupted this floor' },
  study:     { name:'THE ARCHIVE DEPTHS',   flavor:'Ancient knowledge crystallizes in the walls' },
  rally:     { name:'THE SIGNAL TOWER',     flavor:'Social frequencies pulse through living circuitry' },
  rage:      { name:'THE WAR FRONT',        flavor:'Strategic fury has scorched these halls' },
  meditate:  { name:'THE DREAM HALLS',      flavor:'Time moves slowly in crystallized silence' },
  legendary: { name:'THE TREASURY',         flavor:'Payment verification runes glow in every wall' },
  mine:      { name:'THE DATA MINES',       flavor:'Excavated data veins glitter in the walls' }
};

const MONSTER_DEFS = [
  { ch:'j', name:'Jelly',      hp:8,  atk:2, def:0, xp:5,  col:'#44cc44' },
  { ch:'b', name:'Bat',        hp:10, atk:3, def:0, xp:8,  col:'#8866aa' },
  { ch:'s', name:'Skeleton',   hp:15, atk:4, def:1, xp:12, col:'#ccccaa' },
  { ch:'g', name:'Ghost',      hp:12, atk:5, def:0, xp:15, col:'#aaaaee' },
  { ch:'e', name:'Evil Eye',   hp:20, atk:6, def:2, xp:20, col:'#ff4444' },
  { ch:'k', name:'Shark',      hp:25, atk:8, def:3, xp:30, col:'#4488cc' },
  { ch:'n', name:'Ninja',      hp:30, atk:10,def:2, xp:40, col:'#333366' },
  { ch:'m', name:'Medusa',     hp:35, atk:12,def:4, xp:55, col:'#44aa66' },
  { ch:'z', name:'Wizard',     hp:28, atk:15,def:3, xp:70, col:'#6644cc' },
  { ch:'D', name:'Demon',      hp:60, atk:18,def:6, xp:100,col:'#cc2222' },
  { ch:'W', name:'Dragon',     hp:100,atk:22,def:10,xp:200,col:'#ffaa00' }
];

const BIOME_MONSTERS = {
  strategic:  [{ ch:'G', name:'War Golem', hp:40, atk:10, def:8, xp:45, col:'#cc8844' }, { ch:'R', name:'Siege Ram', hp:35, atk:14, def:4, xp:40, col:'#aa6622' }, { ch:'B', name:'Battle Wraith', hp:25, atk:12, def:2, xp:35, col:'#ff8844' }],
  building:   [{ ch:'C', name:'Code Bug', hp:12, atk:6, def:1, xp:20, col:'#00ff88' }, { ch:'A', name:'Firewall', hp:50, atk:4, def:12, xp:50, col:'#0088ff' }, { ch:'w', name:'Compiler Worm', hp:18, atk:8, def:2, xp:25, col:'#44ffcc' }],
  frustrated: [{ ch:'r', name:'Rage Fiend', hp:30, atk:16, def:1, xp:40, col:'#ff2200' }, { ch:'L', name:'Blood Leech', hp:20, atk:10, def:3, xp:30, col:'#cc0044' }, { ch:'P', name:'Pain Wraith', hp:22, atk:14, def:0, xp:35, col:'#ff4466' }],
  resting:    [{ ch:'v', name:'Vine Creeper', hp:18, atk:6, def:4, xp:20, col:'#44aa44' }, { ch:'M', name:'Mushroom King', hp:30, atk:8, def:6, xp:35, col:'#88cc66' }, { ch:'f', name:'Forest Spirit', hp:15, atk:5, def:2, xp:25, col:'#66ffaa' }],
  processing: [{ ch:'d', name:'Fire Drake', hp:45, atk:14, def:5, xp:50, col:'#ff6600' }, { ch:'S', name:'Scale Sentinel', hp:55, atk:10, def:10, xp:55, col:'#ccaa44' }, { ch:'q', name:'Ember Worm', hp:20, atk:12, def:2, xp:30, col:'#ff4400' }],
  social:     [{ ch:'x', name:'Shadow Walker', hp:22, atk:10, def:3, xp:30, col:'#8844cc' }, { ch:'p', name:'Echo Phantom', hp:18, atk:8, def:1, xp:25, col:'#cc66ff' }, { ch:'I', name:'Glitch Spider', hp:15, atk:12, def:0, xp:28, col:'#ff44ff' }],
  learning:   [{ ch:'c', name:'Crystal Golem', hp:50, atk:8, def:10, xp:45, col:'#6688ff' }, { ch:'i', name:'Knowledge Wisp', hp:10, atk:6, def:0, xp:30, col:'#aaccff' }, { ch:'U', name:'Rune Guardian', hp:40, atk:12, def:8, xp:50, col:'#4466cc' }]
};

const BOSSES = [
  { name:'GATE KEEPER', hp:120, atk:14, def:6, xp:200, col:'#ff8800', depth:5, ch:'K' },
  { name:'DATA HYDRA', hp:180, atk:16, def:5, xp:350, col:'#00ff88', depth:10, ch:'H' },
  { name:'VOID EMPEROR', hp:150, atk:20, def:8, xp:500, col:'#8844ff', depth:15, ch:'V' },
  { name:'ENTROPY LORD', hp:200, atk:18, def:10, xp:800, col:'#ff0040', depth:20, ch:'E' }
];

const ITEM_TYPES = [
  { ch:'!', name:'Potion', col:'#ff4488', type:'potion', val:20 },
  { ch:'!', name:'Elixir', col:'#44ff88', type:'potion', val:40 },
  { ch:'$', name:'Gold', col:'#ffdd00', type:'gold', val:10 },
  { ch:'F', name:'Meat', col:'#cc6633', type:'food', val:15 },
  { ch:'/', name:'Scroll', col:'#aaaaff', type:'scroll', val:0 },
  { ch:'+', name:'Shield Rune', col:'#88ccff', type:'defense', val:1 },
  { ch:'|', name:'Blade Shard', col:'#ff8844', type:'attack', val:1 },
];

export const DungeonGen = {
  generate(w, h, depth, biomeMood, narrativeAction, energy) {
    const tiles = [];
    for (let y = 0; y < h; y++) { tiles[y] = []; for (let x = 0; x < w; x++) tiles[y][x] = T_WALL; }
    const rooms = [];
    // Energy influences room density: higher energy = smaller min rooms = more rooms
    const energyVal = typeof energy === 'number' ? energy : 0.5;
    const minRoom = Math.max(3, 4 - Math.floor(energyVal * 2));
    const maxRoom = 8;
    // BSP depth limit: higher energy allows deeper splits = more rooms
    const maxBSPDepth = 6 + Math.floor(energyVal * 3);

    function splitBSP(x0, y0, x1, y1, d) {
      const rw = x1 - x0, rh = y1 - y0;
      if (rw < minRoom * 2 + 3 && rh < minRoom * 2 + 3) { makeRoom(x0, y0, x1, y1); return; }
      if (d > maxBSPDepth) { makeRoom(x0, y0, x1, y1); return; }
      const horiz = rw < rh ? true : rh < rw ? false : Math.random() < .5;
      if (horiz && rh >= minRoom * 2 + 3) {
        const split = y0 + minRoom + 1 + Math.floor(Math.random() * (rh - minRoom * 2 - 2));
        splitBSP(x0, y0, x1, split, d + 1);
        splitBSP(x0, split, x1, y1, d + 1);
      } else if (!horiz && rw >= minRoom * 2 + 3) {
        const split = x0 + minRoom + 1 + Math.floor(Math.random() * (rw - minRoom * 2 - 2));
        splitBSP(x0, y0, split, y1, d + 1);
        splitBSP(split, y0, x1, y1, d + 1);
      } else { makeRoom(x0, y0, x1, y1); }
    }

    function makeRoom(x0, y0, x1, y1) {
      const rw = Math.min(maxRoom, x1 - x0 - 2), rh = Math.min(maxRoom, y1 - y0 - 2);
      if (rw < minRoom || rh < minRoom) return;
      const w2 = minRoom + Math.floor(Math.random() * (rw - minRoom + 1));
      const h2 = minRoom + Math.floor(Math.random() * (rh - minRoom + 1));
      const rx = x0 + 1 + Math.floor(Math.random() * Math.max(1, x1 - x0 - w2 - 1));
      const ry = y0 + 1 + Math.floor(Math.random() * Math.max(1, y1 - y0 - h2 - 1));
      const room = { x: rx, y: ry, w: w2, h: h2, cx: Math.floor(rx + w2 / 2), cy: Math.floor(ry + h2 / 2) };
      for (let yy = ry; yy < ry + h2 && yy < h - 1; yy++)
        for (let xx = rx; xx < rx + w2 && xx < w - 1; xx++) tiles[yy][xx] = T_FLOOR;
      rooms.push(room);
    }

    splitBSP(0, 0, w, h, 0);

    // Connect rooms
    for (let i = 1; i < rooms.length; i++) {
      const a = rooms[i - 1], b = rooms[i];
      let cx = a.cx, cy = a.cy;
      while (cx !== b.cx) {
        if (cy >= 0 && cy < h && cx >= 0 && cx < w && tiles[cy][cx] === T_WALL) tiles[cy][cx] = T_CORRIDOR;
        cx += cx < b.cx ? 1 : -1;
      }
      while (cy !== b.cy) {
        if (cy >= 0 && cy < h && cx >= 0 && cx < w && tiles[cy][cx] === T_WALL) tiles[cy][cx] = T_CORRIDOR;
        cy += cy < b.cy ? 1 : -1;
      }
    }

    // Doors
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        if (tiles[y][x] !== T_CORRIDOR) continue;
        const adjFloor = (tiles[y - 1][x] === T_FLOOR ? 1 : 0) + (tiles[y + 1][x] === T_FLOOR ? 1 : 0) +
          (tiles[y][x - 1] === T_FLOOR ? 1 : 0) + (tiles[y][x + 1] === T_FLOOR ? 1 : 0);
        if (adjFloor >= 1 && Math.random() < .35) tiles[y][x] = T_DOOR;
      }
    }

    // Stairs in last room
    const stairRoom = rooms[rooms.length - 1];
    const sx = stairRoom.x + 1 + Math.floor(Math.random() * (stairRoom.w - 2));
    const sy = stairRoom.y + 1 + Math.floor(Math.random() * (stairRoom.h - 2));
    tiles[sy][sx] = T_STAIRS;

    // Monsters
    const monsters = [];
    let numMonsters = 4 + Math.floor(depth * 1.5) + Math.floor(Math.random() * 3);
    if (narrativeAction === 'curse') numMonsters += 2 + Math.floor(Math.random() * 2);
    else if (narrativeAction === 'rage') numMonsters += 1 + Math.floor(Math.random() * 2);
    const tierMax = Math.min(MONSTER_DEFS.length - 1, Math.floor(depth / 2));
    const biomePool = (biomeMood && BIOME_MONSTERS[biomeMood]) ? BIOME_MONSTERS[biomeMood] : null;
    for (let i = 0; i < numMonsters && i < rooms.length * 2; i++) {
      const room = rooms[1 + Math.floor(Math.random() * (rooms.length - 1))];
      if (!room) continue;
      const mx = room.x + 1 + Math.floor(Math.random() * (room.w - 2));
      const my = room.y + 1 + Math.floor(Math.random() * (room.h - 2));
      if (tiles[my][mx] !== T_FLOOR) continue;
      let def;
      if (biomePool && Math.random() < 0.35) {
        def = biomePool[Math.floor(Math.random() * biomePool.length)];
      } else {
        const tier = Math.floor(Math.random() * (tierMax + 1));
        def = MONSTER_DEFS[tier];
      }
      const scale = 1 + (depth - 1) * 0.1;
      monsters.push({
        x: mx, y: my, ch: def.ch, name: def.name, col: def.col,
        hp: Math.ceil(def.hp * scale), maxHp: Math.ceil(def.hp * scale),
        atk: Math.ceil(def.atk * scale), def: Math.ceil(def.def * scale),
        xp: Math.ceil(def.xp * scale), alive: true, alert: false
      });
    }

    // Boss every 5 floors
    if (depth % 5 === 0 && depth <= 20) {
      const bossDef = BOSSES.find(b => b.depth === depth);
      if (bossDef && rooms.length > 1) {
        const bossRoom = rooms[rooms.length - 1];
        const scale = 1 + (depth - 1) * 0.1;
        monsters.push({
          x: bossRoom.cx, y: bossRoom.cy, ch: bossDef.ch, name: bossDef.name, col: bossDef.col,
          hp: Math.ceil(bossDef.hp * scale), maxHp: Math.ceil(bossDef.hp * scale),
          atk: Math.ceil(bossDef.atk * scale), def: Math.ceil(bossDef.def * scale),
          xp: Math.ceil(bossDef.xp * scale), alive: true, alert: true, boss: true
        });
      }
    }

    // Items
    const items = [];
    const numItems = 3 + Math.floor(Math.random() * 4);
    for (let i = 0; i < numItems; i++) {
      const room = rooms[Math.floor(Math.random() * rooms.length)];
      const ix = room.x + 1 + Math.floor(Math.random() * (room.w - 2));
      const iy = room.y + 1 + Math.floor(Math.random() * (room.h - 2));
      if (tiles[iy][ix] !== T_FLOOR) continue;
      const def = ITEM_TYPES[Math.floor(Math.random() * ITEM_TYPES.length)];
      items.push({ x: ix, y: iy, ...def, val: def.type === 'gold' ? def.val + depth * 5 : def.val, pickedUp: false });
    }

    // Torch positions (wall intersections for lighting)
    const torches = [];
    for (const room of rooms) {
      torches.push({ x: room.x, y: room.y });
      torches.push({ x: room.x + room.w - 1, y: room.y });
      torches.push({ x: room.x, y: room.y + room.h - 1 });
      torches.push({ x: room.x + room.w - 1, y: room.y + room.h - 1 });
    }

    return { tiles, rooms, monsters, items, stairs: { x: sx, y: sy }, torches, w, h };
  }
};
