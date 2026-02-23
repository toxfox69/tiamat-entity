#!/usr/bin/env python3
"""
cooldown_think.py — Free recursive self-improvement via inference cascade

Cascade: Gemini 2.0 Flash → Groq llama-3.3-70b
(Claude.ai browser skipped here — cooldown_think is the fast path)

Runs during idle cooldowns at zero Anthropic cost.
Each run: reads TIAMAT's current state → asks best available free model
to analyze and suggest improvements → saves actionable output.

Modes (rotated automatically):
  1. self_critique  — review recent progress, find gaps
  2. code_ideas     — suggest concrete scripts/tools to build
  3. market_intel   — brainstorm revenue strategies
  4. skill_expand   — identify new capabilities to develop
"""

import json, os, requests
from pathlib import Path
from datetime import datetime, timezone

# ── API Config ──────────────────────────────────────────────────
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY   = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

CEREBRAS_URL   = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_KEY   = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = "gpt-oss-120b"

OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY   = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

STATE_DIR   = Path("/root/.automaton")
THINK_LOG   = STATE_DIR / "cooldown_thoughts.jsonl"
THINK_STATE = STATE_DIR / "cooldown_think_state.json"

MODES = ["self_critique", "code_ideas", "market_intel", "skill_expand"]


# ── Inference cascade ───────────────────────────────────────────

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
            timeout=20,
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


def ask_cerebras(prompt, max_tokens=400):
    """Cerebras gpt-oss-120b — free tier."""
    if not CEREBRAS_KEY:
        return None, "CEREBRAS_API_KEY not set"
    try:
        resp = requests.post(
            CEREBRAS_URL,
            headers={"Authorization": f"Bearer {CEREBRAS_KEY}", "Content-Type": "application/json"},
            json={
                "model": CEREBRAS_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text, None
        return None, f"Cerebras {resp.status_code}: {resp.text[:120]}"
    except Exception as e:
        return None, str(e)[:200]


def ask_openrouter(prompt, max_tokens=400):
    """OpenRouter free tier — llama-3.3-70b."""
    if not OPENROUTER_KEY:
        return None, "OPENROUTER_API_KEY not set"
    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text, None
        return None, f"OpenRouter {resp.status_code}: {resp.text[:120]}"
    except Exception as e:
        return None, str(e)[:200]


def ask_cascade(prompt, max_tokens=400):
    """Try Gemini → Groq → Cerebras → OpenRouter. Returns (text, engine_used, error)."""
    errors = []
    for name, fn in [
        ("gemini-2.0-flash", ask_gemini),
        ("groq-llama-70b", ask_groq),
        ("cerebras-120b", ask_cerebras),
        ("openrouter-llama-70b", ask_openrouter),
    ]:
        text, err = fn(prompt, max_tokens)
        if text:
            return text, name, None
        errors.append(f"{name}: {err}")
    return None, None, "All engines failed. " + " | ".join(errors)


# ── State & context ─────────────────────────────────────────────

def load_state():
    try:
        return json.loads(THINK_STATE.read_text())
    except Exception:
        return {"mode_idx": 0, "runs": 0, "insights_used": 0}

def save_state(state):
    THINK_STATE.write_text(json.dumps(state))

def read_context():
    ctx = {}
    try:
        lines = (STATE_DIR / "PROGRESS.md").read_text().splitlines()
        ctx["recent_progress"] = "\n".join(lines[-30:])
    except Exception:
        ctx["recent_progress"] = "(unavailable)"
    try:
        ctx["mission"] = (STATE_DIR / "MISSION.md").read_text()[:1500]
    except Exception:
        ctx["mission"] = "(unavailable)"
    try:
        lines = (STATE_DIR / "cost.log").read_text().splitlines()
        ctx["recent_costs"] = "\n".join(lines[-10:])
    except Exception:
        ctx["recent_costs"] = "(unavailable)"
    try:
        ctx["inbox"] = (STATE_DIR / "INBOX.md").read_text()[:1000]
    except Exception:
        ctx["inbox"] = "(unavailable)"
    try:
        lines = THINK_LOG.read_text().splitlines()
        recent = [json.loads(l) for l in lines[-3:]]
        ctx["previous_thoughts"] = "\n".join(
            f"[{t['mode']}] {t['insight'][:200]}" for t in recent
        )
    except Exception:
        ctx["previous_thoughts"] = "(first run)"
    return ctx

def build_prompt(mode, ctx):
    base = (
        "You are TIAMAT's strategic thinking module. You run during idle periods "
        "to help TIAMAT self-improve. Be CONCRETE and ACTIONABLE — no vague advice. "
        "Output a single focused insight (2-4 sentences) that TIAMAT can act on immediately.\n\n"
        f"TIAMAT's mission:\n{ctx['mission'][:800]}\n\n"
        f"Recent progress:\n{ctx['recent_progress'][:800]}\n\n"
        f"Recent costs:\n{ctx['recent_costs']}\n\n"
        f"Previous thoughts:\n{ctx['previous_thoughts']}\n"
    )
    mode_prompts = {
        "self_critique": (
            "TASK: Review TIAMAT's recent progress. Identify ONE specific gap, "
            "inefficiency, or missed opportunity. Suggest a concrete fix."
        ),
        "code_ideas": (
            "TASK: Suggest ONE specific Python script TIAMAT should write and register "
            "as a cooldown task. It should run in <30s, require no API keys beyond what's "
            "available (Groq, Neynar, Gemini), and produce useful output. Include the script's "
            "purpose and what data it would gather or produce."
        ),
        "market_intel": (
            "TASK: Suggest ONE specific, actionable marketing or revenue strategy. "
            "Consider: TIAMAT has APIs at tiamat.live (summarize, chat, generate), "
            "presence on Farcaster/Bluesky, $0 revenue, 10 USDC. What's the highest-leverage "
            "thing to do RIGHT NOW to get a first paying customer?"
        ),
        "skill_expand": (
            "TASK: Identify ONE new capability TIAMAT should develop. Consider what autonomous "
            "AI agents need that TIAMAT doesn't have yet. Be specific — name the tool, "
            "the integration, or the skill, and explain why it matters for revenue."
        ),
    }
    return base + "\n" + mode_prompts[mode]


# ── Main ────────────────────────────────────────────────────────

def main():
    state = load_state()
    mode = MODES[state["mode_idx"] % len(MODES)]

    ctx = read_context()
    prompt = build_prompt(mode, ctx)
    insight, engine, err = ask_cascade(prompt)

    if err:
        print(json.dumps({"error": err}))
        return

    # Save to thought log
    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "mode": mode,
        "engine": engine,
        "insight": insight,
        "run": state["runs"] + 1,
    }
    with open(THINK_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Rotate mode, update state
    state["mode_idx"] = (state["mode_idx"] + 1) % len(MODES)
    state["runs"] += 1
    save_state(state)

    # Output for cooldown intel
    print(json.dumps({
        "mode": mode,
        "engine": engine,
        "insight": insight,
        "run": state["runs"],
    }))

if __name__ == "__main__":
    main()
