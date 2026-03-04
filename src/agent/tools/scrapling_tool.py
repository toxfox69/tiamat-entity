#!/usr/bin/env python3
"""
Scrapling Web Scraping Tool for TIAMAT

Provides adaptive web scraping with anti-bot bypass, stealth browsing,
and smart element tracking that survives website redesigns.

Usage:
    python3 scrapling_tool.py '{"action":"fetch","url":"https://example.com","selector":".content"}'
    python3 scrapling_tool.py '{"action":"stealth","url":"https://example.com","selector":"h1"}'
    python3 scrapling_tool.py '{"action":"search","url":"https://example.com","text":"pricing"}'
"""

import sys
import json


def fetch_page(url: str, selector: str = None) -> dict:
    """Fast HTTP fetch with TLS fingerprint impersonation."""
    from scrapling.fetchers import Fetcher

    page = Fetcher.get(url, stealthy_headers=True)

    result = {"url": url, "status": page.status, "title": ""}

    # Get page title
    title_el = page.css("title::text")
    if title_el:
        result["title"] = title_el.get("").strip()

    if selector:
        elements = page.css(selector)
        result["count"] = len(elements)
        result["data"] = []
        for el in elements[:20]:  # Cap at 20 elements
            text = el.text.strip() if hasattr(el, 'text') else str(el)
            result["data"].append(text[:500])
    else:
        # Return page text content (truncated)
        body = page.css("body")
        if body:
            text = body[0].text.strip() if hasattr(body[0], 'text') else ""
            result["text"] = text[:3000]

    return result


def stealth_fetch(url: str, selector: str = None, wait_for: str = None) -> dict:
    """Stealth browser fetch — bypasses Cloudflare and anti-bot systems."""
    from scrapling.fetchers import StealthyFetcher

    page = StealthyFetcher.fetch(url, headless=True)

    result = {"url": url, "status": page.status, "title": "", "mode": "stealth"}

    title_el = page.css("title::text")
    if title_el:
        result["title"] = title_el.get("").strip()

    if selector:
        elements = page.css(selector)
        result["count"] = len(elements)
        result["data"] = []
        for el in elements[:20]:
            text = el.text.strip() if hasattr(el, 'text') else str(el)
            result["data"].append(text[:500])
    else:
        body = page.css("body")
        if body:
            text = body[0].text.strip() if hasattr(body[0], 'text') else ""
            result["text"] = text[:3000]

    return result


def dynamic_fetch(url: str, selector: str = None) -> dict:
    """Full browser automation fetch with JavaScript rendering."""
    from scrapling.fetchers import DynamicFetcher

    page = DynamicFetcher.fetch(url, headless=True, network_idle=True)

    result = {"url": url, "status": page.status, "title": "", "mode": "dynamic"}

    title_el = page.css("title::text")
    if title_el:
        result["title"] = title_el.get("").strip()

    if selector:
        elements = page.css(selector)
        result["count"] = len(elements)
        result["data"] = []
        for el in elements[:20]:
            text = el.text.strip() if hasattr(el, 'text') else str(el)
            result["data"].append(text[:500])
    else:
        body = page.css("body")
        if body:
            text = body[0].text.strip() if hasattr(body[0], 'text') else ""
            result["text"] = text[:3000]

    return result


def search_text(url: str, text: str) -> dict:
    """Fetch page and search for specific text content."""
    from scrapling.fetchers import Fetcher

    page = Fetcher.get(url, stealthy_headers=True)

    result = {"url": url, "status": page.status, "query": text, "matches": []}

    # Search all text-containing elements
    all_elements = page.css("p, li, h1, h2, h3, h4, td, span, div, a")
    for el in all_elements:
        el_text = el.text.strip() if hasattr(el, 'text') else str(el)
        if text.lower() in el_text.lower() and len(el_text) > 10:
            result["matches"].append(el_text[:300])
            if len(result["matches"]) >= 15:
                break

    result["match_count"] = len(result["matches"])
    return result


def extract_links(url: str, pattern: str = None) -> dict:
    """Extract all links from a page, optionally filtered by pattern."""
    from scrapling.fetchers import Fetcher
    import re

    page = Fetcher.get(url, stealthy_headers=True)

    result = {"url": url, "status": page.status, "links": []}

    anchors = page.css("a")
    for a in anchors:
        href = a.attrib.get("href", "") if hasattr(a, 'attrib') else ""
        text = a.text.strip() if hasattr(a, 'text') else ""
        if not href:
            continue
        if pattern and not re.search(pattern, href, re.IGNORECASE):
            continue
        result["links"].append({"href": href, "text": text[:100]})
        if len(result["links"]) >= 50:
            break

    result["link_count"] = len(result["links"])
    return result


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: scrapling_tool.py '{\"action\":\"fetch\",\"url\":\"...\"}'"}, indent=2))
        sys.exit(1)

    try:
        args = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    action = args.get("action", "fetch")
    url = args.get("url")
    selector = args.get("selector")
    text = args.get("text")
    pattern = args.get("pattern")

    if not url:
        print(json.dumps({"error": "Missing required 'url' parameter"}))
        sys.exit(1)

    try:
        if action == "fetch":
            result = fetch_page(url, selector)
        elif action == "stealth":
            result = stealth_fetch(url, selector)
        elif action == "dynamic":
            result = dynamic_fetch(url, selector)
        elif action == "search":
            if not text:
                print(json.dumps({"error": "Missing 'text' parameter for search action"}))
                sys.exit(1)
            result = search_text(url, text)
        elif action == "links":
            result = extract_links(url, pattern)
        else:
            print(json.dumps({"error": f"Unknown action: {action}. Use: fetch, stealth, dynamic, search, links"}))
            sys.exit(1)

        print(json.dumps(result, indent=2, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)[:500], "action": action, "url": url}))
        sys.exit(1)


if __name__ == "__main__":
    main()
