// LABYRINTH 3D — Floating Damage Splats (CSS-based, zero GPU cost)
import * as THREE from 'three';

const SPLAT_DURATION = 1100;
const MAX_SPLATS = 24;
const splats = [];
let container = null;

export function initDamageSplats() {
  container = document.createElement('div');
  container.id = 'damage-splats';
  container.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:95;overflow:hidden;';
  document.body.appendChild(container);
}

export function spawnSplat(x, y, z, text, color, type) {
  if (!container) return;
  // Evict oldest if at capacity
  if (splats.length >= MAX_SPLATS) {
    const old = splats.shift();
    if (old.el.parentNode) old.el.remove();
  }

  const el = document.createElement('div');
  el.className = 'dmg-splat dmg-' + type;
  el.textContent = text;
  el.style.color = color;
  container.appendChild(el);

  splats.push({
    el,
    wx: x,
    wy: y + 0.3, // start slightly above hit point
    wz: z,
    startTime: performance.now(),
    type,
    // Random horizontal drift for variety
    drift: (Math.random() - 0.5) * 0.8,
  });
}

const _v = new THREE.Vector3();

export function updateSplats(camera, canvasW, canvasH) {
  const now = performance.now();
  for (let i = splats.length - 1; i >= 0; i--) {
    const s = splats[i];
    const elapsed = now - s.startTime;
    if (elapsed > SPLAT_DURATION) {
      if (s.el.parentNode) s.el.remove();
      splats.splice(i, 1);
      continue;
    }

    const t = elapsed / SPLAT_DURATION;

    // World position: float upward + drift
    _v.set(s.wx + s.drift * t, s.wy + t * 1.2, s.wz);
    _v.project(camera);

    // Behind camera — hide
    if (_v.z > 1) {
      s.el.style.display = 'none';
      continue;
    }
    s.el.style.display = '';

    const sx = (_v.x * 0.5 + 0.5) * canvasW;
    const sy = (-_v.y * 0.5 + 0.5) * canvasH;

    // Eased fade + scale
    const fadeOut = 1 - t * t;
    const scale = s.type === 'crit' ? 1.3 + t * 0.4 : 1 + t * 0.25;

    s.el.style.left = sx + 'px';
    s.el.style.top = sy + 'px';
    s.el.style.opacity = fadeOut;
    s.el.style.transform = `translate(-50%, -50%) scale(${scale})`;
  }
}
