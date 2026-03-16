// LABYRINTH — Player Input Handler (WASD + Mouse + Touch)
// NEW module for standalone client — enables manual play alongside AI auto-play

const KEYS = {
  'KeyW': 'forward', 'ArrowUp': 'forward',
  'KeyS': 'back', 'ArrowDown': 'back',
  'KeyA': 'left', 'ArrowLeft': 'left',
  'KeyD': 'right', 'ArrowRight': 'right',
  'Space': 'action', 'Enter': 'action',
  'KeyE': 'extract',
  'KeyI': 'inventory',
  'Escape': 'pause',
  'Tab': 'spectate',
};

const state = {
  forward: false,
  back: false,
  left: false,
  right: false,
  action: false,
  extract: false,
  mouseX: 0,
  mouseY: 0,
  mouseDX: 0,
  mouseDY: 0,
  pointerLocked: false,
  autoPlay: true, // Start in auto-play, player can take over
};

let onAction = null;
let onExtract = null;
let onSpectate = null;
let onPause = null;
let onInventory = null;

// Track which keys are currently held
const held = new Set();

export function initInput(canvas) {
  // Keyboard
  document.addEventListener('keydown', (e) => {
    const action = KEYS[e.code];
    if (!action) return;
    e.preventDefault();

    if (action === 'action' && !held.has(e.code)) {
      if (onAction) onAction();
    }
    if (action === 'extract' && !held.has(e.code)) {
      if (onExtract) onExtract();
    }
    if (action === 'spectate' && !held.has(e.code)) {
      if (onSpectate) onSpectate();
    }
    if (action === 'pause' && !held.has(e.code)) {
      if (onPause) onPause();
    }
    if (action === 'inventory' && !held.has(e.code)) {
      if (onInventory) onInventory();
    }

    held.add(e.code);
    if (['forward', 'back', 'left', 'right'].includes(action)) {
      state[action] = true;
      state.autoPlay = false; // Player took control
    }
  });

  document.addEventListener('keyup', (e) => {
    const action = KEYS[e.code];
    if (!action) return;
    held.delete(e.code);
    if (['forward', 'back', 'left', 'right'].includes(action)) {
      state[action] = false;
    }
  });

  // Mouse look (pointer lock)
  if (canvas) {
    canvas.addEventListener('click', () => {
      if (!state.pointerLocked) {
        canvas.requestPointerLock();
      }
    });

    document.addEventListener('pointerlockchange', () => {
      state.pointerLocked = document.pointerLockElement === canvas;
    });

    document.addEventListener('mousemove', (e) => {
      if (state.pointerLocked) {
        state.mouseDX += e.movementX;
        state.mouseDY += e.movementY;
      }
    });
  }

  // Touch controls (mobile)
  let touchStartX = 0, touchStartY = 0;
  document.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }
  });

  document.addEventListener('touchmove', (e) => {
    if (e.touches.length === 1) {
      const dx = e.touches[0].clientX - touchStartX;
      const dy = e.touches[0].clientY - touchStartY;
      const threshold = 30;

      state.forward = dy < -threshold;
      state.back = dy > threshold;
      state.left = dx < -threshold;
      state.right = dx > threshold;

      if (Math.abs(dx) > threshold || Math.abs(dy) > threshold) {
        state.autoPlay = false;
      }
    }
  });

  document.addEventListener('touchend', () => {
    state.forward = state.back = state.left = state.right = false;
  });
}

// Get movement direction this frame (returns {dx, dy} or null)
export function getMovement() {
  if (state.autoPlay) return null;

  let dx = 0, dy = 0;
  if (state.forward) dy = -1;
  if (state.back) dy = 1;
  if (state.left) dx = -1;
  if (state.right) dx = 1;

  if (dx === 0 && dy === 0) return null;
  return { dx, dy };
}

// Get and reset mouse delta
export function getMouseDelta() {
  const dx = state.mouseDX;
  const dy = state.mouseDY;
  state.mouseDX = 0;
  state.mouseDY = 0;
  return { dx, dy };
}

export function isAutoPlay() { return state.autoPlay; }
export function setAutoPlay(v) { state.autoPlay = v; }
export function isPointerLocked() { return state.pointerLocked; }

// Event handlers
export function setOnAction(fn) { onAction = fn; }
export function setOnExtract(fn) { onExtract = fn; }
export function setOnSpectate(fn) { onSpectate = fn; }
export function setOnPause(fn) { onPause = fn; }
export function setOnInventory(fn) { onInventory = fn; }

export function getInputState() { return { ...state }; }
