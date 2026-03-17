// LABYRINTH 3D — Particle system (3DGS-style splats + volumetric fog + dust + events)
import * as THREE from 'three';

const MAX_PARTICLES = 200;
const MAX_WALL_SPLATS = 120;
const MAX_FOG_PARTICLES = 40;
const MAX_DUST_MOTES = 30;
const MAX_GROUND_MIST = 20;

// Shared splat texture
let splatTexture = null;
export function loadSplatTexture() {
  const loader = new THREE.TextureLoader();
  splatTexture = loader.load('assets/splat-blob.png');
  splatTexture.minFilter = THREE.LinearFilter;
  splatTexture.magFilter = THREE.LinearFilter;
}

// ─── Wall Splats (3DGS-style organic surface textures) ───
const wallSplats = [];
export function createWallSplats(level, biomeColor, scene) {
  for (const s of wallSplats) { scene.remove(s); s.material.dispose(); }
  wallSplats.length = 0;
  if (!splatTexture) return;

  const { tiles, w, h } = level;
  const color = new THREE.Color(biomeColor);
  // Make splats brighter than wall color so they're visible
  const brightColor = color.clone().multiplyScalar(2.5);
  let count = 0;

  for (let y = 1; y < h - 1 && count < MAX_WALL_SPLATS; y++) {
    for (let x = 1; x < w - 1 && count < MAX_WALL_SPLATS; x++) {
      if (tiles[y][x] !== 0) continue;
      const adj = [tiles[y-1]?.[x], tiles[y+1]?.[x], tiles[y]?.[x-1], tiles[y]?.[x+1]];
      const hasFloor = adj.some(t => t > 0);
      if (!hasFloor || Math.random() > 0.35) continue;

      const numSplats = 2 + Math.floor(Math.random() * 5);
      for (let s = 0; s < numSplats && count < MAX_WALL_SPLATS; s++) {
        const size = 0.4 + Math.random() * 0.8;
        const splatColor = brightColor.clone().offsetHSL(
          Math.random() * 0.06 - 0.03,
          Math.random() * 0.1 - 0.05,
          Math.random() * 0.15 - 0.075
        );
        const mat = new THREE.SpriteMaterial({
          map: splatTexture,
          color: splatColor,
          transparent: true,
          opacity: 0.3 + Math.random() * 0.4,
          blending: THREE.NormalBlending,
          depthWrite: false,
        });
        const sprite = new THREE.Sprite(mat);
        sprite.scale.set(size, size, 1);

        // Position on wall face adjacent to floor
        const offY = 0.1 + Math.random() * 1.3;
        if (tiles[y-1]?.[x] > 0) sprite.position.set(x + (Math.random()-0.5)*0.7, offY, y - 0.49);
        else if (tiles[y+1]?.[x] > 0) sprite.position.set(x + (Math.random()-0.5)*0.7, offY, y + 0.49);
        else if (tiles[y]?.[x-1] > 0) sprite.position.set(x - 0.49, offY, y + (Math.random()-0.5)*0.7);
        else sprite.position.set(x + 0.49, offY, y + (Math.random()-0.5)*0.7);

        scene.add(sprite);
        wallSplats.push(sprite);
        count++;
      }
    }
  }
}

// ─── Volumetric Fog Particles ───
let fogPoints = null;
const fogPositions = new Float32Array(MAX_FOG_PARTICLES * 3);
const fogVelocities = new Float32Array(MAX_FOG_PARTICLES * 3);

export function createFogParticles(level, biomeColor, scene) {
  if (fogPoints) { scene.remove(fogPoints); fogPoints.geometry.dispose(); fogPoints.material.dispose(); }

  const { rooms } = level;
  const color = new THREE.Color(biomeColor);

  for (let i = 0; i < MAX_FOG_PARTICLES; i++) {
    const room = rooms[Math.floor(Math.random() * rooms.length)];
    fogPositions[i * 3] = room.x + Math.random() * room.w;
    fogPositions[i * 3 + 1] = 0.2 + Math.random() * 1.2;
    fogPositions[i * 3 + 2] = room.y + Math.random() * room.h;
    fogVelocities[i * 3] = (Math.random() - 0.5) * 0.015;
    fogVelocities[i * 3 + 1] = Math.random() * 0.005 + 0.001;
    fogVelocities[i * 3 + 2] = (Math.random() - 0.5) * 0.015;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(fogPositions, 3));

  const mat = new THREE.PointsMaterial({
    color: color,
    size: 1.2,
    transparent: true,
    opacity: 0.07,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
  });

  fogPoints = new THREE.Points(geo, mat);
  scene.add(fogPoints);

  // Ground mist — larger, slower, low-lying fog hugging the floor
  createGroundMist(level, color, scene);
}

export function updateFogParticles(dt) {
  updateGroundMist(dt);
  if (!fogPoints) return;
  const pos = fogPoints.geometry.attributes.position;
  for (let i = 0; i < MAX_FOG_PARTICLES; i++) {
    pos.array[i * 3] += fogVelocities[i * 3] * dt;
    pos.array[i * 3 + 1] += fogVelocities[i * 3 + 1] * dt;
    pos.array[i * 3 + 2] += fogVelocities[i * 3 + 2] * dt;
    if (pos.array[i * 3 + 1] > 1.5) pos.array[i * 3 + 1] = 0.1;
  }
  pos.needsUpdate = true;
}

// ─── Ground Mist (low-lying atmospheric fog) ───
let groundMistPoints = null;
const groundMistPositions = new Float32Array(MAX_GROUND_MIST * 3);
const groundMistVelocities = new Float32Array(MAX_GROUND_MIST * 3);

function createGroundMist(level, biomeColor, scene) {
  if (groundMistPoints) { scene.remove(groundMistPoints); groundMistPoints.geometry.dispose(); groundMistPoints.material.dispose(); }

  const { rooms } = level;
  // Warmer, brighter mist color
  const mistColor = biomeColor.clone().offsetHSL(0, -0.1, 0.15);

  for (let i = 0; i < MAX_GROUND_MIST; i++) {
    const room = rooms[Math.floor(Math.random() * rooms.length)];
    groundMistPositions[i * 3] = room.x + Math.random() * room.w;
    groundMistPositions[i * 3 + 1] = Math.random() * 0.25; // stays near floor
    groundMistPositions[i * 3 + 2] = room.y + Math.random() * room.h;
    groundMistVelocities[i * 3] = (Math.random() - 0.5) * 0.008;
    groundMistVelocities[i * 3 + 1] = Math.random() * 0.002;
    groundMistVelocities[i * 3 + 2] = (Math.random() - 0.5) * 0.008;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(groundMistPositions, 3));

  const mat = new THREE.PointsMaterial({
    color: mistColor,
    size: 0.8,
    transparent: true,
    opacity: 0.05,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
  });

  groundMistPoints = new THREE.Points(geo, mat);
  scene.add(groundMistPoints);
}

function updateGroundMist(dt) {
  if (!groundMistPoints) return;
  const pos = groundMistPoints.geometry.attributes.position;
  for (let i = 0; i < MAX_GROUND_MIST; i++) {
    pos.array[i * 3] += groundMistVelocities[i * 3] * dt;
    pos.array[i * 3 + 1] += groundMistVelocities[i * 3 + 1] * dt;
    pos.array[i * 3 + 2] += groundMistVelocities[i * 3 + 2] * dt;
    // Keep near floor
    if (pos.array[i * 3 + 1] > 0.25) {
      pos.array[i * 3 + 1] = 0.05;
      groundMistVelocities[i * 3] = (Math.random() - 0.5) * 0.008;
      groundMistVelocities[i * 3 + 2] = (Math.random() - 0.5) * 0.008;
    }
  }
  pos.needsUpdate = true;
}

// ─── Dust Motes (near floor, always visible around player) ───
let dustPoints = null;
const dustPositions = new Float32Array(MAX_DUST_MOTES * 3);
const dustVelocities = new Float32Array(MAX_DUST_MOTES * 3);

export function createDustMotes(scene) {
  if (dustPoints) { scene.remove(dustPoints); dustPoints.geometry.dispose(); dustPoints.material.dispose(); }

  for (let i = 0; i < MAX_DUST_MOTES; i++) {
    dustPositions[i * 3] = (Math.random() - 0.5) * 8;
    dustPositions[i * 3 + 1] = Math.random() * 1.4;
    dustPositions[i * 3 + 2] = (Math.random() - 0.5) * 8;
    dustVelocities[i * 3] = (Math.random() - 0.5) * 0.02;
    dustVelocities[i * 3 + 1] = (Math.random() - 0.5) * 0.005;
    dustVelocities[i * 3 + 2] = (Math.random() - 0.5) * 0.02;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));

  const mat = new THREE.PointsMaterial({
    color: 0xffffee,
    size: 0.06,
    transparent: true,
    opacity: 0.5,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
  });

  dustPoints = new THREE.Points(geo, mat);
  scene.add(dustPoints);
}

export function updateDustMotes(dt, playerX, playerZ) {
  if (!dustPoints) return;
  const pos = dustPoints.geometry.attributes.position;
  for (let i = 0; i < MAX_DUST_MOTES; i++) {
    pos.array[i * 3] += dustVelocities[i * 3] * dt;
    pos.array[i * 3 + 1] += dustVelocities[i * 3 + 1] * dt;
    pos.array[i * 3 + 2] += dustVelocities[i * 3 + 2] * dt;

    // Keep centered around player
    const dx = pos.array[i * 3] - playerX;
    const dz = pos.array[i * 3 + 2] - playerZ;
    if (Math.abs(dx) > 5 || Math.abs(dz) > 5 || pos.array[i * 3 + 1] > 1.5 || pos.array[i * 3 + 1] < 0) {
      pos.array[i * 3] = playerX + (Math.random() - 0.5) * 6;
      pos.array[i * 3 + 1] = Math.random() * 1.4;
      pos.array[i * 3 + 2] = playerZ + (Math.random() - 0.5) * 6;
    }
  }
  pos.needsUpdate = true;
}

// ─── Event Particles ───
const eventParticles = [];
const EVENT_COLORS = {
  mine: 0xffdd00, scout: 0x00ffff, curse: 0xff2040, forge: 0x00ccff,
  study: 0x6688ff, rage: 0xff4400, legendary: 0xffffff, heal: 0x44ff88,
  warp: 0xffaa00, death: 0xff0040, default: 0x00ff41,
};

export function emitParticles(x, y, type, count) {
  const color = EVENT_COLORS[type] || EVENT_COLORS.default;
  const isAdditive = type === 'legendary' || type === 'warp' || type === 'forge';

  for (let i = 0; i < Math.min(count, 20) && eventParticles.length < MAX_PARTICLES; i++) {
    const size = 0.04 + Math.random() * 0.08;
    const geo = new THREE.SphereGeometry(size, 4, 4);
    const mat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0.9,
      blending: isAdditive ? THREE.AdditiveBlending : THREE.NormalBlending,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, 0.3 + Math.random() * 0.6, y);
    eventParticles.push({
      mesh, vx: (Math.random() - 0.5) * 2.5,
      vy: 0.8 + Math.random() * 2.5, vz: (Math.random() - 0.5) * 2.5,
      life: 1.0, decay: 0.5 + Math.random() * 0.7,
    });
  }
  return eventParticles.slice(-Math.min(count, 20)).map(p => p.mesh);
}

export function updateEventParticles(dt, scene) {
  for (let i = eventParticles.length - 1; i >= 0; i--) {
    const p = eventParticles[i];
    p.life -= p.decay * dt;
    p.vy -= 3.5 * dt;
    p.mesh.position.x += p.vx * dt;
    p.mesh.position.y += p.vy * dt;
    p.mesh.position.z += p.vz * dt;
    p.mesh.material.opacity = Math.max(0, p.life * 0.9);
    p.mesh.scale.setScalar(Math.max(0.01, p.life));

    if (p.life <= 0) {
      scene.remove(p.mesh);
      p.mesh.geometry.dispose();
      p.mesh.material.dispose();
      eventParticles.splice(i, 1);
    }
  }
}

// ─── Extraction Ring ───
let extractRing = null;
export function createExtractRing(x, y, scene) {
  if (extractRing) scene.remove(extractRing);
  const geo = new THREE.RingGeometry(0.35, 0.45, 24);
  const mat = new THREE.MeshBasicMaterial({
    color: 0x00ff41, transparent: true, opacity: 0.6,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  });
  extractRing = new THREE.Mesh(geo, mat);
  extractRing.rotation.x = -Math.PI / 2;
  extractRing.position.set(x, 0.02, y);
  scene.add(extractRing);
}

export function updateExtractRing(time) {
  if (!extractRing) return;
  extractRing.material.opacity = 0.3 + Math.sin(time * 3) * 0.3;
  extractRing.scale.setScalar(1 + Math.sin(time * 2) * 0.12);
}

// Scale extract ring based on extraction progress (0-1)
export function updateExtractProgress(progress) {
  if (!extractRing) return;
  const p = Math.max(0, Math.min(1, progress));
  // Ring grows and brightens as extraction progresses
  extractRing.scale.setScalar(0.5 + p * 1.0);
  extractRing.material.opacity = 0.2 + p * 0.7;
}

export function clearAllParticles(scene) {
  for (const s of wallSplats) { scene.remove(s); s.material.dispose(); }
  wallSplats.length = 0;
  if (fogPoints) { scene.remove(fogPoints); fogPoints.geometry.dispose(); fogPoints.material.dispose(); fogPoints = null; }
  if (groundMistPoints) { scene.remove(groundMistPoints); groundMistPoints.geometry.dispose(); groundMistPoints.material.dispose(); groundMistPoints = null; }
  for (const p of eventParticles) {
    scene.remove(p.mesh); p.mesh.geometry.dispose(); p.mesh.material.dispose();
  }
  eventParticles.length = 0;
  if (extractRing) { scene.remove(extractRing); extractRing = null; }
  // Dust motes persist across floors (they follow player)
}

export function getParticleCount() {
  return eventParticles.length;
}
