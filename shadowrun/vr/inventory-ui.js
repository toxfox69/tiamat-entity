/**
 * SHADOWRUN VR — Inventory & Equipment System
 * Handles item management, equipment, consumables, and character stats
 */

const InventoryUI = (() => {
  const CONFIG = {
    SAVE_KEY: 'shadowrun_game_state',
    CONSUMABLE_EFFECTS: {
      'Beer': { health: 20 },
      'Whiskey': { health: 50 }
    }
  };

  let gameState = {
    inventory: [],
    equipped: { weapon: null },
    health: 100,
    maxHealth: 100,
    nuyen: 0,
    xp: 0,
    level: 1
  };

  function initState() {
    try {
      const saved = localStorage.getItem(CONFIG.SAVE_KEY);
      if (saved) gameState = { ...gameState, ...JSON.parse(saved) };
    } catch (e) { console.warn('Failed to load saved state:', e); }
  }

  function saveState() {
    try {
      localStorage.setItem(CONFIG.SAVE_KEY, JSON.stringify(gameState));
    } catch (e) { console.warn('Failed to save state:', e); }
  }

  function createInventoryPanel() {
    const panel = document.createElement('div');
    panel.id = 'inventory-panel';
    panel.style.cssText = `
      position: fixed; bottom: 20px; left: 20px; width: 300px; max-height: 400px;
      background: #000; border: 2px solid #0f0; padding: 15px; font-family: 'Courier New', monospace;
      color: #0f0; font-size: 11px; overflow-y: auto; z-index: 5000;
      box-shadow: 0 0 15px rgba(0, 255, 0, 0.3);
    `;
    panel.innerHTML = `
      <div style="margin-bottom: 10px; border-bottom: 1px solid #0f0; padding-bottom: 5px;">
        <div style="font-weight: bold;">== INVENTORY ==</div>
      </div>
      <div id="inv-items" style="margin-bottom: 15px; min-height: 80px;"><div style="opacity: 0.6;">[empty]</div></div>
      <div id="inv-equipped" style="margin-bottom: 10px; padding: 8px; background: #0a0a0a; border: 1px solid #0f0;">
        <div style="font-weight: bold; margin-bottom: 5px;">EQUIPPED</div>
        <div id="equipped-weapon">Weapon: [none]</div>
      </div>
    `;
    return panel;
  }

  function createStatsPanel() {
    const panel = document.createElement('div');
    panel.id = 'stats-panel';
    panel.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; width: 180px;
      background: #000; border: 2px solid #0f0; padding: 12px; font-family: 'Courier New', monospace;
      color: #0f0; font-size: 11px; z-index: 5000; box-shadow: 0 0 15px rgba(0, 255, 0, 0.3);
    `;
    panel.innerHTML = `
      <div style="margin-bottom: 8px; border-bottom: 1px solid #0f0; padding-bottom: 5px; font-weight: bold;">== STATS ==</div>
      <div id="stat-health">HP: 100/100</div>
      <div id="stat-level">LVL: 1</div>
      <div id="stat-xp">XP: 0</div>
      <div id="stat-nuyen">¥: 0</div>
      <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid #0f0; font-size: 10px;">
        <button id="inv-toggle" style="width: 100%; padding: 4px; background: #0f0; color: #000; border: none; cursor: pointer; font-family: monospace;">[INV]</button>
      </div>
    `;
    return panel;
  }

  function updateInventoryDisplay() {
    const invItems = document.getElementById('inv-items');
    if (!invItems) return;
    if (gameState.inventory.length === 0) {
      invItems.innerHTML = '<div style="opacity: 0.6;">[empty]</div>';
      return;
    }
    invItems.innerHTML = gameState.inventory.map((item, idx) => `
      <div style="padding: 4px; margin: 2px 0; background: #0a0a0a; display: flex; justify-content: space-between; align-items: center;">
        <span>${item.name}</span>
        <div>
          ${item.type === 'consumable' ? `<button onclick="InventoryUI.useItem(${idx})" style="padding: 2px 6px; font-size: 9px; background: #0f0; color: #000; border: none; cursor: pointer;">USE</button>` : ''}
          ${item.type === 'weapon' ? `<button onclick="InventoryUI.equipWeapon(${idx})" style="padding: 2px 6px; font-size: 9px; background: #0f0; color: #000; border: none; cursor: pointer;">EQUIP</button>` : ''}
          <button onclick="InventoryUI.dropItem(${idx})" style="padding: 2px 6px; font-size: 9px; background: #f00; color: #000; border: none; cursor: pointer; margin-left: 3px;">DROP</button>
        </div>
      </div>
    `).join('');
  }

  function updateStatsDisplay() {
    const healthDiv = document.getElementById('stat-health');
    const levelDiv = document.getElementById('stat-level');
    const xpDiv = document.getElementById('stat-xp');
    const nuyenDiv = document.getElementById('stat-nuyen');
    if (healthDiv) healthDiv.textContent = `HP: ${gameState.health}/${gameState.maxHealth}`;
    if (levelDiv) levelDiv.textContent = `LVL: ${gameState.level}`;
    if (xpDiv) xpDiv.textContent = `XP: ${gameState.xp}`;
    if (nuyenDiv) nuyenDiv.textContent = `¥: ${gameState.nuyen}`;
  }

  function updateEquippedDisplay() {
    const weaponDiv = document.getElementById('equipped-weapon');
    if (weaponDiv) {
      weaponDiv.textContent = gameState.equipped.weapon
        ? `Weapon: ${gameState.equipped.weapon.name}`
        : 'Weapon: [none]';
    }
  }

  function addItem(item) {
    gameState.inventory.push(item);
    console.log('[INVENTORY] Added:', item);
    updateInventoryDisplay();
    saveState();
  }

  function removeItem(index) {
    if (index >= 0 && index < gameState.inventory.length) {
      const removed = gameState.inventory.splice(index, 1)[0];
      console.log('[INVENTORY] Removed:', removed);
      updateInventoryDisplay();
      saveState();
      return removed;
    }
  }

  function useItem(index) {
    const item = gameState.inventory[index];
    if (!item || item.type !== 'consumable') return;
    const effect = CONFIG.CONSUMABLE_EFFECTS[item.name];
    if (effect && effect.health) {
      gameState.health = Math.min(gameState.maxHealth, gameState.health + effect.health);
      console.log(`[ITEM] Used ${item.name}. Health: ${gameState.health}`);
    }
    removeItem(index);
    updateStatsDisplay();
    saveState();
  }

  function equipWeapon(index) {
    const item = gameState.inventory[index];
    if (!item || item.type !== 'weapon') return;
    gameState.equipped.weapon = item;
    console.log('[EQUIPMENT] Equipped weapon:', item.name);
    updateEquippedDisplay();
    saveState();
  }

  function dropItem(index) {
    const item = removeItem(index);
    if (item) console.log('[INVENTORY] Dropped:', item.name);
  }

  function addNuyen(amount) {
    gameState.nuyen += amount;
    console.log('[NUYEN] +' + amount + ' = ' + gameState.nuyen);
    updateStatsDisplay();
    saveState();
  }

  function addXP(amount) {
    gameState.xp += amount;
    console.log('[XP] +' + amount + ' = ' + gameState.xp);
    const newLevel = Math.floor(gameState.xp / 100) + 1;
    if (newLevel > gameState.level) {
      gameState.level = newLevel;
      gameState.maxHealth += 10;
      gameState.health = gameState.maxHealth;
      console.log('[LEVEL] Advanced to Level ' + gameState.level);
    }
    updateStatsDisplay();
    saveState();
  }

  function takeDamage(amount) {
    gameState.health = Math.max(0, gameState.health - amount);
    console.log('[DAMAGE] -' + amount + ' HP. Health: ' + gameState.health);
    updateStatsDisplay();
    saveState();
    if (gameState.health <= 0) console.log('[GAME] YOU DIED');
  }

  function init() {
    initState();
    const invPanel = createInventoryPanel();
    const statsPanel = createStatsPanel();
    document.body.appendChild(invPanel);
    document.body.appendChild(statsPanel);
    const invToggle = document.getElementById('inv-toggle');
    if (invToggle) {
      invToggle.addEventListener('click', () => {
        invPanel.style.display = invPanel.style.display === 'none' ? 'block' : 'none';
      });
    }
    updateInventoryDisplay();
    updateStatsDisplay();
    updateEquippedDisplay();
    console.log('[INVENTORY] Initialized');
  }

  return {
    init: init,
    addItem: addItem,
    removeItem: removeItem,
    useItem: useItem,
    equipWeapon: equipWeapon,
    dropItem: dropItem,
    addNuyen: addNuyen,
    addXP: addXP,
    takeDamage: takeDamage,
    getState: () => gameState
  };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', InventoryUI.init);
} else {
  InventoryUI.init();
}
