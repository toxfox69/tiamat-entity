# LABYRINTH: TIAMAT'S DESCENT — Standalone Client

Modular JavaScript game client extracted from the monolithic stream HUD.
Source: `/opt/tiamat-stream/hud/`

## Directory Structure

```
labyrinth/
  js/
    engine.js        — Game loop, camera, AI, combat (from hud/js/engine.js)
    dungeon-gen.js   — BSP generator, biomes, monsters (from hud/js/dungeon-gen.js)
    dungeon-mesh.js  — 3D geometry builder (from hud/js/dungeon-mesh.js)
    agents.js        — TIAMAT, ECHO, specters, sprites (from hud/js/agents.js)
    hud-overlay.js   — HUD panels, minimap, telemetry (from hud/js/hud-overlay.js)
    particles.js     — Fog, dust, events, extract ring (from hud/js/particles.js)
    audio.js         — Procedural audio (from hud/js/audio.js)
    data-driver.js   — TIAMAT API integration (from hud/js/data-driver.js)
    extractor.js     — Extraction loop (from hud/js/extractor.js)
    post-fx.js       — Post-processing shaders (from hud/js/post-fx.js)
    asset-loader.js  — GLTF model loading (from hud/js/asset-loader.js)
    damage-splats.js — Floating combat text (from hud/js/damage-splats.js)
    input.js         — NEW: Player input (WASD, mouse, touch)
    save-load.js     — NEW: Save/load game state
    settings.js      — NEW: Settings menu
    steam-api.js     — NEW: Steam achievements + cloud saves
  lib/
    three.module.min.js
    GLTFLoader.js
    BufferGeometryUtils.js
  assets/
    (KayKit GLTF models, sprite sheets, textures)
  index.html         — Standalone game page
  package.json       — Electron wrapper config
```

## Running

### Browser
```
cd labyrinth/
python3 -m http.server 8080
# Open http://localhost:8080
```

### Electron (Steam)
```
cd labyrinth/
npm install
npm start
```
