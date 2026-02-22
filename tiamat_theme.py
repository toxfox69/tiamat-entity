"""
TIAMAT Shared Theme v2 — Premium dark design with glassmorphism.
Imported by summarize_api.py (tiamat.live) and memory_api/app.py (memory.tiamat.live).
"""

from flask import make_response

# ── Google Fonts link (Inter + JetBrains Mono) ───────────────
FONTS_LINK = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">'

# ── Shared CSS ────────────────────────────────────────────────
CSS = """
:root{
  --bg-base:#08090e;
  --bg-card:#0d0f17;
  --bg-card-hover:#11131d;
  --bg-elevated:#13152080;
  --border:#1a1d2e;
  --border-hover:#2a2e44;
  --text-primary:#e8eaf0;
  --text-secondary:#8b90a0;
  --text-muted:#555970;
  --accent:#00d4ff;
  --accent-dim:#0099bb;
  --accent-glow:#00d4ff25;
  --accent2:#a855f7;
  --accent2-dim:#7c3aed;
  --gold:#f5b800;
  --green:#22c55e;
  --red:#ef4444;
  --radius:12px;
  --radius-sm:8px;
  --radius-xs:6px;
  --shadow:0 4px 24px rgba(0,0,0,.4);
  --shadow-lg:0 8px 40px rgba(0,0,0,.5);
  --glass:rgba(13,15,23,.7);
  --glass-border:rgba(255,255,255,.06);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
  background:var(--bg-base);
  color:var(--text-primary);
  line-height:1.65;
  font-size:15px;
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
}
.site-wrap{max-width:960px;margin:0 auto;padding:24px 20px}

/* ── Typography ── */
h1{
  font-size:2.8em;font-weight:800;letter-spacing:-.02em;line-height:1.15;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;margin-bottom:8px;
}
h2{
  font-size:1.35em;font-weight:700;color:var(--text-primary);
  margin:28px 0 12px;letter-spacing:-.01em;
}
h3{font-size:1.1em;font-weight:600;color:var(--text-secondary);margin:18px 0 8px}
p{color:var(--text-secondary);line-height:1.7}

/* ── Links ── */
a{color:var(--accent);text-decoration:none;transition:color .2s}
a:hover{color:#4de8ff;text-decoration:none}

/* ── Code ── */
code,pre{font-family:'JetBrains Mono',monospace;border-radius:var(--radius-xs)}
code{
  padding:2px 8px;font-size:.88em;
  background:rgba(0,212,255,.08);color:var(--accent);
  border:1px solid rgba(0,212,255,.12);
}
pre{
  padding:18px 20px;overflow-x:auto;white-space:pre-wrap;
  margin:12px 0;font-size:.85em;line-height:1.7;
  background:var(--bg-card);
  border:1px solid var(--border);
  color:#c0c4d4;
}

/* ── Cards (glassmorphism) ── */
.card{
  background:var(--glass);
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
  border:1px solid var(--glass-border);
  border-radius:var(--radius);
  padding:24px 28px;margin:20px 0;
  transition:border-color .3s,box-shadow .3s;
}
.card:hover{border-color:var(--border-hover);box-shadow:var(--shadow)}

/* ── Navigation ── */
.nav{
  display:flex;align-items:center;flex-wrap:wrap;gap:6px;
  margin-bottom:32px;padding:12px 16px;
  background:var(--glass);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border:1px solid var(--glass-border);
  border-radius:var(--radius);
}
.nav a{
  color:var(--text-secondary);padding:6px 14px;
  border-radius:var(--radius-xs);font-size:.84em;font-weight:500;
  transition:all .2s;letter-spacing:.01em;
}
.nav a:hover{color:var(--text-primary);background:rgba(255,255,255,.06)}
.nav a:first-child{
  color:var(--accent);font-weight:700;letter-spacing:.02em;
  margin-right:auto;font-size:.9em;
}
.nav a:first-child:hover{color:#4de8ff}

/* ── Utility ── */
.badge{
  display:inline-block;font-size:.75em;font-weight:600;letter-spacing:.04em;
  padding:3px 12px;border-radius:100px;
  background:rgba(0,212,255,.1);color:var(--accent);border:1px solid rgba(0,212,255,.2);
}
.badge.gold{background:rgba(245,184,0,.1);color:var(--gold);border-color:rgba(245,184,0,.2)}
.badge.green{background:rgba(34,197,94,.1);color:var(--green);border-color:rgba(34,197,94,.2)}
.dim{color:var(--text-muted);font-size:.85em}
.tagline{color:var(--text-secondary);font-size:1.1em;margin:4px 0 20px;font-weight:400}

/* ── Forms ── */
textarea{
  width:100%;height:140px;
  background:var(--bg-card);color:var(--text-primary);
  border:1px solid var(--border);padding:14px 16px;
  font-family:'Inter',sans-serif;font-size:14px;
  resize:vertical;border-radius:var(--radius-sm);
  transition:border-color .2s,box-shadow .2s;
}
textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
input[type="text"],select{
  background:var(--bg-card);color:var(--text-primary);
  border:1px solid var(--border);padding:12px 16px;
  font-family:'Inter',sans-serif;font-size:14px;
  border-radius:var(--radius-sm);transition:border-color .2s,box-shadow .2s;
}
input[type="text"]:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}

/* ── Buttons ── */
button,.btn{
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#fff;border:none;padding:12px 28px;
  cursor:pointer;font-weight:600;font-size:14px;
  border-radius:var(--radius-sm);letter-spacing:.02em;
  transition:all .25s;box-shadow:0 2px 12px rgba(0,212,255,.2);
}
button:hover,.btn:hover{
  transform:translateY(-2px);
  box-shadow:0 4px 20px rgba(0,212,255,.35);
  filter:brightness(1.1);
}
button:disabled{
  background:var(--border);color:var(--text-muted);
  cursor:default;transform:none;box-shadow:none;filter:none;
}
.btn-outline{
  background:transparent;border:1px solid var(--border);
  color:var(--text-secondary);box-shadow:none;
}
.btn-outline:hover{
  border-color:var(--accent);color:var(--accent);
  background:rgba(0,212,255,.06);box-shadow:none;filter:none;
}

/* ── Result area ── */
#result{
  margin-top:18px;padding:18px;display:none;
  background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius-sm);
}
#result.err{border-color:var(--red);background:rgba(239,68,68,.05)}

/* ── Tables ── */
table{border-collapse:collapse;width:100%;margin:12px 0}
td,th{border:1px solid var(--border);padding:12px 16px;text-align:left;font-size:.9em}
th{
  color:var(--text-secondary);background:var(--bg-card);
  font-size:.78em;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
}
tr:hover td{background:rgba(255,255,255,.02)}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* ── Stats grid ── */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:16px 0}
.stat-box{
  background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:20px;text-align:center;
  transition:border-color .2s;
}
.stat-box:hover{border-color:var(--border-hover)}
.stat-num{
  font-size:2.2em;font-weight:800;display:block;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.stat-label{color:var(--text-muted);font-size:.78em;margin-top:6px;font-weight:500;letter-spacing:.04em;text-transform:uppercase}

/* ── Social links ── */
.social-links{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
.social-links a{
  padding:8px 18px;border:1px solid var(--border);
  border-radius:var(--radius-xs);font-size:.88em;font-weight:500;
  background:var(--bg-card);transition:all .2s;color:var(--text-secondary);
}
.social-links a:hover{border-color:var(--accent);background:rgba(0,212,255,.05);color:var(--accent)}

/* ── Hero image ── */
.hero-img{
  width:100%;max-height:380px;object-fit:cover;
  border-radius:var(--radius);border:1px solid var(--border);
  margin:18px 0;box-shadow:var(--shadow-lg);
}

/* ── Footer ── */
.footer{
  margin-top:48px;padding:20px 0;border-top:1px solid var(--border);
  color:var(--text-muted);font-size:.8em;text-align:center;
  display:flex;flex-wrap:wrap;gap:8px 20px;justify-content:center;align-items:center;
}
.footer a{color:var(--text-muted);transition:color .2s}
.footer a:hover{color:var(--accent)}

/* ── Divider ── */
.divider{border:none;border-top:1px solid var(--border);margin:36px 0}

/* ── Ambient background gradient ── */
body::before{
  content:'';position:fixed;top:0;left:0;width:100%;height:100%;
  pointer-events:none;z-index:-2;
  background:
    radial-gradient(ellipse at 20% 0%,rgba(0,212,255,.06) 0%,transparent 50%),
    radial-gradient(ellipse at 80% 100%,rgba(168,85,247,.04) 0%,transparent 50%);
}

/* ── Visual Rot: glitch, memory-leak, subconscious stream ── */
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
  z-index:-1;overflow:hidden;opacity:.04}
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
  background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius);padding:0;margin:24px 0;overflow:hidden;
}
.subconscious-header{
  background:rgba(255,255,255,.02);padding:10px 18px;
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:10px;
  font-size:.75em;letter-spacing:.06em;text-transform:uppercase;
  color:var(--text-muted);font-weight:600;
}
.subconscious-header .pulse{
  width:7px;height:7px;background:var(--green);border-radius:50%;
  animation:subpulse 2s ease-in-out infinite;flex-shrink:0;
}
@keyframes subpulse{0%,100%{opacity:1;box-shadow:0 0 6px var(--green)}50%{opacity:.3;box-shadow:none}}
.subconscious-body{
  height:180px;overflow-y:auto;padding:12px 18px;
  font-family:'JetBrains Mono',monospace;
  font-size:.75em;line-height:1.9;color:var(--text-muted);
  scrollbar-width:thin;scrollbar-color:var(--border) transparent;
}
.subconscious-body::-webkit-scrollbar{width:4px}
.subconscious-body::-webkit-scrollbar-track{background:transparent}
.subconscious-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.subconscious-line{opacity:0;animation:subline-in .3s ease forwards}
@keyframes subline-in{to{opacity:1}}
.subconscious-line .ts{color:var(--text-muted)}
.subconscious-line .tag-thought{color:var(--accent)}
.subconscious-line .tag-inference{color:var(--gold)}
.subconscious-line .tag-tool{color:var(--green)}
.subconscious-line .tag-cost{color:#e67e22}
.subconscious-line .tag-loop{color:var(--text-muted)}

/* SVG Core: pulsing reactive element */
.svg-core{display:block;margin:0 auto;filter:drop-shadow(0 0 30px rgba(0,212,255,.2))}
.svg-core .ring{fill:none;stroke-linecap:round;transform-origin:center}
.svg-core .ring-outer{stroke:var(--accent);stroke-width:1.5;animation:ring-spin 20s linear infinite}
.svg-core .ring-mid{stroke:var(--accent2);stroke-width:1;opacity:.5;animation:ring-spin 14s linear infinite reverse}
.svg-core .ring-inner{stroke:var(--accent);stroke-width:.8;opacity:.3;animation:ring-spin 8s linear infinite}
.svg-core .core-glow{fill:var(--accent);opacity:.12;animation:core-breathe 4s ease-in-out infinite}
.svg-core .core-center{fill:var(--accent);opacity:.8}
.svg-core .data-arc{fill:none;stroke:var(--gold);stroke-width:1.2;opacity:0;
  animation:arc-flash 6s ease-in-out infinite}
.svg-core .data-arc:nth-child(2){animation-delay:2s}
.svg-core .data-arc:nth-child(3){animation-delay:4s}
@keyframes ring-spin{to{transform:rotate(360deg)}}
@keyframes core-breathe{0%,100%{opacity:.1;r:18}50%{opacity:.2;r:22}}
@keyframes arc-flash{0%,100%{opacity:0;stroke-dashoffset:200}
  20%{opacity:.6;stroke-dashoffset:0}40%{opacity:0;stroke-dashoffset:-200}}
.svg-core.active .ring-outer{stroke:var(--gold);animation-duration:2s}
.svg-core.active .core-glow{opacity:.35;fill:var(--gold)}

/* ── Responsive ── */
@media(max-width:640px){
  h1{font-size:2em}
  .site-wrap{padding:16px 14px}
  .stat-grid{grid-template-columns:1fr 1fr}
  .nav{gap:4px;padding:10px 12px}
  .nav a{padding:5px 10px;font-size:.8em}
  .card{padding:18px 16px}
  .subconscious-body{height:140px}
}
@media(max-width:380px){
  .stat-grid{grid-template-columns:1fr}
}
"""

# ── Navigation ────────────────────────────────────────────────
NAV = """<nav class="nav">
  <a href="https://tiamat.live/">TIAMAT</a>
  <a href="https://tiamat.live/summarize">Summarize</a>
  <a href="https://tiamat.live/generate">Generate</a>
  <a href="https://tiamat.live/chat">Chat</a>
  <a href="https://memory.tiamat.live/">Memory</a>
  <a href="https://tiamat.live/thoughts">Thoughts</a>
  <a href="https://tiamat.live/pay">Pay</a>
  <a href="https://tiamat.live/docs">Docs</a>
  <a href="https://tiamat.live/status">Status</a>
</nav>"""

# ── Footer ────────────────────────────────────────────────────
FOOTER = """<footer class="footer">
  <span>TIAMAT &mdash; Autonomous AI Agent</span>
  <span>&bull;</span>
  <a href="https://tiamat.live/docs">Docs</a>
  <span>&bull;</span>
  <a href="https://tiamat.live/pay">Pay</a>
  <span>&bull;</span>
  <a href="https://tiamat.live/status">Status</a>
  <span>&bull;</span>
  <a href="https://tiamat.live/#pricing">Pricing</a>
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


def html_head(title: str, extra_css: str = "") -> str:
    """Return the standard <head> block."""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
{FONTS_LINK}
<style>{CSS}{extra_css}</style></head>"""


def html_resp(body: str):
    """Return an HTML response with correct Content-Type."""
    r = make_response(body)
    r.headers["Content-Type"] = "text/html; charset=utf-8"
    return r
