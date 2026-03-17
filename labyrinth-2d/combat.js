// LABYRINTH 2D — Turn-based Bump Combat System
// Walk into enemy to attack, enemy attacks back.
// Damage = ATK - DEF + random(0-2)

function calculateDamage(attackerAtk, defenderDef) {
  const raw = attackerAtk - defenderDef + Math.floor(Math.random() * 3);
  return Math.max(1, raw); // Always at least 1 damage
}

function playerAttackMonster(player, monster) {
  const results = [];

  // Player attacks
  const dmg = calculateDamage(player.totalAtk, 0); // Monsters have no DEF in original
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
    // Monster attacks back
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
  // From labyrinth_state.py on_death()
  gameState.sessionStats.deaths++;
  player.hp = player.maxHp;
  player.gold = Math.floor(player.gold * 0.7);
  // Depth regress handled by caller
  return [{ msg: 'Respawned. Lost 30% gold.', type: 'death' }];
}
