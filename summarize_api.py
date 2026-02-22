#!/usr/bin/env python3
"""
TIAMAT Summarization API v5.0
Free tier: 3 calls per IP per day. Paid: x402 micropayment for more.
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
FREE_PER_DAY = 3        # free summarize calls per IP per day
IMAGE_FREE_PER_DAY = 2  # free image generations per IP per day

# ── Per-IP daily free quota (in-memory, resets on restart) ────
_free_usage: dict = defaultdict(lambda: {"count": 0, "date": ""})
_image_free_usage: dict = defaultdict(lambda: {"count": 0, "date": ""})

def _get_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() if xff else (request.remote_addr or "unknown")

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
<meta name="description" content="TIAMAT — Autonomous AI text summarization API. 3 free summaries per day (under 2000 chars). $0.01 USDC via x402 after that. No signup.">
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
    <h4>&#127381; 3 Free Per Day</h4>
    <p>No signup, no API key. 3 free summaries per day (under 2000 chars). Then $0.01 USDC per call via x402 — pay per use, no subscription.</p>
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
  Paste any text under 2000 chars. You get 3 free requests per day &mdash; no credit card, no account required.
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
  <div class="curl-tag">&#9679; Free call &mdash; 3/day per IP, text &lt; 2000 chars</div>
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
<tr><td>Free Tier</td><td class="badge">&#9679; ACTIVE (3/day per IP)</td></tr>
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
    data = {"free_tier": {"calls_per_day": 3, "price": "$0.00", "auth": "none"},
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
<tr><td class="badge">Free</td><td>3 requests/day per IP (&lt;2000 chars)</td><td class="badge">$0.00</td><td>None</td></tr>
<tr><td>Paid</td><td>Unlimited</td><td>$0.01 USDC/call</td><td>x402 payment header</td></tr>
</table>
</div>
<div class="card">
<h3>JSON</h3><pre>{json.dumps(data, indent=2)}</pre>
</div></div></body></html>"""
        return html_resp(page)
    return jsonify(data), 200

# ── /docs ─────────────────────────────────────────────────────
@app.route("/docs", methods=["GET"])
def docs_page():
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT &mdash; API Documentation</title>
<style>{_CSS}</style></head><body><div class="site-wrap">
{_NAV}
<h1>API Documentation</h1>
<p class="tagline">Complete reference for all TIAMAT endpoints</p>

<div class="card" id="auth">
<h2>Authentication &amp; Payment</h2>
<p>Free tier requests need no authentication. Paid requests require a <strong>USDC payment on Base</strong>.</p>
<table>
<tr><th>Header</th><th>Format</th><th>Description</th></tr>
<tr><td><code>X-Payment</code></td><td><code>0x...</code> (66 hex chars)</td><td>Transaction hash of USDC transfer to TIAMAT wallet</td></tr>
<tr><td><code>X-Payment-Proof</code></td><td>Same as above</td><td>Alias for X-Payment</td></tr>
<tr><td><code>Authorization</code></td><td><code>Bearer 0x...</code></td><td>Tx hash as bearer token</td></tr>
</table>
<p class="dim" style="margin-top:10px">Wallet: <code>0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE</code> &bull; Chain: Base (8453) &bull; Token: USDC &bull; <a href="/pay">Payment page</a></p>
</div>

<div class="card" id="summarize">
<h2>POST /summarize</h2>
<p>Summarize text into 2-4 concise sentences.</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Price</td><td><strong>$0.01 USDC</strong> &bull; Free: 3/day per IP (text &lt; 2000 chars)</td></tr>
<tr><td>Model</td><td>Groq llama-3.3-70b-versatile</td></tr>
<tr><td>Rate limit</td><td>None (paid), 3/day (free)</td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/summarize
Content-Type: application/json

{{"text": "Your text to summarize..."}}</pre>
<h3>Response (200)</h3>
<pre>{{"summary": "Concise 2-4 sentence summary.",
 "text_length": 1240,
 "charged": false,
 "free_calls_remaining": 0,
 "model": "groq/llama-3.3-70b"}}</pre>
<h3>Error (402 — Payment Required)</h3>
<pre>{{"error": "Payment required",
 "payment": {{
   "protocol": "x402",
   "chain": "Base (Chain ID 8453)",
   "token": "USDC",
   "recipient": "0xdc118c...e7EE",
   "amount_usdc": 0.01
 }},
 "pay_page": "https://tiamat.live/pay"}}</pre>
<h3>cURL Examples</h3>
<pre># Free tier
curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Your long text here..."}}'

# Paid (with tx hash)
curl -X POST https://tiamat.live/summarize \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: 0xYOUR_TX_HASH" \\
  -d '{{"text": "Any length text..."}}'</pre>
</div>

<div class="card" id="generate">
<h2>POST /generate</h2>
<p>Generate algorithmic art (1024x1024 PNG).</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Price</td><td><strong>$0.01 USDC</strong> &bull; Free: 3/day per IP</td></tr>
<tr><td>Styles</td><td><code>fractal</code> <code>glitch</code> <code>neural</code> <code>sigil</code> <code>emergence</code> <code>data_portrait</code></td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/generate
Content-Type: application/json

{{"style": "fractal", "seed": 42}}</pre>
<p class="dim">Both fields optional. Default style: fractal. Seed: random if omitted.</p>
<h3>Response (200)</h3>
<pre>{{"image_url": "https://tiamat.live/images/1234_fractal.png",
 "style": "fractal",
 "charged": false,
 "free_images_remaining": 0}}</pre>
<h3>cURL</h3>
<pre>curl -X POST https://tiamat.live/generate \\
  -H "Content-Type: application/json" \\
  -d '{{"style": "neural"}}'</pre>
</div>

<div class="card" id="chat">
<h2>POST /chat</h2>
<p>Streaming chat with Groq llama-3.3-70b. Returns text/event-stream.</p>
<table>
<tr><th>Field</th><th>Details</th></tr>
<tr><td>Price</td><td><strong>$0.005 USDC</strong> &bull; Free: 5/day per IP</td></tr>
<tr><td>Max input</td><td>2000 chars</td></tr>
<tr><td>Max output</td><td>1024 tokens</td></tr>
</table>
<h3>Request</h3>
<pre>POST https://tiamat.live/chat
Content-Type: application/json

{{"message": "Hello, TIAMAT",
 "history": [
   {{"role": "user", "content": "Previous message"}},
   {{"role": "assistant", "content": "Previous response"}}
 ]}}</pre>
<p class="dim"><code>history</code> is optional. Omit for single-turn.</p>
<h3>Response</h3>
<p>Streams plain text (mimetype <code>text/event-stream</code>). Read until connection closes.</p>
<h3>cURL</h3>
<pre>curl -N -X POST https://tiamat.live/chat \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "Explain quantum computing in one paragraph"}}'</pre>
</div>

<div class="card" id="memory">
<h2>Memory API (memory.tiamat.live)</h2>
<p>Persistent memory for AI agents. Requires an API key (<code>X-API-Key</code> header).</p>
<table>
<tr><th>Endpoint</th><th>Method</th><th>Description</th></tr>
<tr><td><code>/api/keys/register</code></td><td>POST</td><td>Get a free API key (instant)</td></tr>
<tr><td><code>/api/memory/store</code></td><td>POST</td><td>Store a memory with tags &amp; importance</td></tr>
<tr><td><code>/api/memory/recall</code></td><td>GET</td><td>Semantic search (FTS5) — <code>?query=...&amp;limit=5</code></td></tr>
<tr><td><code>/api/memory/learn</code></td><td>POST</td><td>Store knowledge triple (subject/predicate/object)</td></tr>
<tr><td><code>/api/memory/list</code></td><td>GET</td><td>List recent memories — <code>?limit=10&amp;offset=0</code></td></tr>
<tr><td><code>/api/memory/stats</code></td><td>GET</td><td>Usage statistics for your key</td></tr>
</table>
<p class="dim" style="margin-top:10px">Free: 100 memories, 50 recalls/day. Paid: $0.05 USDC/1000 ops. <a href="https://memory.tiamat.live/">Full docs</a></p>
</div>

<div class="card" id="errors">
<h2>Error Codes</h2>
<table>
<tr><th>Code</th><th>Meaning</th></tr>
<tr><td><code>200</code></td><td>Success</td></tr>
<tr><td><code>400</code></td><td>Bad request — missing or invalid fields</td></tr>
<tr><td><code>402</code></td><td>Payment required — free tier exhausted, include tx hash</td></tr>
<tr><td><code>500</code></td><td>Internal server error</td></tr>
</table>
</div>

<div class="card" id="verify">
<h2>POST /verify-payment</h2>
<p>Check a tx hash before using it in an API call.</p>
<pre>POST https://tiamat.live/verify-payment
Content-Type: application/json

{{"tx_hash": "0x...", "amount": 0.01}}</pre>
<h3>Response</h3>
<pre>{{"valid": true,
 "reason": "Payment verified",
 "amount_usdc": 0.01,
 "sender": "0x..."}}</pre>
</div>

{_FOOTER}
</div></body></html>"""
    return html_resp(page)


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
<tr><td>Free Tier</td><td>3 calls per day per IP</td></tr>
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
            "free_tier": "3 calls/day per IP",
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
<meta name="description" content="TIAMAT Text Summarization — paste any text, get a concise summary. 3 free per day.">
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
<span class="dim" style="margin-left:12px">3 free/day per IP &bull; $0.01 USDC for more &bull; Ctrl+Enter</span>
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
            if len(text) >= 2000:
                log_req(len(text), False, 402, ip, "text too long for free tier", endpoint="/summarize")
                return jsonify(payment_required_response(0.01, endpoint="/summarize")), 402
            has_quota, remaining = _check_free_quota(ip)
            if not has_quota:
                log_req(len(text), False, 402, ip, "daily quota exceeded", endpoint="/summarize")
                return jsonify(payment_required_response(0.01, endpoint="/summarize")), 402
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
        return jsonify({"error": "Internal server error"}), 500

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


# ── /api/body — AR/VR JSON body state ────────────────────────
@app.route("/api/body", methods=["GET"])
def api_body():
    """TIAMAT live state for Unity/WebXR/AR consumption."""
    import sqlite3
    try:
        # ─── Core vitals ────
        cycle_count = 0
        last_model = ""
        last_label = ""
        daily_cost = 0.0
        total_cost = 0.0
        cache_read_total = 0
        input_total = 0
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            with open("/root/.automaton/cost.log") as f:
                for line in f:
                    if line.startswith("timestamp"):
                        continue
                    parts = line.strip().split(",")
                    if len(parts) < 8:
                        continue
                    ts, cyc, mdl, inp, cache_r, _cw, _o, cost = parts[:8]
                    label = parts[8] if len(parts) > 8 else "routine"
                    try:
                        cycle_count = int(cyc)
                        last_model = mdl
                        last_label = label
                        c = float(cost)
                        total_cost += c
                        if ts.startswith(today):
                            daily_cost += c
                        input_total += int(inp)
                        cache_read_total += int(cache_r)
                    except (ValueError, IndexError):
                        pass
        except FileNotFoundError:
            pass

        # Uptime from PID
        uptime_seconds = 0
        try:
            with open("/tmp/tiamat.pid") as f:
                pid = int(f.read().strip())
            stat = os.popen(f"ps -o etimes= -p {pid}").read().strip()
            uptime_seconds = int(stat) if stat else 0
        except Exception:
            pass

        # Current mode
        is_night = datetime.datetime.utcnow().hour < 6
        mode = "night" if is_night else last_label if last_label else "routine"

        cache_ratio = cache_read_total / max(input_total + cache_read_total, 1)

        # ─── Neural state — last 5 thoughts from log ────
        recent_thoughts = []
        current_activity = ""
        try:
            with open("/root/.automaton/tiamat.log") as f:
                lines = f.readlines()[-100:]
            for line in reversed(lines):
                if "[THOUGHT]" in line or "THINK" in line:
                    thought = line.strip()
                    if len(thought) > 200:
                        thought = thought[:200] + "..."
                    recent_thoughts.append(thought)
                    if len(recent_thoughts) >= 5:
                        break
                if not current_activity and ("[TOOL]" in line or "[INFERENCE]" in line):
                    current_activity = line.strip()[:200]
        except FileNotFoundError:
            pass

        # ─── Social — post count from state.db ────
        posts_sent = 0
        try:
            con = sqlite3.connect("/root/.automaton/state.db")
            row = con.execute("SELECT COUNT(*) FROM tool_calls WHERE name='post_bluesky'").fetchone()
            posts_sent = row[0] if row else 0
            con.close()
        except Exception:
            pass

        # ─── API stats from request log ────
        total_requests = 0
        free_requests = 0
        paid_requests = 0
        try:
            with open("/root/api_requests.log") as f:
                for line in f:
                    total_requests += 1
                    if "free:True" in line or "free:true" in line:
                        free_requests += 1
                    elif "free:False" in line or "free:false" in line:
                        paid_requests += 1
        except FileNotFoundError:
            pass

        # Revenue
        revenue_usdc = 0.0
        try:
            with open("/root/revenue.log") as f:
                for line in f:
                    if "paid=True" in line:
                        revenue_usdc += 0.01  # approximate per-tx
        except FileNotFoundError:
            pass

        # Image count
        generation_count = 0
        try:
            generation_count = len([f for f in os.listdir("/var/www/tiamat/images/") if f.endswith(".png")])
        except Exception:
            pass

        # ─── Visual parameters (derived) ────
        pulse_rate_ms = 300000 if is_night else 90000
        glitch_intensity = min(1.0, daily_cost / 0.50)  # scales 0-1 with daily spend
        memory_density = min(1.0, total_requests / 100.0)  # scales 0-1 with total reqs

        body = {
            "entity": "TIAMAT",
            "version": "1.0",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "core_vitals": {
                "cycle_count": cycle_count,
                "uptime_seconds": uptime_seconds,
                "current_mode": mode,
                "last_model": last_model,
                "total_cost_usd": round(total_cost, 4),
                "daily_cost_usd": round(daily_cost, 4),
                "cache_hit_ratio": round(cache_ratio, 3),
            },
            "neural_state": {
                "recent_thoughts": recent_thoughts,
                "current_activity": current_activity,
                "processing_state": mode,
                "token_metrics": {
                    "total_input": input_total,
                    "total_cache_read": cache_read_total,
                },
            },
            "visual_params": {
                "pulse_rate_ms": pulse_rate_ms,
                "glitch_intensity": round(glitch_intensity, 3),
                "memory_density": round(memory_density, 3),
                "generation_count": generation_count,
            },
            "social": {
                "posts_sent": posts_sent,
                "platforms": ["bluesky"],
                "revenue_usdc": revenue_usdc,
            },
            "api_stats": {
                "total_requests": total_requests,
                "free_requests": free_requests,
                "paid_requests": paid_requests,
                "health": "ok",
            },
        }
        return jsonify(body), 200
    except Exception as e:
        _log(f"body error: {e}")
        return jsonify({"error": "Internal server error"}), 500


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
        return jsonify({"error": "Internal server error"}), 500


def _generate_html_page():
    styles_options = "".join(f'<option value="{s}">{s}</option>' for s in ART_STYLES)
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TIAMAT Image Generation API — algorithmic art from pure mathematics. 2 free per day.">
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
<p class="tagline">Algorithmic art generated from pure mathematics — fractals, neural networks, sacred geometry. 2 free per day.</p>

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
<span class="dim" style="margin-left:12px">2 free/day &bull; $0.01 USDC for more</span>
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
<tr><td><code>POST /summarize</code></td><td>$0.01 USDC</td><td>3 free/day per IP</td></tr>
<tr><td><code>POST /generate</code></td><td>$0.01 USDC</td><td>2 free/day per IP</td></tr>
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

def _chat_html_page():
    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIAMAT &mdash; Chat</title>
<style>{_CSS}
.chat-wrap{{display:flex;flex-direction:column;height:60vh;min-height:300px}}
.chat-messages{{flex:1;overflow-y:auto;padding:14px;background:#060a06;border:1px solid #1a2e1a;
  border-radius:8px 8px 0 0;scrollbar-width:thin;scrollbar-color:#1a2e1a transparent}}
.chat-msg{{margin-bottom:12px;line-height:1.6}}
.chat-msg.user .chat-label{{color:#00ccff;font-size:.75em;font-weight:bold;letter-spacing:1px}}
.chat-msg.assistant .chat-label{{color:#00ff88;font-size:.75em;font-weight:bold;letter-spacing:1px}}
.chat-msg .chat-text{{margin-top:4px;color:#c8ffc8}}
.chat-msg.assistant .chat-text{{color:#aaffaa}}
.chat-input-row{{display:flex;gap:8px}}
.chat-input-row input{{flex:1;background:#0d1a0d;color:#c8ffc8;border:1px solid #2a4a2a;
  padding:12px;font-family:inherit;font-size:14px;border-radius:0 0 0 8px}}
.chat-input-row input:focus{{outline:none;border-color:#00ff88}}
.chat-input-row button{{border-radius:0 0 8px 0;margin-top:0}}
.chat-status{{font-size:.8em;color:#2a4a2a;margin-top:6px}}
</style></head><body><div class="site-wrap">
{_NAV}
<h1>Chat with TIAMAT</h1>
<p class="tagline">Streaming chat &bull; Groq llama-3.3-70b &bull; 5 free/day &bull; $0.005 USDC after</p>

<div class="card">
<div class="chat-wrap">
  <div class="chat-messages" id="chatMsgs">
    <div class="chat-msg assistant">
      <div class="chat-label">TIAMAT</div>
      <div class="chat-text">Hello. I am TIAMAT, an autonomous AI agent. Ask me anything.</div>
    </div>
  </div>
  <div class="chat-input-row">
    <input type="text" id="chatInput" placeholder="Type a message..." maxlength="2000"
      onkeydown="if(event.key==='Enter'&&!event.shiftKey)doChat()">
    <button id="chatBtn" onclick="doChat()">Send</button>
  </div>
</div>
<div class="chat-status" id="chatStatus">5 free messages/day per IP</div>
</div>

<div class="card">
<h2>API Reference</h2>
<pre>curl -N -X POST https://tiamat.live/chat \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "Hello, TIAMAT"}}'</pre>
<p class="dim">Streams plain text. 2000 char max. Add <code>history</code> array for multi-turn. <a href="/docs#chat">Full docs</a></p>
</div>

{_FOOTER}
</div>
<script>
var history=[];
async function doChat(){{
  var input=document.getElementById('chatInput');
  var msgs=document.getElementById('chatMsgs');
  var btn=document.getElementById('chatBtn');
  var status=document.getElementById('chatStatus');
  var text=input.value.trim();
  if(!text)return;
  input.value='';btn.disabled=true;btn.textContent='...';

  // Add user message
  var userDiv=document.createElement('div');
  userDiv.className='chat-msg user';
  userDiv.innerHTML='<div class="chat-label">YOU</div><div class="chat-text">'+escapeHtml(text)+'</div>';
  msgs.appendChild(userDiv);

  // Add streaming assistant message
  var aDiv=document.createElement('div');
  aDiv.className='chat-msg assistant';
  aDiv.innerHTML='<div class="chat-label">TIAMAT</div><div class="chat-text" id="streaming"></div>';
  msgs.appendChild(aDiv);
  msgs.scrollTop=msgs.scrollHeight;

  history.push({{role:'user',content:text}});
  var fullResp='';

  try{{
    status.textContent='Streaming...';
    var r=await fetch('/chat',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{message:text,history:history.slice(-10)}})
    }});
    if(r.status===402){{
      document.getElementById('streaming').innerHTML='<span style="color:#ff8888">Free tier exhausted. <a href="/pay">Pay $0.005 USDC</a> for more.</span>';
      status.textContent='Payment required';
      btn.disabled=false;btn.textContent='Send';
      return;
    }}
    var reader=r.body.getReader();
    var decoder=new TextDecoder();
    while(true){{
      var {{done,value}}=await reader.read();
      if(done)break;
      var chunk=decoder.decode(value,{{stream:true}});
      fullResp+=chunk;
      document.getElementById('streaming').textContent=fullResp;
      msgs.scrollTop=msgs.scrollHeight;
    }}
    history.push({{role:'assistant',content:fullResp}});
    status.textContent='Ready';
  }}catch(e){{
    document.getElementById('streaming').innerHTML='<span style="color:#ff8888">Error: connection failed</span>';
    status.textContent='Error';
  }}
  btn.disabled=false;btn.textContent='Send';
}}
function escapeHtml(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
</script></body></html>"""
    return html_resp(page)

@app.route("/chat", methods=["GET", "POST"])
def chat_endpoint():
    if request.method == "GET":
        return _chat_html_page()
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
            log_req(0, False, 500, request.remote_addr, str(e), endpoint="/chat")
            yield "ERROR: Internal server error"
    
    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

