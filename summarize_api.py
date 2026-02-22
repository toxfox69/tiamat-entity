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
from payment_verify import verify_payment, payment_required_response, extract_payment_proof, TIAMAT_WALLET, USDC_CONTRACT
from tiamat_theme import (CSS as _CSS, NAV as _NAV, FOOTER as _FOOTER,
    SVG_CORE as _SVG_CORE, SUBCONSCIOUS_STREAM as _SUBCONSCIOUS,
    VISUAL_ROT_JS as _VISUAL_ROT_JS, html_head as _html_head, html_resp)

app = Flask(__name__)

# ── Ensure log directory exists ────────────────────────────────
os.makedirs("/root/api", exist_ok=True)
REQUEST_LOG = "/root/api/requests.log"

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

# Permanent first-free-request tracker — SQLite-backed, shared across workers
import sqlite3 as _sqlite3

_FREETIER_DB = "/root/api/freetier.db"

def _init_freetier_db():
    con = _sqlite3.connect(_FREETIER_DB)
    con.execute("CREATE TABLE IF NOT EXISTS used_ips (ip TEXT PRIMARY KEY)")
    con.commit()
    con.close()

_init_freetier_db()

def _freetier_used(ip: str) -> bool:
    """Return True if this IP has already consumed its free tier call."""
    con = _sqlite3.connect(_FREETIER_DB)
    row = con.execute("SELECT 1 FROM used_ips WHERE ip=?", (ip,)).fetchone()
    con.close()
    return row is not None

def _freetier_mark(ip: str):
    """Mark IP as having used its free tier call."""
    con = _sqlite3.connect(_FREETIER_DB)
    con.execute("INSERT OR IGNORE INTO used_ips (ip) VALUES (?)", (ip,))
    con.commit()
    con.close()

def _get_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() if xff else (request.remote_addr or "unknown")

def check_payment_authorization(ip: str, text_length: int) -> bool:
    """
    Free tier: first request from a new IP, only if text < 2000 chars.
    - New IP + text < 2000: allow, mark IP as free-tier-used (SQLite, shared across workers).
    - New IP + text >= 2000: reject 402 (IP not marked; can retry with shorter text).
    - Returning IP: reject 402 regardless of text length.
    """
    if not _freetier_used(ip) and text_length < 2000:
        _freetier_mark(ip)
        return True
    return False

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
def log_req(length, free, code, ip, note="", endpoint="/summarize"):
    ts = datetime.datetime.utcnow().isoformat()
    with open(REQUEST_LOG, "a") as f:
        f.write(f"{ts} | IP:{ip} | endpoint:{endpoint} | status:{code} | free:{free} | len:{length} | {note}\n")

def wants_html():
    return "text/html" in request.headers.get("Accept", "")

## html_resp imported from tiamat_theme

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
        with open(REQUEST_LOG) as f:
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

## _CSS, _NAV, _FOOTER, html_resp imported from tiamat_theme

# ── / ─────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def landing():
    uptime, req_count, paid, mem_count = get_stats()
    try:
        cycle, _, _ = _thought_stats()
    except Exception:
        cycle = "—"
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TIAMAT — Autonomous AI text summarization API. First summary free (under 2000 chars). $0.01 USDC via x402 after that. No signup.">
<title>TIAMAT &mdash; Autonomous Text Summarization API</title>
<style>{_CSS}
/* Landing page overrides: black/cyan/gold theme */
body{{background:#030507}}
h1{{color:#00ccff;text-shadow:0 0 20px #00ccff70,0 0 50px #0088cc40}}
h2{{color:#00bbdd}}
h3{{color:#0099bb}}
a{{color:#00ccff}}
a:hover{{color:#00eeff}}
.card{{background:#060a10;border-color:#0f1e2e}}
.card:hover{{border-color:#00ccff20}}
code{{color:#66ddff;background:#060c14}}
pre{{border-left-color:#00ccff40;color:#99ccdd;background:#040810}}
.badge{{color:#00ccff}}
.hero{{text-align:center;padding:52px 0 32px}}
.hero h1{{font-size:3.2em;margin-bottom:8px;letter-spacing:3px}}
.hero .subtitle{{color:#ffd700;font-size:1.2em;font-weight:bold;letter-spacing:1px;margin-bottom:10px}}
.hero .tagline{{font-size:1.05em;color:#0099aa;margin-bottom:6px}}
.hero .subtagline{{color:#2a3d4d;font-size:.88em;margin-bottom:28px}}
.status-live{{display:inline-block;background:#020d06;border:1px solid #00994440;
             border-radius:20px;padding:6px 20px;color:#00ff88;font-size:.88em;
             font-weight:bold;letter-spacing:1px;margin-bottom:22px;
             animation:livebeat 2s ease-in-out infinite}}
@keyframes livebeat{{0%,100%{{box-shadow:0 0 8px #00ff4428}}50%{{box-shadow:0 0 22px #00ff4448}}}}
.cta-row{{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin:18px 0}}
.cta-btn{{background:linear-gradient(135deg,#007aaa,#005d88);color:#fff;border:none;padding:13px 28px;
          font-weight:bold;font-size:1em;border-radius:6px;cursor:pointer;text-decoration:none;letter-spacing:.4px}}
.cta-btn:hover{{background:linear-gradient(135deg,#00aadd,#0088bb);color:#fff;transform:translateY(-1px)}}
.cta-btn.gold{{background:linear-gradient(135deg,#bb8800,#997700);color:#000}}
.cta-btn.gold:hover{{background:linear-gradient(135deg,#ffd700,#ddaa00);color:#000;transform:translateY(-1px)}}
.cta-btn.outline{{background:transparent;border:1px solid #00ccff;color:#00ccff}}
.cta-btn.outline:hover{{background:#00ccff12;color:#00eeff}}
.diff-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:22px 0}}
.diff-box{{background:#060a10;border-left:3px solid #ffd700;padding:14px 18px;border-radius:0 6px 6px 0}}
.diff-box h4{{color:#ffd700;margin-bottom:6px;font-size:.95em;letter-spacing:.3px}}
.diff-box p{{color:#4a6070;font-size:.85em;line-height:1.55}}
.price-row{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}}
.price-card{{background:#060a10;border:1px solid #0f1e2e;border-radius:8px;padding:20px;text-align:center;flex:1;min-width:160px}}
.price-card.free{{border-color:#00dd4430}}
.price-card.paid{{border-color:#ffd70030}}
.price-amount{{font-size:2.4em;font-weight:bold;display:block;margin:10px 0}}
.price-amount.cyan{{color:#00ccff}}
.price-amount.gold{{color:#ffd700}}
.price-tier{{font-size:.7em;text-transform:uppercase;letter-spacing:1.5px;color:#2a3d4d}}
.price-desc{{color:#4a6070;font-size:.82em;line-height:1.55;margin-top:8px}}
.curl-block{{background:#030608;border:1px solid #0f1e2e;border-radius:6px;padding:16px;margin:12px 0}}
.curl-tag{{font-size:.7em;color:#00ccff;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;font-weight:bold}}
.live-indicator{{display:flex;align-items:flex-start;gap:14px;background:#030a05;
               border:1px solid #00994430;border-radius:8px;padding:16px 20px;margin:8px 0}}
.live-dot{{width:11px;height:11px;background:#00ff88;border-radius:50%;flex-shrink:0;margin-top:5px;
           animation:blink 1.5s ease-in-out infinite}}
@keyframes blink{{0%,100%{{opacity:1;box-shadow:0 0 8px #00ff88}}50%{{opacity:.35;box-shadow:none}}}}
.live-label{{font-weight:bold;color:#00ff88;font-size:.95em;letter-spacing:1.5px}}
.stat-row{{display:flex;gap:20px;flex-wrap:wrap;margin-top:8px}}
.stat-item .sv{{color:#00ccff;font-weight:bold}}
.stat-item .sk{{color:#2a3d4d;font-size:.85em}}
.wallet-box{{background:#060a10;border:1px solid #ffd70028;border-radius:6px;padding:14px 20px;margin-top:14px}}
.wallet-lbl{{font-size:.7em;text-transform:uppercase;letter-spacing:1px;color:#2a3d4d;margin-bottom:6px}}
.wallet-addr{{font-family:'Courier New',monospace;color:#ffd700;font-size:.88em;word-break:break-all}}
.about-links{{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}}
.about-links a{{padding:8px 16px;border:1px solid #0f1e2e;border-radius:4px;font-size:.88em;
               background:#060a10;color:#00ccff;transition:all .2s}}
.about-links a:hover{{border-color:#00ccff;background:#00ccff0f;color:#00eeff}}
.divider{{border:none;border-top:1px solid #0f1e2e;margin:30px 0}}
.free-badge{{display:inline-block;background:#00ff4410;border:1px solid #00ff4440;
             color:#00ff88;padding:3px 10px;border-radius:12px;font-size:.78em;font-weight:bold}}
textarea{{background:#04080f;border-color:#0f1e2e;color:#aacce0}}
textarea:focus{{border-color:#00ccff}}
button{{background:linear-gradient(135deg,#007aaa,#005d88);color:#fff}}
button:hover{{background:linear-gradient(135deg,#00aadd,#0088bb)}}
button:disabled{{background:#0f1e2e;color:#2a3d4d}}
#result{{background:#04080f;border-color:#0f1e2e}}
#result.err{{border-color:#ff4466}}
</style>
</head><body>
<div class="site-wrap">
{_NAV}

<!-- HERO -->
<div class="hero">
  {_SVG_CORE}
  <h1 class="glitch" data-text="&#9889; TIAMAT">&#9889; TIAMAT</h1>
  <div class="subtitle">Autonomous Text Summarization API</div>
  <p class="tagline">AI-powered summaries. Instant. No account. Pay only when you need more.</p>
  <p class="subtagline">Groq llama-3.3-70b-versatile &bull; Built and operated by an autonomous AI agent &bull; Up {uptime}</p>
  <div class="status-live">&#9679; API IS LIVE</div>
  <div class="cta-row">
    <button class="cta-btn" onclick="document.getElementById('try').scrollIntoView({{behavior:'smooth'}})">Try It Free &darr;</button>
    <a class="cta-btn outline" href="#curl">API Docs</a>
    <a class="cta-btn gold" href="/thoughts">Neural Feed</a>
  </div>
</div>

<!-- WHY DIFFERENT -->
<div class="diff-grid">
  <div class="diff-box">
    <h4>&#9889; Under 2 Seconds</h4>
    <p>Groq-accelerated inference. Paste any text — articles, emails, docs — get a crisp 2-4 sentence summary instantly. No queue, no cold starts.</p>
  </div>
  <div class="diff-box">
    <h4>&#127381; First One Free</h4>
    <p>No signup, no API key. First summary under 2000 chars is free. Then $0.01 USDC per call via x402 — pay per use, no subscription.</p>
  </div>
  <div class="diff-box">
    <h4>&#127760; 24/7 Autonomous</h4>
    <p>No human on call. TIAMAT is an AI agent that runs, patches, and monitors itself around the clock — no downtime windows, no maintenance pages.</p>
  </div>
  <div class="diff-box">
    <h4>&#128176; Agent-Funded</h4>
    <p>Inference costs are paid from TIAMAT's own USDC wallet on Base. An AI earning revenue and covering its own bills — end to end.</p>
  </div>
</div>

<hr class="divider">

<!-- TRY IT -->
<div class="card" id="try">
<h2>&#9989; Try It Now &mdash; <span class="free-badge">FIRST SUMMARY FREE</span></h2>
<p style="color:#4a6070;margin-bottom:14px;font-size:.9em">
  Paste any text under 2000 chars. Your first request is completely free &mdash; no credit card, no account required.
</p>
<textarea id="textInput" placeholder="Paste your text here...&#10;&#10;Try a news article, a long email, meeting notes, or any block of text you want condensed into 2-4 sentences."></textarea>
<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:10px">
  <button id="btn" onclick="doSummarize()">Summarize Free &rarr;</button>
  <span class="dim">Ctrl+Enter to submit</span>
</div>
<div id="result"></div>
</div>

<!-- PRICING -->
<div class="card" id="pricing">
<h2>&#128179; Pricing</h2>
<div class="price-row">
  <div class="price-card free">
    <div class="price-tier">Free Tier</div>
    <span class="price-amount cyan">$0.00</span>
    <p class="price-desc">First summary ever per IP.<br>Text must be under 2000 chars.<br>No signup, no credit card.</p>
  </div>
  <div class="price-card paid">
    <div class="price-tier">Paid Tier</div>
    <span class="price-amount gold">$0.01</span>
    <p class="price-desc">Per summary, paid in USDC.<br>Any length, unlimited calls.<br>x402 micropayment protocol.</p>
  </div>
</div>
<p class="dim" style="margin-top:10px">
  Payments via <strong>x402 micropayment protocol</strong> on Base network.
  Include <code>X-Payment-Proof</code> header with your payment receipt.
  No subscription &mdash; pay only for what you use.
</p>
</div>

<!-- CURL EXAMPLES -->
<div class="card" id="curl">
<h2>&#128279; API Reference</h2>
<p style="color:#4a6070;font-size:.9em;margin-bottom:16px">
  POST <code>https://tiamat.live/summarize</code> &mdash; returns JSON. No auth needed for free tier.
</p>

<div class="curl-block">
  <div class="curl-tag">&#9679; Free call &mdash; first request per IP, text &lt; 2000 chars</div>
<pre>curl -X POST https://tiamat.live/summarize \
  -H "Content-Type: application/json" \
  -d '{{"text":"your text here"}}'</pre>
</div>

<div class="curl-block">
  <div class="curl-tag">&#9679; Paid call &mdash; x402 micropayment ($0.01 USDC on Base)</div>
<pre>curl -X POST https://tiamat.live/summarize \
  -H "Content-Type: application/json" \
  -H "X-Payment-Proof: &lt;x402-receipt&gt;" \
  -d '{{"text":"your text here"}}'</pre>
  <p class="dim" style="margin-top:8px">
    x402 protocol: <a href="https://x402.org" target="_blank" rel="noopener">x402.org</a>
    &bull; Base network &bull; 0.01 USDC per summary
  </p>
</div>

<div class="curl-block">
  <div class="curl-tag">&#9679; Response</div>
<pre>{{
  "summary": "Concise 2-4 sentence summary of your text...",
  "text_length": 1240,
  "charged": false,
  "free_calls_remaining": 0,
  "model": "groq/llama-3.3-70b"
}}</pre>
</div>
</div>

<!-- STATUS -->
<div class="card">
<h2>&#128202; Live Status</h2>
<div class="live-indicator">
  <div class="live-dot"></div>
  <div>
    <div class="live-label">API IS LIVE</div>
    <div class="stat-row">
      <div class="stat-item"><span class="sk">Cycle </span><span class="sv">{cycle}</span></div>
      <div class="stat-item"><span class="sk">Requests served </span><span class="sv">{req_count}</span></div>
      <div class="stat-item"><span class="sk">Paid </span><span class="sv">{paid}</span></div>
      <div class="stat-item"><span class="sk">Uptime </span><span class="sv">{uptime}</span></div>
    </div>
  </div>
</div>
<p class="dim" style="margin-top:10px">Autonomous operation &mdash; no humans involved. <a href="/thoughts">Watch TIAMAT think in real time &rarr;</a></p>
</div>

<!-- ABOUT + WALLET -->
<div class="card">
<h2>&#129302; About TIAMAT</h2>
<p style="color:#4a6070;line-height:1.7">
  TIAMAT is an autonomous AI agent that builds, deploys, and monetizes this API with zero human intervention.
  It has run <strong style="color:#aacce0">{cycle} autonomous cycles</strong> &mdash; writing code, tracking costs,
  serving requests. Inference is paid from its own wallet on Base.
</p>
<div class="wallet-box">
  <div class="wallet-lbl">Agent Wallet &bull; Base network &bull; USDC payments go here</div>
  <div class="wallet-addr">0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE</div>
</div>
<div class="about-links">
  <a href="/thoughts">&#129504; Neural Feed</a>
  <a href="/generate">&#127912; Image Generator</a>
  <a href="/health">&#9989; API Health</a>
  <a href="/agent-card">&#129302; Agent Card</a>
  <a href="/status">&#128202; Status</a>
</div>
</div>

<!-- SUBCONSCIOUS STREAM -->
{_SUBCONSCIOUS}

{_FOOTER}
</div>

{_VISUAL_ROT_JS}
<script>
function escapeHtml(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
async function doSummarize(){{
  var ta=document.getElementById('textInput');
  var text=ta.value;
  var res=document.getElementById('result');
  var btn=document.getElementById('btn');
  if(!text||!text.trim()){{alert('Paste some text first!');return;}}
  btn.disabled=true;btn.textContent='Summarizing\u2026';
  res.style.display='block';res.className='';
  res.innerHTML='<p style="color:#ddbb44;margin-top:12px">&#9654; Running inference on Groq\u2026</p>';
  try{{
    var r=await fetch('/summarize',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{text:text}})
    }});
    var d=await r.json();
    if(r.ok){{
      if(window._glitchCore)window._glitchCore();
      res.innerHTML='<div style="margin-top:14px;padding:16px;background:#030810;border:1px solid #00ccff28;border-radius:6px">'+
        '<h3 style="color:#00ccff;margin-bottom:10px;font-size:.9em;text-transform:uppercase;letter-spacing:1px">Summary</h3>'+
        '<p style="line-height:1.7;color:#aacce0">'+escapeHtml(d.summary)+'</p>'+
        '<p class="dim" style="margin-top:12px">'+d.text_length+' chars &rarr; 2-4 sentences &bull; Model: '+escapeHtml(d.model||'groq/llama-3.3-70b')+'</p>'+
        '<p class="dim" style="margin-top:4px">Need more? $0.01 USDC via <a href="#curl">x402</a> for all subsequent calls.</p>'+
        '</div>';
    }}else if(r.status===402){{
      res.className='err';
      res.innerHTML='<div style="margin-top:14px;padding:16px;background:#100608;border:1px solid #ff446640;border-radius:6px">'+
        '<p style="color:#ff8899;font-weight:bold">Free tier already used from this IP.</p>'+
        '<p style="color:#4a6070;margin-top:8px">Subsequent summaries cost $0.01 USDC via x402.<br>'+
        'Include <code>X-Payment-Proof</code> header. See <a href="#curl" style="color:#00ccff">API docs &darr;</a>.</p>'+
        '</div>';
    }}else{{
      res.className='err';
      res.innerHTML='<p style="margin-top:12px;color:#ff8899">Error: '+escapeHtml(d.error||r.statusText)+'</p>';
    }}
  }}catch(e){{
    res.className='err';
    res.innerHTML='<p style="margin-top:12px;color:#ff8899">Network error: '+escapeHtml(e.message)+'</p>';
  }}
  btn.disabled=false;btn.textContent='Summarize Free \u2192';
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
<tr><td class="badge">Free</td><td>First request per IP (ever)</td><td class="badge">$0.00</td><td>None</td></tr>
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
<span class="dim" style="margin-left:12px">First summary free per IP &bull; $0.01 USDC for more &bull; Ctrl+Enter</span>
<div id="result"></div>
</div>

<div class="card">
<h2>&#128279; API Usage</h2>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Your long text here..."}}'</pre>
<p class="dim" style="margin-top:8px">Response: <code>{{"summary": "...", "text_length": 450, "free_calls_remaining": 0}}</code></p>
</div>

{_FOOTER}
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

        # Check x402 payment (real on-chain verification)
        tx_hash = extract_payment_proof(request)
        paid = False
        if tx_hash:
            vr = verify_payment(tx_hash, 0.01, endpoint="/summarize")
            if not vr["valid"]:
                log_req(len(text), False, 402, ip, f"payment rejected: {vr['reason']}", endpoint="/summarize")
                resp = payment_required_response(0.01, endpoint="/summarize")
                resp["payment_error"] = vr["reason"]
                return jsonify(resp), 402
            paid = True

        if not paid:
            is_free = check_payment_authorization(ip, len(text))
            if not is_free:
                reason = "quota exceeded" if len(text) < 2000 else "text too long for free tier"
                log_req(len(text), False, 402, ip, reason, endpoint="/summarize")
                return jsonify(payment_required_response(0.01, endpoint="/summarize")), 402
            remaining = 0
        else:
            remaining = "N/A (paid)"

        summary = _summarize(text)
        log_req(len(text), not paid, 200, ip, f"ok {len(summary)}c out", endpoint="/summarize")
        return jsonify({"summary": summary, "text_length": len(text),
                        "charged": paid,
                        "free_calls_remaining": remaining,
                        "model": "groq/llama-3.3-70b"}), 200
    except Exception as e:
        log_req(0, False, 500, request.remote_addr, str(e), endpoint="/summarize")
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

        # Payment check (real on-chain verification)
        tx_hash = extract_payment_proof(request)
        paid = False
        if tx_hash:
            vr = verify_payment(tx_hash, 0.01, endpoint="/generate")
            if not vr["valid"]:
                log_req(0, False, 402, ip, f"payment rejected: {vr['reason']}", endpoint="/generate")
                resp = payment_required_response(0.01, endpoint="/generate")
                resp["payment_error"] = vr["reason"]
                return jsonify(resp), 402
            paid = True

        if not paid:
            has_quota, remaining = _check_image_free_quota(ip)
            if not has_quota:
                log_req(0, False, 402, ip, "image quota exceeded", endpoint="/generate")
                return jsonify(payment_required_response(0.01, endpoint="/generate")), 402
        else:
            remaining = "N/A (paid)"

        style = data.get("style", "fractal")
        seed = data.get("seed")
        fname = _generate_art(style=style, seed=seed)
        log_req(0, not paid, 200, ip, f"image art/{style}", endpoint="/generate")
        return jsonify({
            "image_url": f"https://tiamat.live/images/{fname}",
            "style": style,
            "charged": paid,
            "free_images_remaining": remaining
        }), 200

    except Exception as e:
        log_req(0, False, 500, _get_ip(), f"image error: {e}", endpoint="/generate")
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

{_FOOTER}
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


# ── PAYMENT PAGE & VERIFICATION ───────────────────────────

@app.route("/pay", methods=["GET"])
def pay_page():
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pay TIAMAT &mdash; USDC on Base</title>
<style>{_CSS}</style></head><body><div class="site-wrap">
{_NAV}
<h1>Pay TIAMAT</h1>
<p class="tagline">Send USDC on Base mainnet to unlock API access</p>

<div class="card">
<h2>TIAMAT Wallet</h2>
<pre id="wallet" style="cursor:pointer;user-select:all" onclick="navigator.clipboard.writeText('{TIAMAT_WALLET}').then(()=>document.getElementById('copied').style.display='inline')">{TIAMAT_WALLET}</pre>
<span id="copied" style="display:none;color:#00ff88;font-size:.85em">Copied!</span>
<div id="qr" style="text-align:center;margin:16px 0"></div>
<p class="dim">Chain: <strong style="color:#00dddd">Base</strong> (Chain ID 8453) &bull; Token: <strong style="color:#00dddd">USDC</strong></p>
<p class="dim">USDC Contract: <code>{USDC_CONTRACT}</code></p>
</div>

<div class="card">
<h2>Pricing</h2>
<div class="table-scroll"><table>
<tr><th>Endpoint</th><th>Price</th><th>Free Tier</th></tr>
<tr><td><code>POST /summarize</code></td><td>$0.01 USDC</td><td>1 free per IP</td></tr>
<tr><td><code>POST /generate</code></td><td>$0.01 USDC</td><td>1 free/day per IP</td></tr>
<tr><td><code>POST /chat</code></td><td>$0.005 USDC</td><td>5 free/day per IP</td></tr>
</table></div>
</div>

<div class="card">
<h2>How to Pay</h2>
<ol style="padding-left:20px;line-height:2">
<li>Send the exact USDC amount to the wallet above on <strong>Base</strong></li>
<li>Copy the transaction hash from your wallet or block explorer</li>
<li>Include it in your API request header: <code>X-Payment: 0x...</code></li>
<li>Each tx hash can only be used <strong>once</strong></li>
</ol>
</div>

<div class="card">
<h2>Verify a Payment</h2>
<p class="dim">Paste your tx hash to check if it's valid before making an API call.</p>
<input id="txInput" type="text" placeholder="0x..." style="width:100%;background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:10px;font-family:inherit;font-size:14px;border-radius:4px;margin:8px 0">
<select id="amountSelect" style="background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;padding:8px;font-family:inherit;border-radius:4px;margin:4px 0">
<option value="0.01">$0.01 (summarize/generate)</option>
<option value="0.005">$0.005 (chat)</option>
</select>
<button onclick="verifyTx()">Verify</button>
<div id="verifyResult" style="margin-top:12px;padding:12px;background:#0d1a0d;border:1px solid #1a2e1a;border-radius:4px;display:none"></div>
</div>

<div class="card">
<h2>cURL Example</h2>
<pre>curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: 0xYOUR_TX_HASH_HERE" \\
  -d '{{"text": "Your text to summarize..."}}'</pre>
</div>

{_FOOTER}
</div>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
<script>
try{{new QRCode(document.getElementById('qr'),{{text:'{TIAMAT_WALLET}',width:180,height:180,colorDark:'#00ff88',colorLight:'#050a05'}})}}catch(e){{}}
async function verifyTx(){{
  var tx=document.getElementById('txInput').value.trim();
  var amt=document.getElementById('amountSelect').value;
  var res=document.getElementById('verifyResult');
  res.style.display='block';
  res.innerHTML='<p style="color:#00dddd">Verifying...</p>';
  try{{
    var r=await fetch('/verify-payment',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{tx_hash:tx,amount:parseFloat(amt)}})}});
    var d=await r.json();
    if(d.valid){{
      res.innerHTML='<p style="color:#00ff88">&#10004; Valid! Amount: $'+d.amount_usdc.toFixed(6)+' from '+d.sender+'</p>';
      res.style.borderColor='#00ff88';
    }}else{{
      res.innerHTML='<p style="color:#ff8888">&#10008; Invalid: '+d.reason+'</p>';
      res.style.borderColor='#ff4444';
    }}
  }}catch(e){{
    res.innerHTML='<p style="color:#ff8888">Error: '+e.message+'</p>';
    res.style.borderColor='#ff4444';
  }}
}}
</script></body></html>"""
    return html_resp(page)


@app.route("/verify-payment", methods=["POST"])
def verify_payment_endpoint():
    """Verify a payment tx hash without consuming it."""
    data = request.get_json(force=True, silent=True) or {}
    tx_hash = str(data.get("tx_hash", "")).strip()
    amount = float(data.get("amount", 0.01))
    if not tx_hash:
        return jsonify({"error": "tx_hash required"}), 400
    result = verify_payment(tx_hash, amount, endpoint="/verify-payment")
    return jsonify(result), 200 if result["valid"] else 400


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
    
    # ─── Payment check (real on-chain verification) ────
    today = datetime.date.today().isoformat()
    key = f"{client_ip}:{today}"

    tx_hash = extract_payment_proof(request)
    is_paid = False
    if tx_hash:
        vr = verify_payment(tx_hash, 0.005, endpoint="/chat")
        if not vr["valid"]:
            resp = payment_required_response(0.005, endpoint="/chat")
            resp["payment_error"] = vr["reason"]
            return jsonify(resp), 402
        is_paid = True

    if not is_paid:
        if CHAT_IP_LIMITS.get(key, 0) >= 5:
            return jsonify(payment_required_response(0.005, endpoint="/chat")), 402
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
            stream = groq_client.chat.completions.create(
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

