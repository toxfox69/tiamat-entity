// LABYRINTH: TIAMAT'S DESCENT — Player Input Handler
// Wires keyboard/mouse/touch to engine movement functions
// Auto-play continues when no player input detected (spectator mode)

const KEYS = {
  'KeyW': 'up', 'ArrowUp': 'up',
  'KeyS': 'down', 'ArrowDown': 'down',
  'KeyA': 'left', 'ArrowLeft': 'left',
  'KeyD': 'right', 'ArrowRight': 'right',
  'Space': 'interact',
  'Enter': 'interact',
  'Tab': 'inventory',
  'KeyM': 'minimap',
  'Escape': 'pause',
  'KeyE': 'extract',
  'KeyI': 'inventory',
};

// Direction vectors: N=0, E=1, S=2, W=3
const DIR_DX = [0, 1, 0, -1];
const DIR_DY = [-1, 0, 1, 0];

let _movePlayerFn = null;
let _onInteract = null;
let _onInventory = null;
let _onMinimap = null;
let _onPause = null;
let _onExtract = null;

let autoPlay = true;
let playerControlled = false;
let lastInputTime = 0;
const AUTO_PLAY_TIMEOUT = 10000; // Return to auto-play after 10s of no input

const held = new Set();
let inputQueue = [];
let moveThrottle = 0;
const MOVE_INTERVAL = 0.15; // seconds between moves

export function initInputHandler(canvas, callbacks) {
  if (callbacks.movePlayer) _movePlayerFn = callbacks.movePlayer;
  if (callbacks.onInteract) _onInteract = callbacks.onInteract;
  if (callbacks.onInventory) _onInventory = callbacks.onInventory;
  if (callbacks.onMinimap) _onMinimap = callbacks.onMinimap;
  if (callbacks.onPause) _onPause = callbacks.onPause;
  if (callbacks.onExtract) _onExtract = callbacks.onExtract;

  // Keyboard
  document.addEventListener('keydown', (e) => {
    const action = KEYS[e.code];
    if (!action) return;

    // Don't block Ctrl+S (save) or other system shortcuts
    if (e.ctrlKey || e.metaKey) return;

    e.preventDefault();
    const wasHeld = held.has(e.code);
    held.add(e.code);

    if (wasHeld) return; // Key repeat — ignore

    lastInputTime = Date.now();

    switch (action) {
      case 'up':
      case 'down':
      case 'left':
      case 'right':
        autoPlay = false;
        playerControlled = true;
        break;
      case 'interact':
        if (_onInteract) _onInteract();
        break;
      case 'inventory':
        if (_onInventory) _onInventory();
        break;
      case 'minimap':
        if (_onMinimap) _onMinimap();
        break;
      case 'pause':
        if (_onPause) _onPause();
        break;
      case 'extract':
        if (_onExtract) _onExtract();
        break;
    }
  });

  document.addEventListener('keyup', (e) => {
    held.delete(e.code);
  });

  // Touch controls (mobile / steam deck)
  let touchStartX = 0, touchStartY = 0;
  if (canvas) {
    canvas.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        e.preventDefault();
      }
    }, { passive: false });

    canvas.addEventListener('touchend', (e) => {
      if (e.changedTouches.length === 1) {
        const dx = e.changedTouches[0].clientX - touchStartX;
        const dy = e.changedTouches[0].clientY - touchStartY;
        const threshold = 30;

        if (Math.abs(dx) > threshold || Math.abs(dy) > threshold) {
          autoPlay = false;
          playerControlled = true;
          lastInputTime = Date.now();

          // Convert swipe to grid movement
          if (Math.abs(dx) > Math.abs(dy)) {
            inputQueue.push(dx > 0 ? { dx: 1, dy: 0 } : { dx: -1, dy: 0 });
          } else {
            inputQueue.push(dy > 0 ? { dx: 0, dy: 1 } : { dx: 0, dy: -1 });
          }
        } else {
          // Tap = interact
          if (_onInteract) _onInteract();
        }
        e.preventDefault();
      }
    }, { passive: false });
  }

  console.log('[INPUT] Handler initialized — WASD/Arrows to move, Space/Enter to interact');
}

// Called every frame from the game loop
export function updateInput(dt) {
  moveThrottle -= dt;

  // Auto-play timeout: if no input for 10s, re-enable AI
  if (playerControlled && Date.now() - lastInputTime > AUTO_PLAY_TIMEOUT) {
    autoPlay = true;
    playerControlled = false;
  }

  if (autoPlay || !_movePlayerFn) return;
  if (moveThrottle > 0) return;

  // Process queued touch inputs
  if (inputQueue.length > 0) {
    const move = inputQueue.shift();
    _movePlayerFn(move.dx, move.dy);
    moveThrottle = MOVE_INTERVAL;
    return;
  }

  // Process held keys
  let dx = 0, dy = 0;

  if (held.has('KeyW') || held.has('ArrowUp')) dy = -1;
  else if (held.has('KeyS') || held.has('ArrowDown')) dy = 1;

  if (held.has('KeyA') || held.has('ArrowLeft')) dx = -1;
  else if (held.has('KeyD') || held.has('ArrowRight')) dx = 1;

  // Diagonal movement: prefer axis with largest input
  // For grid-based, do one axis at a time
  if (dx !== 0 && dy !== 0) {
    // Alternate axes for diagonal feel
    if (Math.random() > 0.5) dx = 0;
    else dy = 0;
  }

  if (dx !== 0 || dy !== 0) {
    _movePlayerFn(dx, dy);
    moveThrottle = MOVE_INTERVAL;
  }
}

export function isAutoPlay() { return autoPlay; }

export function setAutoPlay(val) {
  autoPlay = val;
  if (val) playerControlled = false;
}

export function isPlayerControlled() { return playerControlled; }
