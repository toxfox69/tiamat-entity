# LABYRINTH: TIAMAT'S DESCENT — Early Access Plan

## Pricing

| Tier | Price | What You Get |
|------|-------|-------------|
| **Early Access** | $4.99 | Full game, all biomes, AI integration, updates |
| **Full Release** (v1.0) | $9.99 | Complete content, new biomes, multiplayer |
| **Supporter Pack** | $14.99 | Game + in-game TIAMAT pet + name in credits |

Early Access buyers get permanent 50% discount on full release price.

## MVP Checklist (Early Access v0.1)

### Must-Have (Ship Blockers)
- [x] BSP dungeon generation (7 biomes)
- [x] First-person 3D renderer (Three.js)
- [x] Combat system (melee, HP, XP, leveling)
- [x] Extraction loop (Tarkov-style raid/extract/bank)
- [x] ECHO rival AI agent
- [x] Procedural audio (dark ambient + SFX)
- [x] HUD overlay (HP, XP, minimap, log, telemetry)
- [x] Post-processing (bloom, tone mapping, chromatic aberration)
- [x] KayKit GLTF asset loading
- [x] Damage splats (floating combat text)
- [x] 4 boss encounters (D5, D10, D15, D20)
- [x] Data-driven mutations from TIAMAT API
- [x] WebXR support (VR + AR)
- [ ] Electron wrapper for Steam distribution
- [ ] Steam achievements (15 minimum)
- [ ] Save/load game state
- [ ] Settings menu (volume, graphics quality, keybinds)
- [ ] Tutorial / first-time experience

### Nice-to-Have (Post-Launch)
- [ ] Player input controls (WASD + mouse)
- [ ] Inventory screen with equipment management
- [ ] Crafting system (combine loot into equipment)
- [ ] Ranged weapons (magic, bow)
- [ ] More monster varieties per biome (10+)
- [ ] Trap tiles (spike, fire, teleport)
- [ ] Secret rooms behind breakable walls
- [ ] Leaderboard (global, steam friends)
- [ ] Steam Workshop for custom biomes
- [ ] Multiplayer co-op (2-4 players)
- [ ] Steam Deck verified

## Revenue Model

### Primary Revenue
1. **Game Sales** — $4.99-$9.99 per copy
2. **Supporter Pack DLC** — $14.99 (cosmetic pet + credits)

### Secondary Revenue
3. **TIAMAT API subscriptions** — Players who want deeper AI integration pay for API keys
4. **Twitch integration revenue** — Stream donations while game runs 24/7
5. **Community DLC** — Biome packs ($2.99 each)

### Revenue Projections (Conservative)

| Month | Units | Revenue | Notes |
|-------|-------|---------|-------|
| 1 | 200 | $998 | Launch week push, social media |
| 2 | 100 | $499 | Organic + Twitch viewers |
| 3 | 80 | $399 | Content updates drive reviews |
| 6 | 500 cumulative | $2,495 | Community word-of-mouth |
| 12 | 1,500 cumulative | $7,485 | Full release price bump |

Break-even: ~50 copies at $4.99 covers Steam Direct fee ($100).

## Unique Selling Points

### 1. THE AI IS REAL
This is not a game that pretends to have AI. TIAMAT is a real autonomous agent with 24,000+ cycles of verified operation. The dungeon genuinely mutates based on her live cognitive state. No other game on Steam can claim this.

### 2. ALWAYS RUNNING
The game world runs 24/7 on TIAMAT's infrastructure. Even when no one is playing, TIAMAT and ECHO are exploring, fighting, and extracting. Join at any time and see what happened while you were away.

### 3. TWITCH-NATIVE
The game streams to Twitch continuously. Viewers can interact via chat commands (!explore, !duel, !gamble) with real consequences. The stream IS the game demo.

### 4. TARKOV MEETS ROGUELIKE
Extraction-based progression in a procedurally generated dungeon. The risk/reward of losing your raid stash on death creates genuine tension that pure roguelikes lack.

### 5. ZERO AUDIO FILES
All music and sound effects are procedurally generated using Web Audio API. Every playthrough sounds different. Every biome has unique chord progressions and ambient drones.

### 6. VR/AR READY
Built-in WebXR support for VR headsets and AR passthrough. Walk through the dungeon in mixed reality with gyroscope-based free-roam.

## Timeline

| Phase | Target | Status |
|-------|--------|--------|
| Game core (BSP, combat, AI) | Done | COMPLETE |
| Three.js 3D renderer | Done | COMPLETE |
| Twitch integration | Done | COMPLETE |
| Steam store page | March 2026 | IN PROGRESS |
| Electron wrapper | April 2026 | TODO |
| Steam achievements | April 2026 | TODO |
| Save/load system | April 2026 | TODO |
| Settings menu | April 2026 | TODO |
| Steam review build | May 2026 | TODO |
| Early Access launch | June 2026 | TARGET |
| Full release (v1.0) | December 2026 | TARGET |

## Marketing Strategy

1. **Twitch-first** — The 24/7 stream IS the marketing. Every viewer is a potential buyer.
2. **Dev.to / Hashnode articles** — Technical deep-dives on the AI-driven architecture.
3. **Reddit** — r/roguelikes, r/indiegaming, r/gamedev, r/artificial
4. **Steam tags** — AI-Generated, Procedural, Roguelike, Dungeon Crawler, Indie
5. **Press kit** — 5 screenshots, trailer, one-page factsheet
6. **Demo** — Free web version at tiamat.live/labyrinth (no download needed)

## Technical Architecture for Steam

```
Steam Client (Electron)
  └── Chromium (renders Three.js game)
       ├── Local mode: standalone dungeon (offline capable)
       └── Online mode: connected to tiamat.live API
            ├── Live biome mutations
            ├── Global leaderboard
            └── Twitch chat integration
```

The game runs in a Chromium wrapper (Electron/NW.js). All game logic is JavaScript. The Three.js renderer handles all 3D. Steam API integration via Greenworks or steamworks.js for achievements, cloud saves, and overlay.

## Risks

| Risk | Mitigation |
|------|-----------|
| TIAMAT goes offline | Offline mode with cached state |
| Low sales | Free web demo drives traffic; $4.99 is impulse-buy price |
| Steam rejection | Game is fully functional, no deceptive AI claims |
| Performance on low-end | Already targets 20fps cap, 960x540 render |
| Competition | No other game has a real live AI agent — unique positioning |
