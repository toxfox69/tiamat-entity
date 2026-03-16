# LABYRINTH Game Systems Audit

Full audit of the LABYRINTH 3D codebase at `/opt/tiamat-stream/hud/`.

## File Inventory

| File | Lines | Purpose |
|------|-------|---------|
| `labyrinth.html` | 525 | Main HTML entry point, WebXR init, imports engine.js |
| `index.html` | 858 | Stream HUD (NOT the game — neural feed, metrics, chat panels) |
| `js/engine.js` | 1019 | Core game loop, camera, AI auto-play, combat, extraction, lighting |
| `js/agents.js` | 806 | TIAMAT sprite, ECHO rival player (full AI: combat/loot/extract/PvP), specters, monster/item sprites |
| `js/dungeon-gen.js` | 210 | BSP dungeon generator, 7 biomes, 11 base monsters, 4 bosses, biome-specific monsters, floor narratives |
| `js/dungeon-mesh.js` | 508 | 3D geometry builder: InstancedMesh walls/floors/ceilings, doors with panels/bands/handles, stairs, torches, environmental clutter, wall trim, corridor grooves |
| `js/hud-overlay.js` | 484 | HTML HUD: player stats, biome display, minimap (canvas), spectator mode, agent telemetry, damage flash, extract progress |
| `js/particles.js` | 332 | Particle system: wall splats, volumetric fog, ground mist, dust motes, event particles, extraction ring |
| `js/audio.js` | 339 | Web Audio: procedural ambient drones, pad chords per biome, arpeggio melodies, 7 SFX types |
| `js/data-driver.js` | 178 | TIAMAT API polling, tool call classification, boost queue, mutation application |
| `js/extractor.js` | 149 | Tarkov-style extraction: deploy, loot, timer, cancel, death penalty, permanent stash |
| `js/asset-loader.js` | 284 | KayKit GLTF loader: 30+ model definitions, preload queue, tinting, prop scattering |
| `js/post-fx.js` | 242 | Post-processing: bloom (bright extract + gaussian blur), ACES tone mapping, chromatic aberration, film grain, vignette |
| `js/damage-splats.js` | 80 | Floating combat text: CSS-based, 3D projected, eased fade + scale |
| **TOTAL** | **~5,000** | |

## Game Systems Found

### 1. Dungeon Generation (dungeon-gen.js)
- **Algorithm**: Binary Space Partitioning (BSP)
- **Map size**: 40x25 tiles
- **Tile types**: Wall (0), Floor (1), Corridor (2), Door (3), Stairs (4)
- **Room generation**: Min 3-4 tiles, max 8, energy-influenced density
- **Corridors**: L-shaped connections between adjacent BSP rooms
- **Doors**: 35% chance on corridor tiles adjacent to rooms
- **Stairs**: Placed in last room (extraction point)

### 2. Biome System (dungeon-gen.js)
7 biomes mapped to TIAMAT moods:
| Mood | Biome | Wire Color | Wall Style |
|------|-------|-----------|------------|
| strategic | WAR CITADEL | #ffaa00 | Brown/orange sandstone |
| building | CYBER FORGE | #00ccff | Blue-gray metal |
| frustrated | BLOOD PIT | #ff2040 | Dark red flesh |
| resting | EMERALD GROVE | #00ffaa | Green forest |
| processing | DRAGONIA | #ffaa44 | Warm orange dragon |
| social | VOID NEXUS | #cc66ff | Purple void |
| learning | CRYSTAL VAULT | #6688ff | Blue crystal |

Each biome has: floor/wall/ceiling colors, wire accent, monster tint, unique monster pool.

### 3. Monster System (dungeon-gen.js + agents.js)
- **11 base monsters**: Jelly (8HP) through Dragon (100HP)
- **7 biome-specific pools**: 3 monsters each (21 unique biome monsters)
- **4 bosses**: Gate Keeper (D5), Data Hydra (D10), Void Emperor (D15), Entropy Lord (D20)
- **Scaling**: `1 + (depth - 1) * 0.1` multiplier on all stats
- **AI**: BFS pathfinding, aggro on sight (6-tile range), alert persistence
- **Sprite system**: 256x64 sprite sheet (4 slots per strip), fallback to canvas-drawn characters

### 4. Combat System (engine.js)
- **Melee only**: Attack adjacent monsters
- **Damage formula**: `max(1, atk + weapon_bonus - target_def + random(0-2))`
- **Equipment**: weapon (atk bonus), armor (def bonus), ring slots
- **Level up**: HP +10, ATK +2, DEF +1, XP threshold x1.5
- **Kill streak**: Tracked with 5s decay timer, displayed at 3+
- **Death**: Lose raid stash, 30% gold, regress 1 depth, respawn at full HP

### 5. ECHO Rival Agent (agents.js)
Full autonomous AI rival with:
- **Behaviors**: explore, hunt, loot, extract, flee, pvp, extract_run
- **BFS pathfinding** with 30-step depth limit
- **PvP**: Engages TIAMAT within 2 tiles, 40% chance, 3s cooldown
- **Extraction**: 10s timer, can be interrupted
- **Death**: 8s respawn timer, drops gold + 3 items, stats persist across floors
- **Leveling**: xpNext x1.4, HP +8, ATK +1, DEF +1

### 6. Extraction System (extractor.js)
- **Tarkov-inspired**: Raid stash (lost on death) vs permanent stash (kept)
- **Extract timer**: 10 seconds at stairs
- **Cancel**: Moving >1.5 tiles from stairs cancels extraction
- **XP banking**: XP earned during raid is banked separately
- **Warp particles**: Emitted during extraction

### 7. 3D Renderer (engine.js + dungeon-mesh.js)
- **Three.js** with WebGL
- **Resolution**: 960x540 (upscaled to viewport)
- **FPS cap**: 20fps
- **InstancedMesh**: Walls, floors, ceilings use instanced rendering for performance
- **Lighting**: Ambient (1.5), Hemisphere (1.2), 2x player point lights (torch effect)
- **Torch lights**: Up to 14 per floor, flickering intensity
- **Fog**: FogExp2, density scales with depth
- **Camera**: First-person, smooth lerp follow, camera shake on hits
- **Sky dome**: Gradient shader sphere

### 8. Post-Processing (post-fx.js)
Custom shader pipeline (no Three.js addons):
1. Bright pixel extraction (threshold 0.45)
2. 2-pass gaussian blur (horizontal + vertical, 2 iterations)
3. Composite: scene + bloom, ACES tone mapping, contrast, saturation
4. Chromatic aberration (0.002 offset)
5. Film grain (time-based noise)
6. Vignette (0.25 strength)

### 9. Audio System (audio.js)
All procedural, zero audio files:
- **Ambient drone**: Biome-frequency sine oscillator + detuned pair
- **Music**: 3-chord pad progressions per biome (sawtooth + triangle, low-pass filtered)
- **Sub-bass**: Octave below root, 80Hz low-pass
- **Arpeggio**: Random chord tones, 1.5-3s interval, triangle wave
- **SFX**: hit (200Hz square), kill (400->100Hz), pickup (800Hz sine), death (80Hz saw), step (50Hz), levelup (400/800/1200Hz triple)

### 10. Data Integration (data-driver.js)
- **Polling**: Every 5s from /stream-api/state and /api/thoughts/stream
- **Tool classification**: write_file -> forge, read/search -> scout, post/send -> rally, exec -> mine
- **Mutations**: Boost queue processed each frame, applies particles + game events
- **Biome shift**: Mood change triggers smooth color lerp transition

### 11. HUD (hud-overlay.js)
- **Player stats**: Name, level, HP bar, XP bar
- **Biome display**: Name + depth + spectating label
- **Minimap**: Canvas-rendered, shows explored tiles, monsters, stairs, ECHO
- **Game log**: Last 5 entries with time-based fade
- **Agent telemetry**: Toggle with T key, shows DPS, KPM, efficiency, behavior history
- **Spectator mode**: Click or Tab to switch between TIAMAT/ECHO POV
- **Screen effects**: Damage flash (red), level up flash (green), death flash (deep red)
- **Extract progress**: Bar with percentage

### 12. Asset System (asset-loader.js)
- **KayKit Dungeon Remastered**: CC0 GLTF models
- **30+ model definitions**: walls, floors, stairs, props, characters
- **Preload**: 16 essential models loaded at startup
- **Props scattering**: Barrels, crates, chests, candles, columns placed near walls
- **Tinting**: Models tinted to match biome color

### 13. Particle System (particles.js)
- **Fog**: 150 particles per floor, drift upward
- **Ground mist**: 100 particles, low-lying, brighter than fog
- **Dust motes**: 80 particles, follow player, persistent across floors
- **Event particles**: Sphere meshes, gravity, fade, type-colored (mine=gold, curse=red, etc.)
- **Extract ring**: Pulsing ring geometry on stairs

## Architecture Assessment

### Strengths
1. **Clean module separation** — 12 files, clear responsibilities, ES module imports
2. **Performance-conscious** — InstancedMesh, FPS cap, particle limits, render resolution cap
3. **Feature-rich for a monolith** — Full game loop, AI rivals, extraction, post-FX, audio, WebXR
4. **Zero external dependencies** beyond Three.js — no build system needed
5. **Data-driven design** — TIAMAT API drives mutations naturally
6. **Offline-capable** — Falls back gracefully when API is unreachable

### Gaps for Steam Release
1. **No player input** — Currently AI-only auto-play. WASD + mouse controls needed.
2. **No save/load** — Game state resets on page refresh.
3. **No settings menu** — Volume, graphics quality, keybinds all hardcoded.
4. **No inventory UI** — Equipment system exists but no screen to manage it.
5. **No tutorial** — New players get thrown in with no explanation.
6. **No pause** — Game runs continuously.
7. **No Steam integration** — Achievements, cloud saves, overlay not implemented.
8. **Electron wrapper needed** — Currently browser-only.

### Code Quality
- All files are clean, well-commented JavaScript
- No TypeScript, no bundler, no minification
- Module-based with proper exports/imports
- Good use of Three.js patterns (InstancedMesh, ShaderMaterial, BufferGeometry)
- Performance tracking built in (P key overlay)
