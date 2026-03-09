"""
Real opt-out form submitter.
Automates removal requests on brokers that support web form opt-out.
For brokers requiring email/phone/CAPTCHA, provides direct links + instructions.
"""

import asyncio
import os
import time
import random
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")


@dataclass
class RemovalResult:
    broker_name: str
    broker_key: str
    status: str  # submitted, pending_email, manual_required, blocked, error
    message: str
    removal_url: str
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    instructions: Optional[str] = None


async def _fill_and_submit(page: Page, selectors: dict, values: dict, submit_selector: str) -> bool:
    """Generic form filler. Tries multiple selectors for each field."""
    for field_name, selector_list in selectors.items():
        value = values.get(field_name, "")
        if not value:
            continue
        filled = False
        for sel in selector_list:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(value)
                    filled = True
                    logger.info(f"  Filled {field_name} via {sel}")
                    await asyncio.sleep(random.uniform(0.3, 0.8))
                    break
            except Exception:
                continue
        if not filled:
            logger.warning(f"  Could not fill {field_name}")

    # Submit
    await asyncio.sleep(random.uniform(0.5, 1.5))
    for sel in (submit_selector if isinstance(submit_selector, list) else [submit_selector]):
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                logger.info(f"  Submitted via {sel}")
                return True
        except Exception:
            continue
    return False


# =============================================================================
# BROKER-SPECIFIC REMOVAL FUNCTIONS
# =============================================================================

async def remove_spokeo(context: BrowserContext, first: str, last: str, email: str, scan_id: str) -> RemovalResult:
    """
    Spokeo opt-out: requires finding your listing URL first, then pasting into form.
    We automate the search step.
    """
    page = await context.new_page()
    start = time.time()
    try:
        # Step 1: Search for the person
        search_url = f"https://www.spokeo.com/{first}-{last}"
        await page.goto(search_url, timeout=15000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Step 2: Go to opt-out
        await page.goto("https://www.spokeo.com/optout", timeout=15000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Step 3: Try to paste listing URL and fill email
        # Spokeo opt-out asks for the profile URL
        url_filled = False
        url_selectors = [
            "input[name='url']", "input[id*='url']", "input[placeholder*='URL']",
            "input[placeholder*='url']", "input[placeholder*='profile']",
            "input[type='url']", "input[type='text']",
        ]
        for sel in url_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(search_url)
                    url_filled = True
                    break
            except:
                continue

        email_selectors = [
            "input[type='email']", "input[name='email']", "input[id*='email']",
            "input[placeholder*='email']", "input[placeholder*='Email']",
        ]
        email_filled = False
        for sel in email_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(email)
                    email_filled = True
                    break
            except:
                continue

        # Try submit
        submitted = False
        submit_selectors = [
            "button[type='submit']", "input[type='submit']",
            "button:has-text('Remove')", "button:has-text('Submit')",
            "button:has-text('Opt Out')", "a:has-text('Remove')",
        ]
        for sel in submit_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    submitted = True
                    break
            except:
                continue

        # Screenshot
        ss_path = os.path.join(SCREENSHOT_DIR, f"{scan_id}_spokeo_removal.png")
        try:
            await page.screenshot(path=ss_path)
        except:
            ss_path = None

        await asyncio.sleep(2)

        if submitted:
            return RemovalResult(
                broker_name="Spokeo", broker_key="spokeo",
                status="pending_email",
                message="Opt-out submitted. Check email for confirmation link.",
                removal_url="https://www.spokeo.com/optout",
                screenshot_path=ss_path,
                processing_time=round(time.time() - start, 2),
                instructions="Click the confirmation link in the email Spokeo sends you.",
            )
        else:
            return RemovalResult(
                broker_name="Spokeo", broker_key="spokeo",
                status="manual_required",
                message="Could not auto-submit. Visit the opt-out page manually.",
                removal_url="https://www.spokeo.com/optout",
                screenshot_path=ss_path,
                processing_time=round(time.time() - start, 2),
                instructions=(
                    "1. Go to spokeo.com and search your name\n"
                    "2. Copy your profile URL\n"
                    "3. Go to spokeo.com/optout\n"
                    "4. Paste URL and enter email\n"
                    "5. Click confirmation link in email"
                ),
            )
    except Exception as e:
        return RemovalResult(
            broker_name="Spokeo", broker_key="spokeo",
            status="error", message=str(e),
            removal_url="https://www.spokeo.com/optout",
            error=str(e), processing_time=round(time.time() - start, 2),
        )
    finally:
        await page.close()


async def remove_whitepages(context: BrowserContext, first: str, last: str, email: str, city: str, state: str, scan_id: str) -> RemovalResult:
    """WhitePages suppression request."""
    page = await context.new_page()
    start = time.time()
    try:
        await page.goto("https://www.whitepages.com/suppression-requests", timeout=15000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        name_selectors = {
            "name": [
                "input[name='name']", "input[id*='name']",
                "input[placeholder*='Name']", "input[placeholder*='Full Name']",
                "input[type='text']",
            ],
        }
        email_selectors = {
            "email": [
                "input[type='email']", "input[name='email']",
                "input[id*='email']", "input[placeholder*='email']",
            ],
        }

        full_name = f"{first} {last}"
        all_selectors = {**name_selectors, **email_selectors}
        values = {"name": full_name, "email": email}

        submitted = await _fill_and_submit(
            page, all_selectors, values,
            ["button[type='submit']", "input[type='submit']", "button:has-text('Submit')"],
        )

        ss_path = os.path.join(SCREENSHOT_DIR, f"{scan_id}_whitepages_removal.png")
        try:
            await page.screenshot(path=ss_path)
        except:
            ss_path = None

        if submitted:
            await asyncio.sleep(3)
            return RemovalResult(
                broker_name="WhitePages", broker_key="whitepages",
                status="submitted",
                message="Suppression request submitted.",
                removal_url="https://www.whitepages.com/suppression-requests",
                screenshot_path=ss_path,
                processing_time=round(time.time() - start, 2),
            )
        else:
            return RemovalResult(
                broker_name="WhitePages", broker_key="whitepages",
                status="manual_required",
                message="Form changed. Visit the suppression page manually.",
                removal_url="https://www.whitepages.com/suppression-requests",
                screenshot_path=ss_path,
                processing_time=round(time.time() - start, 2),
                instructions=(
                    "1. Go to whitepages.com/suppression-requests\n"
                    "2. Enter your full name and email\n"
                    "3. Submit the form"
                ),
            )
    except Exception as e:
        return RemovalResult(
            broker_name="WhitePages", broker_key="whitepages",
            status="error", message=str(e),
            removal_url="https://www.whitepages.com/suppression-requests",
            error=str(e), processing_time=round(time.time() - start, 2),
        )
    finally:
        await page.close()


async def remove_fastpeoplesearch(context: BrowserContext, first: str, last: str, email: str, scan_id: str) -> RemovalResult:
    """FastPeopleSearch has a straightforward removal page."""
    page = await context.new_page()
    start = time.time()
    try:
        await page.goto("https://www.fastpeoplesearch.com/removal", timeout=15000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        selectors = {
            "name": [
                "input[name='name']", "input[id*='name']",
                "input[placeholder*='Name']", "input[type='text']",
            ],
            "email": [
                "input[type='email']", "input[name='email']",
                "input[id*='email']", "input[placeholder*='email']",
            ],
        }
        values = {"name": f"{first} {last}", "email": email}

        submitted = await _fill_and_submit(
            page, selectors, values,
            ["button[type='submit']", "input[type='submit']", "button:has-text('Remove')"],
        )

        ss_path = os.path.join(SCREENSHOT_DIR, f"{scan_id}_fastpeoplesearch_removal.png")
        try:
            await page.screenshot(path=ss_path)
        except:
            ss_path = None

        status = "submitted" if submitted else "manual_required"
        return RemovalResult(
            broker_name="FastPeopleSearch", broker_key="fastpeoplesearch",
            status=status,
            message="Removal submitted" if submitted else "Visit removal page manually",
            removal_url="https://www.fastpeoplesearch.com/removal",
            screenshot_path=ss_path,
            processing_time=round(time.time() - start, 2),
            instructions=None if submitted else (
                "1. Go to fastpeoplesearch.com/removal\n"
                "2. Search for your listing\n"
                "3. Click 'Remove This Record'\n"
                "4. Confirm removal"
            ),
        )
    except Exception as e:
        return RemovalResult(
            broker_name="FastPeopleSearch", broker_key="fastpeoplesearch",
            status="error", message=str(e),
            removal_url="https://www.fastpeoplesearch.com/removal",
            error=str(e), processing_time=round(time.time() - start, 2),
        )
    finally:
        await page.close()


async def remove_generic_webform(
    context: BrowserContext,
    broker_name: str,
    broker_key: str,
    removal_url: str,
    first: str, last: str, email: str,
    scan_id: str,
) -> RemovalResult:
    """Generic web form removal — tries standard form selectors."""
    page = await context.new_page()
    start = time.time()
    try:
        await page.goto(removal_url, timeout=15000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        full_name = f"{first} {last}"

        # Try filling common field patterns
        selectors = {
            "first_name": [
                "input[name='first_name']", "input[name='firstName']",
                "input[id*='first']", "input[placeholder*='First']",
            ],
            "last_name": [
                "input[name='last_name']", "input[name='lastName']",
                "input[id*='last']", "input[placeholder*='Last']",
            ],
            "name": [
                "input[name='name']", "input[id*='name']",
                "input[placeholder*='Name']", "input[placeholder*='Full']",
            ],
            "email": [
                "input[type='email']", "input[name='email']",
                "input[id*='email']", "input[placeholder*='email']",
                "input[placeholder*='Email']",
            ],
        }
        values = {
            "first_name": first,
            "last_name": last,
            "name": full_name,
            "email": email,
        }

        submitted = await _fill_and_submit(
            page, selectors, values,
            [
                "button[type='submit']", "input[type='submit']",
                "button:has-text('Submit')", "button:has-text('Remove')",
                "button:has-text('Opt Out')", "button:has-text('Request')",
                "a:has-text('Submit')", "a:has-text('Remove')",
            ],
        )

        ss_path = os.path.join(SCREENSHOT_DIR, f"{scan_id}_{broker_key}_removal.png")
        try:
            await page.screenshot(path=ss_path)
        except:
            ss_path = None

        if submitted:
            await asyncio.sleep(3)
            # Check for success indicators
            body_text = ""
            body = await page.query_selector("body")
            if body:
                body_text = (await body.inner_text()) or ""
            success_words = ["success", "submitted", "received", "confirmed", "pending", "removed", "thank you"]
            confirmed = any(w in body_text.lower() for w in success_words)

            return RemovalResult(
                broker_name=broker_name, broker_key=broker_key,
                status="submitted" if confirmed else "pending_email",
                message="Opt-out submitted" + (". Check email for confirmation." if not confirmed else "."),
                removal_url=removal_url,
                screenshot_path=ss_path,
                processing_time=round(time.time() - start, 2),
            )
        else:
            return RemovalResult(
                broker_name=broker_name, broker_key=broker_key,
                status="manual_required",
                message=f"Could not auto-submit on {broker_name}. Visit the opt-out page.",
                removal_url=removal_url,
                screenshot_path=ss_path,
                processing_time=round(time.time() - start, 2),
                instructions=f"1. Go to {removal_url}\n2. Search for your name\n3. Request removal",
            )
    except Exception as e:
        return RemovalResult(
            broker_name=broker_name, broker_key=broker_key,
            status="error", message=str(e),
            removal_url=removal_url,
            error=str(e), processing_time=round(time.time() - start, 2),
        )
    finally:
        await page.close()


# Manual-only brokers
def manual_removal_result(broker_name: str, broker_key: str, removal_url: str, method: str, instructions: str) -> RemovalResult:
    return RemovalResult(
        broker_name=broker_name, broker_key=broker_key,
        status="manual_required",
        message=f"{broker_name} requires {method}.",
        removal_url=removal_url,
        instructions=instructions,
    )


# =============================================================================
# ORCHESTRATOR
# =============================================================================

async def remove_from_brokers(
    found_brokers: list,
    first_name: str,
    last_name: str,
    email: str,
    city: str = "",
    state: str = "",
    scan_id: str = "",
) -> list:
    """
    Submit removal requests for all brokers where person was found.
    found_brokers: list of broker_key strings
    Returns list of RemovalResult dicts.
    """
    from brokers import BROKERS

    if not found_brokers:
        return []

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        for broker_key in found_brokers:
            broker = BROKERS.get(broker_key)
            if not broker:
                continue

            removal = broker["removal"]
            logger.info(f"[{broker['name']}] Starting removal (method: {removal['method']})")

            # Route to specific handler
            if broker_key == "spokeo":
                result = await remove_spokeo(context, first_name, last_name, email, scan_id)
            elif broker_key == "whitepages":
                result = await remove_whitepages(context, first_name, last_name, email, city, state, scan_id)
            elif broker_key == "fastpeoplesearch":
                result = await remove_fastpeoplesearch(context, first_name, last_name, email, scan_id)
            elif removal["method"] == "web_form" and removal.get("auto_possible"):
                result = await remove_generic_webform(
                    context, broker["name"], broker_key,
                    removal["url"], first_name, last_name, email, scan_id,
                )
            elif removal["method"] == "email":
                result = manual_removal_result(
                    broker["name"], broker_key, removal["url"], "email",
                    f"Send removal request to {removal.get('email', 'their privacy email')}.\n"
                    f"Include your full name, city, state, and request data deletion.",
                )
            elif removal.get("has_captcha"):
                result = manual_removal_result(
                    broker["name"], broker_key, removal["url"], "CAPTCHA verification",
                    f"1. Go to {removal['url']}\n"
                    f"2. Enter your name and email\n"
                    f"3. Complete CAPTCHA\n"
                    f"4. Submit removal request",
                )
            elif removal.get("requires_phone"):
                result = manual_removal_result(
                    broker["name"], broker_key, removal["url"], "phone verification",
                    f"1. Go to {removal['url']}\n"
                    f"2. Enter your information\n"
                    f"3. Complete phone verification\n"
                    f"4. Submit removal request",
                )
            elif removal["method"] == "account_required":
                result = manual_removal_result(
                    broker["name"], broker_key, removal["url"], "account creation",
                    f"1. Go to {removal['url']}\n"
                    f"2. Create an account\n"
                    f"3. Find your profile and request removal",
                )
            else:
                result = await remove_generic_webform(
                    context, broker["name"], broker_key,
                    removal["url"], first_name, last_name, email, scan_id,
                )

            results.append(asdict(result))
            logger.info(f"[{broker['name']}] Status: {result.status}")

            # Delay between brokers
            await asyncio.sleep(random.uniform(3.0, 6.0))

        await browser.close()

    return results
