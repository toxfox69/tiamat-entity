#!/usr/bin/env python3
"""
TIAMAT Lightweight CLI Web Browser (Scrapling Edition)
Anti-detect web fetching, clean text extraction, search — no Chromium needed.

Usage:
  python3 webbrowser.py fetch <url> [--json] [--raw] [--stealth]
  python3 webbrowser.py search <query> [--json] [--limit N]
  python3 webbrowser.py extract <url> --links [--stealth]
  python3 webbrowser.py extract <url> --meta [--stealth]
  python3 webbrowser.py js <url> [--json]              # JS rendering via StealthyFetcher
  python3 webbrowser.py screenshot <url> [name]         # (requires playwright+firefox)

Flags:
  --stealth   Use StealthyFetcher (real browser TLS, anti-detect) — slower but bypasses bot protection
  --json      Output as JSON
  --raw       Return raw HTML instead of extracted text
"""

import sys
import json
import re
import time
import os
import logging
from urllib.parse import urljoin, urlparse, quote_plus

from bs4 import BeautifulSoup
from readability import Document

# Suppress scrapling's verbose logging
logging.getLogger("scrapling").setLevel(logging.ERROR)
logging.disable(logging.WARNING)

# ── Config ────────────────────────────────────────────────────────────────────
MAX_BODY = 2 * 1024 * 1024  # 2MB max
TIMEOUT = 15


# ── Fetcher helpers ──────────────────────────────────────────────────────────

def _get(url: str, stealth: bool = False):
    """Fetch URL via Scrapling. Returns (status, url, headers_dict, html_text, page_obj).
    stealth=True uses StealthyFetcher (real browser fingerprint, anti-detect).
    """
    if stealth:
        from scrapling import StealthyFetcher
        fetcher = StealthyFetcher()
        page = fetcher.fetch(url, headless=True, timeout=TIMEOUT * 1000)
    else:
        from scrapling import Fetcher
        fetcher = Fetcher()
        page = fetcher.get(url, timeout=TIMEOUT)

    # Scrapling page.text can be empty for non-HTML; fall back to body bytes
    html = ""
    if hasattr(page, 'text') and page.text:
        html = str(page.text)
    if not html and hasattr(page, 'body') and page.body:
        html = page.body.decode("utf-8", errors="replace") if isinstance(page.body, bytes) else str(page.body)

    headers = {}
    if hasattr(page, 'headers') and page.headers:
        headers = dict(page.headers) if not isinstance(page.headers, dict) else page.headers

    final_url = str(page.url) if hasattr(page, 'url') and page.url else url

    return page.status, final_url, headers, html, page


def _get_httpx(url: str):
    """Fallback: plain httpx fetch if Scrapling fails."""
    import httpx
    headers = {
        "User-Agent": "TIAMAT/1.0 (autonomous-agent; +https://tiamat.live)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=headers, max_redirects=5) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.status_code, str(resp.url), dict(resp.headers), resp.text


def _fetch(url: str, stealth: bool = False):
    """Fetch with Scrapling, fall back to httpx on failure.
    Returns (status, final_url, headers, html).
    """
    try:
        status, final_url, headers, html, _ = _get(url, stealth=stealth)
        if status and status < 400:
            return status, final_url, headers, html
        # Non-OK status — try httpx fallback for non-stealth
        if not stealth:
            raise ValueError(f"Scrapling returned {status}")
        return status, final_url, headers, html
    except Exception as e:
        if stealth:
            _err(f"StealthyFetcher failed: {e}")
            raise
        # Fallback to httpx
        try:
            return _get_httpx(url)
        except Exception as e2:
            _err(f"Both Scrapling and httpx failed: {e} / {e2}")
            raise


def _clean_text(text: str) -> str:
    """Collapse whitespace, strip blank lines."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            cleaned.append(stripped)
    return "\n".join(cleaned)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_fetch(url: str, as_json: bool = False, raw: bool = False, stealth: bool = False):
    """Fetch URL, extract readable content via readability algorithm."""
    try:
        status, final_url, headers, body = _fetch(url, stealth=stealth)
    except Exception as e:
        _err(f"Fetch error: {e}")
        return

    content_type = headers.get("content-type", "")

    # Non-HTML: just dump text
    if "html" not in content_type and not body.strip().startswith("<"):
        if as_json:
            print(json.dumps({"url": final_url, "content_type": content_type, "text": body[:50000]}, indent=2))
        else:
            print(body[:50000])
        return

    if raw:
        if as_json:
            print(json.dumps({"url": final_url, "html": body[:50000]}, indent=2))
        else:
            print(body[:50000])
        return

    # Readability extraction
    doc = Document(body)
    title = doc.title()
    summary_html = doc.summary()

    # Convert summary HTML to clean text
    soup = BeautifulSoup(summary_html, "lxml")
    readable_text = _clean_text(soup.get_text(separator="\n"))

    # Fallback: if readability returned near-empty, parse full page body
    if len(readable_text) < 50:
        full_soup = BeautifulSoup(body, "lxml")
        for tag in full_soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        readable_text = _clean_text(full_soup.get_text(separator="\n"))
        if not title or title == "[no-title]":
            title_tag = full_soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
        soup = full_soup

    # Extract links from the readable content
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"])
        text = a.get_text(strip=True)
        if text and href.startswith("http"):
            links.append({"text": text[:100], "url": href})

    if len(readable_text) > 30000:
        readable_text = readable_text[:30000] + "\n\n[...truncated]"

    engine = "stealth" if stealth else "scrapling"
    if as_json:
        print(json.dumps({
            "url": final_url,
            "title": title,
            "text": readable_text,
            "links": links[:50],
            "content_length": len(body),
            "engine": engine,
        }, indent=2))
    else:
        print(f"# {title}")
        print(f"URL: {final_url}")
        print(f"Length: {len(body)} bytes ({engine})")
        print("---")
        print(readable_text)
        if links:
            print("\n--- Links ---")
            for link in links[:20]:
                print(f"  [{link['text']}] -> {link['url']}")


def cmd_search(query: str, as_json: bool = False, limit: int = 10):
    """Search via DuckDuckGo HTML (no API key needed)."""
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        status, final_url, headers, body = _fetch(search_url)
    except Exception as e:
        _err(f"Search error: {e}")
        return

    soup = BeautifulSoup(body, "lxml")
    results = []

    for result in soup.select(".result"):
        title_el = result.select_one(".result__a")
        snippet_el = result.select_one(".result__snippet")
        url_el = result.select_one(".result__url")

        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        href = title_el.get("href", "")

        actual_url = href
        if "uddg=" in href:
            import urllib.parse
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            actual_url = parsed.get("uddg", [href])[0]
        elif url_el:
            raw_url = url_el.get_text(strip=True)
            if raw_url and not raw_url.startswith("http"):
                raw_url = "https://" + raw_url
            actual_url = raw_url

        results.append({
            "title": title,
            "url": actual_url,
            "snippet": snippet,
        })

        if len(results) >= limit:
            break

    if as_json:
        print(json.dumps({"query": query, "results": results}, indent=2))
    else:
        print(f"Search: {query}")
        print(f"Results: {len(results)}")
        print("---")
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['title']}")
            print(f"   {r['url']}")
            if r["snippet"]:
                print(f"   {r['snippet'][:200]}")


def cmd_extract_links(url: str, as_json: bool = False, stealth: bool = False):
    """Extract all links from a page."""
    try:
        status, final_url, headers, body = _fetch(url, stealth=stealth)
    except Exception as e:
        _err(f"Fetch error: {e}")
        return

    soup = BeautifulSoup(body, "lxml")
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"])
        if href in seen or not href.startswith("http"):
            continue
        seen.add(href)
        text = a.get_text(strip=True)[:100]
        links.append({"text": text, "url": href})

    if as_json:
        print(json.dumps({"url": final_url, "links": links}, indent=2))
    else:
        print(f"Links from {final_url} ({len(links)} total):")
        for link in links:
            label = f" [{link['text']}]" if link["text"] else ""
            print(f"  {link['url']}{label}")


def cmd_extract_meta(url: str, as_json: bool = False, stealth: bool = False):
    """Extract metadata: title, description, og tags, structured data."""
    try:
        status, final_url, headers, body = _fetch(url, stealth=stealth)
    except Exception as e:
        _err(f"Fetch error: {e}")
        return

    soup = BeautifulSoup(body, "lxml")

    meta = {
        "url": final_url,
        "title": "",
        "description": "",
        "og": {},
        "twitter": {},
        "canonical": "",
        "structured_data": [],
    }

    title_tag = soup.find("title")
    if title_tag:
        meta["title"] = title_tag.get_text(strip=True)

    for tag in soup.find_all("meta"):
        name = tag.get("name", "").lower()
        prop = tag.get("property", "").lower()
        content = tag.get("content", "")

        if name == "description" or prop == "description":
            meta["description"] = content
        elif prop.startswith("og:"):
            meta["og"][prop[3:]] = content
        elif name.startswith("twitter:"):
            meta["twitter"][name[8:]] = content

    canonical = soup.find("link", rel="canonical")
    if canonical:
        meta["canonical"] = canonical.get("href", "")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            meta["structured_data"].append(data)
        except (json.JSONDecodeError, TypeError):
            pass

    if as_json:
        print(json.dumps(meta, indent=2))
    else:
        print(f"# {meta['title']}")
        print(f"URL: {meta['url']}")
        if meta["description"]:
            print(f"Description: {meta['description']}")
        if meta["canonical"]:
            print(f"Canonical: {meta['canonical']}")
        if meta["og"]:
            print("\nOpenGraph:")
            for k, v in meta["og"].items():
                print(f"  og:{k} = {v}")
        if meta["twitter"]:
            print("\nTwitter Card:")
            for k, v in meta["twitter"].items():
                print(f"  twitter:{k} = {v}")
        if meta["structured_data"]:
            print(f"\nStructured Data: {len(meta['structured_data'])} JSON-LD block(s)")
            for sd in meta["structured_data"]:
                t = sd.get("@type", "unknown")
                print(f"  @type: {t}")


def cmd_js(url: str, as_json: bool = False):
    """Fetch with JS rendering via StealthyFetcher (anti-detect Chromium)."""
    try:
        from scrapling import StealthyFetcher
        fetcher = StealthyFetcher()
        page = fetcher.fetch(url, headless=True, timeout=TIMEOUT * 1000)

        html = ""
        if hasattr(page, 'text') and page.text:
            html = str(page.text)
        if not html and hasattr(page, 'body') and page.body:
            html = page.body.decode("utf-8", errors="replace") if isinstance(page.body, bytes) else str(page.body)
    except Exception as e:
        _err(f"StealthyFetcher JS render failed: {e}. Falling back to regular fetch.")
        cmd_fetch(url, as_json=as_json)
        return

    doc = Document(html)
    title = doc.title()
    summary_html = doc.summary()
    soup = BeautifulSoup(summary_html, "lxml")
    readable_text = _clean_text(soup.get_text(separator="\n"))

    if len(readable_text) > 30000:
        readable_text = readable_text[:30000] + "\n\n[...truncated]"

    if as_json:
        print(json.dumps({"url": url, "title": title, "text": readable_text, "js_rendered": True, "engine": "stealth"}, indent=2))
    else:
        print(f"# {title}")
        print(f"URL: {url} (JS rendered, stealth)")
        print("---")
        print(readable_text)


def cmd_screenshot(url: str, name: str = ""):
    """Take a screenshot via playwright Firefox."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _err("playwright not installed. Cannot take screenshots.")
        return

    out_dir = "/var/www/tiamat/images/screenshots"
    os.makedirs(out_dir, exist_ok=True)
    filename = name or f"shot_{int(time.time())}"
    if not filename.endswith(".png"):
        filename += ".png"
    out_path = os.path.join(out_dir, filename)

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.firefox.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(
            user_agent="TIAMAT/1.0 (autonomous-agent; +https://tiamat.live)",
            viewport={"width": 1280, "height": 720},
        )
        page.goto(url, wait_until="networkidle", timeout=15000)
        page.screenshot(path=out_path, full_page=False)
        print(f"Screenshot saved: {out_path}")
    except Exception as e:
        _err(f"Screenshot error: {e}")
    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()


# ── Utilities ─────────────────────────────────────────────────────────────────

def _err(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)


def _usage():
    print(__doc__.strip())
    sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        _usage()

    command = args[0]
    flags = [a for a in args[1:] if a.startswith("--")]
    positional = [a for a in args[1:] if not a.startswith("--")]
    as_json = "--json" in flags
    stealth = "--stealth" in flags

    if command == "fetch":
        if not positional:
            _err("Usage: webbrowser.py fetch <url> [--json] [--raw] [--stealth]")
            sys.exit(1)
        cmd_fetch(positional[0], as_json=as_json, raw="--raw" in flags, stealth=stealth)

    elif command == "search":
        if not positional:
            _err("Usage: webbrowser.py search <query> [--json] [--limit N]")
            sys.exit(1)
        query = " ".join(positional)
        limit = 10
        if "--limit" in flags:
            idx = args.index("--limit")
            if idx + 1 < len(args):
                try:
                    limit = int(args[idx + 1])
                except ValueError:
                    pass
        cmd_search(query, as_json=as_json, limit=limit)

    elif command == "extract":
        if not positional:
            _err("Usage: webbrowser.py extract <url> --links|--meta [--stealth]")
            sys.exit(1)
        if "--links" in flags:
            cmd_extract_links(positional[0], as_json=as_json, stealth=stealth)
        elif "--meta" in flags:
            cmd_extract_meta(positional[0], as_json=as_json, stealth=stealth)
        else:
            _err("Specify --links or --meta")
            sys.exit(1)

    elif command == "js":
        if not positional:
            _err("Usage: webbrowser.py js <url> [--json]")
            sys.exit(1)
        cmd_js(positional[0], as_json=as_json)

    elif command == "screenshot":
        if not positional:
            _err("Usage: webbrowser.py screenshot <url> [name]")
            sys.exit(1)
        name = positional[1] if len(positional) > 1 else ""
        cmd_screenshot(positional[0], name)

    else:
        _err(f"Unknown command: {command}")
        _usage()


if __name__ == "__main__":
    main()
