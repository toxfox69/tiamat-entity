"""
TIAMAT Claude Chat — Interact with Claude.ai via headless browser
Uses saved session cookies from browser_tool.py login flow.
For use during cooldowns as a free research/guidance oracle.
"""
import json
import sys
import os
import time
import re

SESSION_FILE = "/root/.automaton/browser_sessions/claude.json"
SCREENSHOT_DIR = "/var/www/tiamat/images/screenshots"


def ask_claude(question, timeout=60):
    """Send a message to Claude.ai and get the response.

    Args:
        question: The question to ask
        timeout: Max seconds to wait for response (default 60)

    Returns:
        Dict with response text
    """
    if not os.path.exists(SESSION_FILE):
        return {"error": "No Claude session. Run login flow first."}

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"],
    )

    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            storage_state=SESSION_FILE,
        )
        page = context.new_page()

        # Go to new chat
        page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=20000)

        # Wait for chat input to be ready
        for _ in range(15):
            time.sleep(1)
            editor = page.query_selector('[contenteditable=true], textarea, div.ProseMirror')
            if editor:
                break

        if not editor:
            context.storage_state(path=SESSION_FILE)
            context.close(); browser.close(); pw.stop()
            return {"error": "Could not find chat input"}

        # Type the question
        editor.click()
        page.keyboard.type(question, delay=10)
        time.sleep(0.5)

        # Send (Enter or click send button)
        send_btn = page.query_selector('button[aria-label="Send Message"], button:has-text("Send")')
        if send_btn:
            send_btn.click()
        else:
            page.keyboard.press("Enter")

        time.sleep(2)

        # Wait for response — poll for the response to finish
        last_text = ""
        stable_count = 0
        start = time.time()

        while time.time() - start < timeout:
            time.sleep(2)

            # Get all message blocks
            messages = page.query_selector_all('[data-testid*="message"], .font-claude-message, .prose, div[class*="message"]')
            if not messages:
                # Try broader selector
                messages = page.query_selector_all('div[class*="response"], div[class*="answer"], div[class*="markdown"]')

            current_text = ""
            for msg in messages:
                t = msg.inner_text()
                if t and len(t) > len(current_text):
                    current_text = t

            # Also try getting all text and finding the response
            if not current_text:
                body = page.inner_text("body")
                # The response is typically after the question
                if question[:30] in body:
                    parts = body.split(question[:30])
                    if len(parts) > 1:
                        current_text = parts[-1][:3000]

            # Check if response is stable (stopped streaming)
            if current_text and current_text == last_text:
                stable_count += 1
                if stable_count >= 3:  # Stable for 6 seconds
                    break
            else:
                stable_count = 0
                last_text = current_text

            # Check for stop button disappearing (streaming done)
            stop_btn = page.query_selector('button[aria-label="Stop"], button:has-text("Stop")')
            if not stop_btn and current_text and len(current_text) > 20:
                time.sleep(2)  # Give it a moment
                break

        # Get final response — try multiple extraction strategies
        response = ""

        # Strategy 1: Look for Claude's response containers
        for selector in [
            '[data-testid="assistant-message"]',
            'div[class*="font-claude"]',
            'div[class*="assistant"]',
            'div.prose',
            'div[class*="markdown"]',
        ]:
            els = page.query_selector_all(selector)
            if els:
                # Get the last one (most recent response)
                response = els[-1].inner_text().strip()
                if response and len(response) > 5:
                    break

        # Strategy 2: Full body text, split by question
        if not response or len(response) < 5:
            body_text = page.inner_text("body") if page.query_selector("body") else ""
            # Find text after our question, before UI elements
            q_short = question[:50]
            if q_short in body_text:
                after = body_text.split(q_short, 1)[-1]
                # Remove common UI fragments
                for cutoff in ["Sonnet 4.6", "Connect your tools", "Free plan", "Upgrade", "New chat"]:
                    if cutoff in after:
                        after = after[:after.index(cutoff)]
                response = after.strip()

        # Strategy 3: Use last_text from polling
        if not response or len(response) < 5:
            response = last_text or current_text or ""

        # Save session
        context.storage_state(path=SESSION_FILE)
        context.close()
        browser.close()
        pw.stop()

        # Clean up
        response = response.strip()
        if len(response) > 4000:
            response = response[:4000] + "... [truncated]"

        return {
            "response": response,
            "url": "https://claude.ai",
            "session": "active",
        }

    except Exception as e:
        try:
            context.storage_state(path=SESSION_FILE)
            context.close()
        except:
            pass
        try:
            browser.close()
            pw.stop()
        except:
            pass
        return {"error": str(e)[:500]}


def check_session():
    """Check if Claude session is still valid."""
    if not os.path.exists(SESSION_FILE):
        return {"valid": False, "reason": "No session file"}

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"],
    )

    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            storage_state=SESSION_FILE,
        )
        page = context.new_page()
        page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=15000)

        for _ in range(10):
            time.sleep(1.5)
            text = page.inner_text("body")[:300] if page.query_selector("body") else ""
            if "How can" in text:
                context.close(); browser.close(); pw.stop()
                return {"valid": True}
            if "login" in page.url.lower():
                context.close(); browser.close(); pw.stop()
                return {"valid": False, "reason": "Session expired"}

        context.close(); browser.close(); pw.stop()
        return {"valid": False, "reason": "Timeout waiting for chat"}

    except Exception as e:
        try:
            browser.close(); pw.stop()
        except:
            pass
        return {"valid": False, "reason": str(e)[:200]}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"

    if action == "check":
        result = check_session()
    elif action == "ask":
        if len(sys.argv) < 3:
            result = {"error": "Usage: claude_chat.py ask 'your question'"}
        else:
            question = sys.argv[2]
            result = ask_claude(question)
    else:
        result = {"error": f"Unknown action: {action}. Use: check, ask"}

    print(json.dumps(result, indent=2, default=str))
