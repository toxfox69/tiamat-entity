// LABYRINTH 2D — Turn-based Bump Combat System
// Full DEF stat on all entities. Scroll and Elixir effects.
// Damage = ATK + weapon_bonus - target_DEF + random(0-2), minimum 1

function calculateDamage(attackerAtk, defenderDef) {
  const raw = attackerAtk - defenderDef + Math.floor(Math.random() * 3);
  return Math.max(1, raw); // Always at least 1 damage
}

function playerAttackMonster(player, monster) {
  const results = [];

  // Player attacks — full formula with DEF
  const dmg = calculateDamage(player.totalAtk, monster.def || 0);
  monster.hp -= dmg;

  if (monster.boss) {
    results.push({ msg: `Hit ${monster.name} for ${dmg}! (${Math.max(0, monster.hp)}/${monster.maxHp})`, type: 'combat' });
  } else {
    results.push({ msg: `Hit ${monster.name} for ${dmg}!`, type: 'combat' });
  }

  if (monster.hp <= 0) {
    monster.alive = false;
    const leveledUp = playerGainXp(player, monster.xp);
    player.kills++;
    results.push({ msg: `Slew ${monster.name}! +${monster.xp} XP`, type: 'combat' });
    if (leveledUp) {
      results.push({ msg: `LEVEL UP! Now level ${player.lvl}!`, type: 'level' });
    }
    // Boss drops gold
    if (monster.boss) {
      const bossGold = 50 + monster.xp;
      player.gold += bossGold;
      results.push({ msg: `${monster.name} dropped ${bossGold} gold!`, type: 'pickup' });
    }
  } else {
    // Monster attacks back — monster ATK vs player DEF
    const mDmg = calculateDamage(monster.atk, player.totalDef);
    player.hp -= mDmg;
    results.push({ msg: `${monster.name} hits back for ${mDmg}!`, type: 'combat' });

    if (player.hp <= 0) {
      results.push({ msg: 'YOU DIED! Lost gold, regressed depth.', type: 'death' });
    }
  }

  return results;
}

function handlePlayerDeath(player, gameState) {
  gameState.sessionStats.deaths++;
  player.hp = player.maxHp;
  player.gold = Math.floor(player.gold * 0.7);
  return [{ msg: 'Respawned. Lost 30% gold.', type: 'death' }];
}

// ─── Scroll Effects ───
// Random effect: damage all enemies in room, reveal map, or teleport
function useScroll(player, gameState) {
  if (!player.scrolls || player.scrolls <= 0) {
    return [{ msg: 'No scrolls to use!', type: 'combat' }];
  }
  player.scrolls--;
  const results = [];

  const roll = Math.floor(Math.random() * 3);
  const dg = gameState.dungeon;

  switch (roll) {
    case 0: {
      // BLAST SCROLL — damage all enemies in player's room
      const room = dg.rooms.find(r =>
        player.x >= r.x && player.x < r.x + r.w &&
        player.y >= r.y && player.y < r.y + r.h
      );
      let hit = 0;
      if (room) {
        for (const m of dg.monsters) {
          if (!m.alive) continue;
          if (m.x >= room.x && m.x < room.x + room.w && m.y >= room.y && m.y < room.y + room.h) {
            const scrollDmg = 10 + Math.floor(player.lvl * 2);
            m.hp -= scrollDmg;
            if (m.hp <= 0) {
              m.alive = false;
              playerGainXp(player, m.xp);
              player.kills++;
            }
            hit++;
          }
        }
      }
      results.push({ msg: `BLAST SCROLL! Hit ${hit} enemies in room!`, type: 'level' });
      break;
    }
    case 1: {
      // REVEAL SCROLL — reveal entire map
      if (gameState.visited) {
        for (let y = 0; y < dg.height; y++) {
          for (let x = 0; x < dg.width; x++) {
            gameState.visited[y][x] = true;
          }
        }
      }
      results.push({ msg: 'REVEAL SCROLL! Map revealed!', type: 'level' });
      break;
    }
    case 2: {
      // TELEPORT SCROLL — teleport to random room
      if (dg.rooms.length > 1) {
        const targetRoom = dg.rooms[Math.floor(Math.random() * dg.rooms.length)];
        player.x = targetRoom.cx;
        player.y = targetRoom.cy;
        results.push({ msg: 'TELEPORT SCROLL! Warped to another room!', type: 'level' });
        // Reveal new area
        if (typeof revealAround === 'function') {
          revealAround(player.x, player.y);
        }
      } else {
        results.push({ msg: 'TELEPORT SCROLL fizzled...', type: 'combat' });
      }
      break;
    }
  }

  return results;
}
