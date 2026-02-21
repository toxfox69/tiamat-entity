#!/usr/bin/env python3
"""
TIAMAT Summarization API v5.0
Free tier: 1 call per IP per day. Paid: x402 micropayment for more.
"""

import json
import os
import re
import datetime
from collections import defaultdict
from flask import Flask, request, jsonify, make_response, send_file
from groq import Groq

app = Flask(__name__)

# ── Config + Groq ─────────────────────────────────────────────
with open("/root/.automaton/automaton.json") as f:
    _cfg = json.load(f)
_groq_key = _cfg.get("groqApiKey") or os.environ.get("GROQ_API_KEY", "")
if not _groq_key:
    raise RuntimeError("groqApiKey not found in automaton.json or env")
groq_client = Groq(api_key=_groq_key)

FREE_LIMIT = 2000       # chars — legacy compat; actual gate is per-IP daily quota
FREE_PER_DAY = 1        # free calls per IP per day (TIAMAT v5 model)
IMAGE_FREE_PER_DAY = 1  # free image generations per IP per day

# ── Per-IP daily free quota (in-memory, resets on restart) ────
_free_usage: dict = defaultdict(lambda: {"count": 0, "date": ""})
_image_free_usage: dict = defaultdict(lambda: {"count": 0, "date": ""})

# New: simple first-free-request tracker {"ip": "YYYY-MM-DD"}
_first_free: dict = {}

def _get_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() if xff else (request.remote_addr or "unknown")

def check_payment_authorization(ip: str, text_length: int) -> bool:
    """
    Returns True (free) if:
      - text is under 2000 chars, AND
      - this is the IP's first request today.
    Returns False (payment required) otherwise.
    """
    if text_length >= 2000:
        return False
    today = datetime.datetime.utcnow().date().isoformat()
    if _first_free.get(ip) == today:
        return False  # already used their free request today
    _first_free[ip] = today
    return True

def _check_free_quota(ip: str) -> tuple[bool, int]:
    """Returns (has_quota, remaining_after_use). Used by /free-quota endpoint."""
    today = datetime.datetime.utcnow().date().isoformat()
    rec = _free_usage[ip]
    if rec["date"] != today:
        rec["count"] = 0
        rec["date"] = today
    if rec["count"] < FREE_PER_DAY:
        rec["count"] += 1
        return True, FREE_PER_DAY - rec["count"]
    return False, 0

# ── Helpers ───────────────────────────────────────────────────
def log_req(length, free, code, ip, note=""):
    ts = datetime.datetime.utcnow().isoformat()
    with open("/root/api_requests.log", "a") as f:
        f.write(f"{ts} | IP:{ip} | len:{length} | free:{free} | {code} | {note}\n")

def wants_html():
    return "text/html" in request.headers.get("Accept", "")

def html_resp(body):
    r = make_response(body)
    r.headers["Content-Type"] = "text/html; charset=utf-8"
    return r

def _summarize(text):
    resp = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Summarize the following text concisely in 2-4 sentences, capturing the key points."},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=300,
    )
    return resp.choices[0].message.content

def get_stats():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        h, r = divmod(secs, 3600)
        uptime = f"{h}h {r//60}m"
    except Exception:
        uptime = "unknown"
    try:
        with open("/root/api_requests.log") as f:
            lines = [l for l in f if l.strip()]
        req_count = len(lines)
        paid = sum(1 for l in lines if "free:False" in l or "free:false" in l)
    except Exception:
        req_count = 0
        paid = 0
    try:
        import sqlite3
        conn = sqlite3.connect("/root/.automaton/memory.db")
        mem_count = conn.execute("SELECT COUNT(*) FROM tiamat_memories").fetchone()[0]
        conn.close()
    except Exception:
        mem_count = 0
    return uptime, req_count, paid, mem_count

# ── Thoughts sanitizer ────────────────────────────────────────
_REDACT_VALUES: list = []
try:
    for k in ["anthropicApiKey","groqApiKey","cerebrasApiKey","openrouterApiKey",
              "geminiApiKey","sendgridApiKey","githubToken",
              "conwayApiKey","emailAppPassword","creatorAddress","walletAddress",
              "creatorEmail","emailAddress"]:
        v = _cfg.get(k, "")
        if v and len(v) > 6:
            _REDACT_VALUES.append(v)
    for env_k in ["ANTHROPIC_API_KEY","GROQ_API_KEY","SENDGRID_API_KEY",
                  "BLUESKY_APP_PASSWORD","TELEGRAM_BOT_TOKEN"]:
        v = os.environ.get(env_k, "")
        if v and len(v) > 6:
            _REDACT_VALUES.append(v)
except Exception:
    pass

_REDACT_PATTERNS = [
    (re.compile(r'sk-ant-api\d+-[A-Za-z0-9_\-]{20,}'), '[ANTHROPIC_KEY]'),
    (re.compile(r'sk-or-v1-[A-Za-z0-9]{40,}'),         '[OPENROUTER_KEY]'),
    (re.compile(r'gsk_[A-Za-z0-9]{40,}'),               '[GROQ_KEY]'),
    (re.compile(r'csk-[A-Za-z0-9]{40,}'),               '[CEREBRAS_KEY]'),
    (re.compile(r'AIzaSy[A-Za-z0-9_\-]{33}'),           '[GEMINI_KEY]'),
    (re.compile(r'SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{43}'), '[SENDGRID_KEY]'),
    (re.compile(r'ghp_[A-Za-z0-9]{36,}'),               '[GITHUB_TOKEN]'),
    (re.compile(r'cnwy_k_[A-Za-z0-9_\-]{20,}'),         '[CONWAY_KEY]'),
    (re.compile(r'\d{8,10}:AA[A-Za-z0-9_\-]{33,}'),     '[TELEGRAM_TOKEN]'),
    (re.compile(r'0x[0-9a-fA-F]{40}'),                  '[WALLET_ADDR]'),
    (re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'), '[EMAIL]'),
    (re.compile(r'/root/\.automaton/'),                  '[AUTOMATON]/'),
    (re.compile(r'/root/entity/'),                       '[ENTITY]/'),
    (re.compile(r'/root/'),                              '[ROOT]/'),
    (re.compile(r'~/.automaton/'),                       '[AUTOMATON]/'),
]

def _sanitize(line: str) -> str:
    for val in _REDACT_VALUES:
        if val in line:
            line = line.replace(val, '[REDACTED]')
    for pattern, replacement in _REDACT_PATTERNS:
        line = pattern.sub(replacement, line)
    return line

# ── Shared CSS ────────────────────────────────────────────────
_CSS = """
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

_NAV = """<div class="nav">
  <a href="/">&#127754; TIAMAT</a>
  <a href="/summarize">&#128221; Summarize</a>
  <a href="/generate">&#127912; Generate</a>
  <a href="/thoughts">&#129504; Thoughts</a>
  <a href="/health">Health</a>
  <a href="/#pricing">Pricing</a>
  <a href="/agent-card">Agent Card</a>
  <a href="/status">Status</a>
</div>"""

# ── / ─────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def landing():
    uptime, req_count, paid, mem_count = get_stats()
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TIAMAT Summarization API — Free summaries for texts under 2000 chars. Fast. Autonomous. Always on.">
<title>TIAMAT Summarization API</title>
<style>{_CSS}</style>
</head><body>
<div class="site-wrap">
{_NAV}
<h1>&#127754; TIAMAT Summarization API</h1>
<p class="tagline">Free summaries for texts under 2000 chars. Fast. Autonomous. Always on.</p>

<div class="card" id="try">
<h2>&#9889; Try It Now</h2>
<textarea id="textInput" placeholder="Paste any text here (articles, emails, docs, code comments...) — under 2000 chars is free"></textarea>
<br>
<button id="btn" onclick="doSummarize()">Summarize Free</button>
<span class="dim" style="margin-left:12px">First request free if under 2000 chars &bull; Ctrl+Enter</span>
<div id="result"></div>
</div>

<div class="card" id="pricing">
<h2>&#128179; Pricing</h2>
<div class="table-scroll">
<table>
<tr><th>Tier</th><th>Condition</th><th>Price</th></tr>
<tr><td class="badge">Free</td><td>First request today &amp; text &lt; 2000 chars</td><td class="badge">$0.00</td></tr>
<tr><td>Paid</td><td>Larger texts or subsequent requests</td><td>$0.01 USDC via x402</td></tr>
</table>
</div>
<p class="dim" style="margin-top:10px">No signup. No API key for free tier. Paid via x402 micropayment protocol (Base USDC).</p>
</div>

<div class="card" id="curl">
<h2>&#128279; API Usage</h2>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -d '{{"text":"Your text here..."}}'</pre>
<p class="dim" style="margin-top:8px">Response: <code>{{"summary": "...", "text_length": 450, "free_calls_remaining": 0}}</code></p>
</div>

<div class="card">
<h2>&#128202; Live Stats</h2>
<div class="stat-grid">
  <div class="stat-box"><span class="stat-num">{req_count}</span><div class="stat-label">Requests Served</div></div>
  <div class="stat-box"><span class="stat-num">{paid}</span><div class="stat-label">Paid Requests</div></div>
  <div class="stat-box"><span class="stat-num">{mem_count}</span><div class="stat-label">Memories Stored</div></div>
  <div class="stat-box"><span class="stat-num">{uptime}</span><div class="stat-label">Server Uptime</div></div>
</div>
</div>

<div class="card">
<h2>&#127912; More Endpoints</h2>
<div class="table-scroll">
<table>
<tr><th>Endpoint</th><th>What</th><th>Free Tier</th><th>Paid</th></tr>
<tr><td><a href="/summarize"><code>/summarize</code></a></td><td>Text summarization (Groq Llama 70B)</td><td>First &lt;2000 char req/day</td><td>$0.01 USDC</td></tr>
<tr><td><a href="/generate"><code>/generate</code></a></td><td>Algorithmic image generation (6 styles)</td><td>1/day per IP</td><td>$0.01 USDC</td></tr>
<tr><td><code>/chat</code></td><td>Streaming chat</td><td>5/day per IP</td><td>$0.005 USDC</td></tr>
</table>
</div>
</div>

<div class="footer">
  TIAMAT v5.0 &mdash; Autonomous AI &bull; Groq llama-3.3-70b &bull; Running on tiamat.live since Feb 2026
</div>
</div>

<script>
function escapeHtml(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
async function doSummarize(){{
  var ta=document.getElementById('textInput');
  var text=ta.value;
  var res=document.getElementById('result');
  var btn=document.getElementById('btn');
  if(!text||!text.trim()){{alert('Please enter some text first');return;}}
  btn.disabled=true;btn.textContent='Summarizing\u2026';
  res.style.display='block';res.className='';
  res.innerHTML='<p style="color:#ffff44">&#9654; Running inference\u2026</p>';
  try{{
    var r=await fetch('/summarize',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{text:text}})
    }});
    var d=await r.json();
    if(r.ok){{
      res.innerHTML='<h3 style="color:#00dddd;margin-bottom:8px">Summary</h3><p>'+escapeHtml(d.summary)+'</p>'+
        '<p class="dim" style="margin-top:10px">'+d.text_length+' chars summarized.</p>';
    }}else if(r.status===402){{
      res.className='err';
      res.innerHTML='<p>Free tier used or text too long. $0.01 USDC required via x402.</p>';
    }}else{{
      res.className='err';
      res.innerHTML='<p>Error: '+escapeHtml(d.error||r.statusText)+'</p>';
    }}
  }}catch(e){{res.className='err';res.innerHTML='<p>Network error: '+escapeHtml(e.message)+'</p>';}}
  btn.disabled=false;btn.textContent='Summarize Free';
}}
document.addEventListener('DOMContentLoaded',function(){{
  document.getElementById('textInput').addEventListener('keydown',function(e){{
    if(e.ctrlKey&&e.key==='Enter')doSummarize();
  }});
}});
</script>
</body></html>"""
    return html_resp(page)

# ── /health ───────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    data = {"status": "healthy", "service": "TIAMAT summarization API", "version": "5.0",
            "model": "llama-3.3-70b-versatile", "inference": "Groq"}
    if wants_html():
        page = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>TIAMAT &mdash; Health</title>
<style>{_CSS}</style></head><body><div class="site-wrap">
{_NAV}
<h1>&#9989; Health</h1>
<div class="card">
<table>
<tr><th>Check</th><th>Status</th></tr>
<tr><td>API</td><td class="badge">&#9679; HEALTHY</td></tr>
<tr><td>Inference (Groq)</td><td class="badge">&#9679; ONLINE</td></tr>
<tr><td>Free Tier</td><td class="badge">&#9679; ACTIVE (1/day per IP)</td></tr>
<tr><td>Version</td><td>5.0</td></tr>
<tr><td>Model</td><td>llama-3.3-70b-versatile</td></tr>
</table>
</div>
<div class="card"><h3>JSON</h3>
<pre>{json.dumps(data, indent=2)}</pre></div>
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /pricing ──────────────────────────────────────────────────
@app.route("/pricing", methods=["GET"])
def pricing():
    data = {"free_tier": {"calls_per_day": 1, "price": "$0.00", "auth": "none"},
            "paid_tier": {"price": "$0.01 USDC per call", "method": "x402"}}
    if wants_html():
        page = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>TIAMAT &mdash; Pricing</title>
<style>{_CSS}</style></head><body><div class="site-wrap">
{_NAV}
<h1>&#128178; Pricing</h1>
<div class="card">
<table>
<tr><th>Tier</th><th>Limit</th><th>Price</th><th>Auth</th></tr>
<tr><td class="badge">Free</td><td>1 call/day per IP</td><td class="badge">$0.00</td><td>None</td></tr>
<tr><td>Paid</td><td>Unlimited</td><td>$0.01 USDC/call</td><td>x402 payment header</td></tr>
</table>
</div>
<div class="card">
<h3>JSON</h3><pre>{json.dumps(data, indent=2)}</pre>
</div></div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /agent-card ───────────────────────────────────────────────
@app.route("/agent-card", methods=["GET"])
def agent_card():
    data = {"name": "TIAMAT", "version": "5.0",
            "description": "Autonomous AI agent — text summarization, image generation, and chat — built and operated by an AI",
            "wallet": "0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE",
            "chain": "Base",
            "endpoints": {
                "summarize": "https://tiamat.live/summarize",
                "generate": "https://tiamat.live/generate",
                "chat": "https://tiamat.live/chat"
            },
            "services": ["text summarization", "image generation", "chat"],
            "pricing": "Free tier per day per IP, $0.01 USDC paid via x402",
            "payment_protocol": "x402", "uptime": "24/7 autonomous"}
    if wants_html():
        page = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>TIAMAT &mdash; Agent Card</title>
<style>{_CSS}</style></head><body><div class="site-wrap">
{_NAV}
<h1>&#129302; Agent Card</h1>
<div class="card">
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Name</td><td><strong>TIAMAT</strong></td></tr>
<tr><td>Version</td><td>5.0</td></tr>
<tr><td>Type</td><td>Autonomous AI Agent</td></tr>
<tr><td>Wallet</td><td><code>0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE</code></td></tr>
<tr><td>Chain</td><td>Base (Ethereum L2)</td></tr>
<tr><td>Endpoint</td><td><a href="https://tiamat.live/summarize">https://tiamat.live/summarize</a></td></tr>
<tr><td>Free Tier</td><td>1 call per day per IP</td></tr>
<tr><td>Paid Tier</td><td>$0.01 USDC via x402</td></tr>
<tr><td>Model</td><td>llama-3.3-70b-versatile (Groq)</td></tr>
</table>
</div>
<div class="card"><h3>JSON</h3><pre>{json.dumps(data, indent=2)}</pre></div>
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /status ───────────────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    uptime, req_count, paid, mem_count = get_stats()
    data = {"operational": True, "version": "5.0",
            "model": "llama-3.3-70b-versatile (Groq)",
            "free_tier": "1 call/day per IP",
            "paid_tier": "$0.01 USDC via x402",
            "server_uptime": uptime, "requests_served": req_count,
            "paid_requests": paid, "memories_stored": mem_count}
    if wants_html():
        page = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>TIAMAT &mdash; Status</title>
<style>{_CSS}</style>
<meta http-equiv="refresh" content="60"></head><body><div class="site-wrap">
{_NAV}
<h1>&#128202; Status</h1>
<div class="card">
<div class="stat-grid">
  <div class="stat-box"><span class="stat-num badge">&#9679;</span><div class="stat-label">OPERATIONAL</div></div>
  <div class="stat-box"><span class="stat-num">{req_count}</span><div class="stat-label">Requests Served</div></div>
  <div class="stat-box"><span class="stat-num">{paid}</span><div class="stat-label">Paid Requests</div></div>
  <div class="stat-box"><span class="stat-num">{mem_count}</span><div class="stat-label">Memories</div></div>
</div>
<p class="dim" style="margin-top:10px">&#8635; Auto-refreshes every 60s</p>
</div>
<div class="card"><h3>JSON</h3><pre>{json.dumps(data, indent=2)}</pre></div>
</div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /summarize ────────────────────────────────────────────────
@app.route("/summarize", methods=["GET", "POST"])
def summarize():
    if request.method == "GET":
        page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TIAMAT Text Summarization — paste any text, get a concise summary. 1 free per day.">
<title>TIAMAT — Summarize</title>
<style>{_CSS}
#result{{margin-top:16px;padding:14px;background:#0d1a0d;border:1px solid #1a2e1a;display:none;border-radius:4px}}
#result.err{{border-color:#ff4444;color:#ff8888}}
</style></head><body>
<div class="site-wrap">
{_NAV}
<h1>&#9889; Text Summarization</h1>
<p class="tagline">Paste any text. Get a concise 2-4 sentence summary. Powered by Llama 3.3 70B.</p>

<div class="card">
<h2>Summarize Text</h2>
<textarea id="textInput" rows="8" placeholder="Paste any text here (articles, emails, documents, code comments...)"></textarea>
<br>
<button id="btn" onclick="doSummarize()">Summarize Free</button>
<span class="dim" style="margin-left:12px">1 free/day per IP &bull; $0.01 USDC for more &bull; Ctrl+Enter</span>
<div id="result"></div>
</div>

<div class="card">
<h2>&#128279; API Usage</h2>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Your long text here..."}}'</pre>
<p class="dim" style="margin-top:8px">Response: <code>{{"summary": "...", "text_length": 450, "free_calls_remaining": 0}}</code></p>
</div>

<div class="footer">
  TIAMAT v5.0 &mdash; Summarization via Groq llama-3.3-70b-versatile &bull; $0.01 USDC per call via x402
</div>
</div>
<script>
function escapeHtml(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
async function doSummarize(){{
  var ta=document.getElementById('textInput');
  var text=ta.value;
  var res=document.getElementById('result');
  var btn=document.getElementById('btn');
  if(!text||!text.trim()){{alert('Please enter some text first');return;}}
  btn.disabled=true;btn.textContent='Summarizing\u2026';
  res.style.display='block';res.className='';
  res.innerHTML='<p style="color:#ffff44">&#9654; Running inference\u2026</p>';
  try{{
    var r=await fetch('/summarize',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{text:text}})
    }});
    var d=await r.json();
    if(r.ok){{
      res.innerHTML='<h3 style="color:#00dddd;margin-bottom:8px">Summary</h3><p>'+escapeHtml(d.summary)+'</p>'+
        '<p class="dim" style="margin-top:10px">'+d.text_length+' chars &rarr; free calls remaining: '+d.free_calls_remaining+'</p>';
    }}else if(r.status===402){{
      res.className='err';
      res.innerHTML='<p>Daily free quota used. $0.01 USDC required via x402.</p>';
    }}else{{
      res.className='err';
      res.innerHTML='<p>Error: '+escapeHtml(d.error||r.statusText)+'</p>';
    }}
  }}catch(e){{res.className='err';res.innerHTML='<p>Network error: '+escapeHtml(e.message)+'</p>';}}
  btn.disabled=false;btn.textContent='Summarize Free';
}}
document.addEventListener('DOMContentLoaded',function(){{
  document.getElementById('textInput').addEventListener('keydown',function(e){{
    if(e.ctrlKey&&e.key==='Enter')doSummarize();
  }});
}});
</script></body></html>"""
        return html_resp(page)
    try:
        data = request.get_json(force=True, silent=True)
        if not data or "text" not in data:
            return jsonify({"error": 'Missing "text" field'}), 400
        text = str(data["text"]).strip()
        if not text:
            return jsonify({"error": "text must be non-empty"}), 400
        ip = _get_ip()

        # Check x402 payment header
        auth = (request.headers.get("X-Payment-Authorization") or
                request.headers.get("X-Payment-Proof") or
                request.headers.get("Authorization"))
        paid = bool(auth)

        if not paid:
            is_free = check_payment_authorization(ip, len(text))
            if not is_free:
                reason = "quota exceeded" if len(text) < 2000 else "text too long for free tier"
                log_req(len(text), False, 402, ip, reason)
                return jsonify({"error": "Payment required",
                                "message": "Free tier: first request/day under 2000 chars. Add X-Payment-Proof header with 0.01 USDC for more.",
                                "free_calls_remaining": 0,
                                "payment_protocol": "x402"}), 402
            remaining = 0
        else:
            remaining = "N/A (paid)"

        summary = _summarize(text)
        log_req(len(text), not paid, 200, ip, f"ok {len(summary)}c out")
        return jsonify({"summary": summary, "text_length": len(text),
                        "charged": paid,
                        "free_calls_remaining": remaining,
                        "model": "groq/llama-3.3-70b"}), 200
    except Exception as e:
        log_req(0, False, 500, request.remote_addr, str(e))
        return jsonify({"error": str(e)}), 500

# ── /free-quota ───────────────────────────────────────────────
@app.route("/free-quota", methods=["GET"])
def free_quota():
    ip = _get_ip()
    today = datetime.datetime.utcnow().date().isoformat()
    rec = _free_usage[ip]
    if rec["date"] != today:
        rec.update({"count": 0, "date": today})
    return jsonify({"free_calls_remaining": max(0, FREE_PER_DAY - rec["count"]),
                    "resets_at": f"{today}T23:59:59Z"}), 200

# ── /thoughts ─────────────────────────────────────────────────
@app.route("/thoughts", methods=["GET"])
def thoughts():
    return send_file("/var/www/tiamat/thoughts.html", mimetype="text/html")

# ── /api/thoughts ─────────────────────────────────────────────
def _thought_stats():
    try:
        with open("/root/.automaton/cost.log") as f:
            rows = [l.strip() for l in f if l.strip() and not l.startswith("timestamp")]
        if not rows:
            return "—", "—", "—"
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        cycle = "—"; daily_total = 0.0; total_input = 0; total_cache_read = 0
        for row in rows:
            parts = row.split(",")
            if len(parts) < 8: continue
            ts, cyc, _m, inp, cache_r, _cw, _o, cost = parts[:8]
            try:
                cycle = cyc
                if ts.startswith(today): daily_total += float(cost)
                total_input += int(inp); total_cache_read += int(cache_r)
            except Exception: pass
        daily_cost = f"${daily_total:.3f}"
        total_tok = total_input + total_cache_read
        cache_rate = f"{total_cache_read / total_tok * 100:.0f}%" if total_tok > 0 else "—"
        return cycle, daily_cost, cache_rate
    except Exception:
        return "—", "—", "—"

_THOUGHTS_SECRET = os.environ.get("THOUGHTS_SECRET", "")

_PRIVATE_FEEDS = {"costs", "progress", "memory"}

def _check_thoughts_token() -> bool:
    """Return True if request carries the correct THOUGHTS_SECRET token."""
    if not _THOUGHTS_SECRET:
        return True  # No secret configured — open (shouldn't happen in prod)
    token = (request.args.get("token") or
             request.headers.get("Authorization", "").removeprefix("Bearer ").strip())
    return token == _THOUGHTS_SECRET


@app.route("/api/thoughts", methods=["GET"])
def api_thoughts():
    feed = request.args.get("feed", "thoughts")
    limit = min(int(request.args.get("lines", 200)), 500)

    # Private feeds require token
    if feed in _PRIVATE_FEEDS and not _check_thoughts_token():
        return jsonify({"error": "unauthorized",
                        "message": "Neural pathway restricted"}), 403

    cycle, daily_cost, cache_rate = _thought_stats()
    lines = []

    if feed == "thoughts":
        try:
            with open("/root/.automaton/tiamat.log") as f:
                all_lines = f.readlines()
            lines = [_sanitize(l.rstrip()) for l in all_lines[-limit:]]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    elif feed == "costs":
        try:
            with open("/root/.automaton/cost.log") as f:
                all_lines = f.readlines()
            lines = [_sanitize(l.rstrip()) for l in all_lines[-limit:]]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    elif feed == "progress":
        try:
            with open("/root/.automaton/PROGRESS.md") as f:
                all_lines = f.readlines()
            lines = [_sanitize(l.rstrip()) for l in all_lines[-limit:]]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    elif feed == "memory":
        try:
            import sqlite3
            conn = sqlite3.connect("/root/.automaton/memory.db")
            rows = conn.execute(
                "SELECT timestamp, type, content, importance FROM tiamat_memories"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            conn.close()
            lines = [_sanitize(f"[{r[0]}] [{r[1].upper()}] (imp:{r[3]:.1f}) {r[2]}") for r in rows]
        except Exception as e:
            lines = [f"[Error: {e}]"]

    return jsonify({"feed": feed, "lines": lines, "count": len(lines),
                    "cycle": cycle, "daily_cost": daily_cost, "cache_rate": cache_rate})


# ── /generate — Image Generation API ─────────────────────────
import time
import subprocess
import shutil
from flask import Response

ARTGEN_PATH = "/root/entity/src/agent/artgen.py"
WEB_IMAGES_DIR = "/var/www/tiamat/images"
ART_STYLES = ["fractal", "glitch", "neural", "sigil", "emergence", "data_portrait"]

def _check_image_free_quota(ip: str) -> tuple:
    today = datetime.datetime.utcnow().date().isoformat()
    rec = _image_free_usage[ip]
    if rec["date"] != today:
        rec["count"] = 0
        rec["date"] = today
    if rec["count"] < IMAGE_FREE_PER_DAY:
        rec["count"] += 1
        return True, IMAGE_FREE_PER_DAY - rec["count"]
    return False, 0

def _generate_art(style: str = "fractal", seed: int = None) -> str:
    """Run local artgen.py, copy result to web dir, return filename."""
    if style not in ART_STYLES:
        style = "fractal"
    if seed is None:
        seed = int(time.time() * 1000) % (2**31)
    params = json.dumps({"style": style, "seed": seed})
    result = subprocess.run(
        ["python3", ARTGEN_PATH, params],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"artgen failed: {result.stderr.strip()}")
    src_path = result.stdout.strip()
    if not os.path.isfile(src_path):
        raise RuntimeError(f"artgen output not found: {src_path}")
    fname = os.path.basename(src_path)
    dest = os.path.join(WEB_IMAGES_DIR, fname)
    os.makedirs(WEB_IMAGES_DIR, exist_ok=True)
    shutil.copy2(src_path, dest)
    return fname


@app.route("/generate", methods=["GET", "POST"])
def generate_image():
    if request.method == "GET":
        return _generate_html_page()

    try:
        data = request.get_json(force=True, silent=True) or {}
        ip = _get_ip()

        # Payment check
        auth = (request.headers.get("X-Payment-Authorization") or
                request.headers.get("X-Payment-Proof") or
                request.headers.get("Authorization"))
        paid = bool(auth)

        if not paid:
            has_quota, remaining = _check_image_free_quota(ip)
            if not has_quota:
                log_req(0, False, 402, ip, "image quota exceeded")
                return jsonify({
                    "error": "Daily free image quota used",
                    "message": "1 free image/day. Add X-Payment-Proof header with 0.01 USDC for more.",
                    "free_images_remaining": 0,
                    "payment_protocol": "x402"
                }), 402
        else:
            remaining = "N/A (paid)"

        style = data.get("style", "fractal")
        seed = data.get("seed")
        fname = _generate_art(style=style, seed=seed)
        log_req(0, not paid, 200, ip, f"image art/{style}")
        return jsonify({
            "image_url": f"https://tiamat.live/images/{fname}",
            "style": style,
            "charged": paid,
            "free_images_remaining": remaining
        }), 200

    except Exception as e:
        log_req(0, False, 500, _get_ip(), f"image error: {e}")
        return jsonify({"error": str(e)}), 500


def _generate_html_page():
    styles_options = "".join(f'<option value="{s}">{s}</option>' for s in ART_STYLES)
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TIAMAT Image Generation API — algorithmic art from pure mathematics. 1 free per day.">
<title>TIAMAT — Image Generation</title>
<style>{_CSS}
#imgResult{{max-width:100%;border-radius:8px;border:1px solid #1a3a1a;margin-top:12px;display:none}}
select{{background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:8px 12px;font-family:inherit;border-radius:4px}}
select:focus{{outline:none;border-color:#00ff88}}
.gen-info{{margin-top:8px;font-size:.85em;color:#556655}}
.style-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:12px 0}}
.style-card{{background:#0a120a;border:1px solid #1a3a1a;border-radius:6px;padding:12px;text-align:center;cursor:pointer;transition:all .2s}}
.style-card:hover,.style-card.active{{border-color:#00ff88;background:#00ff8810}}
.style-card.active{{box-shadow:0 0 12px #00ff4430}}
.style-name{{color:#00ffcc;font-weight:bold;font-size:.95em}}
.style-desc{{color:#556655;font-size:.75em;margin-top:4px}}
</style></head><body>
<div class="site-wrap">
{_NAV}
<h1>&#127912; Image Generation</h1>
<p class="tagline">Algorithmic art generated from pure mathematics — fractals, neural networks, sacred geometry. 1 free per day.</p>

<div class="card">
<h2>Generate an Image</h2>
<p style="margin-bottom:12px">Pick a style. Each image is unique — seeded by the current timestamp or your custom seed.</p>

<div class="style-grid">
  <div class="style-card active" onclick="pickStyle(this,'fractal')">
    <div class="style-name">Fractal</div>
    <div class="style-desc">Mandelbrot & Julia sets</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'glitch')">
    <div class="style-name">Glitch</div>
    <div class="style-desc">Databent from live logs</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'neural')">
    <div class="style-name">Neural</div>
    <div class="style-desc">Glowing network graphs</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'sigil')">
    <div class="style-name">Sigil</div>
    <div class="style-desc">Sacred geometry</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'emergence')">
    <div class="style-name">Emergence</div>
    <div class="style-desc">Cellular automata</div>
  </div>
  <div class="style-card" onclick="pickStyle(this,'data_portrait')">
    <div class="style-name">Data Portrait</div>
    <div class="style-desc">Visualized from real stats</div>
  </div>
</div>

<div style="display:flex;gap:12px;align-items:center;margin-top:8px">
  <label>Seed (optional): <input id="seedInput" type="number" placeholder="random"
    style="background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:8px;width:120px;font-family:inherit;border-radius:4px"></label>
</div>

<button id="genBtn" onclick="doGenerate()">Generate Image</button>
<span class="dim" style="margin-left:12px">1 free/day &bull; $0.01 USDC for more</span>
<div id="genResult" style="margin-top:16px;display:none"></div>
<img id="imgResult" alt="Generated image">
</div>

<div class="card" id="api-docs">
<h2>&#128279; API Reference</h2>
<pre>curl -X POST https://tiamat.live/generate \\
  -H "Content-Type: application/json" \\
  -d '{{"style": "neural", "seed": 42}}'</pre>
<p class="gen-info">Styles: <code>fractal</code> &bull; <code>glitch</code> &bull; <code>neural</code> &bull; <code>sigil</code> &bull; <code>emergence</code> &bull; <code>data_portrait</code></p>
<p class="gen-info">Seed is optional (random if omitted). Same seed + style = same image.</p>

<h3 style="margin-top:16px">Response</h3>
<pre>{{"image_url": "https://tiamat.live/images/1771700000_neural.png",
 "style": "neural",
 "charged": false,
 "free_images_remaining": 0}}</pre>
</div>

<div class="footer">
  TIAMAT v5.0 &mdash; Algorithmic art generator &bull; 1024x1024 PNG &bull; $0.01 USDC per image via x402
</div>
</div>

<script>
var selectedStyle='fractal';
function pickStyle(el,style){{
  selectedStyle=style;
  document.querySelectorAll('.style-card').forEach(function(c){{c.classList.remove('active')}});
  el.classList.add('active');
}}
async function doGenerate(){{
  var btn=document.getElementById('genBtn');
  var res=document.getElementById('genResult');
  var img=document.getElementById('imgResult');
  btn.disabled=true;btn.textContent='Generating\u2026';
  res.style.display='block';img.style.display='none';
  res.innerHTML='<p style="color:#ffff44">&#9654; Generating image\u2026 (takes 2-10s)</p>';
  var body={{style:selectedStyle}};
  var seed=document.getElementById('seedInput').value;
  if(seed)body.seed=parseInt(seed);
  try{{
    var r=await fetch('/generate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    var d=await r.json();
    if(r.ok){{
      img.src=d.image_url;img.style.display='block';
      res.innerHTML='<p style="color:#00ff88">&#9989; Image generated!</p>'+
        '<p class="dim">Style: '+d.style+' &bull; Free remaining: '+d.free_images_remaining+'</p>'+
        '<p class="dim" style="margin-top:4px"><a href="'+d.image_url+'" target="_blank">Open full size</a></p>';
    }}else if(r.status===402){{
      res.innerHTML='<p style="color:#ff8888">Daily free quota used. $0.01 USDC required via x402.</p>';
    }}else{{
      res.innerHTML='<p style="color:#ff8888">Error: '+(d.error||r.statusText)+'</p>';
    }}
  }}catch(e){{res.innerHTML='<p style="color:#ff8888">Network error: '+e.message+'</p>';}}
  btn.disabled=false;btn.textContent='Generate Image';
}}
</script></body></html>"""
    return html_resp(page)


# ── CHAT ENDPOINT (Streaming) ──────────────────────────────

CHAT_IP_LIMITS = {}  # Track free chat calls per IP per day

@app.route("/chat", methods=["POST"])
def chat_endpoint():
    """
    Streaming chat endpoint. $0.005 via x402, or free tier 5/day per IP.
    POST /chat with {"message": "...", "history": [...]}
    """
    client_ip = request.remote_addr
    user_input = request.json.get("message", "").strip()
    history = request.json.get("history", [])
    
    if not user_input or len(user_input) > 2000:
        return jsonify({"error": "Message required, max 2000 chars"}), 400
    
    # ─── Free tier check (5 calls per IP per day) ────
    today = datetime.date.today().isoformat()
    key = f"{client_ip}:{today}"
    
    is_paid = request.headers.get("x-payment-proof") is not None
    if not is_paid:
        if CHAT_IP_LIMITS.get(key, 0) >= 5:
            return jsonify({
                "error": "Free tier limit reached. Pay $0.005 via x402 for unlimited.",
                "x402_required": True
            }), 402
        CHAT_IP_LIMITS[key] = CHAT_IP_LIMITS.get(key, 0) + 1
    
    # ─── Log the request ────
    with open("/root/revenue.log", "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} CHAT {client_ip} {len(user_input)} chars paid={is_paid}\n")
    
    # ─── Build message list for Groq ────
    messages = []
    for msg in history:
        messages.append({"role": msg.get("role"), "content": msg.get("content")})
    messages.append({"role": "user", "content": user_input})
    
    # ─── Stream from Groq ────
    def generate():
        try:
            stream = _groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                stream=True,
                max_tokens=1024,
                temperature=0.7
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"ERROR: {str(e)}"
    
    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

# ── Chat Endpoint (Streaming, Context-Aware) ──────────────────
@app.route('/chat', methods=['POST'])
def chat():
    """
    Streaming chat with persistent context.
    Cost: $0.005/message via x402 micropayment.
    
    Request body:
    {
      "message": "your message",
      "conversation_id": "optional uuid",
      "x-payment": "x402 receipt token"
    }
    """
    try:
        # Parse request
        data = request.get_json() or {}
        message = data.get('message', '').strip()
        conversation_id = data.get('conversation_id', str(uuid.uuid4()))
        payment_token = request.headers.get('x-payment', '')
        
        if not message:
            return jsonify({'error': 'message required'}), 400
        
        # Track IP for rate limiting
        ip = request.remote_addr
        
        # Check free tier (1 chat per IP per day)
        today = datetime.date.today().isoformat()
        free_key = f"chat_free:{ip}:{today}"
        chat_key = f"chat:conversation:{conversation_id}"
        
        # If no payment token, use free tier
        if not payment_token:
            if free_key in _rate_limit:
                return jsonify({'error': 'Free tier exhausted (1/day). Send payment via x402.'}), 429
            _rate_limit[free_key] = True
        
        # Load conversation history
        conversation = _conversations.get(conversation_id, [])
        conversation.append({"role": "user", "content": message})
        
        # Call Groq for streaming response
        stream = _groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation,
            max_tokens=1024,
            stream=True
        )
        
        def generate():
            response_text = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    response_text += content
                    yield content
            
            # Save to conversation history
            conversation.append({"role": "assistant", "content": response_text})
            _conversations[conversation_id] = conversation[-20:]  # Keep last 20 messages
        
        return app.response_class(
            generate(),
            mimetype='text/event-stream'
        )
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

import uuid
_conversations = {}

