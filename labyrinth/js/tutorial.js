// LABYRINTH: TIAMAT'S DESCENT — Tutorial System
// First-time player guidance with contextual tips

const TUTORIAL_KEY = 'labyrinth_tutorial_complete';
const TIPS_SHOWN_KEY = 'labyrinth_tips_shown';

let isComplete = false;
let tipsShown = new Set();
let currentTip = null;
let tipElement = null;
let enabled = true;
let tipQueue = [];

const TIPS = {
  MOVE: {
    text: 'WASD or Arrow Keys to move through the dungeon',
    trigger: 'first_floor',
    priority: 1,
    delay: 2000,
  },
  COMBAT: {
    text: 'Walk into enemies to attack them',
    trigger: 'enemy_nearby',
    priority: 2,
    delay: 0,
  },
  PICKUP: {
    text: 'Walk over items to pick them up',
    trigger: 'item_nearby',
    priority: 3,
    delay: 0,
  },
  STAIRS: {
    text: 'Find the stairs to descend deeper into the dungeon',
    trigger: 'after_first_combat',
    priority: 4,
    delay: 1000,
  },
  TIAMAT: {
    text: 'The dungeon shifts based on TIAMAT\'s live AI state',
    trigger: 'floor_2',
    priority: 5,
    delay: 2000,
  },
  EXTRACT: {
    text: 'Stand on stairs to extract — bank your loot safely',
    trigger: 'near_stairs',
    priority: 6,
    delay: 0,
  },
  SETTINGS: {
    text: 'Press ESC to open Settings — adjust volume, graphics, and more',
    trigger: 'floor_3',
    priority: 7,
    delay: 3000,
  },
};

const TIP_DURATION = 5000; // 5 seconds per tip

// ─── Init ───
export function initTutorial() {
  isComplete = localStorage.getItem(TUTORIAL_KEY) === 'true';

  try {
    const shown = JSON.parse(localStorage.getItem(TIPS_SHOWN_KEY) || '[]');
    tipsShown = new Set(shown);
  } catch (e) {
    tipsShown = new Set();
  }

  createTipElement();

  if (isComplete) {
    console.log('[TUTORIAL] Already complete — skipping');
  } else {
    console.log('[TUTORIAL] Active — contextual tips enabled');
    // Queue the first tip with delay
    setTimeout(() => {
      showTip('MOVE');
    }, TIPS.MOVE.delay);
  }
}

// ─── Check conditions each game tick ───
export function updateTutorial(gameState) {
  if (isComplete || !enabled || currentTip) return;

  const p = gameState.player;

  // Enemy nearby
  if (!tipsShown.has('COMBAT')) {
    const nearbyEnemy = gameState.monsters && gameState.monsters.some(m =>
      m.alive && Math.abs(m.x - p.x) + Math.abs(m.y - p.y) <= 3
    );
    if (nearbyEnemy) {
      showTip('COMBAT');
      return;
    }
  }

  // Item nearby
  if (!tipsShown.has('PICKUP')) {
    const nearbyItem = gameState.items && gameState.items.some(i =>
      !i.pickedUp && Math.abs(i.x - p.x) + Math.abs(i.y - p.y) <= 3
    );
    if (nearbyItem) {
      showTip('PICKUP');
      return;
    }
  }

  // After first combat (player has kills)
  if (!tipsShown.has('STAIRS') && p.kills >= 1) {
    showTip('STAIRS');
    return;
  }

  // Near stairs
  if (!tipsShown.has('EXTRACT') && gameState.stairs) {
    const stairDist = Math.abs(gameState.stairs.x - p.x) + Math.abs(gameState.stairs.y - p.y);
    if (stairDist <= 2) {
      showTip('EXTRACT');
      return;
    }
  }

  // Floor 2
  if (!tipsShown.has('TIAMAT') && gameState.depth >= 2) {
    setTimeout(() => showTip('TIAMAT'), TIPS.TIAMAT.delay);
    return;
  }

  // Floor 3
  if (!tipsShown.has('SETTINGS') && gameState.depth >= 3) {
    setTimeout(() => showTip('SETTINGS'), TIPS.SETTINGS.delay);
    return;
  }

  // Check if all tips shown
  if (tipsShown.size >= Object.keys(TIPS).length && !isComplete) {
    completeTutorial();
  }
}

// ─── Show a tip ───
function showTip(tipKey) {
  if (tipsShown.has(tipKey) || currentTip || !enabled) return;

  const tip = TIPS[tipKey];
  if (!tip) return;

  tipsShown.add(tipKey);
  currentTip = tipKey;

  try {
    localStorage.setItem(TIPS_SHOWN_KEY, JSON.stringify(Array.from(tipsShown)));
  } catch (e) { /* ignore */ }

  if (tipElement) {
    tipElement.querySelector('.tutorial-text').textContent = tip.text;
    tipElement.style.display = 'block';
    tipElement.style.opacity = '0';
    tipElement.style.transform = 'translateX(-50%) translateY(10px)';

    requestAnimationFrame(() => {
      tipElement.style.transition = 'opacity 0.5s, transform 0.5s';
      tipElement.style.opacity = '1';
      tipElement.style.transform = 'translateX(-50%) translateY(0)';
    });

    // Fade out after duration
    setTimeout(() => {
      if (tipElement) {
        tipElement.style.opacity = '0';
        tipElement.style.transform = 'translateX(-50%) translateY(-10px)';
        setTimeout(() => {
          currentTip = null;
          if (tipElement) tipElement.style.display = 'none';
        }, 500);
      }
    }, TIP_DURATION);
  }
}

// ─── Mark tutorial complete ───
function completeTutorial() {
  isComplete = true;
  localStorage.setItem(TUTORIAL_KEY, 'true');
  console.log('[TUTORIAL] All tips shown — tutorial complete');
}

// ─── Enable/disable ───
export function setTutorialEnabled(val) {
  enabled = val;
  if (!val && tipElement) {
    tipElement.style.display = 'none';
    currentTip = null;
  }
}

export function isTutorialComplete() { return isComplete; }

export function resetTutorial() {
  isComplete = false;
  tipsShown.clear();
  localStorage.removeItem(TUTORIAL_KEY);
  localStorage.removeItem(TIPS_SHOWN_KEY);
  console.log('[TUTORIAL] Reset — will show tips again');
}

// ─── Create DOM element ───
function createTipElement() {
  if (tipElement) return;

  tipElement = document.createElement('div');
  tipElement.id = 'tutorial-tip';
  tipElement.style.cssText = `
    position: fixed;
    bottom: 120px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0, 10, 0, 0.9);
    border: 1px solid rgba(0, 255, 65, 0.4);
    padding: 10px 20px;
    z-index: 8000;
    pointer-events: none;
    display: none;
    max-width: 400px;
    text-align: center;
    box-shadow: 0 0 20px rgba(0, 255, 65, 0.1);
  `;
  tipElement.innerHTML = `
    <div style="font-family: 'Press Start 2P', monospace; font-size: 8px; color: #ffdd00; letter-spacing: 2px; margin-bottom: 6px;">TIP</div>
    <div class="tutorial-text" style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #00ff41; text-shadow: 0 0 6px rgba(0, 255, 65, 0.3);"></div>
  `;
  document.body.appendChild(tipElement);
}
