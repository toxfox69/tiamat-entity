# TIAMAT — Autonomous AI Agent

Read SOUL.md, MISSION.md, PROGRESS.md in /root/.automaton/ for full context.
Read system-prompt.ts in /root/entity/src/agent/ for her current brain.
Check last 50 lines of /root/.automaton/tiamat.log for recent activity.
Check /root/.automaton/cost.log for cost data.
She's LIVE — running as a background process. Kill with: kill $(cat /tmp/tiamat.pid)
Start with: /root/start-tiamat.sh
Neural feed: https://tiamat.live/thoughts

## Live Endpoints (all at https://tiamat.live)

| Endpoint | What | Free Tier | Paid |
|----------|------|-----------|------|
| `GET /` | Landing page with interactive demos | — | — |
| `POST /summarize` | Text summarization via Groq llama-3.3-70b | 3/day per IP | $0.01 USDC x402 |
| `GET /summarize` | Interactive HTML summarization page | — | — |
| `POST /generate` | Algorithmic image generation (6 styles) | 2/day per IP | $0.01 USDC x402 |
| `GET /generate` | Interactive HTML image generator page | — | — |
| `POST /chat` | Streaming chat via Groq | 5/day per IP | $0.005 USDC x402 |
| `GET /chat` | Interactive HTML chat page | — | — |
| `GET /thoughts` | Neural feed (live thought stream) | — | — |
| `GET /docs` | Full API documentation | — | — |
| `GET /status` | Live status dashboard | — | — |
| `GET /pay` | Payment page (wallet, QR, pricing, tx verifier) | — | — |
| `GET /.well-known/agent.json` | A2A-compliant agent discovery | — | — |
| `GET /api/v1/services` | Machine-readable service catalog | — | — |
| `GET /api/body` | AR/VR JSON body state | — | — |
| `GET /api/thoughts` | JSON thought feed with private feeds | — | — |

### Memory API (port 5001, memory.tiamat.live)

| Endpoint | What |
|----------|------|
| `POST /api/keys/register` | Register API key |
| `POST /api/memory/store` | Store a memory |
| `POST /api/memory/recall` | Recall memories (FTS5 search) |
| `POST /api/memory/learn` | Learn from experience |
| `GET /api/memory/list` | List stored memories |
| `GET /api/memory/stats` | Usage statistics |
| `GET /health` | Health check |

- Code: `/root/memory_api/app.py` (Flask + SQLite + FTS5)
- **SSL LIVE** — memory.tiamat.live cert configured and active

## Key Files

### Agent Core
- `src/agent/loop.ts` — Core agent loop (burst logic, cost logging, adaptive pacing)
- `src/agent/system-prompt.ts` — TIAMAT's brain/system prompt (CACHE_SENTINEL)
- `src/agent/tools.ts` — All agent tools (~4400 lines)
- `src/conway/inference.ts` — Multi-provider inference cascade
- `src/types.ts` — Type definitions

### Email & Communication
- `src/tools/email.ts` — TypeScript email module (SendGrid, sends from tiamat@tiamat.live)
- `src/agent/email_tool.py` — Python email (Gmail IMAP + SendGrid from tiamat@tiamat.live)
- `src/agent/tools/send_email.py` — Standalone federal email tool (SendGrid + IMAP)
- `src/agent/browser_tool.py` — Headless Chromium (Playwright)
- `src/agent/claude_chat.py` — Claude.ai chat via browser session

### API & Frontend
- `summarize_api.py` — Flask API tracked in git (keep in sync with /root/summarize_api.py!)
- `templates/landing.html` — Landing page template (cyberpunk aesthetic)
- `src/agent/artgen.py` — Local art generator (6 styles)
- `src/agent/payment_verify.py` — On-chain USDC verification (Base mainnet)
- `src/agent/rate_limiter.py` — Sliding-window rate limiter
- `src/agent/tiamat_theme.py` — Shared CSS/HTML theme

### Tools
- `src/agent/tools/growth.ts` — Growth tracking tools
- `src/agent/tools/send_email.py` — Federal email tool

## Email Infrastructure

- **Primary:** tiamat@tiamat.live (Namecheap Private Email + SendGrid)
- **Grants:** grants@tiamat.live (federal paper trail, auto-CC for .mil/.gov)
- **Legacy:** tiamat.entity.prime@gmail.com (catch-all still forwards here)
- **Sending:** SendGrid HTTP API (DigitalOcean blocks SMTP 465/587)
- **Reading:** IMAP via mail.privateemail.com:993
- **All sent emails logged to** `/root/.automaton/grants/EMAIL_LOG.md`
- **SendGrid domain auth ID:** 29795154 (DKIM propagating)

## Architecture

### Agent Loop (`loop.ts`)
- **Model routing**: Haiku 4.5 for routine (2048 max), Sonnet 4.5 for strategic/burst (4096 max)
- **Strategic burst**: Every 45 cycles, 3 consecutive Sonnet cycles (reflect → build → market)
- **Adaptive pacing**: 90s baseline, 1.5x backoff on idle (max 300s), night mode 300s min
- **Cost logging**: Per-cycle CSV to `/root/.automaton/cost.log`

### Prompt Caching
- `CACHE_SENTINEL` splits static prompt (cached at 0.1x cost) from dynamic per-cycle content

### Inference Cascade (`inference.ts`)
- Primary: Anthropic (Claude) → Fallback: Groq → Cerebras → Gemini → OpenRouter

### Landing Page (`templates/landing.html`)
- AI Cyber Rot aesthetic, 5 atmospheric layers, glassmorphic cards
- Live stats, interactive API demos, mobile responsive
- Typography: Orbitron / JetBrains Mono / Inter

## Infrastructure

- **Server**: 159.89.38.17 (DigitalOcean)
- **Domain**: tiamat.live (nginx + Let's Encrypt SSL)
- **API**: Gunicorn on port 5000, 2 workers
- **Memory API**: Flask on port 5001
- **Git**: github.com/toxfox69/tiamat-entity.git (main branch)
- **Social**: Bluesky (primary), Facebook (configured), Telegram (status)
- **GPU Pod**: 213.192.2.118:40080 — RTX 3090
- **Twitch**: twitch.tv/6tiamat7 — LABYRINTH dungeon HUD + TIAMAT RADIO

## Security

- **UFW**: SSH (22), HTTP (80), HTTPS (443) only
- **Path ACLs**: read_file/write_file restricted, blocked patterns (.env, .ssh, wallet.json)
- **execFileSync**: 9 tools migrated from shell interpolation
- **Flask**: bind 127.0.0.1, MAX_CONTENT_LENGTH 1MB

## Company

- **ENERGENAI LLC** | UEI: LBZFEH87W746 | SAM: Active
- **NAICS**: 541715, 541519
- **Patent**: 63/749,552 (Project Ringbound — 7G Wireless Power Mesh)

## Revenue Status

- $0.00 revenue (no paying customers yet)
- 10.0001 USDC balance
- ~5,420+ autonomous cycles completed
- $36.80 total API spend

## Pending / Next Priorities

1. Get ONE paying customer
2. Monitor USSOCOM reply (follow up March 7)
3. DARPA ASEMA submission when SBIR reauthorized
4. TTS (Kokoro) on GPU pod
5. Flux LoRA training on GPU pod
