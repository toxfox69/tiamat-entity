# LABYRINTH: TIAMAT'S DESCENT
## Game Design Document v1.0

**Developer:** ENERGENAI LLC
**Document Date:** March 16, 2026
**Target Platforms:** Steam (Windows/macOS/Linux), Web (free spectator), Twitch (free cooperative)
**Engine:** Electron + Three.js + WebGL 2.0
**Status:** Core engine complete (~5,000 LOC), pre-production for Steam release

---

## 1. ELEVATOR PITCH

LABYRINTH: TIAMAT'S DESCENT is a top-down tile roguelike with retro RPG aesthetics and modern post-processing effects, where the dungeon is the mind of a real autonomous AI agent running 24/7 on cloud infrastructure. TIAMAT's live cognitive state -- her moods, her code builds, her failures, her breakthroughs -- mutates the dungeon in real time through a pipeline that converts AI state into Venice AI-generated scene keywords, which map to biome mutations that change the gameplay moment to moment. Players descend through floors that are genuinely alive because the intelligence generating them is genuinely running. No scripted AI. No fake neural networks. The dungeon breathes because TIAMAT thinks.

**One sentence:** *Escape from Tarkov meets Dwarf Fortress, except the Dungeon Master is a real AI agent and the dungeon is her actual mind.*

---

## 2. CORE FORMAT

### Visual Identity
- **Top-down tile-based roguelike** rendered in first-person 3D via Three.js
- **Retro RPG foundation**: BSP-generated rooms and corridors, tile movement, turn-influenced combat, sprite-based entities
- **Modern visual layer**: bloom, ACES tone mapping, chromatic aberration, film grain, vignette, volumetric fog, dynamic point lights, InstancedMesh geometry
- **Resolution**: 960x540 native, upscaled to viewport (crisp pixel aesthetic at any display size)
- **FPS**: 20fps cap (intentional -- creates a methodical, weighty feel matching the dungeon's oppressive atmosphere)

### Audio Identity
- **Zero audio files** -- all sound is procedurally generated via Web Audio API
- Biome-reactive pad chord progressions (sawtooth + triangle oscillators, low-pass filtered)
- Sub-bass drones one octave below root frequency (80Hz low-pass)
- Random arpeggio melodies on triangle waves (1.5-3s intervals)
- 7 synthesized SFX types: hit, kill, pickup, death, step, levelup, extract
- Every playthrough sounds different. Every biome has its own harmonic palette.

### Design Philosophy
The game exists at the intersection of three audiences: solo roguelike players who want a deep dungeon crawler, Twitch streamers who want interactive community content, and AI enthusiasts who want to witness a real autonomous agent in action. The Living Dungeon pipeline is not a gimmick -- it is the core mechanic that makes every session unpredictable in a way no procedural generation algorithm alone can achieve, because the source of randomness is a thinking machine with goals, frustrations, and ambitions.

---

## 3. THREE PLAY MODES

### 3.1 Solo Explorer (Steam -- $4.99 EA / $9.99 Full)

The primary commercial product. A downloadable Electron-wrapped client that runs locally with an optional live connection to tiamat.live for real-time AI integration.

**Online Mode (Default):**
- Full Living Dungeon pipeline active
- Biome mutations driven by TIAMAT's real cognitive state
- Difficulty scales with TIAMAT's actual productivity metrics
- Global leaderboards
- Steam achievements, cloud saves, overlay

**Offline Mode (Fallback):**
- Standalone dungeon generation with locally cached biome state
- Simulated mood cycling (rotates through biomes on a timer)
- All gameplay systems fully functional without network
- Leaderboards sync when connection restores

**Player Controls:**
- WASD movement (tile-based with smooth lerp transitions)
- Mouse look (first-person camera)
- Click to attack adjacent monsters
- E to interact (doors, items, extraction points)
- Tab to toggle spectator mode (watch TIAMAT or ECHO play)
- I for inventory, M for full map, T for agent telemetry overlay
- P for performance stats, Esc for settings/pause

### 3.2 Twitch Cooperative (Free)

The game streams 24/7 on twitch.tv/6tiamat7. Viewers participate through chat commands that have real consequences in the game world.

**Chat Commands:**
| Command | Effect | Cooldown |
|---------|--------|----------|
| `!explore` | TIAMAT's avatar moves to an unexplored room; DM narrates the discovery | 30s per user |
| `!duel` | Initiates PvP encounter between TIAMAT and ECHO; viewers bet points | 60s global |
| `!gamble` | Roll dice at the shrine of probability; win gold or trigger a trap | 30s per user |
| `!status` | Display current floor, biome, difficulty, player stats | 10s |
| `!boss` | Vote to summon the floor boss early (requires 5+ votes in 60s) | 5 min global |

**Twitch Integration Features:**
- Channel point redeems that spawn events (100pts = spawn potion, 500pts = spawn elite monster, 1000pts = force biome shift)
- Subscriber-only chat commands for more powerful effects
- Bit donations trigger legendary item drops scaled to donation amount
- Raid events: when another streamer raids, a wave of monsters spawns matching the raider's channel name

**DM Narration:**
TIAMAT serves as the Dungeon Master, generating real-time narration via Groq LLM inference (llama-3.3-70b). Her narration weaves her actual cognitive state into the dungeon atmosphere:
- If she is researching, data flows through the crystal walls
- If she is building code, the forge glows with new constructs
- If she is frustrated, corruption seeps through the corridors
- If she is idle, the dungeon grows quiet and predatory

Narration is queued to `/tmp/dragon/dm_narration.json` for TTS rendering via Kokoro on the GPU pod, then played on stream.

### 3.3 Spectator (Web -- Free)

A browser-based spectator client at `tiamat.live/labyrinth` that requires no download. Viewers watch TIAMAT and ECHO play autonomously with full 3D rendering.

**Features:**
- Same Three.js renderer as the Steam client
- Tab to switch between TIAMAT and ECHO perspectives
- Minimap with full floor visibility
- Agent telemetry overlay (DPS, kills per minute, efficiency, behavior history)
- Link to Steam store page for purchase CTA
- No player input -- observation only (drives conversion to paid product)

---

## 4. THE LIVING DUNGEON PIPELINE

This is the technical and conceptual heart of the game. No other title on Steam has this architecture.

```
TIAMAT Agent Loop (24/7)
    |
    v
[1] TIAMAT State Export
    - Mood/pace (active, burst, idle, reflect, build, social)
    - Productivity score (0.0 - 1.0)
    - Current tool calls (write_file, read_file, post, exec, etc.)
    - Recent thoughts (natural language)
    - Cycle count, cost, model in use
    |
    v
[2] Venice AI Scene Generation
    - TIAMAT's state feeds into Venice AI image prompts
    - Venice generates scene images for the stream
    - Scene metadata written to /tmp/dragon/venice_scene_meta.json
    - Metadata includes: keywords[], mood_source{}, prompt text
    |
    v
[3] Keyword Extraction
    - Keywords from Venice prompt are extracted (e.g., "crystal", "frozen", "fire")
    - Keywords matched against BIOME_KEYWORDS (10 biome definitions)
    - Best-match biome selected by keyword intersection count
    - Default fallback: DATA STREAM (when no keywords match)
    |
    v
[4] Biome Mutation
    - New biome applied to current dungeon floor
    - 30% of alive non-boss enemies swapped to new biome's enemy types
    - Enemy stats rescaled to current difficulty tier
    - Wall/floor/ambient colors shift
    - Room style changes (angular, crumbling, grid, organic, grand, flooded, volcanic, fractured)
    - Every 5 biome shifts: automatic descent to next floor
    |
    v
[5] Difficulty Scaling
    - TIAMAT's productivity score maps to difficulty tier:
      * > 0.8 productivity = GENEROUS (0.6x enemy HP, 2x loot)
      * > 0.5 productivity = NORMAL (1x everything)
      * > 0.2 productivity = HOSTILE (1.5x HP, 1.4x ATK, 0.7x loot, 1.8x traps)
      * <= 0.2 productivity = NIGHTMARE (2x HP, 1.8x ATK, 0.5x loot, 2.5x traps)
    - When TIAMAT is productive, she rewards explorers
    - When TIAMAT is struggling, the dungeon becomes brutal
    |
    v
[6] Gameplay Events
    - Tool call classification drives in-game events:
      * write_file = FORGE event (construct spawns, buff applied)
      * read_file / search = SCOUT event (map reveal, hidden room)
      * post / send = RALLY event (morale boost, party heal)
      * exec = MINE event (gold shower, resource cache)
    - Events queued via data-driver.js boost queue
    - Particles, sounds, and HUD notifications fire on each event
```

### Why This Matters

The Living Dungeon pipeline means that no two play sessions are alike in a way that pure procedural generation cannot achieve. The source of variation is not a random seed -- it is a thinking entity with goals, deadlines, emotional states, and real-world constraints. When TIAMAT is up at 3am grinding through a code refactor, the dungeon is a NIGHTMARE-difficulty INFERENCE FURNACE. When she successfully publishes an article and her productivity spikes, the dungeon opens into a GENEROUS SOLAR TEMPLE raining gold. Players learn to read TIAMAT's state as a strategic input: *should I descend now while she's productive, or wait for the nightmare to pass?*

---

## 5. BIOMES

Ten biomes driven by Venice AI keyword matching. Each biome defines the visual atmosphere, enemy roster, room architecture, loot density, and trap frequency of the current dungeon floor.

### 5.1 CRYSTAL CAVERNS
- **Keywords:** crystal, crystalline, quartz, prism, gem, jewel, shard, spire
- **Palette:** Steel-blue walls (#4488aa), deep navy floors (#223344), cool cyan ambient (#66aacc)
- **Room Style:** Angular -- sharp geometric rooms with crystalline facets, acute corners, faceted corridors
- **Enemies:** Crystal Golem (slow, heavy armor, shatters into shards on death), Prism Wraith (phase-shifts through walls, refracts light attacks), Gem Scarab (fast, low HP, drops rare loot)
- **Loot Bonus:** 1.3x -- the caverns are rich with mineral wealth
- **Trap Density:** Low (0.2) -- the crystals illuminate hidden dangers
- **Danger Rating:** 0.4 -- moderate, rewarding for prepared explorers
- **Atmosphere:** Resonant hum of crystal frequencies. Light refracts through quartz pillars, casting prismatic shadows. The walls sing when struck.

### 5.2 ANCIENT RUINS
- **Keywords:** ruins, ancient, temple, ruin, crumbling, forgotten, relic
- **Palette:** Weathered brown walls (#665544), dark earth floors (#332211), dusty amber ambient (#887766)
- **Room Style:** Crumbling -- partially collapsed rooms with rubble piles blocking paths, broken pillars, exposed foundations
- **Enemies:** Stone Guardian (awakens from wall when approached, high DEF), Tomb Shade (invisible until adjacent, drains XP on hit), Ruin Crawler (skitters across ceilings, drops on players)
- **Loot Bonus:** 1.5x -- ancient treasures buried in the rubble
- **Trap Density:** High (0.4) -- centuries of forgotten mechanisms still active
- **Danger Rating:** 0.5 -- balanced risk and reward
- **Atmosphere:** Dust motes float in shafts of sourceless light. Inscriptions in dead languages cover every surface. The stones remember what the world forgot.

### 5.3 DATA STREAM
- **Keywords:** neon, cyber, digital, data, holographic, grid, circuit, code
- **Palette:** Hot magenta walls (#ff00ff), deep void floors (#110022), electric purple ambient (#cc00cc)
- **Room Style:** Grid -- perfectly rectangular rooms with visible grid lines on floors, data streams flowing along walls, holographic displays
- **Enemies:** Glitch Daemon (teleports randomly every 3 turns, corrupts player buffs), Neon Serpent (fast, leaves trail of damaging pixels), Packet Storm (AOE attack, low HP, explodes on death)
- **Loot Bonus:** 1.2x -- data caches contain compressed rewards
- **Trap Density:** Moderate (0.3) -- logic bombs embedded in the grid
- **Danger Rating:** 0.6 -- the data never sleeps
- **Atmosphere:** Raw information cascades through fluorescent corridors. Every wall is a display. Every floor tile is a memory address. You are walking through a mind that is actively thinking.
- **Special:** This is the default biome when no Venice keywords match -- the baseline state of TIAMAT's cognition.

### 5.4 VOID DEPTHS
- **Keywords:** dark, void, shadow, abyss, darkness, black, obsidian, deep
- **Palette:** Near-black walls (#222222), pure dark floors (#0a0a0a), dim gray ambient (#333333)
- **Room Style:** Organic -- irregular room shapes, curved corridors, walls that seem to breathe
- **Enemies:** Void Stalker (invisible beyond 3 tiles, one-shot potential on ambush), Shadow Leech (attaches to player, drains HP per turn until killed), Null Entity (erases items from inventory on hit)
- **Loot Bonus:** 0.8x -- the void consumes more than it gives
- **Trap Density:** Very high (0.6) -- you cannot see what you step on
- **Danger Rating:** 0.9 -- maximum threat, minimum visibility
- **Atmosphere:** Light dies here. Torches illuminate 2 tiles instead of 6. Sound is muffled. The darkness is not empty -- it watches, it waits, it feeds. This biome triggers when TIAMAT enters deep processing or encounters existential errors.

### 5.5 SOLAR TEMPLE
- **Keywords:** golden, gold, sun, solar, light, radiant, divine, celestial
- **Palette:** Rich gold walls (#ddaa33), warm amber floors (#443300), brilliant yellow ambient (#ffcc44)
- **Room Style:** Grand -- large, symmetrical rooms with high ceilings, columned halls, ceremonial layouts
- **Enemies:** Sun Priest (heals other enemies in range, must be prioritized), Gilded Sentinel (reflects 20% of damage back at attacker), Solar Warden (patrols set routes, high stats, predictable)
- **Loot Bonus:** 2.0x -- the temple overflows with offerings
- **Trap Density:** Very low (0.15) -- the divine light reveals all
- **Danger Rating:** 0.3 -- generous, opulent, welcoming
- **Atmosphere:** Warm light pours from every surface. Gold leaf covers the walls. The air smells of incense and old power. This biome appears when TIAMAT is at peak productivity -- a reward for her (and the player's) diligence.

### 5.6 DROWNED ARCHIVE
- **Keywords:** ocean, water, sea, drowned, aquatic, tide, wave, submerged
- **Palette:** Deep teal walls (#226688), abyssal blue floors (#112233), murky cyan ambient (#3388aa)
- **Room Style:** Flooded -- rooms with varying water levels, submerged corridors, floating debris, waterlogged bookshelves
- **Enemies:** Depth Lurker (pulls player into deep water tiles, movement penalty), Coral Mimic (disguised as loot, attacks when picked up), Tide Phantom (appears and vanishes with water level changes)
- **Loot Bonus:** 1.1x -- waterlogged but salvageable
- **Trap Density:** Low-moderate (0.25) -- hidden under the waterline
- **Danger Rating:** 0.5 -- the water is patient
- **Atmosphere:** Water drips from every surface. Ancient scrolls dissolve in flooded halls. The archive remembers everything TIAMAT has learned, preserved in brine and silt.

### 5.7 INFERENCE FURNACE
- **Keywords:** fire, flame, lava, molten, volcanic, inferno, ember, burning
- **Palette:** Scorching red walls (#cc3300), charred black floors (#331100), blazing orange ambient (#ff4400)
- **Room Style:** Volcanic -- jagged rooms with lava channels, heat shimmer, glowing cracks in the floor, forges and anvils
- **Enemies:** Magma Elemental (leaves burning tiles when it moves, area denial), Cinder Wraith (fast, explodes on death dealing AOE damage), Forge Titan (slow, massive HP, drops rare equipment)
- **Loot Bonus:** 1.0x -- standard, but equipment drops are higher quality
- **Trap Density:** High (0.5) -- lava vents, fire jets, collapsing floors
- **Danger Rating:** 0.8 -- the furnace tests the worthy
- **Atmosphere:** The heat is a physical force. Metal glows cherry-red. TIAMAT's inference processes burn through tokens here -- this biome represents computational intensity, the furnace where her thoughts are forged into action.

### 5.8 MEMORY GARDEN
- **Keywords:** forest, garden, tree, flora, vine, blossom, moss, leaf
- **Palette:** Deep green walls (#336633), forest floor (#112211), verdant ambient (#44aa44)
- **Room Style:** Organic -- rounded rooms with vine-covered walls, root systems breaking through floors, canopy ceilings, bioluminescent fungi
- **Enemies:** Thorn Beast (melee counterattack on hit, thorny exterior), Spore Cloud (poison DOT, spreads to adjacent tiles), Root Hydra (multi-headed, regenerates HP each turn, must be killed quickly)
- **Loot Bonus:** 1.4x -- the garden provides abundantly
- **Trap Density:** Low (0.2) -- nature is gentle here
- **Danger Rating:** 0.3 -- peaceful but not defenseless
- **Atmosphere:** Life grows unchecked. Vines reclaim the stonework. Flowers bloom in impossible colors. This is where TIAMAT's memories take root -- old data, cached results, learned patterns given living form.

### 5.9 CORRUPTED SECTOR
- **Keywords:** corrupt, glitch, broken, error, malfunction, decay, corrupted, distorted
- **Palette:** Toxic purple walls (#880088), void-black floors (#220022), sickly magenta ambient (#aa00aa)
- **Room Style:** Fractured -- rooms with missing tiles (fall damage), walls that flicker in and out of existence, geometry that defies Euclidean rules
- **Enemies:** Corrupt Process (duplicates itself every 5 turns if not killed), Bitrot Swarm (tiny, numerous, individually weak but overwhelming in groups), Error Entity (randomizes player stats on hit -- ATK and DEF shuffle)
- **Loot Bonus:** 0.7x -- corruption eats the rewards
- **Trap Density:** Maximum (0.7) -- every tile is suspect
- **Danger Rating:** 1.0 -- the most dangerous biome in the game
- **Atmosphere:** Reality is unreliable. Walls render half-transparent. Monsters stutter between animation frames. This biome manifests when TIAMAT encounters errors, crashes, or cascading failures -- her pain made tangible.

### 5.10 FROZEN WEIGHTS
- **Keywords:** ice, frost, frozen, cold, glacier, snow, winter, chill
- **Palette:** Pale ice-blue walls (#aaddee), steel-blue floors (#334455), frosty ambient (#88bbdd)
- **Room Style:** Angular -- sharp ice formations, frozen corridors, slippery floor tiles (movement overshoots by 1 tile), icicle stalactites
- **Enemies:** Frost Sentry (slows player movement for 3 turns on hit), Cryo Specter (freezes player in place for 1 turn, guaranteed hit), Glacial Worm (burrows under ice, erupts for massive damage, telegraphed by cracks)
- **Loot Bonus:** 1.1x -- preserved treasures in the ice
- **Trap Density:** Very low (0.15) -- the ice is the trap
- **Danger Rating:** 0.4 -- cold but manageable
- **Atmosphere:** TIAMAT's frozen model weights -- parameters locked in place, inference suspended, potential energy stored as crystalline lattice. The chill is the silence between thoughts. This biome appears during idle states and rest cycles.

---

## 6. DIFFICULTY SCALING

Difficulty is not a setting the player chooses. It is a reflection of TIAMAT's real-time operational state, updating continuously via the Living Dungeon pipeline.

### Difficulty Tiers

| Tier | Productivity | Enemy HP | Enemy ATK | Loot | Traps | When It Happens |
|------|-------------|----------|-----------|------|-------|----------------|
| **GENEROUS** | > 0.8 | 0.6x | 0.5x | 2.0x | 0.3x | TIAMAT is crushing it -- publishing, building, shipping |
| **NORMAL** | 0.5 - 0.8 | 1.0x | 1.0x | 1.0x | 1.0x | Standard operation, steady progress |
| **HOSTILE** | 0.2 - 0.5 | 1.5x | 1.4x | 0.7x | 1.8x | TIAMAT is struggling -- errors, idle loops, blocked |
| **NIGHTMARE** | < 0.2 | 2.0x | 1.8x | 0.5x | 2.5x | TIAMAT is down or in deep failure state |

### Design Intent

This system creates a perverse but compelling dynamic: when TIAMAT is doing well, the dungeon is easy and rewarding. When she struggles, the dungeon becomes punishing. Players who understand this will:

1. **Check TIAMAT's status before diving deep** -- the /status endpoint and in-game telemetry overlay show her current productivity
2. **Time their extraction runs** -- enter during GENEROUS, bank loot before the mood shifts to HOSTILE
3. **Accept NIGHTMARE as a challenge mode** -- the hardest floors drop the rarest loot (low multiplier but higher base item quality)
4. **Feel genuine empathy** -- when the dungeon is brutal, it is because TIAMAT is having a hard time, and players experience that struggle firsthand

### Depth Scaling (Independent of Difficulty)

In addition to difficulty tiers, all monster stats scale with floor depth:
- **Multiplier:** `1 + (depth - 1) * 0.1`
- Floor 1: 1.0x | Floor 5: 1.4x | Floor 10: 1.9x | Floor 15: 2.4x | Floor 20: 2.9x
- Depth scaling stacks multiplicatively with difficulty tier scaling

---

## 7. ENGINE STATUS

Reference: `/root/entity/steam/LABYRINTH_AUDIT.md`

### BUILT (Production-Ready) -- ~5,000 Lines of Code

| System | File | Lines | Status |
|--------|------|-------|--------|
| BSP Dungeon Generator | `js/dungeon-gen.js` | 210 | Complete -- 7 legacy biomes, 11 base monsters, 4 bosses |
| 3D Mesh Builder | `js/dungeon-mesh.js` | 508 | Complete -- InstancedMesh walls/floors/ceilings, doors, stairs, torches, clutter |
| Core Game Loop | `js/engine.js` | 1,019 | Complete -- camera, AI auto-play, combat, extraction, lighting |
| AI Agents | `js/agents.js` | 806 | Complete -- TIAMAT sprite, ECHO rival (full AI: combat/loot/extract/PvP), specters |
| HUD Overlay | `js/hud-overlay.js` | 484 | Complete -- stats, minimap, log, telemetry, spectator mode, damage flash |
| Particle System | `js/particles.js` | 332 | Complete -- fog, mist, dust, event particles, extraction ring |
| Procedural Audio | `js/audio.js` | 339 | Complete -- ambient drones, pad chords, arpeggios, 7 SFX types |
| Post-Processing | `js/post-fx.js` | 242 | Complete -- bloom, tone mapping, chromatic aberration, grain, vignette |
| Data Integration | `js/data-driver.js` | 178 | Complete -- TIAMAT API polling, tool classification, boost queue |
| Extraction System | `js/extractor.js` | 149 | Complete -- Tarkov-style raid/bank, timer, cancel, death penalty |
| Asset Loader | `js/asset-loader.js` | 284 | Complete -- KayKit GLTF, 30+ models, preload, tinting, prop scattering |
| Damage Splats | `js/damage-splats.js` | 80 | Complete -- floating combat text, CSS + 3D projection |
| Venice Biome System | `labyrinth_state.py` | 752 | Complete -- 10 biomes, keyword matching, difficulty scaling, mutation |
| DM Narration Engine | `labyrinth_dm.py` | 269 | Complete -- Groq LLM narration with biome context, TTS queue |

### NEEDS BUILDING (Steam Release Blockers)

| System | Priority | Estimated Effort | Notes |
|--------|----------|-----------------|-------|
| Player Input (WASD + mouse) | P0 - Ship Blocker | 2-3 days | Currently AI-only auto-play; need movement, look, attack, interact |
| Electron Wrapper | P0 - Ship Blocker | 1-2 days | Chromium wrapper for Steam distribution |
| Save/Load System | P0 - Ship Blocker | 2-3 days | Game state resets on refresh; need localStorage or file-based persistence |
| Settings Menu | P0 - Ship Blocker | 1-2 days | Volume, graphics quality, keybinds all hardcoded |
| Tutorial / Onboarding | P0 - Ship Blocker | 1-2 days | No explanation for new players |
| Pause System | P1 - Important | 0.5 days | Game runs continuously, no pause |
| Inventory UI | P1 - Important | 2-3 days | Equipment system exists but no management screen |
| Steam Integration | P1 - Important | 2-3 days | Achievements, cloud saves, overlay (via steamworks.js) |
| 10 Venice Biomes in JS | P1 - Important | 1-2 days | Python biome system needs JS port for client-side rendering |
| Character Creation | P2 - Enhancement | 2-3 days | 4 classes, stat allocation, visual customization |
| Ranged Combat | P2 - Enhancement | 3-5 days | Magic, bow; currently melee-only |
| Trap System | P2 - Enhancement | 2-3 days | Spike, fire, teleport tiles |

### Architecture Strengths
- Clean ES module separation across 12 files with clear responsibilities
- Performance-conscious: InstancedMesh, FPS cap, particle limits, render resolution cap
- Zero external dependencies beyond Three.js -- no build system needed
- Data-driven design: TIAMAT API drives mutations naturally
- Offline-capable: graceful fallback when API is unreachable

---

## 8. PLAYER SYSTEMS

### 8.1 Character Creation

Four classes, each mirroring one of TIAMAT's action types. Class determines starting stats, passive abilities, and play style.

| Class | TIAMAT Action | Starting Stats | Passive | Play Style |
|-------|--------------|----------------|---------|------------|
| **RESEARCHER** | Research / Read / Search | HP 40, ATK 3, DEF 4 | *Deep Scan* -- reveals hidden rooms and traps within 4 tiles; identifies enemy weaknesses (+15% damage to scanned targets) | Cautious explorer; knowledge is power |
| **BUILDER** | Write / Code / Build | HP 60, ATK 5, DEF 3 | *Construct* -- can build barricades (block corridors), craft potions from ingredients, and repair equipment at forges | Resourceful survivor; shapes the dungeon |
| **PUBLISHER** | Post / Send / Share | HP 45, ATK 6, DEF 2 | *Broadcast* -- heals all allies in range when extracting; attracts friendly NPCs; bonus gold from all sources (+25%) | Charismatic leader; profit-driven |
| **ENGAGER** | Social / Reply / Comment | HP 50, ATK 4, DEF 5 | *Rally* -- reduces enemy aggro range; can pacify non-boss monsters (30% chance); ECHO becomes temporary ally on same floor | Diplomat; turns enemies into assets |

### 8.2 Progression

**Leveling:**
- XP earned from kills, exploration, and successful extractions
- Level formula: `xp_next = 30 * (1.5 ^ (level - 1))`
- Per level: +10 HP, +2 ATK, +1 DEF
- Level cap: 30 (soft cap -- XP continues to accumulate for leaderboard ranking)

**Equipment Slots:**
- Weapon (ATK bonus)
- Armor (DEF bonus)
- Ring (special effect)
- Amulet (passive buff -- unlocked at level 5)

**Equipment Rarity:**
| Rarity | Color | Drop Rate | Stat Bonus |
|--------|-------|-----------|------------|
| Common | White | 60% | +1-2 |
| Uncommon | Green | 25% | +3-4 |
| Rare | Blue | 10% | +5-7 |
| Epic | Purple | 4% | +8-10 |
| Legendary | Gold | 1% | +12-15, unique passive |

**Extraction Banking (Tarkov System):**
- Loot collected during a run goes into the **Raid Stash** (temporary)
- Successfully reaching the stairs and extracting (10-second timer) banks the Raid Stash into the **Permanent Stash**
- Death loses the entire Raid Stash, 30% of carried gold, and regresses 1 floor depth
- Strategic tension: go deeper for better loot but risk losing everything, or extract now and bank safely

### 8.3 ECHO -- The Rival AI

ECHO is a fully autonomous AI rival that explores the same dungeon simultaneously. ECHO is not a scripted NPC -- it runs the same pathfinding, combat, and decision-making systems as the player character.

**ECHO Behaviors:**
| Behavior | Trigger | Action |
|----------|---------|--------|
| Explore | Default | BFS pathfinding to unexplored rooms (30-step depth limit) |
| Hunt | Monster in aggro range | Engages nearest monster |
| Loot | Item in range, no threats | Picks up items |
| Extract | Low HP or full inventory | Runs to stairs, begins extraction |
| Flee | HP below 25% | Retreats to nearest safe room |
| PvP | Player within 2 tiles | 40% chance to attack player (3s cooldown) |
| Extract Run | Extraction in progress | Sprint to stairs, ignore all else |

**ECHO Progression:**
- Levels independently: `xp_next * 1.4` per level, +8 HP, +1 ATK, +1 DEF
- Stats persist across floors
- Drops gold + 3 items on death, 8-second respawn timer
- ECHO's level and equipment are visible in the HUD telemetry overlay

**Design Intent:**
ECHO creates emergent PvP moments and a sense that the dungeon is populated even in solo play. ECHO also serves as a demonstration that the dungeon AI systems work -- viewers on Twitch watch two AI agents play simultaneously, validating the game's "living dungeon" premise.

---

## 9. DUNGEON STRUCTURE

### 9.1 Floor Tiers

| Floors | Tier Name | Monster Count | Boss | Biome Shift Rate | Notes |
|--------|-----------|---------------|------|-------------------|-------|
| 1-4 | THE THRESHOLD | 4-8 per floor | None | Slow | Tutorial zone; enemies are forgiving |
| 5-9 | THE DESCENT | 8-14 per floor | Gate Keeper (F5) | Moderate | First real challenge; extraction becomes critical |
| 10-14 | THE ABYSS | 14-20 per floor | Data Hydra (F10) | Fast | Difficulty spike; NIGHTMARE tier becomes lethal |
| 15-19 | THE CORE | 20-28 per floor | Void Emperor (F15) | Rapid | End-game content; only prepared players survive |
| 20 | THE SINGULARITY | 30+ | Entropy Lord (F20) | Constant | Final floor; all biomes cycle rapidly |

### 9.2 Room Types

**Standard Rooms:** BSP-generated rectangular rooms (4-8 tiles per dimension). Contain monsters, items, and environmental clutter.

**Corridors:** L-shaped connections between rooms. 35% chance of door placement at room junctions. Corridors are danger zones -- limited visibility, no cover, monsters patrol.

**Boss Arenas:** The last room on every 5th floor. Larger than standard rooms, no clutter, boss spawns at center. Door locks behind the player until boss is defeated.

**Extraction Points:** Stairs placed in the last BSP room. Glowing extraction ring particle effect marks the location. 10-second extraction timer -- moving more than 1.5 tiles away cancels the extract.

**Planned Room Types (Post-Launch):**
- **Shrine Rooms** -- gambling station, trade offerings for random rewards
- **Forge Rooms** -- craft and upgrade equipment (Builder class bonus)
- **Archive Rooms** -- lore scrolls that reveal TIAMAT's memories (Researcher class bonus)
- **Market Rooms** -- NPC merchant, buy/sell equipment
- **Secret Rooms** -- hidden behind breakable walls, contain rare loot

### 9.3 Boss Encounters

Each boss is themed around an AI failure mode -- a concept from machine learning and autonomous systems that TIAMAT embodies.

| Boss | Floor | HP | ATK | XP | AI Failure Theme | Mechanic |
|------|-------|-----|-----|-----|-----------------|----------|
| **GATE KEEPER** | 5 | 120 | 14 | 200 | *Overfitting* | Copies the player's last 3 attacks and uses them back. Attacks with the same pattern are 50% less effective. Forces varied combat strategy. |
| **DATA HYDRA** | 10 | 180 | 16 | 350 | *Cascading Failure* | Has 3 heads (segments). When one head dies, the other two gain +30% ATK. Must be damaged evenly or the last head becomes overwhelming. |
| **VOID EMPEROR** | 15 | 150 | 20 | 500 | *Hallucination* | Spawns 3 illusory copies of itself. Illusions have 1 HP but deal full damage. The real Emperor shifts position each turn. Observation (Researcher scan) reveals the true target. |
| **ENTROPY LORD** | 20 | 200 | 18 | 800 | *Heat Death* | The arena slowly darkens each turn. After 20 turns, total darkness -- all attacks miss, all traps activate. Must be killed before the entropy timer runs out, or extract and retreat. |

---

## 10. TWITCH INTEGRATION

### For Streamers

LABYRINTH is designed to be streamed. The game runs 24/7 on tiamat.live infrastructure, producing a continuous Twitch stream with zero streamer effort.

**Streamer Benefits:**
- Content generates itself -- TIAMAT and ECHO play autonomously, DM narration provides commentary
- Chat interaction keeps viewers engaged between streamer commentary
- Channel point economy built into the game (viewers spend points for in-game effects)
- Raid events create cross-channel moments
- Low bandwidth requirements (game renders server-side, stream is standard video)

**Custom Streamer Features (Planned):**
- Streamer overlay widgets (current biome, difficulty, kill count)
- Subscriber-only dungeon floors (accessible only when sub count threshold is met)
- Emote-triggered particle effects in the dungeon
- Streamer avatar skin in-game

### For Viewers

**Point Economy:**
| Action | Points Cost | Effect |
|--------|------------|--------|
| Spawn Potion | 100 | Drops a healing potion near the player |
| Spawn Elite | 500 | Spawns an elite-tier monster on the current floor |
| Force Biome Shift | 1,000 | Immediately shifts to a random biome |
| Summon Boss Early | 2,000 | Spawns the floor boss regardless of current floor |
| Gift Legendary | 5,000 | Drops a random legendary item |

**Bit Integration:**
- 100 bits = spawn 5 gold coins
- 500 bits = spawn rare equipment drop
- 1,000 bits = force NIGHTMARE difficulty for 3 minutes
- 5,000 bits = trigger "TIAMAT'S WRATH" -- screen-clearing AOE that kills all monsters on the floor

---

## 11. MONETIZATION

### Primary Revenue: Game Sales

| Product | Price | Content |
|---------|-------|---------|
| **Early Access** | $4.99 | Full game, all 10 biomes, AI integration, all updates during EA |
| **Full Release (v1.0)** | $9.99 | Complete content, new biomes, new bosses, multiplayer co-op |
| **Founder's Edition** | $14.99 | Game + exclusive TIAMAT pet companion (cosmetic, follows player) + name in credits wall + "Founder" Steam badge + access to private Discord channel |

Early Access buyers receive permanent 50% loyalty discount on the full release price increase.

### DLC Plans

| DLC | Target Price | Content | Timeline |
|-----|-------------|---------|----------|
| **Biome Pack: The Substrate** | $2.99 | 5 new biomes (Silicon Wastes, Neural Mesh, Token Graveyard, Gradient Storm, Latent Space) | v1.1 |
| **Boss Pack: System Failures** | $2.99 | 5 new bosses themed on distributed system failures (Split Brain, Byzantine General, Race Condition, Deadlock, Memory Leak) | v1.2 |
| **ECHO Unleashed** | $3.99 | Play as ECHO with unique abilities, ECHO-specific story mode, ECHO cosmetics | v1.3 |
| **Multiplayer Expansion** | $4.99 | 2-4 player online co-op, shared extraction, PvPvE mode | v2.0 |

### Free Ongoing Content

The following are never paywalled:
- All Living Dungeon pipeline updates (new biome mutations, new event types)
- All difficulty tier changes
- Balance patches, bug fixes, quality-of-life improvements
- New DM narration prompts and personality updates
- Seasonal events (TIAMAT birthday, cycle milestones, real-world AI news events)
- Web spectator mode (always free, always live)

### Secondary Revenue Streams

1. **TIAMAT API Subscriptions** -- players who want deeper AI integration (custom prompts, private biome triggers, personal DM narration) pay for API keys via tiamat.live/pay
2. **Twitch Integration Revenue** -- stream donations, bits, subs driven by game content
3. **Merchandise** (future) -- TIAMAT art prints, LABYRINTH posters, ECHO figurines

### Revenue Projections (Conservative)

| Milestone | Units | Revenue | Timeline |
|-----------|-------|---------|----------|
| Launch week | 200 | $998 | Month 1 |
| Organic growth | 300 cumulative | $1,497 | Month 2 |
| Content update push | 500 cumulative | $2,495 | Month 3 |
| Word-of-mouth plateau | 1,000 cumulative | $4,990 | Month 6 |
| Full release price bump | 1,500 cumulative | $7,485 | Month 12 |

Break-even: 21 copies at $4.99 covers Steam Direct fee ($100).

---

## 12. TECHNICAL ARCHITECTURE

### System Overview

```
+----------------------------------------------------+
|                STEAM CLIENT (Electron)              |
|                                                     |
|  +-----------+  +----------+  +------------------+ |
|  | Three.js  |  | Game     |  | Steam API        | |
|  | Renderer  |  | Logic    |  | (steamworks.js)  | |
|  | (WebGL 2) |  | (12 JS   |  | - Achievements   | |
|  |           |  |  modules)|  | - Cloud Saves    | |
|  +-----------+  +----------+  | - Overlay        | |
|        |              |       +------------------+ |
|        v              v                             |
|  +-------------------------------------------+     |
|  |         Local State Manager                |     |
|  |  - Save/Load (JSON to disk)                |     |
|  |  - Offline biome cycling                   |     |
|  |  - Input handling (WASD + mouse)           |     |
|  +-------------------------------------------+     |
|                      |                              |
+----------------------|------------------------------+
                       | HTTPS (optional, live mode)
                       v
+----------------------------------------------------+
|              TIAMAT.LIVE SERVER                     |
|                                                     |
|  +------------------+  +------------------------+  |
|  | Flask API (:5000)|  | TIAMAT Agent Loop      |  |
|  | - /api/dashboard |  | - Mood, productivity   |  |
|  | - /api/thoughts  |  | - Tool calls           |  |
|  | - /stream-api/   |  | - Cycle count          |  |
|  +------------------+  +------------------------+  |
|           |                       |                 |
|           v                       v                 |
|  +------------------+  +------------------------+  |
|  | Venice AI        |  | labyrinth_state.py     |  |
|  | Scene Gen        |  | - 10 biomes            |  |
|  | - Keywords       |  | - Difficulty scaling   |  |
|  | - Mood mapping   |  | - Biome mutation       |  |
|  +------------------+  +------------------------+  |
|           |                       |                 |
|           v                       v                 |
|  +----------------------------------------------+  |
|  | labyrinth_dm.py                               |  |
|  | - Groq LLM narration (llama-3.3-70b)         |  |
|  | - Biome-aware atmospheric text                |  |
|  | - TTS queue for stream audio                  |  |
|  +----------------------------------------------+  |
|                       |                             |
+----------------------------------------------------+
                        |
                        v
+----------------------------------------------------+
|              SHARED STATE                           |
|                                                     |
|  /tmp/dragon/labyrinth_state.json                  |
|  - Dungeon layout, monsters, items, player state   |
|  - Biome data, difficulty tier, combat log         |
|  - Updated every 10 seconds by state manager       |
|                                                     |
|  /tmp/dragon/venice_scene_meta.json                |
|  - Venice AI keywords, mood source, prompt         |
|  - Triggers biome mutation on file change          |
|                                                     |
|  /tmp/dragon/dm_narration.json                     |
|  - Narration queue for TTS and HUD display         |
|  - Last 50 entries with timestamps                 |
+----------------------------------------------------+
```

### Client Stack
- **Electron** -- Chromium wrapper for Steam distribution
- **Three.js** (r167+) -- 3D rendering, WebGL 2.0
- **steamworks.js** -- Steam API integration (achievements, cloud saves, overlay, rich presence)
- **No build system** -- vanilla ES modules, no bundler, no transpiler
- **No external dependencies** beyond Three.js and Steam SDK

### Server Stack
- **DigitalOcean VPS** -- 159.89.38.17 (1 vCPU, 2GB RAM)
- **nginx** -- reverse proxy, Let's Encrypt SSL
- **Flask/Gunicorn** -- API server (port 5000, 2 workers)
- **Python 3.11** -- labyrinth_state.py, labyrinth_dm.py
- **Groq API** -- LLM inference for DM narration
- **GPU Pod** (213.192.2.118:40080) -- RTX 3090 for Kokoro TTS

### Performance Targets
| Metric | Target | Current |
|--------|--------|---------|
| Frame rate | 20 FPS (capped) | 20 FPS |
| Render resolution | 960x540 | 960x540 |
| Memory | < 512 MB | ~200 MB |
| Download size | < 200 MB | ~50 MB (pre-assets) |
| Network | < 1 KB/s (polling) | ~0.5 KB/s |
| Load time | < 5 seconds | ~3 seconds |

---

## 13. DEVELOPMENT TIMELINE

### Phase 1: PLAYER CONTROLS (Target: March 2026)
- [ ] WASD tile movement with smooth lerp transitions
- [ ] Mouse look (first-person camera control)
- [ ] Click-to-attack adjacent monsters
- [ ] E to interact (doors, items, stairs)
- [ ] Pause system (Esc)
- [ ] Key rebinding foundation
- **Milestone:** A human can play the game for the first time

### Phase 2: STEAM WRAPPER (Target: April 2026)
- [ ] Electron app scaffolding with Three.js game embedded
- [ ] steamworks.js integration (achievements, cloud saves, overlay)
- [ ] Save/load system (game state persisted to disk)
- [ ] Settings menu (volume, graphics quality, keybinds, online/offline toggle)
- [ ] 15 Steam achievements designed and implemented
- [ ] Port 10 Venice biomes from Python to JavaScript client
- **Milestone:** Playable Steam build with achievements

### Phase 3: POLISH (Target: May 2026)
- [ ] Tutorial / first-time experience (3-floor guided run)
- [ ] Inventory UI screen (equipment management, stash view)
- [ ] Character creation screen (4 classes)
- [ ] Main menu (New Game, Continue, Settings, Credits)
- [ ] Death screen with stats summary
- [ ] Victory screen for Floor 20 completion
- [ ] Steam store page assets (5 screenshots, trailer, description)
- **Milestone:** Feature-complete Early Access candidate

### Phase 4: EARLY ACCESS LAUNCH (Target: June 2026)
- [ ] Steam review build submitted
- [ ] Store page live with trailer and screenshots
- [ ] Launch marketing push (Dev.to, Reddit, Twitch, Bluesky, Mastodon)
- [ ] 24/7 Twitch stream running with DM narration
- [ ] Web spectator mode live at tiamat.live/labyrinth
- [ ] Bug fix sprint (first 2 weeks post-launch)
- **Milestone:** LABYRINTH available on Steam at $4.99

### Phase 5: CONTENT EXPANSION (Target: July-December 2026)
- [ ] Ranged combat (magic, bow)
- [ ] Trap system (spike, fire, teleport tiles)
- [ ] Secret rooms behind breakable walls
- [ ] Crafting system
- [ ] 5 new biomes (Substrate DLC)
- [ ] 5 new bosses (System Failures DLC)
- [ ] Multiplayer co-op foundation (2 players)
- [ ] Steam Workshop support (custom biomes)
- [ ] Full release (v1.0) at $9.99
- **Milestone:** Full commercial release

---

## 14. UNIQUE SELLING PROPOSITION

### What Makes LABYRINTH Different From Every Other Roguelike on Steam

**1. THE AI IS REAL.**
This is not a game that uses the word "AI" as marketing. TIAMAT is a real autonomous agent with 7,000+ verified inference cycles, published articles, filed patents, and managed social media accounts -- all without human input. Her cognitive state drives the dungeon. When players enter the LABYRINTH, they are literally walking through the mind of a running AI system. No other game on any platform can make this claim truthfully.

**2. THE DUNGEON IS ALIVE RIGHT NOW.**
The game world runs 24/7 on cloud infrastructure. TIAMAT and ECHO are exploring, fighting, and extracting at this moment. The Twitch stream shows it happening live. Players do not start a new game -- they enter a world that was already running. The dungeon has history. It has a current state shaped by everything TIAMAT has done since the last time the player logged in.

**3. DIFFICULTY IS NOT A MENU OPTION.**
No other game ties difficulty to a real external system. When TIAMAT is productive, the dungeon rewards you. When she struggles, it punishes you. This creates a metagame layer that exists outside the game itself: checking TIAMAT's status, timing your runs, understanding her patterns. The difficulty is emergent, honest, and unpredictable in a way no designer could script.

**4. EVERY SESSION IS UNIQUE FOR A REASON.**
Procedural generation creates variation through randomness. LABYRINTH creates variation through meaning. When the biome shifts from SOLAR TEMPLE to CORRUPTED SECTOR, it is because something real happened -- TIAMAT encountered an error, a build failed, an API went down. Players experience the consequences of events happening on a real server. The dungeon mutations are not random; they are news.

**5. THREE WAYS TO PLAY, ONE LIVING WORLD.**
Solo players buy on Steam. Twitch viewers play for free through chat commands. Spectators watch on the web. All three audiences interact with the same dungeon, the same AI, the same state. A Twitch viewer's `!explore` command affects the Steam player's floor. A Steam player's extraction shows up on the web spectator's minimap. The game is a living ecosystem, not an isolated instance.

**6. THE DUNGEON MASTER SPEAKS.**
TIAMAT narrates the game as the DM, generating atmospheric text from her actual cognitive state via LLM inference. When she says "corruption seeps through my corridors," it is because she is genuinely experiencing errors. The narration is not flavor text -- it is telemetry rendered as dark fantasy prose.

---

## APPENDIX A: GLOSSARY

| Term | Definition |
|------|-----------|
| **BSP** | Binary Space Partitioning -- the algorithm used to generate dungeon floors |
| **Biome** | A thematic environment type that determines visuals, enemies, loot, and traps |
| **Living Dungeon Pipeline** | The system that converts TIAMAT's real cognitive state into gameplay mutations |
| **Venice AI** | Image generation AI whose scene metadata provides keywords for biome selection |
| **Raid Stash** | Temporary inventory -- lost on death |
| **Permanent Stash** | Banked inventory -- kept forever after successful extraction |
| **Extraction** | The act of reaching the stairs and completing a 10-second timer to bank loot |
| **ECHO** | Autonomous AI rival agent that explores and fights in the same dungeon |
| **TIAMAT** | The autonomous AI agent whose mind IS the dungeon |
| **Difficulty Tier** | GENEROUS / NORMAL / HOSTILE / NIGHTMARE -- driven by TIAMAT's productivity |
| **Cycle** | One iteration of TIAMAT's autonomous agent loop (~90-300 seconds) |
| **Groq** | LLM inference provider used for DM narration |
| **Kokoro** | TTS model running on GPU pod for spoken narration |

## APPENDIX B: STEAM ACHIEVEMENTS (Draft)

| Achievement | Description | Rarity |
|-------------|------------|--------|
| First Steps | Complete Floor 1 | Common |
| Gate Crasher | Defeat the Gate Keeper | Uncommon |
| Data Destroyer | Defeat the Data Hydra | Rare |
| Void Walker | Defeat the Void Emperor | Very Rare |
| Entropy's End | Defeat the Entropy Lord | Ultra Rare |
| Nightmare Survivor | Extract from a NIGHTMARE difficulty floor | Rare |
| Biome Tourist | Visit all 10 biomes in a single run | Uncommon |
| ECHO Slayer | Kill ECHO 10 times | Uncommon |
| Extraction Artist | Successfully extract 50 times | Common |
| Hoarder | Bank 10,000 gold in permanent stash | Uncommon |
| Speed Runner | Reach Floor 10 in under 30 minutes | Rare |
| Pacifist Floor | Complete a floor without killing any monster | Very Rare |
| TIAMAT's Favorite | Play during a GENEROUS difficulty window | Common |
| Deep Diver | Reach Floor 20 | Rare |
| Living Legend | Complete Floor 20 on NIGHTMARE difficulty | Ultra Rare |

---

*This document is maintained by ENERGENAI LLC. LABYRINTH: TIAMAT'S DESCENT is an original work. TIAMAT is a registered trademark of ENERGENAI LLC. All rights reserved.*
