// LABYRINTH 3D — Convert 2D tile grid to 3D geometry
// Full environment: walls, floors, ceilings, doors, torches, clutter, trim
import * as THREE from 'three';
import { T_WALL, T_FLOOR, T_CORRIDOR, T_DOOR, T_STAIRS, BIOMES } from './dungeon-gen.js';

const WALL_H = 1.6;
const CELL = 1;

// ─── Gradient Map (4-step cel-shading ramp) ───
let gradientMap = null;
function createGradientMap() {
  if (gradientMap) return gradientMap;
  const c = document.createElement('canvas');
  c.width = 4; c.height = 1;
  const ctx = c.getContext('2d');
  // 4 discrete light bands: deep shadow → shadow → midtone → highlight
  [51, 115, 185, 255].forEach((v, i) => {
    ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.fillRect(i, 0, 1, 1);
  });
  const tex = new THREE.CanvasTexture(c);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  gradientMap = tex;
  return tex;
}

// ─── Texture Loader ───
const loader = new THREE.TextureLoader();
const textures = {};
let texturesLoaded = false;

export function loadDungeonTextures() {
  const base = 'assets/';
  const toLoad = {
    wall: 'wall-stone.png',
    floor: 'floor-tile.png',
    ceiling: 'ceiling-plank.png',
    door: 'door-iron.png',
    noise: 'noise.png',
    flame: 'sprite-flame.png',
  };
  for (const [key, file] of Object.entries(toLoad)) {
    const tex = loader.load(base + file);
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.wrapS = THREE.RepeatWrapping;
    tex.wrapT = THREE.RepeatWrapping;
    tex.generateMipmaps = true;
    // Scale textures to tile nicely on geometry
    if (key === 'wall') { tex.repeat.set(1, WALL_H); }
    if (key === 'floor') { tex.repeat.set(1, 1); }
    if (key === 'ceiling') { tex.repeat.set(1, 1); }
    textures[key] = tex;
  }
  texturesLoaded = true;
  // Force rebuild so materials pick up textures
  biomeMatsBuilt = false;
}

// ─── Biome Materials (MeshPhongMaterial — smooth per-pixel lighting, RuneScape-era look) ───
function makeMats(biome) {
  const wall = new THREE.Color(biome.wall);
  const wallD = new THREE.Color(biome.wallDark);
  const wallL = new THREE.Color(biome.wallLight);
  const floor = new THREE.Color(biome.floor).multiplyScalar(1.8);
  const floorAlt = new THREE.Color(biome.floorAlt).multiplyScalar(1.8);
  const wire = new THREE.Color(biome.wire);
  const ceil = new THREE.Color(biome.wallDark).multiplyScalar(0.7);

  // Smooth Phong material with subtle specular + biome emissive glow
  const wireGlow = wire.clone().multiplyScalar(0.18);
  function phong(color, opts = {}) {
    return new THREE.MeshPhongMaterial({
      color,
      map: opts.map || null,
      side: opts.side || THREE.FrontSide,
      shininess: opts.shininess ?? 10,
      specular: new THREE.Color(0x1a1a1a),
      emissive: opts.emissive || new THREE.Color(0x000000),
      emissiveIntensity: opts.emissiveIntensity ?? 0,
    });
  }

  const wallMap = texturesLoaded ? textures.wall : null;
  const floorMap = texturesLoaded ? textures.floor : null;
  const ceilMap = texturesLoaded ? textures.ceiling : null;
  const doorMap = texturesLoaded ? textures.door : null;
  const noiseMap = texturesLoaded ? textures.noise : null;

  return {
    wall: phong(wall, { map: wallMap, emissive: wireGlow, emissiveIntensity: 0.25 }),
    wallDark: phong(wallD, { map: wallMap, emissive: wireGlow, emissiveIntensity: 0.18 }),
    wallLight: phong(wallL, { map: wallMap, emissive: wireGlow, emissiveIntensity: 0.3 }),
    floor: phong(floor, { map: floorMap, side: THREE.DoubleSide, emissive: wireGlow, emissiveIntensity: 0.12 }),
    floorAlt: phong(floorAlt, { map: floorMap, side: THREE.DoubleSide, emissive: wireGlow, emissiveIntensity: 0.1 }),
    ceiling: phong(ceil, { map: ceilMap, side: THREE.DoubleSide }),
    trim: new THREE.MeshPhongMaterial({ color: 0x000000, emissive: wire.clone().multiplyScalar(0.3), emissiveIntensity: 1.0, transparent: true, opacity: 0.5, fog: true }),
    doorFrame: phong(wallL, { map: doorMap, shininess: 20, emissive: wireGlow, emissiveIntensity: 0.15 }),
    doorBars: new THREE.MeshPhongMaterial({ color: wire.clone().multiplyScalar(0.6), shininess: 30, specular: new THREE.Color(0x333333), emissive: wire, emissiveIntensity: 0.1 }),
    stairs: new THREE.MeshPhongMaterial({ color: wire, emissive: wire, emissiveIntensity: 0.5, shininess: 25 }),
    stairsRing: new THREE.MeshBasicMaterial({ color: wire, transparent: true, opacity: 0.6, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }),
    torchPost: phong(0x554433, { map: noiseMap }),
    torchFlame: new THREE.MeshBasicMaterial({ color: wire, transparent: true, opacity: 0.95, map: texturesLoaded ? textures.flame : null }),
    crate: phong(0x665533, { map: noiseMap, emissive: wireGlow, emissiveIntensity: 0.05 }),
    barrel: phong(0x553322, { map: noiseMap, emissive: wireGlow, emissiveIntensity: 0.05 }),
    rubble: phong(wallD),
    pillar: phong(wallL, { map: wallMap, shininess: 15, emissive: wireGlow, emissiveIntensity: 0.1 }),
    wireColor: wire,
    biome: biome,
  };
}

const biomeMats = {};
let biomeMatsBuilt = false;

function ensureBiomeMats() {
  if (biomeMatsBuilt) return;
  for (const [k, b] of Object.entries(BIOMES)) biomeMats[k] = makeMats(b);
  biomeMatsBuilt = true;
}

export function rebuildBiomeMaterials() {
  biomeMatsBuilt = false;
  ensureBiomeMats();
}

export function getBiomeMaterials(mood) {
  ensureBiomeMats();
  return biomeMats[mood] || biomeMats.processing;
}

// ─── Shared Geometries (created once) ───
const geoCache = {};
function getGeo(key, factory) {
  if (!geoCache[key]) geoCache[key] = factory();
  return geoCache[key];
}

// ─── Main Build ───
export function buildDungeonMesh(level, mood) {
  const { tiles, w, h, stairs, rooms, torches } = level;
  const mats = getBiomeMaterials(mood);
  const group = new THREE.Group();

  // ── 1. Walls (InstancedMesh) ──
  const wallGeo = getGeo('wall', () => new THREE.BoxGeometry(CELL, WALL_H, CELL));
  let wallCount = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (tiles[y][x] === T_WALL) wallCount++;

  const wallMesh = new THREE.InstancedMesh(wallGeo, mats.wall, wallCount);
  const m4 = new THREE.Matrix4();
  let wi = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (tiles[y][x] !== T_WALL) continue;
      m4.makeTranslation(x, WALL_H / 2, y);
      wallMesh.setMatrixAt(wi, m4);
      // Color variation: edge walls darker, interior lighter
      const isOuter = x === 0 || y === 0 || x === w - 1 || y === h - 1;
      const adjFloor = !isOuter && ((tiles[y-1]?.[x] > 0) || (tiles[y+1]?.[x] > 0) || (tiles[y]?.[x-1] > 0) || (tiles[y]?.[x+1] > 0));
      const c = isOuter ? new THREE.Color(mats.wallDark.color) : adjFloor ? new THREE.Color(mats.wallLight.color) : new THREE.Color(mats.wall.color);
      // Slight random variation
      c.offsetHSL(0, 0, (Math.random() - 0.5) * 0.03);
      wallMesh.setColorAt(wi, c);
      wi++;
    }
  }
  wallMesh.instanceMatrix.needsUpdate = true;
  if (wallMesh.instanceColor) wallMesh.instanceColor.needsUpdate = true;
  group.add(wallMesh);

  // ── 2. Floors (InstancedMesh with checkerboard) ──
  const floorGeo = getGeo('floor', () => new THREE.PlaneGeometry(CELL, CELL));
  let floorCount = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (tiles[y][x] !== T_WALL) floorCount++;

  const floorRot = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
  const floorMesh = new THREE.InstancedMesh(floorGeo, mats.floor, floorCount);
  const floorColors = new Float32Array(floorCount * 3);
  const fCol = new THREE.Color(mats.floor.color);
  const fAlt = new THREE.Color(mats.floorAlt.color);
  let fi = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (tiles[y][x] === T_WALL) continue;
      m4.compose(new THREE.Vector3(x, 0.001, y), floorRot, new THREE.Vector3(1, 1, 1));
      floorMesh.setMatrixAt(fi, m4);
      const c = (x + y) % 2 === 0 ? fCol : fAlt;
      floorColors[fi * 3] = c.r; floorColors[fi * 3 + 1] = c.g; floorColors[fi * 3 + 2] = c.b;
      fi++;
    }
  }
  floorMesh.instanceColor = new THREE.InstancedBufferAttribute(floorColors, 3);
  floorMesh.instanceMatrix.needsUpdate = true;
  group.add(floorMesh);

  // ── 3. Ceiling ──
  const ceilRot = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2);
  const ceilMesh = new THREE.InstancedMesh(floorGeo, mats.ceiling, floorCount);
  const ceilCol = new THREE.Color(mats.ceiling.color);
  let ci = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (tiles[y][x] === T_WALL) continue;
      m4.compose(new THREE.Vector3(x, WALL_H, y), ceilRot, new THREE.Vector3(1, 1, 1));
      ceilMesh.setMatrixAt(ci, m4);
      ci++;
    }
  }
  ceilMesh.instanceMatrix.needsUpdate = true;
  group.add(ceilMesh);

  // ── 4. Wall Trim (emissive strips at base of walls facing corridors) ──
  const trimGeo = getGeo('trim', () => new THREE.PlaneGeometry(CELL, 0.03));
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      if (tiles[y][x] !== T_WALL) continue;
      // Check each face for adjacent floor
      const faces = [
        { cond: tiles[y - 1]?.[x] > 0, pos: [x, 0.03, y - 0.499], rot: [0, 0, 0] },
        { cond: tiles[y + 1]?.[x] > 0, pos: [x, 0.03, y + 0.499], rot: [0, Math.PI, 0] },
        { cond: tiles[y]?.[x - 1] > 0, pos: [x - 0.499, 0.03, y], rot: [0, Math.PI / 2, 0] },
        { cond: tiles[y]?.[x + 1] > 0, pos: [x + 0.499, 0.03, y], rot: [0, -Math.PI / 2, 0] },
      ];
      for (const f of faces) {
        if (!f.cond) continue;
        const trim = new THREE.Mesh(trimGeo, mats.trim);
        trim.position.set(...f.pos);
        trim.rotation.set(...f.rot);
        group.add(trim);
      }
    }
  }

  // ── 5. Door Archways with Real Door Panels ──
  const pillarGeo = getGeo('doorPillar', () => new THREE.BoxGeometry(0.15, WALL_H * 0.85, 0.15));
  const lintelGeo = getGeo('lintel', () => new THREE.BoxGeometry(0.15, 0.12, CELL * 0.9));
  // Door panel — solid slab that fills the doorway
  const doorPanelNS = getGeo('doorPanelNS', () => new THREE.BoxGeometry(0.65, WALL_H * 0.78, 0.06));
  const doorPanelEW = getGeo('doorPanelEW', () => new THREE.BoxGeometry(0.06, WALL_H * 0.78, 0.65));
  // Door handle — small knob
  const handleGeo = getGeo('doorHandle', () => new THREE.BoxGeometry(0.04, 0.06, 0.08));
  // Iron bands across door (horizontal reinforcement strips)
  const bandNS = getGeo('doorBandNS', () => new THREE.BoxGeometry(0.62, 0.04, 0.07));
  const bandEW = getGeo('doorBandEW', () => new THREE.BoxGeometry(0.07, 0.04, 0.62));

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (tiles[y][x] !== T_DOOR) continue;
      // Determine door orientation (N-S corridor or E-W)
      const nsCorr = (tiles[y - 1]?.[x] > 0 && tiles[y + 1]?.[x] > 0);

      // Left pillar
      const lp = new THREE.Mesh(pillarGeo, mats.doorFrame);
      // Right pillar
      const rp = new THREE.Mesh(pillarGeo, mats.doorFrame);
      // Lintel
      const lt = new THREE.Mesh(lintelGeo, mats.doorFrame);

      if (nsCorr) {
        lp.position.set(x - 0.4, WALL_H * 0.425, y);
        rp.position.set(x + 0.4, WALL_H * 0.425, y);
        lt.position.set(x, WALL_H * 0.85, y);
        lt.rotation.y = 0;
      } else {
        lp.position.set(x, WALL_H * 0.425, y - 0.4);
        rp.position.set(x, WALL_H * 0.425, y + 0.4);
        lt.position.set(x, WALL_H * 0.85, y);
        lt.rotation.y = Math.PI / 2;
      }
      group.add(lp, rp, lt);

      // Solid door panel (textured with door-iron.png)
      const panel = new THREE.Mesh(nsCorr ? doorPanelNS : doorPanelEW, mats.doorFrame);
      panel.position.set(x, WALL_H * 0.40, y);
      group.add(panel);

      // Iron reinforcement bands (3 horizontal strips across door)
      const bandMat = mats.doorBars;
      for (let b = 0; b < 3; b++) {
        const band = new THREE.Mesh(nsCorr ? bandNS : bandEW, bandMat);
        band.position.set(x, 0.2 + b * 0.4, y);
        group.add(band);
      }

      // Door handle
      const handle = new THREE.Mesh(handleGeo, mats.doorBars);
      if (nsCorr) {
        handle.position.set(x + 0.2, WALL_H * 0.38, y + 0.04);
      } else {
        handle.position.set(x + 0.04, WALL_H * 0.38, y + 0.2);
      }
      group.add(handle);
    }
  }

  // ── 6. Stairs (stepped platform + glowing ring) ──
  if (stairs) {
    const stairGeo = getGeo('stairs', () => new THREE.BoxGeometry(0.8, 0.08, 0.8));
    for (let i = 0; i < 3; i++) {
      const step = new THREE.Mesh(stairGeo, mats.stairs);
      step.position.set(stairs.x, 0.04 + i * 0.08, stairs.y);
      step.scale.setScalar(1 - i * 0.15);
      group.add(step);
    }
    // Pulsing ring
    const ringGeo = getGeo('stairRing', () => new THREE.RingGeometry(0.35, 0.42, 24));
    const ring = new THREE.Mesh(ringGeo, mats.stairsRing);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(stairs.x, 0.01, stairs.y);
    ring.userData.isExtractRing = true;
    group.add(ring);
    // Second ring for depth
    const ring2 = new THREE.Mesh(getGeo('stairRing2', () => new THREE.RingGeometry(0.5, 0.54, 24)), mats.stairsRing.clone());
    ring2.material.opacity = 0.25;
    ring2.rotation.x = -Math.PI / 2;
    ring2.position.set(stairs.x, 0.005, stairs.y);
    ring2.userData.isExtractRing2 = true;
    group.add(ring2);
  }

  // ── 7. Torch Geometry (post + flame orb) ──
  const torchPostGeo = getGeo('torchPost', () => new THREE.CylinderGeometry(0.025, 0.035, 0.6, 6));
  const torchBracketGeo = getGeo('torchBracket', () => new THREE.BoxGeometry(0.18, 0.04, 0.04));
  const flameGeo = getGeo('flame', () => new THREE.SphereGeometry(0.06, 8, 6));

  const torchMeshes = [];
  const maxTorchGeo = 16;
  let torchCount = 0;
  for (const t of torches) {
    if (torchCount >= maxTorchGeo) break;
    // Find which wall face to attach to
    if (t.x <= 0 || t.y <= 0 || t.x >= w - 1 || t.y >= h - 1) continue;
    // Find adjacent wall
    let wx = t.x, wy = t.y, fx = 0, fz = 0;
    if (tiles[t.y]?.[t.x - 1] === T_WALL) { wx = t.x - 0.42; fx = 0; fz = 0; }
    else if (tiles[t.y]?.[t.x + 1] === T_WALL) { wx = t.x + 0.42; fx = 0; fz = 0; }
    else if (tiles[t.y - 1]?.[t.x] === T_WALL) { wy = t.y - 0.42; fx = 0; fz = 0; }
    else if (tiles[t.y + 1]?.[t.x] === T_WALL) { wy = t.y + 0.42; fx = 0; fz = 0; }
    else continue;

    // Post
    const post = new THREE.Mesh(torchPostGeo, mats.torchPost);
    post.position.set(wx, 0.9, wy);
    group.add(post);

    // Bracket
    const bracket = new THREE.Mesh(torchBracketGeo, mats.torchPost);
    bracket.position.set(wx, 1.18, wy);
    group.add(bracket);

    // Flame orb (bright emissive)
    const flame = new THREE.Mesh(flameGeo, mats.torchFlame.clone());
    flame.position.set(wx, 1.25, wy);
    flame.userData.isTorchFlame = true;
    group.add(flame);
    torchMeshes.push(flame);

    torchCount++;
  }

  // ── 8. Environmental Clutter ──
  const crateGeo = getGeo('crate', () => new THREE.BoxGeometry(0.25, 0.25, 0.25));
  const barrelGeo = getGeo('barrel', () => new THREE.CylinderGeometry(0.12, 0.14, 0.35, 8));
  const rubbleGeo = getGeo('rubble', () => new THREE.DodecahedronGeometry(0.1, 0));
  const pillarGeoFull = getGeo('pillarFull', () => new THREE.CylinderGeometry(0.1, 0.12, WALL_H, 8));
  const pillarCapGeo = getGeo('pillarCap', () => new THREE.CylinderGeometry(0.14, 0.14, 0.06, 8));

  for (const room of rooms) {
    // Pillars in large rooms (corners)
    if (room.w >= 6 && room.h >= 6 && Math.random() < 0.6) {
      const corners = [
        [room.x + 1, room.y + 1],
        [room.x + room.w - 2, room.y + 1],
        [room.x + 1, room.y + room.h - 2],
        [room.x + room.w - 2, room.y + room.h - 2],
      ];
      for (const [px, py] of corners) {
        if (tiles[py]?.[px] !== T_FLOOR) continue;
        const pil = new THREE.Mesh(pillarGeoFull, mats.pillar);
        pil.position.set(px, WALL_H / 2, py);
        group.add(pil);
        // Cap on top
        const cap = new THREE.Mesh(pillarCapGeo, mats.pillar);
        cap.position.set(px, WALL_H - 0.03, py);
        group.add(cap);
        // Base
        const base = new THREE.Mesh(pillarCapGeo, mats.pillar);
        base.position.set(px, 0.03, py);
        group.add(base);
      }
    }

    // Crates and barrels along walls
    if (Math.random() < 0.5) {
      const cx = room.x + 1 + Math.floor(Math.random() * Math.max(1, room.w - 2));
      const cy = room.y + 1;
      if (tiles[cy]?.[cx] === T_FLOOR) {
        const crate = new THREE.Mesh(crateGeo, mats.crate);
        crate.position.set(cx - 0.3, 0.125, cy - 0.3);
        crate.rotation.y = Math.random() * 0.3;
        group.add(crate);
        if (Math.random() < 0.5) {
          const crate2 = new THREE.Mesh(crateGeo, mats.crate);
          crate2.position.set(cx - 0.1, 0.125, cy - 0.35);
          crate2.rotation.y = Math.random() * 0.5;
          group.add(crate2);
        }
      }
    }

    if (Math.random() < 0.4) {
      const bx = room.x + room.w - 2;
      const by = room.y + 1 + Math.floor(Math.random() * Math.max(1, room.h - 2));
      if (tiles[by]?.[bx] === T_FLOOR) {
        const barrel = new THREE.Mesh(barrelGeo, mats.barrel);
        barrel.position.set(bx + 0.3, 0.175, by);
        group.add(barrel);
      }
    }

    // Rubble scattered
    if (Math.random() < 0.3) {
      for (let r = 0; r < 3 + Math.floor(Math.random() * 4); r++) {
        const rx = room.x + Math.random() * room.w;
        const ry = room.y + Math.random() * room.h;
        const rub = new THREE.Mesh(rubbleGeo, mats.rubble);
        rub.position.set(rx, 0.05 + Math.random() * 0.03, ry);
        rub.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0);
        rub.scale.setScalar(0.5 + Math.random() * 1.0);
        group.add(rub);
      }
    }
  }

  // ── 9. Corridor wall grooves (horizontal lines on walls facing corridors) ──
  const grooveGeo = getGeo('groove', () => new THREE.PlaneGeometry(CELL, 0.02));
  const grooveMat = new THREE.MeshLambertMaterial({ color: mats.wireColor.clone().multiplyScalar(0.2), side: THREE.DoubleSide });
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      if (tiles[y][x] !== T_WALL) continue;
      // Only walls adjacent to corridors get grooves
      const adjCorridor = tiles[y - 1]?.[x] === T_CORRIDOR || tiles[y + 1]?.[x] === T_CORRIDOR ||
                          tiles[y]?.[x - 1] === T_CORRIDOR || tiles[y]?.[x + 1] === T_CORRIDOR;
      if (!adjCorridor || Math.random() > 0.4) continue;

      for (let gh = 0; gh < 3; gh++) {
        const groove = new THREE.Mesh(grooveGeo, grooveMat);
        const gy = 0.3 + gh * 0.4;
        // Determine face
        if (tiles[y - 1]?.[x] === T_CORRIDOR) {
          groove.position.set(x, gy, y - 0.498);
        } else if (tiles[y + 1]?.[x] === T_CORRIDOR) {
          groove.position.set(x, gy, y + 0.498);
          groove.rotation.y = Math.PI;
        } else if (tiles[y]?.[x - 1] === T_CORRIDOR) {
          groove.position.set(x - 0.498, gy, y);
          groove.rotation.y = Math.PI / 2;
        } else {
          groove.position.set(x + 0.498, gy, y);
          groove.rotation.y = -Math.PI / 2;
        }
        group.add(groove);
      }
    }
  }

  // Store references
  group.userData.wallMesh = wallMesh;
  group.userData.floorMesh = floorMesh;
  group.userData.ceilMesh = ceilMesh;
  group.userData.materials = mats;
  group.userData.torchMeshes = torchMeshes;

  return group;
}

// Update torch flame animation
export function updateTorchFlames(dungeonGroup, time) {
  if (!dungeonGroup?.userData?.torchMeshes) return;
  for (let i = 0; i < dungeonGroup.userData.torchMeshes.length; i++) {
    const flame = dungeonGroup.userData.torchMeshes[i];
    // Flicker scale and position
    const flicker = 0.8 + Math.sin(time * 8 + i * 3.7) * 0.2 + Math.sin(time * 13 + i * 1.1) * 0.1;
    flame.scale.setScalar(flicker);
    flame.position.y = 1.25 + Math.sin(time * 6 + i * 2.1) * 0.02;
  }
}

// Lerp biome materials (color + emissive for smooth biome transitions)
export function lerpBiomeMaterials(dungeonGroup, targetMood, t) {
  const current = dungeonGroup.userData.materials;
  const target = getBiomeMaterials(targetMood);
  if (!current || !target) return;
  current.wall.color.lerp(new THREE.Color(target.wall.color), t);
  current.wallDark.color.lerp(new THREE.Color(target.wallDark.color), t);
  current.floor.color.lerp(new THREE.Color(target.floor.color), t);
  current.floorAlt.color.lerp(new THREE.Color(target.floorAlt.color), t);
  current.ceiling.color.lerp(new THREE.Color(target.ceiling.color), t);
  // Lerp emissive glow to match new biome
  if (current.wall.emissive && target.wall.emissive) {
    current.wall.emissive.lerp(new THREE.Color(target.wall.emissive), t);
    current.wallDark.emissive.lerp(new THREE.Color(target.wallDark.emissive), t);
    current.wallLight.emissive.lerp(new THREE.Color(target.wallLight.emissive), t);
    current.floor.emissive.lerp(new THREE.Color(target.floor.emissive), t);
  }
}
