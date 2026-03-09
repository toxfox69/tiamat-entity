"""
Real Playwright-based scanner.
Actually visits broker sites and checks if a person's data is listed.
Takes screenshots as proof.
"""

import asyncio
import os
import time
import random
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict
from playwright.async_api import async_playwright, Browser, BrowserContext

from brokers import BROKERS, get_scan_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]


@dataclass
class ScanResult:
    broker_name: str
    broker_key: str
    found: bool
    confidence: float
    url_checked: str
    screenshot_path: Optional[str]
    snippet: Optional[str]
    error: Optional[str]
    scan_time: float
    removal_url: str
    removal_method: str
    auto_removable: bool


async def scan_single_broker(
    context: BrowserContext,
    broker_key: str,
    first_name: str,
    last_name: str,
    city: str,
    state: str,
    take_screenshot: bool = True,
    scan_id: str = "",
) -> ScanResult:
    """Scan a single broker site for a person's listing."""
    broker = BROKERS.get(broker_key)
    if not broker:
        return ScanResult(
            broker_name=broker_key, broker_key=broker_key, found=False,
            confidence=0, url_checked="", screenshot_path=None,
            snippet=None, error=f"Unknown broker: {broker_key}",
            scan_time=0, removal_url="", removal_method="", auto_removable=False,
        )

    config = broker["scan"]
    url = get_scan_url(broker_key, first_name, last_name, city, state)
    start = time.time()

    page = await context.new_page()
    try:
        logger.info(f"[{broker['name']}] Scanning {url}")

        # Navigate with retry
        for attempt in range(2):
            try:
                resp = await page.goto(url, timeout=config["timeout"], wait_until="domcontentloaded")
                break
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning(f"[{broker['name']}] Retry after: {e}")
                await asyncio.sleep(2)

        # Wait for JS rendering
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Get page text
        body = await page.query_selector("body")
        page_text = ""
        if body:
            page_text = (await body.inner_text()) or ""

        page_html = await page.content()

        # Check HTTP status
        status_code = resp.status if resp else 0
        if status_code in (403, 429, 503):
            return ScanResult(
                broker_name=broker["name"], broker_key=broker_key, found=False,
                confidence=0, url_checked=url, screenshot_path=None,
                snippet=None, error=f"Blocked (HTTP {status_code})",
                scan_time=time.time() - start, removal_url=broker["removal"]["url"],
                removal_method=broker["removal"]["method"],
                auto_removable=broker["removal"].get("auto_possible", False),
            )

        # Detect "not found"
        not_found = False
        for phrase in config["not_found_indicators"]:
            if phrase.lower() in page_text.lower():
                not_found = True
                break

        # Detect "found" via CSS selectors
        found_by_selector = False
        for selector in config["found_indicators"]:
            if selector.startswith(".") or selector.startswith("#") or selector.startswith("["):
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        found_by_selector = True
                        break
                except:
                    pass

        # Detect "found" via text content
        found_by_text = False
        text_lower = page_text.lower()
        name_lower = f"{first_name} {last_name}".lower()
        for phrase in config["found_indicators"]:
            if not phrase.startswith(".") and not phrase.startswith("#") and not phrase.startswith("["):
                if phrase.lower() in text_lower:
                    found_by_text = True
                    break

        # Name appears on page
        name_on_page = name_lower in text_lower or (
            first_name.lower() in text_lower and last_name.lower() in text_lower
        )

        # Confidence scoring
        confidence = 0.0
        if name_on_page:
            confidence += 0.35
        if found_by_selector:
            confidence += 0.25
        if found_by_text:
            confidence += 0.20
        if city.lower() in text_lower:
            confidence += 0.10
        if state.upper() in page_text:
            confidence += 0.05
        if not_found:
            confidence = max(0, confidence - 0.60)

        found = confidence >= 0.40 and not not_found

        # Extract snippet (first ~200 chars around name mention)
        snippet = None
        if found and name_on_page:
            idx = text_lower.find(last_name.lower())
            if idx >= 0:
                start_idx = max(0, idx - 50)
                end_idx = min(len(page_text), idx + 150)
                snippet = page_text[start_idx:end_idx].strip()
                snippet = " ".join(snippet.split())  # normalize whitespace

        # Screenshot
        screenshot_path = None
        if take_screenshot and found:
            fname = f"{scan_id}_{broker_key}.png"
            screenshot_path = os.path.join(SCREENSHOT_DIR, fname)
            try:
                await page.screenshot(path=screenshot_path, full_page=False)
            except:
                screenshot_path = None

        scan_time = time.time() - start
        logger.info(
            f"[{broker['name']}] {'FOUND' if found else 'NOT FOUND'} "
            f"(confidence={confidence:.2f}, time={scan_time:.1f}s)"
        )

        return ScanResult(
            broker_name=broker["name"],
            broker_key=broker_key,
            found=found,
            confidence=round(confidence, 2),
            url_checked=url,
            screenshot_path=screenshot_path,
            snippet=snippet,
            error=None,
            scan_time=round(scan_time, 2),
            removal_url=broker["removal"]["url"],
            removal_method=broker["removal"]["method"],
            auto_removable=broker["removal"].get("auto_possible", False),
        )

    except Exception as e:
        scan_time = time.time() - start
        logger.error(f"[{broker['name']}] Error: {e}")
        return ScanResult(
            broker_name=broker["name"], broker_key=broker_key, found=False,
            confidence=0, url_checked=url, screenshot_path=None,
            snippet=None, error=str(e), scan_time=round(scan_time, 2),
            removal_url=broker["removal"]["url"],
            removal_method=broker["removal"]["method"],
            auto_removable=broker["removal"].get("auto_possible", False),
        )
    finally:
        await page.close()


async def full_scan(
    first_name: str,
    last_name: str,
    city: str,
    state: str,
    broker_keys: list = None,
    scan_id: str = "",
) -> dict:
    """
    Scan all (or specified) brokers for a person.
    Returns full report dict.
    """
    if not broker_keys:
        broker_keys = list(BROKERS.keys())

    logger.info(f"Starting scan for {first_name} {last_name}, {city}, {state} — {len(broker_keys)} brokers")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="en-US",
            timezone_id="America/Denver",
        )
        # Stealth: override navigator.webdriver
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        results = []
        start = time.time()

        for i, broker_key in enumerate(broker_keys):
            result = await scan_single_broker(
                context, broker_key, first_name, last_name, city, state,
                take_screenshot=True, scan_id=scan_id,
            )
            results.append(result)

            # Rate limiting between brokers
            if i < len(broker_keys) - 1:
                delay = random.uniform(2.0, 4.0)
                await asyncio.sleep(delay)

        await browser.close()

    total_time = time.time() - start
    found_results = [r for r in results if r.found]
    errors = [r for r in results if r.error]

    report = {
        "scan_id": scan_id,
        "person": {
            "first_name": first_name,
            "last_name": last_name,
            "city": city,
            "state": state,
        },
        "summary": {
            "brokers_scanned": len(results),
            "brokers_found": len(found_results),
            "brokers_error": len(errors),
            "total_time": round(total_time, 1),
            "auto_removable": sum(1 for r in found_results if r.auto_removable),
        },
        "found_on": [asdict(r) for r in found_results],
        "not_found_on": [r.broker_name for r in results if not r.found and not r.error],
        "errors": [
            {
                "broker": r.broker_name,
                "broker_key": r.broker_key,
                "error": r.error,
                "search_url": r.url_checked,
                "removal_url": r.removal_url,
            }
            for r in errors
        ],
        "all_results": [asdict(r) for r in results],
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(
        f"Scan complete: {len(found_results)}/{len(results)} brokers have listing "
        f"({len(errors)} errors, {total_time:.1f}s total)"
    )

    return report


# CLI test
if __name__ == "__main__":
    import sys
    import json

    first = sys.argv[1] if len(sys.argv) > 1 else "John"
    last = sys.argv[2] if len(sys.argv) > 2 else "Smith"
    city = sys.argv[3] if len(sys.argv) > 3 else "Denver"
    state = sys.argv[4] if len(sys.argv) > 4 else "CO"

    report = asyncio.run(full_scan(first, last, city, state, scan_id="test"))
    print(json.dumps(report, indent=2, default=str))
