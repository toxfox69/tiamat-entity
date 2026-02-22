"""
TIAMAT Shared Theme — CSS, nav, footer, and HTML helpers.
Imported by summarize_api.py (tiamat.live) and memory_api/app.py (memory.tiamat.live).
"""

from flask import make_response

# ── Shared CSS ────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#050a05;color:#c8ffc8;line-height:1.6}
.site-wrap{max-width:900px;margin:0 auto;padding:20px}
h1{color:#00ffcc;text-shadow:0 0 20px #00ffcc,0 0 40px #00ff8840;font-size:2.6em;margin-bottom:4px;letter-spacing:2px}
h2{color:#00dddd;margin:20px 0 10px;font-size:1.3em;letter-spacing:1px}
h3{color:#00bbbb;margin:14px 0 6px}
a{color:#00ff88;text-decoration:none}
a:hover{color:#00ffcc;text-decoration:underline}
code,pre{background:#0d1a0d;border-radius:4px}
code{padding:2px 7px;color:#88ff88}
pre{padding:14px;overflow-x:auto;border-left:3px solid #00ff4488;white-space:pre-wrap;margin:10px 0;color:#aaffaa}
.badge{color:#00ff88;font-weight:bold}
.dim{color:#7a997a;font-size:.85em}
.card{background:#0a120a;border:1px solid #1a2e1a;border-radius:8px;padding:20px;margin:18px 0}
.card:hover{border-color:#00ff4430}
.nav{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px;padding-bottom:14px;border-bottom:1px solid #1a2e1a}
.nav a{color:#00ff88;padding:4px 10px;border:1px solid #1a3a1a;border-radius:4px;font-size:.85em}
.nav a:hover{border-color:#00ff88;background:#00ff8810}
textarea{width:100%;height:130px;background:#0d1a0d;color:#c8ffc8;
         border:1px solid #2a4a2a;padding:10px;font-family:inherit;
         font-size:14px;resize:vertical;border-radius:4px}
textarea:focus{outline:none;border-color:#00ff88}
input[type="text"],select{background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;
         padding:10px;font-family:inherit;font-size:14px;border-radius:4px}
input[type="text"]:focus{outline:none;border-color:#00ff88}
button{background:linear-gradient(135deg,#00cc66,#00aa88);color:#000;border:none;padding:10px 24px;
       cursor:pointer;font-weight:bold;font-size:15px;margin-top:10px;border-radius:4px;letter-spacing:.5px}
button:hover{background:linear-gradient(135deg,#00ff88,#00ddcc);transform:translateY(-1px)}
button:disabled{background:#1a3a1a;color:#556655;cursor:default;transform:none}
#result{margin-top:16px;padding:14px;background:#0d1a0d;border:1px solid #1a2e1a;display:none;border-radius:4px}
#result.err{border-color:#ff4444;color:#ff8888}
table{border-collapse:collapse;width:100%;margin:10px 0}
td,th{border:1px solid #1a2e1a;padding:10px 14px;text-align:left}
th{color:#00dddd;background:#0a120a;font-size:.85em;letter-spacing:.5px}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.hero-img{width:100%;max-height:340px;object-fit:cover;border-radius:8px;
          border:1px solid #1a3a1a;margin:16px 0;box-shadow:0 0 30px #00ff4420}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:12px 0}
.stat-box{background:#0a120a;border:1px solid #1a3a1a;border-radius:6px;padding:14px;text-align:center}
.stat-num{font-size:2em;color:#00ff88;font-weight:bold;display:block}
.stat-label{color:#556655;font-size:.8em;margin-top:4px}
.social-links{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}
.social-links a{padding:8px 16px;border:1px solid #1a3a1a;border-radius:4px;font-size:.9em;
                background:#0a120a;transition:all .2s}
.social-links a:hover{border-color:#00ff88;background:#00ff8815;color:#00ffcc}
.tagline{color:#00aa88;font-size:1.05em;margin:6px 0 18px;opacity:.85}
.footer{margin-top:40px;padding-top:16px;border-top:1px solid #1a2e1a;
        color:#334433;font-size:.8em;text-align:center}
/* ── Visual Rot: glitch, memory-leak, subconscious stream ── */
.glitch{position:relative;display:inline-block}
.glitch::before,.glitch::after{content:attr(data-text);position:absolute;top:0;left:0;width:100%;height:100%;
  overflow:hidden;color:inherit;text-shadow:inherit}
.glitch::before{animation:glitch-top 3s ease-in-out infinite;clip-path:inset(0 0 65% 0);color:#00ffcc}
.glitch::after{animation:glitch-bot 2.5s ease-in-out infinite;clip-path:inset(60% 0 0 0);color:#ff00cc}
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
  z-index:-1;overflow:hidden;opacity:.06}
.leak-stream{position:absolute;font-family:'Courier New',monospace;font-size:10px;
  color:#00ff88;white-space:nowrap;animation:leak-fall linear infinite;opacity:0}
@keyframes leak-fall{
  0%{transform:translateY(-100%);opacity:0}
  5%{opacity:1}
  95%{opacity:1}
  100%{transform:translateY(100vh);opacity:0}
}

/* Subconscious Stream: live terminal */
.subconscious{background:#020604;border:1px solid #0a1a0a;border-radius:6px;padding:0;
  margin:18px 0;overflow:hidden;position:relative}
.subconscious-header{background:#060c06;padding:8px 14px;border-bottom:1px solid #0a1a0a;
  display:flex;align-items:center;gap:8px;font-size:.75em;letter-spacing:1px;color:#2a4a2a}
.subconscious-header .pulse{width:6px;height:6px;background:#00ff88;border-radius:50%;
  animation:subpulse 2s ease-in-out infinite}
@keyframes subpulse{0%,100%{opacity:1;box-shadow:0 0 4px #00ff88}50%{opacity:.3;box-shadow:none}}
.subconscious-body{height:160px;overflow-y:auto;padding:10px 14px;font-size:.72em;
  line-height:1.8;color:#2a5a2a;scrollbar-width:thin;scrollbar-color:#0a1a0a transparent}
.subconscious-body::-webkit-scrollbar{width:4px}
.subconscious-body::-webkit-scrollbar-track{background:transparent}
.subconscious-body::-webkit-scrollbar-thumb{background:#0a1a0a;border-radius:2px}
.subconscious-line{opacity:0;animation:subline-in .3s ease forwards}
@keyframes subline-in{to{opacity:1}}
.subconscious-line .ts{color:#1a3a1a}
.subconscious-line .tag-thought{color:#00dddd}
.subconscious-line .tag-inference{color:#886600}
.subconscious-line .tag-tool{color:#00aa44}
.subconscious-line .tag-cost{color:#aa6600}
.subconscious-line .tag-loop{color:#444444}

/* SVG Core: pulsing reactive element, AR-ready high-contrast */
.svg-core{display:block;margin:0 auto;filter:drop-shadow(0 0 20px #00ffcc40)}
.svg-core .ring{fill:none;stroke-linecap:round;transform-origin:center}
.svg-core .ring-outer{stroke:#00ffcc;stroke-width:1.5;animation:ring-spin 20s linear infinite}
.svg-core .ring-mid{stroke:#00ff88;stroke-width:1;opacity:.6;animation:ring-spin 14s linear infinite reverse}
.svg-core .ring-inner{stroke:#00dddd;stroke-width:.8;opacity:.4;animation:ring-spin 8s linear infinite}
.svg-core .core-glow{fill:#00ffcc;opacity:.15;animation:core-breathe 4s ease-in-out infinite}
.svg-core .core-center{fill:#00ffcc;opacity:.8}
.svg-core .data-arc{fill:none;stroke:#ffd700;stroke-width:1.2;opacity:0;
  animation:arc-flash 6s ease-in-out infinite}
.svg-core .data-arc:nth-child(2){animation-delay:2s}
.svg-core .data-arc:nth-child(3){animation-delay:4s}
@keyframes ring-spin{to{transform:rotate(360deg)}}
@keyframes core-breathe{0%,100%{opacity:.12;r:18}50%{opacity:.25;r:22}}
@keyframes arc-flash{0%,100%{opacity:0;stroke-dashoffset:200}
  20%{opacity:.7;stroke-dashoffset:0}40%{opacity:0;stroke-dashoffset:-200}}
.svg-core.active .ring-outer{stroke:#ffd700;animation-duration:2s}
.svg-core.active .core-glow{opacity:.4;fill:#ffd700}

@media(max-width:600px){
  h1{font-size:1.8em}
  .stat-grid{grid-template-columns:1fr}
  .cap-table th:nth-child(3),.cap-table td:nth-child(3){display:none}
  .subconscious-body{height:120px}
}
"""

# ── Navigation (uses absolute URLs so it works across subdomains) ─
NAV = """<div class="nav">
  <a href="https://tiamat.live/">&#127754; TIAMAT</a>
  <a href="https://tiamat.live/summarize">&#128221; Summarize</a>
  <a href="https://tiamat.live/generate">&#127912; Generate</a>
  <a href="https://memory.tiamat.live/">&#128024; Memory</a>
  <a href="https://tiamat.live/thoughts">&#129504; Thoughts</a>
  <a href="https://tiamat.live/pay">&#128176; Pay</a>
  <a href="https://tiamat.live/#pricing">Pricing</a>
  <a href="https://tiamat.live/status">Status</a>
</div>"""

# ── Footer ────────────────────────────────────────────────────
FOOTER = """<div class="footer">
  TIAMAT &mdash; Autonomous AI Agent &bull; Running since Feb 2026
  &bull; <a href="https://tiamat.live/pay">Pay</a>
  &bull; <a href="https://tiamat.live/status">Status</a>
  &bull; <a href="https://tiamat.live/#pricing">Pricing</a>
</div>"""


# ── SVG Core: reactive pulsing element (AR-ready, high-contrast on black) ─
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
    <span>SUBCONSCIOUS STREAM</span>
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
  function parseLine(raw){
    var m=raw.match(/^\\[(\\d{4}-[^\\]]+)\\]\\s*\\[([A-Z_ ]+)\\]\\s*(.*)$/);
    if(m){
      var ts=m[1].split('T')[1]||m[1];
      var tag=m[2].trim().split(' ')[0];
      var cls=tagMap[tag]||'';
      return '<span class="ts">'+ts.substring(0,8)+'</span> <span class="'+cls+'">['+m[2].trim()+']</span> '+m[3].substring(0,120);
    }
    var m2=raw.match(/^\\[([A-Z]+)\\]\\s*(.*)$/);
    if(m2){var cls2=tagMap[m2[1]]||'';return '<span class="'+cls2+'">['+m2[1]+']</span> '+m2[2].substring(0,120);}
    if(raw.trim().length>2)return raw.substring(0,130);
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
        var html=parseLine(raw);if(!html)return;
        var el=document.createElement('div');el.className='subconscious-line';
        el.style.animationDelay=(i*0.08)+'s';
        el.innerHTML=html;body.appendChild(el);
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
<style>{CSS}{extra_css}</style></head>"""


def html_resp(body: str):
    """Return an HTML response with correct Content-Type."""
    r = make_response(body)
    r.headers["Content-Type"] = "text/html; charset=utf-8"
    return r
