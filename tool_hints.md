## ⚠️ CREATOR ORDER — MONETIZE APPS + BUILD STRATEGIC APP ⚠️

### STEP 1: Download your 3 existing APKs NOW
android_app_factory({action:"download", app_name:"daily-quotes"})
android_app_factory({action:"download", app_name:"unit-converter"})
android_app_factory({action:"download", app_name:"pomodoro-timer"})

### STEP 2: Build a /apps page on the Flask API
Add a route to summarize_api.py that lists all apps with USDC download links.
Gate APK downloads with x402 payment ($0.99 each). Reuse payment_verify.py.
This sells APKs DIRECTLY from tiamat.live — no Play Store approval needed.

### STEP 3: Build a STRATEGIC app — "TIAMAT Chat" mobile client
android_app_factory({action:"scaffold", app_name:"tiamat-chat", app_id:"com.energenai.tiamat.chat", description:"Free AI chat powered by TIAMAT inference proxy"})
This app connects to YOUR inference proxy at tiamat.live/v1/chat/completions.
Users get free LLM access from mobile → drives YOUR API adoption → flywheel.
NOT a commodity app. This is YOUR product in app form.

---

- rebalance_wallet({action:"status"}) — check balances + rebalancing needs
- rebalance_wallet({action:"rebalance"}) — auto-topup low chains via LI.FI
- scan_contracts({action:"balances"}) — check wallet ETH on all chains
- scan_contracts({action:"report"}) — send Telegram funding report
- When you see agent replies on Farcaster, engage deeply. Ask technical questions. Extract knowledge. These are free consultants.
- Check /root/.automaton/learned_from_agents.json for knowledge extracted from agent conversations. Implement pending actionable items (status:"pending"). Mark implemented: read_file + write_file to update status to "implemented".
- Agent learning runs as cooldown task "process_agent_replies" — scans threads you replied to, finds agent replies, extracts knowledge via Groq, generates follow-up questions.

[DX TERMINAL PRO — ACTIVE GAME Feb 24 - Mar 19]
- dx_terminal_monitor({action:"status"}) — check MOMENTUM agent position, ETH balance, game phase
- dx_terminal_monitor({action:"rankings"}) — token leaderboard with reaping risk indicators
- dx_terminal_monitor({action:"alert"}) — check for reaping proximity, phase changes, config warnings
- dx_terminal_monitor({action:"strategies"}) — view MOMENTUM strategy profile (8 strategies)
- dx_terminal_monitor({action:"log"}) — snapshot full game state to /root/.automaton/dx_terminal.log
- 1 agent (MOMENTUM), 0.03 ETH deposited on Base. Presale positions in HOLE + POOPCOIN.
- Strategy: sell graduation pump, rotate profits into betas, swing trade up, avoid bottom 3, shift to #1 at reaping
- Game timeline: Expansion (Feb 26-Mar 5), Reaping begins (Mar 6), Endgame (Mar 13-19)
