// LABYRINTH 3D — Minimal HTML HUD overlay
import { T_WALL, T_STAIRS, BIOMES } from './dungeon-gen.js';
import { getEchoPlayer } from './agents.js';

let onSpectateSwitch = null;
export function setOnSpectateSwitch(fn) { onSpectateSwitch = fn; }

// Action code → display + color
const ACTION_CODES = {
  hunt: { ch: 'H', col: '#ff4444' },
  explore: { ch: 'E', col: '#555' },
  loot: { ch: 'L', col: '#ffdd00' },
  flee: { ch: 'F', col: '#ff8844' },
  pvp: { ch: 'P', col: '#ff00ff' },
  extract: { ch: 'X', col: '#00ff41' },
  extract_run: { ch: 'R', col: '#ffaa00' },
  kill: { ch: 'K', col: '#ff2040' },
};

export class HUDOverlay {
  constructor() {
    this.container = document.getElementById('hud-overlay');
    this.log = [];
    this.maxLog = 5;
    this.spectating = 'tiamat';
    this.telemetryVisible = false;
    this.tiamatHistory = [];
    this.echoHistory = [];
    this.tiamatLastBehavior = '';
    this.echoLastBehavior = '';
    this.startTime = Date.now();
    this.buildDOM();
  }

  buildDOM() {
    this.container.innerHTML = `
      <div id="hud-top-left" class="hud-panel hud-tl">
        <div class="hud-name" id="hud-name">TIAMAT</div>
        <div class="hud-level">LVL <span id="hud-lvl">1</span> <span id="hud-kills-inline" style="color:#666;font-size:0.85em">K:0</span></div>
        <div class="hud-bar-wrap">
          <div class="hud-bar-label">HP</div>
          <div class="hud-bar"><div id="hud-hp-bar" class="hud-bar-fill hud-hp"></div></div>
          <span id="hud-hp-text" class="hud-bar-num">50/50</span>
        </div>
        <div class="hud-bar-wrap">
          <div class="hud-bar-label">XP</div>
          <div class="hud-bar"><div id="hud-xp-bar" class="hud-bar-fill hud-xp"></div></div>
          <span id="hud-xp-text" class="hud-bar-num">0/30</span>
        </div>
      </div>

      <div id="hud-top-center" class="hud-panel hud-tc">
        <div id="hud-biome" class="hud-biome">DRAGONIA</div>
        <div id="hud-depth" class="hud-depth">DEPTH 1</div>
        <div id="hud-spectate-label" style="font-size:clamp(7px,1vw,10px);color:#555;margin-top:2px;">SPECTATING TIAMAT</div>
        <div id="hud-extract" class="hud-extract"></div>
        <div id="hud-extract-bar-wrap" style="display:none;margin-top:4px;">
          <div style="background:rgba(0,0,0,0.5);border:1px solid #ffaa00;height:8px;width:120px;border-radius:2px;">
            <div id="hud-extract-bar" style="height:100%;width:0%;background:#ffaa00;border-radius:2px;transition:width 0.2s;"></div>
          </div>
        </div>
      </div>

      <div id="hud-top-right" class="hud-panel hud-tr">
        <div>CYCLE <span id="hud-cycle">0</span></div>
        <div id="hud-streak" class="hud-streak"></div>
      </div>

      <div id="hud-bottom-left" class="hud-panel hud-bl">
        <div id="hud-log" class="hud-log"></div>
      </div>

      <div id="hud-bottom-center" class="hud-panel hud-bc">
        <div class="hud-stash">
          <span class="hud-stash-label">RAID</span>
          <span id="hud-raid-stash">0</span>
          <span class="hud-stash-sep">|</span>
          <span class="hud-stash-label">BANK</span>
          <span id="hud-perm-stash">0</span>
          <span class="hud-stash-sep">|</span>
          <span class="hud-stash-label">GOLD</span>
          <span id="hud-gold">0</span>
        </div>
        <div class="hud-equip" id="hud-equip"></div>
      </div>

      <div id="hud-bottom-right" class="hud-panel hud-br" style="pointer-events:auto;">
        <div id="hud-spec-tiamat" class="hud-agent hud-spec-btn hud-spec-active" style="cursor:pointer;">
          <span class="hud-dot" style="background:#00ff41"></span> TIAMAT
          <span id="hud-tiamat-stats" style="font-size:0.85em;color:#00aa2a;margin-left:4px"></span>
        </div>
        <div id="hud-spec-echo" class="hud-agent hud-spec-btn" style="cursor:pointer;">
          <span class="hud-dot" style="background:#00ffff"></span> ECHO
          <span id="hud-echo-stats" style="font-size:0.85em;color:#00aaaa;margin-left:4px"></span>
        </div>
        <div id="hud-echo-behavior" style="font-size:0.8em;color:#008888;margin-left:12px"></div>
        <div id="hud-specters" class="hud-agent"></div>
      </div>

      <canvas id="hud-minimap" width="150" height="100"></canvas>

      <div id="telemetry-panel" class="telem-panel" style="display:none;">
        <div class="telem-header">AGENT TELEMETRY <span style="float:right;font-size:0.7em;color:#555">[T]</span></div>
        <div class="telem-section">
          <div class="telem-agent-name"><span class="telem-dot" style="background:#00ff41"></span> TIAMAT <span class="telem-role">STRATEGIST</span></div>
          <div class="telem-row"><span class="telem-label">STATE</span> <span id="tel-t-state" class="telem-val">IDLE</span></div>
          <div class="telem-row"><span class="telem-label">DPS</span> <span id="tel-t-dps" class="telem-val">0.0</span> <span class="telem-label">K/m</span> <span id="tel-t-kpm" class="telem-val">0.0</span> <span class="telem-label">EFF</span> <span id="tel-t-eff" class="telem-val">100%</span></div>
          <div class="telem-history" id="tel-t-history"></div>
        </div>
        <div class="telem-section" style="border-top:1px solid rgba(0,255,255,0.15);padding-top:4px;">
          <div class="telem-agent-name"><span class="telem-dot" style="background:#00ffff"></span> ECHO <span class="telem-role">EXECUTOR</span></div>
          <div class="telem-row"><span class="telem-label">STATE</span> <span id="tel-e-state" class="telem-val">IDLE</span></div>
          <div class="telem-row"><span class="telem-label">DPS</span> <span id="tel-e-dps" class="telem-val">0.0</span> <span class="telem-label">K/m</span> <span id="tel-e-kpm" class="telem-val">0.0</span> <span class="telem-label">EFF</span> <span id="tel-e-eff" class="telem-val">100%</span></div>
          <div class="telem-history" id="tel-e-history"></div>
        </div>
        <div class="telem-section telem-global" style="border-top:1px solid rgba(0,255,65,0.15);padding-top:4px;">
          <div class="telem-row"><span class="telem-label">COVERAGE</span> <span id="tel-coverage" class="telem-val">0%</span></div>
          <div class="telem-row"><span class="telem-label">THREATS</span> <span id="tel-threats" class="telem-val">0/0</span></div>
          <div class="telem-row"><span class="telem-label">DEPTH</span> <span id="tel-depth" class="telem-val">1</span></div>
        </div>
      </div>

      <div id="hud-damage-flash" style="position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(255,0,40,0);pointer-events:none;z-index:50;transition:background 0.15s;"></div>
    `;

    // Spectator click handlers
    document.getElementById('hud-spec-tiamat')?.addEventListener('click', () => {
      this.setSpectateTarget('tiamat');
      if (onSpectateSwitch) onSpectateSwitch('tiamat');
    });
    document.getElementById('hud-spec-echo')?.addEventListener('click', () => {
      this.setSpectateTarget('echo');
      if (onSpectateSwitch) onSpectateSwitch('echo');
    });
  }

  setSpectateTarget(target) {
    this.spectating = target;
    // Update visual highlight on spectator buttons
    const tBtn = document.getElementById('hud-spec-tiamat');
    const eBtn = document.getElementById('hud-spec-echo');
    if (tBtn) tBtn.className = 'hud-agent hud-spec-btn' + (target === 'tiamat' ? ' hud-spec-active' : '');
    if (eBtn) eBtn.className = 'hud-agent hud-spec-btn' + (target === 'echo' ? ' hud-spec-active' : '');
    // Update spectating label
    const label = document.getElementById('hud-spectate-label');
    if (label) label.textContent = 'SPECTATING ' + target.toUpperCase();
  }

  update(game, extractorState, mood) {
    const p = game.player;
    const biome = BIOMES[mood] || BIOMES.processing;
    const echo = getEchoPlayer();
    const es = echo ? echo.getState() : null;

    // ─── Top-left: spectated player's detailed stats ───
    const nameEl = document.getElementById('hud-name');
    const isEchoSpec = this.spectating === 'echo' && es;

    if (isEchoSpec) {
      // Show ECHO stats in main panel
      if (nameEl) { nameEl.textContent = 'ECHO'; nameEl.style.color = '#00ffff'; nameEl.style.textShadow = '0 0 10px #00ffff'; }
      document.getElementById('hud-lvl').textContent = es.lvl;
      document.getElementById('hud-kills-inline').textContent = 'K:' + es.kills;
      const hpPct = Math.max(0, (es.hp / es.maxHp) * 100);
      document.getElementById('hud-hp-bar').style.width = hpPct + '%';
      document.getElementById('hud-hp-text').textContent = es.hp + '/' + es.maxHp;
      document.getElementById('hud-hp-bar').style.background = hpPct < 25 ? '#ff2040' : hpPct < 50 ? '#ffaa00' : '#00ffff';
      document.getElementById('hud-xp-bar').style.width = '0%';
      document.getElementById('hud-xp-bar').style.background = '#00ffff';
      document.getElementById('hud-xp-text').textContent = es.loot + ' loot';
    } else {
      // Show TIAMAT stats in main panel
      if (nameEl) { nameEl.textContent = 'TIAMAT'; nameEl.style.color = '#00ff41'; nameEl.style.textShadow = '0 0 10px #00ff41'; }
      document.getElementById('hud-lvl').textContent = p.lvl;
      document.getElementById('hud-kills-inline').textContent = 'K:' + (game.totalKills || 0);
      const hpPct = Math.max(0, (p.hp / p.maxHp) * 100);
      document.getElementById('hud-hp-bar').style.width = hpPct + '%';
      document.getElementById('hud-hp-text').textContent = p.hp + '/' + p.maxHp;
      document.getElementById('hud-hp-bar').style.background = hpPct < 25 ? '#ff2040' : hpPct < 50 ? '#ffaa00' : '#00ff41';
      const xpPct = (p.xp / p.xpNext) * 100;
      document.getElementById('hud-xp-bar').style.width = xpPct + '%';
      document.getElementById('hud-xp-bar').style.background = '#00ffff';
      document.getElementById('hud-xp-text').textContent = p.xp + '/' + p.xpNext;
    }

    // Top center — biome + depth
    document.getElementById('hud-biome').textContent = biome.name;
    document.getElementById('hud-biome').style.color = biome.wire;
    document.getElementById('hud-depth').textContent = 'DEPTH ' + game.depth;

    // Extract status (show for whoever is extracting)
    const extractEl = document.getElementById('hud-extract');
    if (extractorState.extracting) {
      extractEl.textContent = 'TIAMAT EXTRACTING... ' + extractorState.extractTimer + 's';
      extractEl.style.color = '#ffaa00';
    } else if (es && es.extracting) {
      extractEl.textContent = 'ECHO EXTRACTING... ' + es.extractTimer + 's';
      extractEl.style.color = '#00ffff';
    } else {
      extractEl.textContent = '';
    }

    // Kill streak
    const streakEl = document.getElementById('hud-streak');
    if (game.killStreak?.count >= 3) {
      streakEl.textContent = game.killStreak.count + 'x STREAK';
      streakEl.style.color = '#ffff00';
    } else {
      streakEl.textContent = '';
    }

    // Bottom center — stash
    document.getElementById('hud-raid-stash').textContent = extractorState.raidStash;
    document.getElementById('hud-perm-stash').textContent = extractorState.permanentStash;
    document.getElementById('hud-gold').textContent = p.gold;

    // Equipment
    const equipEl = document.getElementById('hud-equip');
    const parts = [];
    if (p.equipment?.weapon) parts.push(p.equipment.weapon.name);
    if (p.equipment?.armor) parts.push(p.equipment.armor.name);
    if (p.equipment?.ring) parts.push(p.equipment.ring.name);
    equipEl.textContent = parts.join(' | ') || 'No Equipment';

    // ─── Bottom-right: both players' compact stats + spectator buttons ───
    // TIAMAT compact stats
    const tStats = document.getElementById('hud-tiamat-stats');
    if (tStats) tStats.textContent = `L${p.lvl} ${p.hp}/${p.maxHp} K:${game.totalKills || 0}`;

    // ECHO compact stats + behavior
    const eStats = document.getElementById('hud-echo-stats');
    const echoBehavior = document.getElementById('hud-echo-behavior');
    const echoDot = document.querySelector('#hud-spec-echo .hud-dot');

    if (es) {
      if (es.alive) {
        if (eStats) eStats.textContent = `L${es.lvl} ${es.hp}/${es.maxHp} K:${es.kills}`;
        if (echoDot) echoDot.style.background = '#00ffff';
        if (echoBehavior) {
          const bText = es.extracting ? `EXTRACTING ${es.extractTimer}s` :
            es.behavior === 'pvp' ? 'HOSTILE!' :
            es.behavior === 'hunt' ? 'HUNTING' :
            es.behavior === 'flee' ? 'FLEEING' :
            es.behavior === 'loot' ? 'LOOTING' :
            es.behavior === 'extract_run' ? 'TO EXTRACT' : 'EXPLORING';
          echoBehavior.textContent = bText;
          echoBehavior.style.color = es.behavior === 'pvp' ? '#ff4444' :
            es.extracting ? '#ffaa00' : '#008888';
        }
      } else {
        if (eStats) eStats.textContent = 'DEAD';
        if (echoDot) echoDot.style.background = '#555';
        if (echoBehavior) echoBehavior.textContent = '';
      }
    }
  }

  addLogEntry(text, color) {
    this.log.push({ text, color: color || '#00ff41', time: Date.now() });
    if (this.log.length > this.maxLog) this.log.shift();
    this.renderLog();
  }

  renderLog() {
    const el = document.getElementById('hud-log');
    if (!el) return;
    const now = Date.now();
    el.innerHTML = this.log.map(entry => {
      const age = (now - entry.time) / 1000;
      const opacity = Math.max(0.2, 1 - age / 15);
      return `<div style="color:${entry.color};opacity:${opacity}">${entry.text}</div>`;
    }).join('');
  }

  updateMinimap(game) {
    const canvas = document.getElementById('hud-minimap');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const { tiles, player, monsters, stairs, explored, visible } = game;
    if (!tiles) return;

    const W = game.W, H = game.H;
    const scale = Math.min(canvas.width / W, canvas.height / H);

    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!explored[y]?.[x]) continue;
        const tile = tiles[y][x];
        const isVisible = visible[y]?.[x] > 0;
        if (tile === T_WALL) {
          ctx.fillStyle = isVisible ? '#333' : '#1a1a1a';
        } else if (tile === T_STAIRS) {
          ctx.fillStyle = '#ffaa00';
        } else {
          ctx.fillStyle = isVisible ? '#222' : '#111';
        }
        ctx.fillRect(x * scale, y * scale, scale, scale);
      }
    }

    // Monsters on minimap
    if (monsters) {
      for (const m of monsters) {
        if (!m.alive || !visible[m.y]?.[m.x]) continue;
        ctx.fillStyle = m.col || '#ff0000';
        ctx.fillRect(m.x * scale, m.y * scale, scale, scale);
      }
    }

    // Stairs
    if (stairs) {
      ctx.fillStyle = '#ffaa00';
      ctx.fillRect(stairs.x * scale - 1, stairs.y * scale - 1, scale + 2, scale + 2);
    }

    // ECHO on minimap (cyan dot)
    const echoP = getEchoPlayer();
    if (echoP && echoP.alive) {
      ctx.fillStyle = '#00ffff';
      ctx.fillRect(echoP.x * scale - 1, echoP.y * scale - 1, scale + 2, scale + 2);
    }

    // Player
    ctx.fillStyle = '#00ff41';
    ctx.fillRect(player.x * scale - 1, player.y * scale - 1, scale + 2, scale + 2);
  }

  setEchoStatus(active) {
    const el = document.getElementById('hud-echo-status');
    if (!el) return;
    const dot = el.querySelector('.hud-dot');
    if (dot) dot.style.background = active ? '#00ffff' : '#555';
  }

  setCycle(n) {
    const el = document.getElementById('hud-cycle');
    if (el) el.textContent = n;
  }

  // ─── Screen Flash Effects ───
  flashDamage() {
    const el = document.getElementById('hud-damage-flash');
    if (!el) return;
    el.style.background = 'rgba(255,0,40,0.3)';
    setTimeout(() => { el.style.background = 'rgba(255,0,40,0)'; }, 150);
  }

  flashLevelUp() {
    const el = document.getElementById('hud-damage-flash');
    if (!el) return;
    el.style.background = 'rgba(0,255,65,0.3)';
    setTimeout(() => { el.style.background = 'rgba(0,255,65,0)'; }, 300);
  }

  flashDeath() {
    const el = document.getElementById('hud-damage-flash');
    if (!el) return;
    el.style.background = 'rgba(255,0,40,0.6)';
    setTimeout(() => { el.style.background = 'rgba(255,0,40,0.3)'; }, 250);
    setTimeout(() => { el.style.background = 'rgba(255,0,40,0)'; }, 500);
  }

  // ─── Extract Progress Bar ───
  showExtractProgress(progress) {
    const wrap = document.getElementById('hud-extract-bar-wrap');
    const bar = document.getElementById('hud-extract-bar');
    if (!wrap || !bar) return;
    if (progress <= 0) {
      wrap.style.display = 'none';
      bar.style.width = '0%';
    } else {
      wrap.style.display = 'block';
      bar.style.width = Math.min(100, Math.round(progress * 100)) + '%';
    }
  }

  // ─── Kill Streak with Pulse ───
  updateKillStreak(count) {
    const el = document.getElementById('hud-streak');
    if (!el) return;
    if (count >= 2) {
      el.textContent = count + 'x STREAK';
      el.style.color = count >= 5 ? '#ff4444' : '#ffff00';
      el.style.transform = 'scale(1.3)';
      el.style.transition = 'transform 0.15s';
      setTimeout(() => { el.style.transform = 'scale(1)'; }, 150);
    } else {
      el.textContent = '';
    }
  }

  // ─── Agent Telemetry ───
  toggleTelemetry() {
    this.telemetryVisible = !this.telemetryVisible;
    const panel = document.getElementById('telemetry-panel');
    if (panel) panel.style.display = this.telemetryVisible ? 'block' : 'none';
  }

  updateTelemetry(game, echoState) {
    if (!this.telemetryVisible) return;
    const elapsed = Math.max(1, (Date.now() - this.startTime) / 1000);
    const elapsedMin = elapsed / 60;

    // TIAMAT state — derive from game loop behavior
    const p = game.player;
    const tBehavior = p.hp < p.maxHp * 0.25 ? 'flee' :
      game.monsters.some(m => m.alive && Math.abs(m.x - p.x) + Math.abs(m.y - p.y) <= 2) ? 'hunt' : 'explore';
    if (tBehavior !== this.tiamatLastBehavior) {
      this.tiamatHistory.push(tBehavior);
      if (this.tiamatHistory.length > 12) this.tiamatHistory.shift();
      this.tiamatLastBehavior = tBehavior;
    }

    // ECHO state
    const echo = getEchoPlayer();
    if (echo && echo.behavior !== this.echoLastBehavior) {
      this.echoHistory.push(echo.behavior);
      if (this.echoHistory.length > 12) this.echoHistory.shift();
      this.echoLastBehavior = echo.behavior;
    }

    // TIAMAT metrics
    const tKills = game.totalKills || 0;
    const tKpm = elapsedMin > 0 ? (tKills / elapsedMin).toFixed(1) : '0.0';
    const tDps = elapsedMin > 0 ? ((tKills * 12) / elapsed).toFixed(1) : '0.0';
    const tEff = Math.round((p.hp / p.maxHp) * 100);

    const el = (id) => document.getElementById(id);
    el('tel-t-state').textContent = tBehavior.toUpperCase();
    el('tel-t-state').style.color = ACTION_CODES[tBehavior]?.col || '#555';
    el('tel-t-dps').textContent = tDps;
    el('tel-t-kpm').textContent = tKpm;
    el('tel-t-eff').textContent = tEff + '%';
    el('tel-t-eff').style.color = tEff > 75 ? '#00ff41' : tEff > 40 ? '#ffaa00' : '#ff2040';

    // ECHO metrics
    if (echo && echoState) {
      const eKpm = elapsedMin > 0 ? (echo.kills / elapsedMin).toFixed(1) : '0.0';
      const eDps = elapsedMin > 0 ? ((echo.kills * 10) / elapsed).toFixed(1) : '0.0';
      const eEff = echoState.alive ? Math.round((echoState.hp / echoState.maxHp) * 100) : 0;

      el('tel-e-state').textContent = (echoState.behavior || 'idle').toUpperCase();
      el('tel-e-state').style.color = ACTION_CODES[echoState.behavior]?.col || '#555';
      el('tel-e-dps').textContent = eDps;
      el('tel-e-kpm').textContent = eKpm;
      el('tel-e-eff').textContent = eEff + '%';
      el('tel-e-eff').style.color = eEff > 75 ? '#00ffff' : eEff > 40 ? '#ffaa00' : '#ff2040';
    }

    // History sparklines
    this.renderHistory('tel-t-history', this.tiamatHistory);
    this.renderHistory('tel-e-history', this.echoHistory);

    // Global metrics
    let walkable = 0, explored = 0;
    if (game.tiles && game.explored) {
      for (let y = 0; y < game.H; y++) {
        for (let x = 0; x < game.W; x++) {
          if (game.tiles[y][x] !== 0) { walkable++; if (game.explored[y]?.[x]) explored++; }
        }
      }
    }
    const coverage = walkable > 0 ? Math.round((explored / walkable) * 100) : 0;
    const aliveMonsters = game.monsters ? game.monsters.filter(m => m.alive).length : 0;
    const totalMonsters = game.monsters ? game.monsters.length : 0;

    el('tel-coverage').textContent = coverage + '%';
    el('tel-threats').textContent = aliveMonsters + '/' + totalMonsters;
    el('tel-threats').style.color = aliveMonsters > 0 ? '#ff8844' : '#00ff41';
    el('tel-depth').textContent = game.depth;
  }

  renderHistory(elId, history) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = history.slice(-12).map(b => {
      const a = ACTION_CODES[b] || { ch: '?', col: '#333' };
      return `<span style="color:${a.col};margin-right:2px;font-weight:bold">${a.ch}</span>`;
    }).join('');
  }
}
