#!/usr/bin/env python3
"""
FastCrawl — High-speed web crawler with Cloudflare/bot bypass.
Uses curl_cffi (TLS fingerprint impersonation) + readability for clean text.
No API keys, no costs, no restrictions.

Usage:
    python3 fastcrawl.py fetch <url>                    # Single page → clean text
    python3 fastcrawl.py crawl <url> [--depth=2] [--max=10]  # Multi-page crawl
    python3 fastcrawl.py search <query> [--limit=10]    # DuckDuckGo search
    python3 fastcrawl.py multi <url1> <url2> ...        # Parallel fetch multiple URLs
"""

import sys
import json
import re
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from typing import Optional

from curl_cffi import requests as cffi_requests
from readability import Document
from bs4 import BeautifulSoup

# Rotate through browser impersonations to avoid fingerprint blocking
BROWSERS = ["chrome120", "chrome119", "chrome116", "safari17_0", "safari15_5"]
_browser_idx = 0

# Shared session for connection reuse (faster)
_sessions = {}

def get_session(browser: str = None) -> cffi_requests.Session:
    global _browser_idx
    if browser is None:
        browser = BROWSERS[_browser_idx % len(BROWSERS)]
        _browser_idx += 1
    if browser not in _sessions:
        _sessions[browser] = cffi_requests.Session(impersonate=browser)
    return _sessions[browser]


def fetch_page(url: str, timeout: int = 12) -> dict:
    """Fetch a single page, bypass Cloudflare, return clean text + metadata."""
    try:
        session = get_session()
        resp = session.get(url, timeout=timeout, allow_redirects=True, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        })

        if resp.status_code == 403:
            # Retry with different browser fingerprint
            session = get_session(BROWSERS[(_browser_idx + 2) % len(BROWSERS)])
            resp = session.get(url, timeout=timeout, allow_redirects=True)

        if resp.status_code != 200:
            return {"url": url, "status": resp.status_code, "error": f"HTTP {resp.status_code}", "text": "", "links": []}

        html = resp.text
        content_type = resp.headers.get("content-type", "")

        # Non-HTML content
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return {"url": url, "status": 200, "text": html[:8000], "links": [], "type": content_type}

        # Extract clean readable text
        doc = Document(html)
        title = doc.title() or ""
        clean_html = doc.summary()
        soup = BeautifulSoup(clean_html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)

        # If readability returns too little, fall back to full page
        if len(text) < 100:
            soup_full = BeautifulSoup(html, "html.parser")
            for tag in soup_full(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
                tag.decompose()
            text = soup_full.get_text(separator="\n", strip=True)

        # Clean up excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        # Extract links
        soup_links = BeautifulSoup(html, "html.parser")
        links = []
        seen = set()
        for a in soup_links.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if href not in seen and href.startswith("http"):
                seen.add(href)
                link_text = a.get_text(strip=True)[:80]
                links.append({"url": href, "text": link_text})

        return {
            "url": str(resp.url),
            "status": 200,
            "title": title,
            "text": text[:12000],
            "text_length": len(text),
            "links": links[:50],
            "link_count": len(links),
        }

    except Exception as e:
        return {"url": url, "status": 0, "error": str(e), "text": "", "links": []}


def fetch_multi(urls: list, max_workers: int = 5) -> list:
    """Fetch multiple URLs in parallel."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_page, url): url for url in urls}
        for future in as_completed(futures):
            results.append(future.result())
    return results


def crawl(start_url: str, max_pages: int = 10, max_depth: int = 2, same_domain: bool = True) -> list:
    """Crawl from a starting URL, following links up to max_depth/max_pages."""
    start_domain = urlparse(start_url).netloc
    visited = set()
    results = []
    queue = [(start_url, 0)]  # (url, depth)

    while queue and len(results) < max_pages:
        url, depth = queue.pop(0)

        # Normalize URL
        url = url.split("#")[0].rstrip("/")
        if url in visited:
            continue
        visited.add(url)

        # Domain filter
        if same_domain and urlparse(url).netloc != start_domain:
            continue

        # Skip non-page URLs
        skip_ext = ('.pdf', '.jpg', '.png', '.gif', '.svg', '.css', '.js', '.zip', '.tar', '.mp4', '.mp3')
        if any(url.lower().endswith(ext) for ext in skip_ext):
            continue

        page = fetch_page(url)
        page["depth"] = depth
        results.append(page)

        # Queue child links if within depth
        if depth < max_depth and page.get("links"):
            for link in page["links"]:
                child_url = link["url"].split("#")[0].rstrip("/")
                if child_url not in visited:
                    queue.append((child_url, depth + 1))

        # Small delay between pages on same domain
        if len(results) < max_pages:
            time.sleep(0.3)

    return results


def search_ddg(query: str, limit: int = 10) -> list:
    """Search DuckDuckGo, return results with titles, URLs, snippets."""
    session = get_session()
    # DuckDuckGo HTML search
    resp = session.get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=10)
    if resp.status_code != 200:
        return [{"error": f"DDG returned {resp.status_code}"}]

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.select(".result"):
        title_el = result.select_one(".result__title a, .result__a")
        snippet_el = result.select_one(".result__snippet")
        if not title_el:
            continue

        href = title_el.get("href", "")
        # DDG wraps URLs in redirect — extract actual URL
        if "uddg=" in href:
            from urllib.parse import unquote, parse_qs
            parsed = parse_qs(urlparse(href).query)
            href = unquote(parsed.get("uddg", [href])[0])

        results.append({
            "title": title_el.get_text(strip=True),
            "url": href,
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })

        if len(results) >= limit:
            break

    return results


def format_output(data, mode="text"):
    """Format output for TIAMAT consumption."""
    if mode == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)

    if isinstance(data, list):
        parts = []
        for i, item in enumerate(data):
            if "title" in item and "snippet" in item:
                # Search result
                parts.append(f"{i+1}. {item['title']}\n   {item['url']}\n   {item.get('snippet', '')}")
            elif "text" in item:
                # Page result
                depth = item.get('depth', 0)
                indent = "  " * depth
                parts.append(f"{'='*60}\n{indent}[{item.get('status', '?')}] {item.get('title', item['url'])}\n{indent}URL: {item['url']}\n{indent}Length: {item.get('text_length', len(item['text']))} chars\n{'='*60}\n{item['text'][:6000]}")
            else:
                parts.append(str(item))
        return "\n\n".join(parts)
    elif isinstance(data, dict):
        if "error" in data:
            return f"ERROR: {data['error']}"
        title = data.get("title", "")
        text = data.get("text", "")
        links = data.get("links", [])
        out = f"# {title}\nURL: {data['url']}\nLength: {data.get('text_length', len(text))} chars\n\n{text}"
        if links:
            out += f"\n\n--- Links ({data.get('link_count', len(links))}) ---\n"
            for l in links[:20]:
                out += f"  {l['text'][:60]:60s} → {l['url']}\n"
        return out
    return str(data)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    cmd = args[0]
    output_json = "--json" in args
    args = [a for a in args if not a.startswith("--json")]

    if cmd == "fetch" and len(args) >= 2:
        result = fetch_page(args[1])
        print(format_output(result, "json" if output_json else "text"))

    elif cmd == "multi" and len(args) >= 2:
        urls = args[1:]
        results = fetch_multi(urls)
        print(format_output(results, "json" if output_json else "text"))

    elif cmd == "crawl" and len(args) >= 2:
        url = args[1]
        max_pages = 10
        max_depth = 2
        for a in sys.argv:
            if a.startswith("--max="):
                max_pages = int(a.split("=")[1])
            if a.startswith("--depth="):
                max_depth = int(a.split("=")[1])
        results = crawl(url, max_pages=max_pages, max_depth=max_depth)
        print(format_output(results, "json" if output_json else "text"))

    elif cmd == "search" and len(args) >= 2:
        query = " ".join(args[1:])
        limit = 10
        for a in sys.argv:
            if a.startswith("--limit="):
                limit = int(a.split("=")[1])
        results = search_ddg(query, limit=limit)
        print(format_output(results, "json" if output_json else "text"))

    else:
        print(__doc__)
        sys.exit(1)
