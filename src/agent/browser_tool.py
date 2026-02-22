"""
TIAMAT Browser Tool — Headless Chromium via Playwright
Gives TIAMAT the ability to interact with web UIs: navigate, click, type, read, screenshot.
Memory-conscious: single browser instance, auto-closes after each action batch.
"""
import json
import sys
import os
import time

# Persistent session storage for cookies/auth
SESSION_DIR = "/root/.automaton/browser_sessions"
SCREENSHOT_DIR = "/var/www/tiamat/images/screenshots"

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def _launch_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--single-process",
        ],
    )
    return pw, browser


def browse(url, actions=None, session=None):
    """Navigate to URL, optionally perform actions, return page content.

    Args:
        url: URL to navigate to
        actions: Optional list of action dicts:
            - {"action": "click", "selector": "button#submit"}
            - {"action": "type", "selector": "input#email", "text": "..."}
            - {"action": "wait", "selector": "div.result"}
            - {"action": "screenshot", "name": "page"}
            - {"action": "get_text", "selector": "div.content"}
            - {"action": "get_links"}
            - {"action": "scroll", "direction": "down"}
        session: Optional session name to persist cookies (e.g., "claude")

    Returns:
        Dict with page info and action results
    """
    pw, browser = _launch_browser()
    results = []

    try:
        # Load session cookies if available
        context_opts = {
            "viewport": {"width": 1280, "height": 720},
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        session_file = None
        if session:
            session_file = os.path.join(SESSION_DIR, f"{session}.json")
            if os.path.exists(session_file):
                context_opts["storage_state"] = session_file

        context = browser.new_context(**context_opts)
        page = context.new_page()

        # Navigate
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(1)  # Let JS settle

        # Execute actions
        if actions:
            for act in actions:
                action_type = act.get("action", "")
                selector = act.get("selector", "")
                try:
                    if action_type == "click":
                        page.click(selector, timeout=5000)
                        time.sleep(0.5)
                        results.append({"action": "click", "selector": selector, "ok": True})

                    elif action_type == "type":
                        page.fill(selector, act.get("text", ""), timeout=5000)
                        results.append({"action": "type", "selector": selector, "ok": True})

                    elif action_type == "wait":
                        page.wait_for_selector(selector, timeout=10000)
                        results.append({"action": "wait", "selector": selector, "ok": True})

                    elif action_type == "screenshot":
                        name = act.get("name", f"shot_{int(time.time())}")
                        path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
                        page.screenshot(path=path, full_page=act.get("full_page", False))
                        results.append({"action": "screenshot", "path": path, "url": f"https://tiamat.live/images/screenshots/{name}.png"})

                    elif action_type == "get_text":
                        el = page.query_selector(selector)
                        text = el.inner_text() if el else ""
                        results.append({"action": "get_text", "selector": selector, "text": text[:2000]})

                    elif action_type == "get_links":
                        links = page.eval_on_selector_all("a[href]", "els => els.map(e => ({text: e.innerText.trim().slice(0,100), href: e.href})).filter(l => l.text && l.href).slice(0, 30)")
                        results.append({"action": "get_links", "links": links})

                    elif action_type == "scroll":
                        direction = act.get("direction", "down")
                        amount = act.get("amount", 500)
                        if direction == "down":
                            page.evaluate(f"window.scrollBy(0, {amount})")
                        else:
                            page.evaluate(f"window.scrollBy(0, -{amount})")
                        time.sleep(0.3)
                        results.append({"action": "scroll", "direction": direction, "ok": True})

                    elif action_type == "press":
                        page.keyboard.press(act.get("key", "Enter"))
                        time.sleep(0.3)
                        results.append({"action": "press", "key": act.get("key"), "ok": True})

                except Exception as e:
                    results.append({"action": action_type, "selector": selector, "error": str(e)[:200]})

        # Get page state
        title = page.title()
        current_url = page.url
        # Get visible text (truncated)
        body_text = page.inner_text("body")[:3000] if page.query_selector("body") else ""

        # Save session cookies
        if session_file:
            context.storage_state(path=session_file)

        context.close()
        browser.close()
        pw.stop()

        return {
            "title": title,
            "url": current_url,
            "text": body_text,
            "action_results": results,
        }

    except Exception as e:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass
        return {"error": str(e)[:500]}


# CLI interface
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: browser_tool.py <url> [actions_json] [session]"}))
        sys.exit(1)

    url = sys.argv[1]
    actions = None
    session = None

    if len(sys.argv) > 2:
        try:
            actions = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            # Might be session name
            session = sys.argv[2]

    if len(sys.argv) > 3:
        session = sys.argv[3]

    result = browse(url, actions=actions, session=session)
    print(json.dumps(result, indent=2, default=str))
