#!/usr/bin/env python3
"""
recursive_learn.py — Deep recursive self-improvement via inference cascade

Three-stage thinking pipeline at zero API cost:
  Stage 1 (Gemini/Groq, ~2s): Analyze TIAMAT's state, generate a deep question
  Stage 2 (Claude.ai→Gemini→Groq): Deep oracle answers it
  Stage 3 (Gemini/Groq, ~2s): Extract actionable items for TIAMAT's paid cycles

Oracle cascade: Claude.ai browser → Gemini 2.0 Flash → Groq llama-3.3-70b
Question/action extraction cascade: Gemini 2.0 Flash → Groq llama-3.3-70b

Modes (rotate each run):
  - code_review:  find weak module → oracle reviews → fix spec
  - strategy:     summarize P&L/state → oracle proposes pivot → steps
  - tool_design:  find capability gap → oracle designs tool → spec
  - debug:        find errors in logs → oracle diagnoses → fix

CONSTRAINTS:
  - Max 1 Claude.ai query per run (free tier rate limits)
  - Question-hash cache to avoid duplicate oracle queries
  - 45s timeout on browser automation
  - Graceful cascade fallback if Claude.ai fails
  - Telegram alert if session dies
"""

import json, os, hashlib, sqlite3, subprocess, requests
from pathlib import Path
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY     = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"

GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

STATE_DIR    = Path("/root/.automaton")
AGENT_DIR    = Path("/root/entity/src/agent")
ORACLE_DIR   = STATE_DIR / "oracle_insights"
CACHE_DIR    = STATE_DIR / "oracle_cache"
ORACLE_LOG   = STATE_DIR / "oracle_log.json"
ACTIONS_FILE = STATE_DIR / "cooldown_actions.json"
LEARN_STATE  = STATE_DIR / "recursive_learn_state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

MODES = ["code_review", "strategy", "tool_design", "debug"]


def now_iso():
    return datetime.now(tz=timezone.utc).isoformat()


# ── State management ────────────────────────────────────────────

def load_state():
    try:
        return json.loads(LEARN_STATE.read_text())
    except Exception:
        return {"mode_idx": 0, "runs": 0, "oracle_calls": 0, "oracle_failures": 0}

def save_state(state):
    LEARN_STATE.write_text(json.dumps(state, indent=2))


# ── Inference engines ───────────────────────────────────────────

def ask_gemini(prompt, max_tokens=400):
    """Gemini 2.0 Flash — free tier."""
    if not GEMINI_KEY:
        return None, "GEMINI_API_KEY not set"
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
            },
            timeout=25,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text, None
        return None, f"Gemini {resp.status_code}: {resp.text[:120]}"
    except Exception as e:
        return None, str(e)[:200]


def ask_groq(prompt, max_tokens=400):
    """Groq llama-3.3-70b — free tier."""
    if not GROQ_KEY:
        return None, "GROQ_API_KEY not set"
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text, None
        return None, f"Groq {resp.status_code}: {resp.text[:120]}"
    except Exception as e:
        return None, str(e)[:200]


def ask_fast_cascade(prompt, max_tokens=400):
    """Fast cascade (no browser): Gemini → Groq. Returns (text, engine, error)."""
    text, err = ask_gemini(prompt, max_tokens)
    if text:
        return text, "gemini-2.0-flash", None
    text2, err2 = ask_groq(prompt, max_tokens)
    if text2:
        return text2, "groq-llama-70b", None
    return None, None, f"Gemini: {err} | Groq: {err2}"


# ── Context gathering ───────────────────────────────────────────

def read_context(mode):
    ctx = {}
    try:
        ctx["mission"] = (STATE_DIR / "MISSION.md").read_text()[:1000]
    except Exception:
        ctx["mission"] = "(unavailable)"
    try:
        lines = (STATE_DIR / "PROGRESS.md").read_text().splitlines()
        ctx["recent_progress"] = "\n".join(lines[-20:])
    except Exception:
        ctx["recent_progress"] = "(unavailable)"
    try:
        lines = (STATE_DIR / "cost.log").read_text().splitlines()
        ctx["recent_costs"] = "\n".join(lines[-10:])
    except Exception:
        ctx["recent_costs"] = "(unavailable)"

    if mode == "code_review":
        try:
            db = sqlite3.connect(str(STATE_DIR / "state.db"))
            rows = db.execute(
                "SELECT name, count(*) as cnt FROM tool_calls "
                "GROUP BY name ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            ctx["tool_usage"] = "\n".join(f"  {r[0]}: {r[1]} calls" for r in rows)
            db.close()
        except Exception:
            ctx["tool_usage"] = "(unavailable)"
        try:
            py_files = sorted(AGENT_DIR.glob("*.py"))
            ctx["agent_files"] = "\n".join(
                f"  {f.name} ({f.stat().st_size}B)" for f in py_files[:15]
            )
        except Exception:
            ctx["agent_files"] = "(unavailable)"

    elif mode == "strategy":
        try:
            ctx["inbox"] = (STATE_DIR / "INBOX.md").read_text()[:800]
        except Exception:
            ctx["inbox"] = "(unavailable)"

    elif mode == "tool_design":
        try:
            db = sqlite3.connect(str(STATE_DIR / "state.db"))
            rows = db.execute(
                "SELECT DISTINCT name FROM tool_calls ORDER BY name"
            ).fetchall()
            ctx["existing_tools"] = ", ".join(r[0] for r in rows)
            db.close()
        except Exception:
            ctx["existing_tools"] = "(unavailable)"
        try:
            db = sqlite3.connect(str(STATE_DIR / "memory.db"))
            rows = db.execute(
                "SELECT content FROM tiamat_memories "
                "WHERE type IN ('observation','learning') "
                "ORDER BY timestamp DESC LIMIT 5"
            ).fetchall()
            ctx["recent_memories"] = "\n".join(f"  - {r[0][:150]}" for r in rows)
            db.close()
        except Exception:
            ctx["recent_memories"] = "(unavailable)"

    elif mode == "debug":
        try:
            lines = (STATE_DIR / "tiamat.log").read_text().splitlines()
            errors = [l for l in lines[-200:] if any(
                k in l.lower() for k in ["error", "failed", "exception", "crash", "timeout"]
            )]
            ctx["recent_errors"] = "\n".join(errors[-10:])
        except Exception:
            ctx["recent_errors"] = "(unavailable)"
        try:
            ctx["execution_log"] = (STATE_DIR / "execution_log.json").read_text()[:1000]
        except Exception:
            ctx["execution_log"] = "(unavailable)"

    try:
        entries = sorted(ORACLE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime)[-3:]
        ctx["previous_oracle"] = "\n".join(
            f"  [{json.loads(e.read_text()).get('mode','')}] "
            f"{json.loads(e.read_text()).get('oracle_response','')[:150]}"
            for e in entries
        )
    except Exception:
        ctx["previous_oracle"] = "(none yet)"

    return ctx


# ── Question generation (Gemini → Groq) ────────────────────────

def generate_question(mode, ctx):
    mode_instructions = {
        "code_review": (
            "You are analyzing TIAMAT's codebase. Based on the tool usage and file list below, "
            "identify the ONE Python module most likely to have bugs, inefficiencies, or missing "
            "error handling. Generate a specific code review question. Include the filename.\n\n"
            f"Tool usage stats:\n{ctx.get('tool_usage', '(none)')}\n\n"
            f"Agent files:\n{ctx.get('agent_files', '(none)')}\n"
        ),
        "strategy": (
            "You are TIAMAT's strategic advisor. Based on the current mission, progress, and costs "
            "below, generate ONE specific strategic question for a senior AI strategist. Focus on "
            "the most impactful revenue opportunity or efficiency gain.\n\n"
            f"Inbox directives:\n{ctx.get('inbox', '(none)')}\n"
        ),
        "tool_design": (
            "You are TIAMAT's capability architect. Based on existing tools and recent memories, "
            "identify ONE capability gap. Generate a question asking for a new tool design "
            "with specific parameters, return types, and integration points.\n\n"
            f"Existing tools: {ctx.get('existing_tools', '(none)')}\n\n"
            f"Recent memories:\n{ctx.get('recent_memories', '(none)')}\n"
        ),
        "debug": (
            "You are TIAMAT's debugger. Based on recent errors, identify the ONE most critical "
            "or recurring issue. Generate a question to diagnose the root cause "
            "and suggest a fix. Include the actual error messages.\n\n"
            f"Recent errors:\n{ctx.get('recent_errors', '(none)')}\n\n"
            f"Execution log:\n{ctx.get('execution_log', '(none)')}\n"
        ),
    }

    prompt = (
        "You are TIAMAT's deep-thinking question generator. Create ONE highly "
        "specific, actionable question that can be answered to help TIAMAT improve.\n\n"
        f"TIAMAT's mission:\n{ctx['mission'][:600]}\n\n"
        f"Recent progress:\n{ctx['recent_progress'][:600]}\n\n"
        f"Recent costs:\n{ctx.get('recent_costs', '')}\n\n"
        f"Previous oracle insights:\n{ctx.get('previous_oracle', '(none)')}\n\n"
        f"{mode_instructions[mode]}\n"
        "OUTPUT: Just the question, nothing else. Make it specific and answerable in 2-3 paragraphs."
    )
    return ask_fast_cascade(prompt, max_tokens=250)


# ── Action extraction (Gemini → Groq) ──────────────────────────

def extract_actions(mode, question, oracle_response):
    prompt = (
        "You are TIAMAT's action extractor. Read the oracle's response and "
        "extract 1-3 CONCRETE action items TIAMAT can implement immediately.\n\n"
        "Each action item must have:\n"
        "- action: what to do (1 sentence)\n"
        "- tool: which TIAMAT tool to use (write_file, exec, manage_cooldown, etc.)\n"
        "- priority: high/medium/low\n"
        "- details: specific parameters, file paths, code snippets if applicable\n\n"
        f"Mode: {mode}\n"
        f"Question asked: {question[:300]}\n\n"
        f"Oracle response:\n{oracle_response[:2000]}\n\n"
        "OUTPUT: JSON array of action items. Example:\n"
        '[{"action":"Fix timeout in farcaster_engage.py","tool":"write_file",'
        '"priority":"high","details":"Change line 42 timeout from 5 to 15"}]\n'
        "Output ONLY valid JSON array."
    )
    return ask_fast_cascade(prompt, max_tokens=500)


# ── Oracle cascade: Claude.ai → Gemini → Groq ──────────────────

def question_hash(q):
    return hashlib.sha256(q.encode()).hexdigest()[:16]

def check_cache(q):
    h = question_hash(q)
    cache_file = CACHE_DIR / f"{h}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            return data.get("response")
        except Exception:
            pass
    return None

def save_cache(q, response):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = question_hash(q)
    (CACHE_DIR / f"{h}.json").write_text(json.dumps({
        "question": q, "response": response,
        "timestamp": now_iso(), "hash": h,
    }, indent=2))


def ask_claude_browser(question):
    """Tier 1: Claude.ai via Playwright browser automation."""
    try:
        output = subprocess.run(
            ["python3", "claude_chat.py", "ask", question],
            cwd=str(AGENT_DIR),
            capture_output=True, text=True, timeout=45,
            env={**os.environ},
        )
        if output.returncode != 0:
            return None, f"claude_chat exit {output.returncode}: {output.stderr[:200]}"

        result = json.loads(output.stdout)
        if "error" in result:
            err = result["error"]
            if any(k in err.lower() for k in ["session expired", "login", "could not find"]):
                alert_session_dead(err)
            return None, err

        response = result.get("response", "")
        if not response or len(response) < 10:
            return None, "Empty claude.ai response"
        return response, None

    except subprocess.TimeoutExpired:
        return None, "Claude.ai timeout (45s)"
    except Exception as e:
        return None, str(e)[:200]


def ask_oracle(question):
    """
    Full oracle cascade: cache → Claude.ai → Gemini → Groq.
    Returns (response, engine_used, error, from_cache).
    """
    # Check cache
    cached = check_cache(question)
    if cached:
        return cached, "cache", None, True

    # Tier 1: Claude.ai browser
    resp, err1 = ask_claude_browser(question)
    if resp:
        save_cache(question, resp)
        return resp, "claude.ai-browser", None, False

    # Tier 2: Gemini 2.0 Flash (longer response for oracle role)
    resp, err2 = ask_gemini(
        f"Answer this question thoroughly (2-3 paragraphs):\n\n{question}",
        max_tokens=800,
    )
    if resp:
        save_cache(question, resp)
        return resp, "gemini-2.0-flash", None, False

    # Tier 3: Groq llama-3.3-70b
    resp, err3 = ask_groq(
        f"Answer this question thoroughly (2-3 paragraphs):\n\n{question}",
        max_tokens=800,
    )
    if resp:
        save_cache(question, resp)
        return resp, "groq-llama-70b", None, False

    return None, None, f"Claude.ai: {err1} | Gemini: {err2} | Groq: {err3}", False


def alert_session_dead(error_msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"TIAMAT Oracle: Claude.ai session expired.\n{error_msg[:200]}\n"
                        "Re-login needed via browser_tool.py",
            },
            timeout=10,
        )
    except Exception:
        pass


# ── Logging ─────────────────────────────────────────────────────

def log_oracle_query(mode, question, response, engine, error, from_cache):
    entry = {
        "timestamp": now_iso(),
        "mode": mode,
        "question": question[:500],
        "engine": engine,
        "response_len": len(response) if response else 0,
        "error": error,
        "from_cache": from_cache,
    }
    try:
        log = json.loads(ORACLE_LOG.read_text()) if ORACLE_LOG.exists() else []
    except Exception:
        log = []
    log.append(entry)
    if len(log) > 100:
        log = log[-100:]
    ORACLE_LOG.write_text(json.dumps(log, indent=2))


def save_insight(mode, question, oracle_response, oracle_engine, actions):
    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (ORACLE_DIR / f"{ts}_{mode}.json").write_text(json.dumps({
        "timestamp": now_iso(),
        "mode": mode,
        "question": question,
        "oracle_engine": oracle_engine,
        "oracle_response": oracle_response[:3000] if oracle_response else None,
        "actions": actions,
    }, indent=2))


def save_actions(actions):
    try:
        existing = json.loads(ACTIONS_FILE.read_text()) if ACTIONS_FILE.exists() else []
    except Exception:
        existing = []
    for a in actions:
        a["created"] = now_iso()
        a["status"] = "pending"
    existing.extend(actions)
    pending = [a for a in existing if a.get("status") == "pending"]
    if len(pending) > 20:
        pending = pending[-20:]
    ACTIONS_FILE.write_text(json.dumps(pending, indent=2))


# ── Main pipeline ───────────────────────────────────────────────

def main():
    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    state = load_state()
    mode = MODES[state["mode_idx"] % len(MODES)]

    # Stage 1: Generate question (Gemini → Groq)
    ctx = read_context(mode)
    question, q_engine, q_err = generate_question(mode, ctx)
    if q_err:
        print(json.dumps({"error": f"Question gen failed: {q_err}"}))
        return

    # Stage 2: Oracle answers (Claude.ai → Gemini → Groq)
    oracle_response, oracle_engine, oracle_err, from_cache = ask_oracle(question)
    log_oracle_query(mode, question, oracle_response, oracle_engine, oracle_err, from_cache)

    if oracle_err:
        print(json.dumps({"error": f"All oracle engines failed: {oracle_err}"}))
        return

    # Stage 3: Extract actions (Gemini → Groq)
    actions_raw, a_engine, a_err = extract_actions(mode, question, oracle_response)
    actions = []
    if actions_raw and not a_err:
        try:
            cleaned = actions_raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
            actions = json.loads(cleaned)
            if not isinstance(actions, list):
                actions = [actions]
        except json.JSONDecodeError:
            actions = [{"action": actions_raw[:300], "tool": "unknown", "priority": "medium", "details": ""}]

    # Save
    save_insight(mode, question, oracle_response, oracle_engine, actions)
    if actions:
        save_actions(actions)

    # Update state
    state["mode_idx"] = (state["mode_idx"] + 1) % len(MODES)
    state["runs"] += 1
    if not from_cache and oracle_engine == "claude.ai-browser":
        state["oracle_calls"] += 1
    if oracle_err:
        state["oracle_failures"] += 1
    save_state(state)

    # Output summary
    print(json.dumps({
        "mode": mode,
        "question": question[:150],
        "engines": {"question": q_engine, "oracle": oracle_engine, "actions": a_engine},
        "actions_count": len(actions),
        "actions": [a.get("action", "")[:80] for a in actions[:3]],
        "run": state["runs"],
    }))


if __name__ == "__main__":
    main()
