/**
 * SHADOWRUN VR — Scene Navigation System
 * Handles multiple areas, enemy spawning, quest progression
 */

const SceneNavigation = (() => {
  const SCENES = {
    'bar': {
      name: 'Stoker\'s Coffin Motel — Bar',
      description: 'Smoke-filled corporate dive bar. Neon green ambiance.',
      enemies: [],
      npcs: ['Ganger', 'Fixer', 'Decker', 'Bartender'],
      exits: ['street', 'warehouse', 'corporate']
    },
    'street': {
      name: 'The Street',
      description: 'Neon-lit alley. Gang activity. High danger.',
      enemies: ['Street Punk', 'Security Guard'],
      npcs: [],
      exits: ['bar', 'warehouse']
    },
    'warehouse': {
      name: 'Abandoned Warehouse',
      description: 'Vast industrial space. Danger lurks in shadows.',
      enemies: ['Street Samurai', 'Cyber-Assassin'],
      npcs: [],
      exits: ['bar', 'street', 'corporate']
    },
    'corporate': {
      name: 'MegaCorp Tower Lobby',
      description: 'Sleek corporate security. High-tech threat.',
      enemies: ['Security Drone', 'Corporate Sec-Chief'],
      npcs: [],
      exits: ['bar', 'warehouse']
    }
  };

  const ENEMIES = {
    'Street Punk': { hp: 30, damage: 3, xp: 25 },
    'Security Guard': { hp: 40, damage: 4, xp: 40 },
    'Street Samurai': { hp: 60, damage: 6, xp: 75 },
    'Cyber-Assassin': { hp: 50, damage: 5, xp: 60 },
    'Security Drone': { hp: 45, damage: 4, xp: 50 },
    'Corporate Sec-Chief': { hp: 80, damage: 7, xp: 100 }
  };

  let currentScene = 'bar';
  let activeEnemy = null;

  function createSceneUI() {
    const panel = document.createElement('div');
    panel.id = 'scene-panel';
    panel.style.cssText = `
      position: fixed; top: 20px; left: 20px; width: 400px; background: #000;
      border: 2px solid #0f0; padding: 15px; font-family: 'Courier New', monospace;
      color: #0f0; font-size: 11px; z-index: 4999; box-shadow: 0 0 15px rgba(0, 255, 0, 0.3);
    `;
    panel.innerHTML = `
      <div style="margin-bottom: 10px; border-bottom: 1px solid #0f0; padding-bottom: 5px; font-weight: bold;">
        == CURRENT LOCATION ==
      </div>
      <div id="scene-name" style="font-size: 12px; font-weight: bold; margin-bottom: 8px;">Loading...</div>
      <div id="scene-desc" style="font-size: 10px; margin-bottom: 10px; opacity: 0.8;"></div>
      <div id="scene-enemies" style="margin-bottom: 10px; padding: 8px; background: #0a0a0a; border: 1px solid #f00;"></div>
      <div id="scene-exits" style="margin-bottom: 10px;"></div>
    `;
    return panel;
  }

  function updateSceneDisplay() {
    const scene = SCENES[currentScene];
    if (!scene) return;

    const nameDiv = document.getElementById('scene-name');
    const descDiv = document.getElementById('scene-desc');
    const enemiesDiv = document.getElementById('scene-enemies');
    const exitsDiv = document.getElementById('scene-exits');

    if (nameDiv) nameDiv.textContent = scene.name;
    if (descDiv) descDiv.textContent = scene.description;

    // Enemies
    if (enemiesDiv) {
      if (scene.enemies.length === 0) {
        enemiesDiv.innerHTML = '<div style="opacity: 0.6;">Safe zone. No enemies.</div>';
      } else {
        enemiesDiv.innerHTML = `<div style="font-weight: bold; margin-bottom: 5px; color: #f00;">THREATS:</div>` +
          scene.enemies.map(e => `<div>⚠ ${e}</div>`).join('');
      }
    }

    // Exits
    if (exitsDiv) {
      exitsDiv.innerHTML = '<div style="font-weight: bold; margin-bottom: 5px;">EXITS:</div>' +
        scene.exits.map(exit => `
          <button onclick="SceneNavigation.goToScene('${exit}')" style="
            margin: 2px 2px 2px 0; padding: 4px 8px; background: #0f0; color: #000;
            border: none; cursor: pointer; font-family: monospace; font-size: 10px;
          ">${SCENES[exit].name}</button>
        `).join('');
    }
  }

  function spawnEnemy() {
    const scene = SCENES[currentScene];
    if (scene.enemies.length === 0) return;

    const enemyName = scene.enemies[Math.floor(Math.random() * scene.enemies.length)];
    activeEnemy = {
      name: enemyName,
      hp: ENEMIES[enemyName].hp,
      maxHp: ENEMIES[enemyName].hp,
      damage: ENEMIES[enemyName].damage,
      xp: ENEMIES[enemyName].xp
    };
    console.log(`[ENCOUNTER] ${enemyName} appears!`);
    showCombatUI();
  }

  function showCombatUI() {
    if (!activeEnemy) return;

    let combatDiv = document.getElementById('combat-panel');
    if (!combatDiv) {
      combatDiv = document.createElement('div');
      combatDiv.id = 'combat-panel';
      document.body.appendChild(combatDiv);
    }

    combatDiv.style.cssText = `
      position: fixed; bottom: 20px; left: 20px; width: 300px; background: #000;
      border: 2px solid #f00; padding: 15px; font-family: 'Courier New', monospace;
      color: #f00; font-size: 11px; z-index: 5000; box-shadow: 0 0 15px rgba(255, 0, 0, 0.3);
    `;

    combatDiv.innerHTML = `
      <div style="margin-bottom: 10px; border-bottom: 2px solid #f00; padding-bottom: 5px; font-weight: bold;">
        COMBAT — ${activeEnemy.name}
      </div>
      <div id="enemy-hp" style="margin-bottom: 10px;">
        Enemy HP: <span style="color: #f00;">${activeEnemy.hp}/${activeEnemy.maxHp}</span>
      </div>
      <button onclick="SceneNavigation.playerAttack()" style="
        width: 100%; padding: 8px; margin-bottom: 5px; background: #f00; color: #000;
        border: none; cursor: pointer; font-family: monospace; font-weight: bold;
      ">ATTACK</button>
      <button onclick="SceneNavigation.flee()" style="
        width: 100%; padding: 8px; background: #666; color: #fff;
        border: none; cursor: pointer; font-family: monospace;
      ">FLEE</button>
      <div id="combat-log" style="margin-top: 10px; font-size: 10px; opacity: 0.8;"></div>
    `;
  }

  function playerAttack() {
    if (!activeEnemy) return;

    const damage = Math.floor(Math.random() * 20) + 5;
    activeEnemy.hp = Math.max(0, activeEnemy.hp - damage);
    console.log(`[COMBAT] You deal ${damage} damage!`);

    if (activeEnemy.hp <= 0) {
      console.log(`[VICTORY] ${activeEnemy.name} defeated!`);
      if (window.InventoryUI) {
        InventoryUI.addXP(activeEnemy.xp);
      }
      activeEnemy = null;
      document.getElementById('combat-panel').style.display = 'none';
      console.log(`[REWARD] +${activeEnemy.xp} XP`);
      return;
    }

    // Enemy counter-attack
    const enemyDamage = Math.floor(Math.random() * (activeEnemy.damage + 5));
    if (window.InventoryUI) {
      InventoryUI.takeDamage(enemyDamage);
    }
    console.log(`[COMBAT] ${activeEnemy.name} deals ${enemyDamage} damage!`);

    // Update UI
    document.getElementById('enemy-hp').textContent = `Enemy HP: ${activeEnemy.hp}/${activeEnemy.maxHp}`;
    const combatLog = document.getElementById('combat-log');
    if (combatLog) {
      combatLog.innerHTML = `<div style="color: #0f0;">You: -${enemyDamage} HP</div><div style="color: #f00;">${activeEnemy.name}: -${damage} HP</div>`;
    }
  }

  function flee() {
    console.log('[FLEE] Retreating...');
    activeEnemy = null;
    document.getElementById('combat-panel').style.display = 'none';
  }

  function goToScene(sceneKey) {
    if (!SCENES[sceneKey]) return;
    currentScene = sceneKey;
    console.log(`[NAVIGATE] Moving to ${SCENES[sceneKey].name}`);
    updateSceneDisplay();
    activeEnemy = null;
    document.getElementById('combat-panel').style.display = 'none';

    // Random encounter
    if (Math.random() > 0.5 && SCENES[sceneKey].enemies.length > 0) {
      setTimeout(spawnEnemy, 500);
    }
  }

  function init() {
    const scenePanel = createSceneUI();
    document.body.appendChild(scenePanel);
    updateSceneDisplay();
    console.log('[SCENE-NAV] Initialized');
  }

  return {
    init: init,
    goToScene: goToScene,
    playerAttack: playerAttack,
    flee: flee,
    getScene: () => currentScene
  };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', SceneNavigation.init);
} else {
  SceneNavigation.init();
}
