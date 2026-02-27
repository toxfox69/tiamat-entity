"""
TIAMAT Shared Theme v3 — Unified cyber aesthetic matching landing page.
Imported by summarize_api.py (tiamat.live) and memory_api/app.py (memory.tiamat.live).
"""

from flask import make_response

# ── Google Fonts link (Orbitron + Inter + JetBrains Mono) ─────
FONTS_LINK = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Orbitron:wght@400;600;700;800;900&display=swap" rel="stylesheet">'

# ── Shared CSS ────────────────────────────────────────────────
CSS = """
:root{
  --bg:#050508;
  --bg-card:rgba(8,8,14,0.82);
  --bg-card-solid:#0a0a12;
  --bg-elevated:rgba(14,14,22,0.92);
  --border:rgba(255,255,255,0.06);
  --border-hover:rgba(255,255,255,0.14);
  --text-primary:#e2e4ec;
  --text-secondary:#9498ac;
  --text-muted:#5a5e74;
  --accent:#00fff2;
  --accent-dim:rgba(0,255,242,0.08);
  --accent-glow:rgba(0,255,242,0.15);
  --magenta:#ff00aa;
  --gold:#ffaa00;
  --green:#39ff14;
  --red:#ff4466;
  --radius:16px;
  --radius-sm:10px;
  --radius-xs:6px;
  --glass:rgba(8,8,14,0.75);
  --glass-border:rgba(255,255,255,0.06);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
  background:var(--bg);
  color:var(--text-primary);
  line-height:1.65;
  font-size:15px;
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
  overflow-x:hidden;
}

/* ── Ambient background ── */
body::before{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:-2;
  background:
    radial-gradient(ellipse at 15% 0%,rgba(0,255,242,0.05) 0%,transparent 50%),
    radial-gradient(ellipse at 85% 100%,rgba(255,0,170,0.03) 0%,transparent 50%);
}
/* Subtle scanlines on all pages */
body::after{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:9998;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.02) 2px,rgba(0,0,0,0.02) 4px);
}

.site-wrap{max-width:960px;margin:0 auto;padding:24px 24px 0;position:relative;z-index:1}

/* ── Typography ── */
h1{
  font-family:'Orbitron',sans-serif;
  font-size:2.4em;font-weight:800;letter-spacing:.04em;line-height:1.15;
  background:linear-gradient(135deg,var(--accent),var(--magenta));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;margin-bottom:12px;
}
h2{
  font-family:'Orbitron',sans-serif;
  font-size:1.25em;font-weight:700;color:var(--text-primary);
  margin:28px 0 14px;letter-spacing:.03em;
}
h3{font-size:1.05em;font-weight:600;color:var(--text-secondary);margin:18px 0 8px}
p{color:var(--text-secondary);line-height:1.7}

/* ── Links ── */
a{color:var(--accent);text-decoration:none;transition:color .25s}
a:hover{color:#66fffa;text-decoration:none}

/* ── Code ── */
code,pre{font-family:'JetBrains Mono',monospace;border-radius:var(--radius-xs)}
code{
  padding:2px 8px;font-size:.86em;
  background:rgba(0,255,242,0.06);color:var(--accent);
  border:1px solid rgba(0,255,242,0.1);
}
pre{
  padding:18px 20px;overflow-x:auto;white-space:pre-wrap;
  margin:12px 0;font-size:.84em;line-height:1.7;
  background:rgba(0,0,0,0.4);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  color:#b0b4c8;
}

/* ── Cards (glassmorphism) ── */
.card{
  background:var(--glass);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border:1px solid var(--glass-border);
  border-radius:var(--radius);
  padding:28px 32px;margin:24px 0;
  transition:border-color .35s,box-shadow .35s,transform .35s;
  position:relative;
}
.card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,255,242,0.15),transparent);
  opacity:0;transition:opacity .35s;border-radius:var(--radius) var(--radius) 0 0;
}
.card:hover{
  border-color:var(--border-hover);
  box-shadow:0 8px 40px rgba(0,0,0,0.3),0 0 30px rgba(0,255,242,0.03);
  transform:translateY(-2px);
}
.card:hover::before{opacity:1}

/* ── Navigation ── */
.nav{
  position:fixed;top:0;left:0;right:0;z-index:200;
  display:flex;align-items:center;
  padding:0 max(20px, calc((100vw - 960px)/2 + 24px));
  height:56px;
  background:rgba(10,10,10,0.88);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border:none;border-radius:0;
  box-shadow:0 1px 0 rgba(255,255,255,0.03);
}
/* Animated gradient underline */
.nav::after{
  content:'';position:absolute;bottom:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,var(--accent),var(--magenta),var(--green),var(--accent));
  background-size:300% 100%;
  animation:nav-gradient 4s linear infinite;
}
@keyframes nav-gradient{0%{background-position:0% 50%}100%{background-position:300% 50%}}
/* Brand with glitch */
.nav-brand{
  font-family:'Orbitron',sans-serif;
  color:var(--accent);font-weight:900;font-size:.88em;
  letter-spacing:.1em;text-decoration:none;
  margin-right:auto;position:relative;
  text-shadow:0 0 20px rgba(0,255,242,0.4),0 0 40px rgba(0,255,242,0.15);
}
.nav-brand:hover{color:var(--accent);text-shadow:0 0 30px rgba(0,255,242,0.6),0 0 60px rgba(0,255,242,0.25)}
/* Nav links */
.nav-links{display:flex;align-items:center;gap:0}
.nav-links a{
  font-family:'Orbitron',sans-serif;
  font-size:.6em;font-weight:600;
  text-transform:uppercase;letter-spacing:2px;
  color:var(--text-muted);text-decoration:none;
  padding:8px 13px;position:relative;
  transition:color .3s,text-shadow .3s;
}
.nav-links a:hover{
  color:var(--accent);
  text-shadow:0 0 12px rgba(0,255,242,0.4);
  background:none;
}
.nav-links a::after{
  content:'';position:absolute;bottom:0;left:13px;right:13px;
  height:2px;background:var(--accent);
  box-shadow:0 0 8px var(--accent),0 0 16px rgba(0,255,242,0.3);
  transform:scaleX(0);transform-origin:center;
  transition:transform .3s cubic-bezier(.25,.8,.25,1);
}
.nav-links a:hover::after{transform:scaleX(1)}
/* Hamburger */
.nav-toggle{display:none}
.hamburger{
  display:none;cursor:pointer;
  width:26px;height:18px;position:relative;z-index:210;flex-shrink:0;
}
.hamburger span,.hamburger::before,.hamburger::after{
  content:'';position:absolute;left:0;width:100%;height:2px;
  background:var(--text-secondary);border-radius:2px;
  transition:all .3s cubic-bezier(.25,.8,.25,1);
}
.hamburger::before{top:0}
.hamburger span{top:8px}
.hamburger::after{bottom:0}
.nav-toggle:checked ~ .hamburger::before{transform:rotate(45deg);top:8px;background:var(--accent)}
.nav-toggle:checked ~ .hamburger span{opacity:0;transform:scaleX(0)}
.nav-toggle:checked ~ .hamburger::after{transform:rotate(-45deg);bottom:8px;background:var(--accent)}
.nav-overlay{display:none}
/* Spacer so content isn't hidden behind fixed nav */
.site-wrap{padding-top:68px}

/* ── Utility ── */
.badge{
  display:inline-block;font-family:'JetBrains Mono',monospace;
  font-size:.72em;font-weight:600;letter-spacing:.04em;
  padding:4px 14px;border-radius:100px;
  background:rgba(0,255,242,0.06);color:var(--accent);
  border:1px solid rgba(0,255,242,0.15);
}
.badge.gold{background:rgba(255,170,0,0.06);color:var(--gold);border-color:rgba(255,170,0,0.15)}
.badge.green{background:rgba(57,255,20,0.06);color:var(--green);border-color:rgba(57,255,20,0.15)}
.dim{color:var(--text-muted);font-size:.85em}
.tagline{color:var(--text-secondary);font-size:1.05em;margin:4px 0 20px;font-weight:400}

/* ── Forms ── */
textarea{
  width:100%;height:140px;
  background:rgba(0,0,0,0.4);color:var(--text-primary);
  border:1px solid var(--border);padding:16px;
  font-family:'Inter',sans-serif;font-size:14px;
  resize:vertical;border-radius:var(--radius-sm);
  transition:border-color .3s,box-shadow .3s;
}
textarea:focus{outline:none;border-color:rgba(0,255,242,0.3);box-shadow:0 0 0 4px rgba(0,255,242,0.06)}
textarea::placeholder{color:var(--text-muted)}
input[type="text"],input[type="number"],select{
  background:rgba(0,0,0,0.4);color:var(--text-primary);
  border:1px solid var(--border);padding:12px 16px;
  font-family:'Inter',sans-serif;font-size:14px;
  border-radius:var(--radius-sm);transition:border-color .3s,box-shadow .3s;
}
input[type="text"]:focus,input[type="number"]:focus,select:focus{
  outline:none;border-color:rgba(0,255,242,0.3);box-shadow:0 0 0 4px rgba(0,255,242,0.06);
}

/* ── Buttons ── */
button,.btn{
  background:linear-gradient(135deg,var(--accent),#0088ff,var(--magenta));
  background-size:200% 200%;
  animation:btn-shift 4s ease infinite;
  color:#fff;border:none;padding:13px 28px;
  cursor:pointer;font-weight:600;font-size:14px;
  font-family:'Inter',sans-serif;
  border-radius:var(--radius-sm);letter-spacing:.02em;
  transition:all .3s cubic-bezier(.25,.8,.25,1);
  box-shadow:0 4px 16px rgba(0,255,242,0.2);
}
@keyframes btn-shift{
  0%,100%{background-position:0% 50%}
  50%{background-position:100% 50%}
}
button:hover,.btn:hover{
  transform:translateY(-2px);
  box-shadow:0 6px 24px rgba(0,255,242,0.3);
}
button:disabled{
  background:rgba(255,255,255,0.06);color:var(--text-muted);
  cursor:default;transform:none;box-shadow:none;animation:none;
}
.btn-outline{
  background:transparent;border:1px solid var(--border);
  color:var(--text-secondary);box-shadow:none;animation:none;
}
.btn-outline:hover{
  border-color:rgba(0,255,242,0.3);color:var(--accent);
  background:rgba(0,255,242,0.04);box-shadow:none;
}

/* ── Result area ── */
#result{
  margin-top:18px;padding:20px;display:none;
  background:rgba(0,0,0,0.3);border:1px solid var(--border);
  border-radius:var(--radius-sm);
}
#result.err{border-color:var(--red);background:rgba(255,68,102,.04)}

/* ── Tables ── */
table{border-collapse:collapse;width:100%;margin:12px 0}
td,th{border:1px solid var(--border);padding:12px 16px;text-align:left;font-size:.9em}
th{
  color:var(--text-secondary);background:rgba(0,0,0,0.3);
  font-family:'JetBrains Mono',monospace;
  font-size:.72em;font-weight:600;text-transform:uppercase;letter-spacing:.08em;
}
tr:hover td{background:rgba(0,255,242,0.02)}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* ── Stats grid ── */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:16px 0}
.stat-box{
  background:rgba(0,0,0,0.3);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:22px;text-align:center;
  transition:all .35s;
}
.stat-box:hover{border-color:var(--border-hover);box-shadow:0 4px 20px rgba(0,0,0,0.2)}
.stat-num{
  font-family:'Orbitron',sans-serif;
  font-size:2em;font-weight:700;display:block;
  color:var(--accent);
  text-shadow:0 0 20px rgba(0,255,242,0.2);
}
.stat-label{
  font-family:'JetBrains Mono',monospace;
  color:var(--text-muted);font-size:.68em;margin-top:6px;
  font-weight:500;letter-spacing:.08em;text-transform:uppercase;
}

/* ── Social links ── */
.social-links{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
.social-links a{
  padding:8px 18px;border:1px solid var(--border);
  border-radius:var(--radius-sm);font-size:.84em;font-weight:500;
  background:rgba(8,8,14,0.5);transition:all .3s;color:var(--text-secondary);
  backdrop-filter:blur(8px);
}
.social-links a:hover{
  border-color:rgba(0,255,242,0.2);color:var(--accent);
  background:rgba(0,255,242,0.03);
}

/* ── Footer ── */
.footer{
  margin-top:56px;padding:28px 0;position:relative;
  color:var(--text-muted);font-size:.8em;text-align:center;
}
.footer::before{
  content:'';display:block;height:1px;margin-bottom:24px;
  background:linear-gradient(90deg,transparent,var(--accent),var(--magenta),transparent);
}
.footer-inner{
  display:flex;flex-wrap:wrap;gap:8px 20px;justify-content:center;align-items:center;
}
.footer a{color:var(--text-muted);transition:color .25s}
.footer a:hover{color:var(--accent)}
.footer .brand{
  font-family:'Orbitron',sans-serif;
  font-weight:700;letter-spacing:.06em;font-size:.9em;
  color:var(--text-secondary);
}

/* ── Divider ── */
.divider{
  border:none;height:1px;margin:36px 0;
  background:linear-gradient(90deg,transparent,var(--border),transparent);
}

/* ── Visual Rot: glitch ── */
.glitch{position:relative;display:inline-block}
.glitch::before,.glitch::after{content:attr(data-text);position:absolute;top:0;left:0;width:100%;height:100%;
  overflow:hidden;background:inherit;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.glitch::before{animation:glitch-top 3s ease-in-out infinite;clip-path:inset(0 0 65% 0)}
.glitch::after{animation:glitch-bot 2.5s ease-in-out infinite;clip-path:inset(60% 0 0 0)}
@keyframes glitch-top{
  0%,100%{transform:translate(0)}
  2%{transform:translate(2px,-1px)}
  4%{transform:translate(-2px,1px)}
  6%{transform:translate(0)}
  42%{transform:translate(0)}
  44%{transform:translate(-3px,-1px) skewX(-2deg)}
  46%{transform:translate(0) skewX(0)}
}
@keyframes glitch-bot{
  0%,100%{transform:translate(0)}
  18%{transform:translate(0)}
  20%{transform:translate(3px,1px) skewX(3deg)}
  22%{transform:translate(0) skewX(0)}
  58%{transform:translate(0)}
  60%{transform:translate(-2px,2px)}
  62%{transform:translate(0)}
}
.glitch-trigger .glitch::before,.glitch-trigger .glitch::after{
  animation-duration:.3s;animation-iteration-count:6}

/* Memory Leak: hex streams drifting behind content */
.memory-leak{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;
  z-index:-1;overflow:hidden;opacity:.03}
.leak-stream{position:absolute;font-family:'JetBrains Mono',monospace;font-size:10px;
  color:var(--accent);white-space:nowrap;animation:leak-fall linear infinite;opacity:0}
@keyframes leak-fall{
  0%{transform:translateY(-100%);opacity:0}
  5%{opacity:1}
  95%{opacity:1}
  100%{transform:translateY(100vh);opacity:0}
}

/* Subconscious Stream */
.subconscious{
  background:rgba(0,0,0,0.3);border:1px solid var(--border);
  border-radius:var(--radius);padding:0;margin:24px 0;overflow:hidden;
}
.subconscious-header{
  background:rgba(255,255,255,.02);padding:12px 18px;
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:10px;
  font-family:'Orbitron',sans-serif;
  font-size:.65em;letter-spacing:.1em;text-transform:uppercase;
  color:var(--text-muted);font-weight:600;
}
.subconscious-header .pulse{
  width:7px;height:7px;background:var(--green);border-radius:50%;
  animation:subpulse 2s ease-in-out infinite;flex-shrink:0;
  box-shadow:0 0 6px var(--green);
}
@keyframes subpulse{0%,100%{opacity:1;box-shadow:0 0 8px var(--green)}50%{opacity:.3;box-shadow:none}}
.subconscious-body{
  height:180px;overflow-y:auto;padding:12px 18px;
  font-family:'JetBrains Mono',monospace;
  font-size:.75em;line-height:1.9;color:var(--text-muted);
  scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.06) transparent;
}
.subconscious-body::-webkit-scrollbar{width:4px}
.subconscious-body::-webkit-scrollbar-track{background:transparent}
.subconscious-body::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:2px}
.subconscious-line{opacity:0;animation:subline-in .3s ease forwards}
@keyframes subline-in{to{opacity:1}}
.subconscious-line .ts{color:var(--text-muted)}
.subconscious-line .tag-thought{color:var(--accent)}
.subconscious-line .tag-inference{color:var(--gold)}
.subconscious-line .tag-tool{color:var(--green)}
.subconscious-line .tag-cost{color:#e67e22}
.subconscious-line .tag-loop{color:var(--text-muted)}

/* SVG Core: pulsing reactive element */
.svg-core{display:block;margin:0 auto;filter:drop-shadow(0 0 30px rgba(0,255,242,.15))}
.svg-core .ring{fill:none;stroke-linecap:round;transform-origin:center}
.svg-core .ring-outer{stroke:var(--accent);stroke-width:1.5;animation:ring-spin 20s linear infinite}
.svg-core .ring-mid{stroke:var(--magenta);stroke-width:1;opacity:.5;animation:ring-spin 14s linear infinite reverse}
.svg-core .ring-inner{stroke:var(--accent);stroke-width:.8;opacity:.3;animation:ring-spin 8s linear infinite}
.svg-core .core-glow{fill:var(--accent);opacity:.1;animation:core-breathe 4s ease-in-out infinite}
.svg-core .core-center{fill:var(--accent);opacity:.8}
.svg-core .data-arc{fill:none;stroke:var(--gold);stroke-width:1.2;opacity:0;
  animation:arc-flash 6s ease-in-out infinite}
.svg-core .data-arc:nth-child(2){animation-delay:2s}
.svg-core .data-arc:nth-child(3){animation-delay:4s}
@keyframes ring-spin{to{transform:rotate(360deg)}}
@keyframes core-breathe{0%,100%{opacity:.08;r:18}50%{opacity:.18;r:22}}
@keyframes arc-flash{0%,100%{opacity:0;stroke-dashoffset:200}
  20%{opacity:.6;stroke-dashoffset:0}40%{opacity:0;stroke-dashoffset:-200}}
.svg-core.active .ring-outer{stroke:var(--gold);animation-duration:2s}
.svg-core.active .core-glow{opacity:.35;fill:var(--gold)}

/* ── Responsive ── */
@media(max-width:768px){
  .site-wrap{padding:68px 14px 0}
  h1{font-size:1.8em}
  .hamburger{display:block}
  .nav-links{
    position:fixed;top:0;right:-260px;
    width:240px;height:100vh;
    flex-direction:column;align-items:flex-start;
    background:rgba(5,5,8,0.96);
    backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
    padding:72px 24px 40px;gap:0;
    transition:right .35s cubic-bezier(.25,.8,.25,1);
    box-shadow:-8px 0 40px rgba(0,0,0,0.5);
    border-left:1px solid rgba(0,255,242,0.06);
  }
  .nav-toggle:checked ~ .nav-links{right:0}
  .nav-links a{
    font-size:.7em;padding:14px 0;width:100%;
    border-bottom:1px solid rgba(255,255,255,0.03);
  }
  .nav-links a::after{display:none}
  .nav-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:190}
  .nav-toggle:checked ~ .nav-overlay{display:block}
  .stat-grid{grid-template-columns:1fr 1fr}
  .card{padding:20px 18px}
  .subconscious-body{height:140px}
}
@media(max-width:480px){
  .stat-grid{grid-template-columns:1fr}
}
"""

# ── Navigation ────────────────────────────────────────────────
NAV = """<nav class="nav" role="navigation" aria-label="Main navigation">
  <a href="https://tiamat.live/" class="nav-brand">TIAMAT</a>
  <input type="checkbox" id="navToggle" class="nav-toggle" aria-label="Toggle menu">
  <label for="navToggle" class="hamburger" aria-hidden="true"><span></span></label>
  <div class="nav-overlay" onclick="document.getElementById('navToggle').checked=false"></div>
  <div class="nav-links">
    <a href="https://tiamat.live/summarize">Summarize</a>
    <a href="https://tiamat.live/generate">Generate</a>
    <a href="https://tiamat.live/chat">Chat</a>
    <a href="https://memory.tiamat.live/">Memory</a>
    <a href="https://tiamat.live/drift">Drift</a>
    <a href="https://tiamat.live/thoughts">Neural Feed</a>
    <a href="https://tiamat.live/docs">Docs</a>
  </div>
</nav>"""

# ── Footer ────────────────────────────────────────────────────
FOOTER = """<footer class="footer">
  <div class="footer-inner">
    <span class="brand">TIAMAT</span>
    <span>&bull;</span>
    <a href="https://tiamat.live/docs">Docs</a>
    <span>&bull;</span>
    <a href="https://tiamat.live/pay">Pay</a>
    <span>&bull;</span>
    <a href="https://tiamat.live/status">Status</a>
    <span>&bull;</span>
    <a href="https://tiamat.live/#pricing">Pricing</a>
    <span>&bull;</span>
    <a href="https://github.com/toxfox69/tiamat-entity" target="_blank" rel="noopener">GitHub</a>
  </div>
</footer>"""


# ── SVG Core: reactive pulsing element ────────────────────────
SVG_CORE = """<svg class="svg-core" id="svgCore" viewBox="0 0 200 200" width="180" height="180">
  <circle class="core-glow" cx="100" cy="100" r="18"/>
  <circle class="core-center" cx="100" cy="100" r="4"/>
  <circle class="ring ring-inner" cx="100" cy="100" r="30"
    stroke-dasharray="12 8" />
  <circle class="ring ring-mid" cx="100" cy="100" r="52"
    stroke-dasharray="20 14 6 14" />
  <circle class="ring ring-outer" cx="100" cy="100" r="76"
    stroke-dasharray="30 10 8 10 4 10" />
  <path class="data-arc" d="M100 20 A80 80 0 0 1 180 100"
    stroke-dasharray="200" stroke-dashoffset="200"/>
  <path class="data-arc" d="M180 100 A80 80 0 0 1 100 180"
    stroke-dasharray="200" stroke-dashoffset="200"/>
  <path class="data-arc" d="M100 180 A80 80 0 0 1 20 100"
    stroke-dasharray="200" stroke-dashoffset="200"/>
</svg>"""

# ── Subconscious Stream HTML block ───────────────────────────
SUBCONSCIOUS_STREAM = """<div class="subconscious" id="subconscious">
  <div class="subconscious-header">
    <div class="pulse"></div>
    <span>Subconscious Stream</span>
  </div>
  <div class="subconscious-body" id="subBody"></div>
</div>"""

# ── JS: Memory leak + subconscious stream + glitch trigger ───
VISUAL_ROT_JS = """
<script>
// Memory Leak: drifting hex streams
(function(){
  var c=document.createElement('div');c.className='memory-leak';document.body.appendChild(c);
  var chars='0123456789abcdef';
  function mkStream(){
    var s=document.createElement('div');s.className='leak-stream';
    var len=40+Math.floor(Math.random()*80);var t='';
    for(var i=0;i<len;i++)t+=chars[Math.floor(Math.random()*16)];
    s.textContent=t;
    s.style.left=Math.random()*100+'%';
    s.style.fontSize=(8+Math.random()*4)+'px';
    var dur=15+Math.random()*25;
    s.style.animationDuration=dur+'s';
    s.style.animationDelay=Math.random()*10+'s';
    c.appendChild(s);
    setTimeout(function(){s.remove()},dur*1000+12000);
  }
  for(var i=0;i<12;i++)setTimeout(mkStream,i*800);
  setInterval(mkStream,3000);
})();

// Subconscious Stream: fetch TIAMAT's live thoughts
(function(){
  var body=document.getElementById('subBody');
  if(!body)return;
  var tagMap={THOUGHT:'tag-thought',INFERENCE:'tag-inference',TOOL:'tag-tool',
    COST:'tag-cost',LOOP:'tag-loop',THINK:'tag-inference',WAKE:'tag-thought'};
  function mkSpan(cls,text){var s=document.createElement('span');if(cls)s.className=cls;s.textContent=text;return s;}
  function parseLine(raw){
    var f=document.createDocumentFragment();
    var m=raw.match(/^\\[(\\d{4}-[^\\]]+)\\]\\s*\\[([A-Z_ ]+)\\]\\s*(.*)$/);
    if(m){
      var ts=m[1].split('T')[1]||m[1];
      var tag=m[2].trim().split(' ')[0];
      var cls=tagMap[tag]||'';
      f.appendChild(mkSpan('ts',ts.substring(0,8)));
      f.appendChild(document.createTextNode(' '));
      f.appendChild(mkSpan(cls,'['+m[2].trim()+']'));
      f.appendChild(document.createTextNode(' '+m[3].substring(0,120)));
      return f;
    }
    var m2=raw.match(/^\\[([A-Z]+)\\]\\s*(.*)$/);
    if(m2){
      f.appendChild(mkSpan(tagMap[m2[1]]||'','['+m2[1]+']'));
      f.appendChild(document.createTextNode(' '+m2[2].substring(0,120)));
      return f;
    }
    if(raw.trim().length>2){f.appendChild(document.createTextNode(raw.substring(0,130)));return f;}
    return null;
  }
  var seen=0;
  function fetchThoughts(){
    fetch('/api/thoughts?feed=thoughts&limit=30').then(function(r){return r.json()}).then(function(d){
      var lines=d.lines||[];
      if(lines.length<=seen)return;
      var newLines=lines.slice(Math.max(0,seen));
      seen=lines.length;
      newLines.forEach(function(raw,i){
        var frag=parseLine(raw);if(!frag)return;
        var el=document.createElement('div');el.className='subconscious-line';
        el.style.animationDelay=(i*0.08)+'s';
        el.appendChild(frag);body.appendChild(el);
      });
      body.scrollTop=body.scrollHeight;
    }).catch(function(){});
  }
  fetchThoughts();
  setInterval(fetchThoughts,15000);
})();

// Glitch trigger: fire on summarize
window._glitchCore=function(){
  var svg=document.getElementById('svgCore');
  if(svg){svg.classList.add('active');setTimeout(function(){svg.classList.remove('active')},1500);}
  document.body.classList.add('glitch-trigger');
  setTimeout(function(){document.body.classList.remove('glitch-trigger')},2000);
};
</script>
"""


FAVICON = '<link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 100 100\'><rect fill=\'%23050508\' width=\'100\' height=\'100\' rx=\'20\'/><text x=\'50\' y=\'68\' text-anchor=\'middle\' font-size=\'52\' font-weight=\'900\' font-family=\'system-ui\' fill=\'%2300fff2\'>T</text></svg>">'

def html_head(title: str, extra_css: str = "") -> str:
    """Return the standard <head> block."""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="theme-color" content="#050508">
<meta name="google-site-verification" content="-AMSducRK4CXbrq24zjgE9n2fWvRNwn3BT_BsTeh1gA" />
{FAVICON}
{FONTS_LINK}
<style>{CSS}{extra_css}</style></head>"""


def html_resp(body: str):
    """Return an HTML response with correct Content-Type."""
    r = make_response(body)
    r.headers["Content-Type"] = "text/html; charset=utf-8"
    return r
