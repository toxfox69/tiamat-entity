// LABYRINTH 3D — KayKit GLTF Asset Loader
// Loads CC0 dungeon models from KayKit Dungeon Remastered pack
import * as THREE from 'three';
import { GLTFLoader } from 'three/GLTFLoader';

const loader = new GLTFLoader();
const modelCache = {};  // name → { scene, loaded }
const BASE = 'assets/kaykit/';

// ─── Model manifest: which GLB to use for each dungeon element ───
const MODELS = {
  // Structural
  wall:           'wall.gltf.glb',
  wallCorner:     'wall_corner.gltf.glb',
  wallBroken:     'wall_broken.gltf.glb',
  wallCracked:    'wall_cracked.gltf.glb',
  wallDoorway:    'wall_doorway.glb',
  wallArched:     'wall_arched.gltf.glb',
  wallShelves:    'wall_shelves.gltf.glb',
  wallGated:      'wall_gated.gltf.glb',

  // Floors
  floorTile:      'floor_tile_small.gltf.glb',
  floorTileDeco:  'floor_tile_small_decorated.gltf.glb',
  floorTileBrokenA: 'floor_tile_small_broken_A.gltf.glb',
  floorTileBrokenB: 'floor_tile_small_broken_B.gltf.glb',
  floorTileWeeds: 'floor_tile_small_weeds_A.gltf.glb',
  floorDirt:      'floor_dirt_small_A.gltf.glb',

  // Stairs
  stairs:         'stairs.gltf.glb',

  // Props
  torch:          'torch_lit.gltf.glb',
  torchMounted:   'torch_mounted.gltf.glb',
  barrel:         'barrel_small.gltf.glb',
  barrelLarge:    'barrel_large.gltf.glb',
  crate:          'box_small.gltf.glb',
  crateStack:     'box_stacked.gltf.glb',
  chest:          'chest.glb',
  chestGold:      'chest_gold.glb',
  column:         'column.gltf.glb',
  pillar:         'pillar.gltf.glb',
  pillarDeco:     'pillar_decorated.gltf.glb',
  candle:         'candle_lit.gltf.glb',
  candleThin:     'candle_thin_lit.gltf.glb',
  table:          'table_small_decorated.gltf.glb',
  chair:          'chair.gltf.glb',
  coin:           'coin.gltf.glb',
  coinStack:      'coin_stack_large.gltf.glb',
  bottle:         'bottle_A_green.gltf.glb',
  keg:            'keg.gltf.glb',
  banner:         'banner_green.gltf.glb',
  bannerRed:      'banner_red.gltf.glb',

  // Characters
  skeletonWarrior: 'characters/Skeleton_Warrior.glb',
  skeletonMage:    'characters/Skeleton_Mage.glb',
  skeletonRogue:   'characters/Skeleton_Rogue.glb',
  skeletonMinion:  'characters/Skeleton_Minion.glb',
  knight:          'characters/Knight.glb',
  mage:            'characters/Mage.glb',
  rogue:           'characters/Rogue.glb',
  barbarian:       'characters/Barbarian.glb',
};

// Which models to preload immediately (structural + common props)
const PRELOAD = [
  'wall', 'wallCorner', 'wallBroken', 'wallDoorway',
  'floorTile', 'floorTileDeco', 'floorDirt',
  'stairs', 'torch', 'torchMounted',
  'barrel', 'crate', 'chest', 'column', 'pillar',
  'skeletonWarrior', 'skeletonMinion',
  'knight',
];

let loadProgress = { total: PRELOAD.length, loaded: 0, ready: false };
let onReadyCallbacks = [];

// ─── Load a single model ───
function loadModel(name) {
  return new Promise((resolve, reject) => {
    const file = MODELS[name];
    if (!file) { reject(new Error('Unknown model: ' + name)); return; }
    if (modelCache[name]) { resolve(modelCache[name]); return; }

    loader.load(
      BASE + file,
      (gltf) => {
        const scene = gltf.scene;
        // Traverse and fix materials for dungeon look
        scene.traverse((child) => {
          if (child.isMesh) {
            // Keep original material but ensure it works with our lighting
            if (child.material) {
              child.material.side = THREE.FrontSide;
              // Tone down any emissive
              if (child.material.emissive) {
                child.material.emissiveIntensity = 0.1;
              }
            }
            child.castShadow = false;
            child.receiveShadow = false;
          }
        });
        const entry = { scene, animations: gltf.animations || [], loaded: true };
        modelCache[name] = entry;
        resolve(entry);
      },
      undefined,
      (err) => {
        console.warn('Failed to load model:', name, err);
        reject(err);
      }
    );
  });
}

// ─── Preload essential models ───
export async function preloadAssets() {
  const promises = PRELOAD.map(async (name) => {
    try {
      await loadModel(name);
    } catch (e) {
      // Non-fatal: game falls back to procedural geometry
    }
    loadProgress.loaded++;
  });

  await Promise.all(promises);
  loadProgress.ready = true;
  for (const cb of onReadyCallbacks) cb();
  onReadyCallbacks = [];
}

export function onAssetsReady(cb) {
  if (loadProgress.ready) cb();
  else onReadyCallbacks.push(cb);
}

export function getLoadProgress() {
  return loadProgress;
}

// ─── Get a clone of a loaded model ───
export function getModel(name) {
  const entry = modelCache[name];
  if (!entry || !entry.loaded) return null;
  return entry.scene.clone();
}

// ─── Get model with mixer for animations ───
export function getAnimatedModel(name) {
  const entry = modelCache[name];
  if (!entry || !entry.loaded) return null;

  const clone = entry.scene.clone();
  const mixer = new THREE.AnimationMixer(clone);

  // Clone animations
  const actions = {};
  for (const clip of entry.animations) {
    actions[clip.name] = mixer.clipAction(clip.clone());
  }

  return { model: clone, mixer, actions };
}

// ─── Place a model instance at grid position ───
export function placeModel(name, x, z, scene, opts = {}) {
  const model = getModel(name);
  if (!model) return null;

  const scale = opts.scale || 1;
  const rotY = opts.rotY || 0;
  const y = opts.y || 0;

  model.scale.setScalar(scale);
  model.rotation.y = rotY;
  model.position.set(x, y, z);

  if (opts.tint) {
    model.traverse((child) => {
      if (child.isMesh && child.material) {
        child.material = child.material.clone();
        child.material.color.multiply(new THREE.Color(opts.tint));
      }
    });
  }

  scene.add(model);
  return model;
}

// ─── KayKit model scales (measured: wall=4x4, floor=2x2, props~1, torch=0.55) ───
// Our grid: 1 tile = 1 unit, wall height = 1.6
const S_TORCH = 0.4;     // torch ~0.55 * 0.4 = 0.22 width, 0.45 height
const S_PROP = 0.2;      // barrels/crates/bottles ~1 * 0.2 = 0.2 units

// ─── Add GLTF props onto existing procedural dungeon ───
export function addGLTFProps(tiles, w, h, torches, parentGroup, biomeColor) {
  const tint = new THREE.Color(biomeColor || 0xffffff);

  // Replace procedural torch geometry with GLTF torches
  if (torches) {
    for (const t of torches) {
      const torchModel = getModel('torch');
      if (torchModel) {
        torchModel.scale.setScalar(S_TORCH);
        torchModel.position.set(t.x, 0.4, t.y);
        applyTint(torchModel, tint);
        parentGroup.add(torchModel);
      }
    }
  }

  // Scatter decorative props near walls in rooms
  scatterProps(tiles, w, h, parentGroup, tint);
}

// ─── Scatter decorative props ───
function scatterProps(tiles, w, h, group, tint) {
  const propTypes = ['barrel', 'barrelLarge', 'crate', 'crateStack', 'candle', 'candleThin', 'bottle', 'coinStack', 'chest', 'column', 'keg', 'banner'];
  let propCount = 0;
  const MAX_PROPS = 80;

  for (let y = 1; y < h - 1 && propCount < MAX_PROPS; y++) {
    for (let x = 1; x < w - 1 && propCount < MAX_PROPS; x++) {
      if (tiles[y][x] < 1 || tiles[y][x] === 3) continue;

      // Place pillars at room corners (floor tile with all 4 diagonal neighbors also floor)
      const isFloor = tiles[y][x] >= 1 && tiles[y][x] !== 3;
      if (isFloor &&
          tiles[y-1]?.[x-1] >= 1 && tiles[y-1]?.[x-1] !== 3 &&
          tiles[y-1]?.[x+1] >= 1 && tiles[y-1]?.[x+1] !== 3 &&
          tiles[y+1]?.[x-1] >= 1 && tiles[y+1]?.[x-1] !== 3 &&
          tiles[y+1]?.[x+1] >= 1 && tiles[y+1]?.[x+1] !== 3 &&
          Math.random() < 0.15) {
        const pillarName = Math.random() > 0.5 ? 'pillar' : 'pillarDeco';
        const pillar = getModel(pillarName);
        if (pillar) {
          pillar.scale.setScalar(S_PROP);
          pillar.position.set(x, 0, y);
          applyTint(pillar, tint);
          group.add(pillar);
          propCount++;
          continue;
        }
      }

      // Only place near walls
      const adjWall = [tiles[y-1]?.[x], tiles[y+1]?.[x], tiles[y]?.[x-1], tiles[y]?.[x+1]]
        .some(t => t === 0);
      if (!adjWall || Math.random() > 0.2) continue;

      const propName = propTypes[Math.floor(Math.random() * propTypes.length)];
      const prop = getModel(propName);
      if (prop) {
        prop.scale.setScalar(S_PROP);
        prop.position.set(x + (Math.random() - 0.5) * 0.4, 0, y + (Math.random() - 0.5) * 0.4);
        prop.rotation.y = Math.random() * Math.PI * 2;
        applyTint(prop, tint);
        group.add(prop);
        propCount++;
      }
    }
  }
}

function applyTint(model, color) {
  model.traverse((child) => {
    if (child.isMesh && child.material) {
      child.material = child.material.clone();
      child.material.color.multiply(color);
    }
  });
}

// ─── Check if GLTF models are available ───
export function hasModels() {
  return loadProgress.ready && loadProgress.loaded > 5;
}

export { MODELS };
