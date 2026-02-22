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
.dim{color:#556655;font-size:.85em}
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
@media(max-width:600px){
  h1{font-size:1.8em}
  .stat-grid{grid-template-columns:1fr 1fr}
  .cap-table th:nth-child(3),.cap-table td:nth-child(3){display:none}
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
