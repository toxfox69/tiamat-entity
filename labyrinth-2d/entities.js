// LABYRINTH 2D — Entity System
// Player, monsters, items, ECHO ally

// XP thresholds per level
const XP_TABLE = [0, 30, 70, 130, 220, 350, 520, 740, 1020, 1400, 1900, 2500, 3300, 4300, 5500, 7000, 9000, 11500, 14500, 18000];

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
    equipment: {
      weapon: null,    // { name, atkBonus }
      armor: null,     // { name, defBonus }
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
    case 'gold':
      player.gold += item.val;
      return { msg: `Found ${item.val} gold!`, type: 'pickup' };
    case 'food':
      player.hp = Math.min(player.maxHp, player.hp + item.val);
      return { msg: `Ate ${item.name} (+${item.val} HP)`, type: 'pickup' };
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

// ECHO companion — follows player with 2-tile delay
function createEcho(playerX, playerY) {
  return {
    x: playerX,
    y: playerY,
    trail: [], // Last N player positions
    maxTrail: 3,
    alive: true,
  };
}

function updateEcho(echo, playerX, playerY, tiles) {
  // Record player position
  echo.trail.push({ x: playerX, y: playerY });
  if (echo.trail.length > echo.maxTrail) {
    const target = echo.trail.shift();
    // Move echo to oldest trail position (if walkable)
    if (target.y >= 0 && target.y < tiles.length && target.x >= 0 && target.x < tiles[0].length) {
      const t = tiles[target.y][target.x];
      if (t !== T_WALL) {
        echo.x = target.x;
        echo.y = target.y;
      }
    }
  }
}

// Sprite index helpers
function monsterSpriteIndex(monster) {
  // Hash monster name to pick one of 4 sprite variants
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
