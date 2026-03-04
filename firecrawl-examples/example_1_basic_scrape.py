"""
Firecrawl Python SDK — Example: Basic URL to Markdown Scraper
=============================================================

Pass any URL → get clean, LLM-ready Markdown. Firecrawl handles
JavaScript rendering, anti-bot measures, and boilerplate stripping
automatically. No browser needed, no parsing required.

Requirements:
    pip install firecrawl-py

Setup:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    # Get a free key at https://firecrawl.dev/app/api-keys

Usage:
    python example_1_basic_scrape.py
    python example_1_basic_scrape.py https://news.ycombinator.com
    python example_1_basic_scrape.py https://example.com --full-page

Output:
    Title, word count, and a Markdown preview printed to stdout.

Example output:
    Scraping: https://news.ycombinator.com
    Title : Hacker News
    Words : 1,412
    ---
    # Hacker News
    1. Some Article Title (example.com) ...
"""

import os
import sys
from firecrawl import FirecrawlApp


def scrape_to_markdown(url: str, only_main_content: bool = True) -> dict:
    """Scrape a URL and return clean Markdown with page metadata.

    Args:
        url:               Full URL to scrape (must start with https://).
        only_main_content: Strip nav, ads, and footers (default: True).

    Returns:
        dict with keys: ``url``, ``markdown``, ``title``,
        ``description``, and ``word_count``.

    Raises:
        EnvironmentError: FIRECRAWL_API_KEY environment variable is not set.
        RuntimeError:     Scrape succeeded but returned no Markdown content.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FIRECRAWL_API_KEY is not set.\n"
            "  export FIRECRAWL_API_KEY='fc-your-key-here'\n"
            "  Free key: https://firecrawl.dev/app/api-keys"
        )

    app = FirecrawlApp(api_key=api_key)
    print(f"Scraping: {url}")

    # scrape() renders JavaScript, rotates proxies, and bypasses bot checks.
    # only_main_content=True removes nav/footer/ads, keeping the article body.
    doc = app.scrape(url, formats=["markdown"], only_main_content=only_main_content)

    if not doc:
        raise RuntimeError(f"Empty response from Firecrawl for: {url}")

    # Normalise: SDK may return a Document object or a plain dict
    def _get(key: str):
        if hasattr(doc, key):
            return getattr(doc, key)
        if isinstance(doc, dict):
            return doc.get(key)
        return None

    markdown = _get("markdown") or ""
    if not markdown:
        raise RuntimeError(f"No Markdown content returned for: {url}")

    raw_meta = _get("metadata") or {}
    meta = (
        raw_meta.model_dump()
        if hasattr(raw_meta, "model_dump")
        else (raw_meta if isinstance(raw_meta, dict) else {})
    )

    return {
        "url": url,
        "markdown": markdown,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "word_count": len(markdown.split()),
    }


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com"
    only_main = "--full-page" not in sys.argv

    try:
        result = scrape_to_markdown(url, only_main_content=only_main)
    except (EnvironmentError, RuntimeError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    md = result["markdown"]
    print(f"Title : {result['title'] or '(none)'}")
    print(f"Words : {result['word_count']:,}  ({len(md):,} characters)")

    desc = result["description"]
    if desc:
        print(f"Desc  : {desc[:100]}{'...' if len(desc) > 100 else ''}")

    print()
    print("─" * 60)
    print("Markdown preview (first 800 characters)")
    print("─" * 60)
    print(md[:800])
    if len(md) > 800:
        print(f"\n... [{len(md) - 800:,} more characters]")


if __name__ == "__main__":
    main()
