"""
Firecrawl Python SDK — Example 1: Basic Web Scraper
====================================================

Scrapes a single URL and returns clean Markdown, page metadata, and
an outbound-links list. Ideal for feeding web content into LLMs, RAG
pipelines, content archives, or one-off research tasks.

Requirements:
    pip install firecrawl-py

Setup:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    # Get a free key at https://www.firecrawl.dev/app/api-keys

Usage:
    # Scrape the default demo URL (Hacker News):
    python basic_web_scraper.py

    # Scrape a custom URL:
    python basic_web_scraper.py https://example.com

    # Scrape with HTML output included:
    python basic_web_scraper.py https://example.com --html

Output:
    Saved files under ./output/scrape/:
        <slug>_<timestamp>.md          — clean Markdown content
        <slug>_<timestamp>.html        — raw HTML (if --html flag used)
        <slug>_<timestamp>_meta.json   — metadata + top 20 links
    Console summary: title, word count, link count, Markdown preview.

Example output (Hacker News):
    [firecrawl] Scraping: https://news.ycombinator.com
    [firecrawl] Markdown saved: output/scrape/news.ycombinator.com_20260304_120000.md
    [firecrawl] Metadata saved: output/scrape/news.ycombinator.com_20260304_120000_meta.json
    ============================================================
    SCRAPE SUMMARY
    ============================================================
    URL:          https://news.ycombinator.com
    Title:        Hacker News
    Description:  (none)
    Markdown len: 8,421 characters  (~1,400 words)
    Links found:  312
    --- Markdown preview (first 600 chars) ---
    # Hacker News
    ...
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from firecrawl import FirecrawlApp


# ---------------------------------------------------------------------------
# Core scrape function
# ---------------------------------------------------------------------------

def scrape_url(
    url: str,
    *,
    only_main_content: bool = True,
    include_html: bool = False,
    include_links: bool = True,
    output_dir: str = "output/scrape",
) -> dict:
    """
    Scrape a URL and return Markdown, metadata, and links.

    Uses Firecrawl's v2 ``scrape`` endpoint which renders JavaScript,
    handles anti-bot measures, and strips boilerplate (nav, ads, footers)
    when *only_main_content* is True.

    Args:
        url:               Full URL to scrape (must start with http:// or https://).
        only_main_content: Strip navigation, ads, and footer — keeps article body.
        include_html:      Also request raw HTML alongside Markdown.
        include_links:     Collect outbound links from the page.
        output_dir:        Directory where output files are saved.

    Returns:
        dict with keys:
            ``url``         — original URL
            ``scraped_at``  — ISO-8601 UTC timestamp
            ``markdown``    — clean Markdown string
            ``html``        — raw HTML string (empty if include_html=False)
            ``links``       — list of outbound href strings
            ``metadata``    — dict of page metadata (title, description, OG tags…)

    Raises:
        EnvironmentError: FIRECRAWL_API_KEY not set.
        RuntimeError:     Scrape returned no content.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FIRECRAWL_API_KEY is not set.\n"
            "Export it: export FIRECRAWL_API_KEY='fc-your-key-here'\n"
            "Get a free key at https://www.firecrawl.dev/app/api-keys"
        )

    app = FirecrawlApp(api_key=api_key)

    # Build the list of formats to request from the API
    formats = ["markdown"]
    if include_html:
        formats.append("html")
    if include_links:
        formats.append("links")

    print(f"[firecrawl] Scraping: {url}")
    print(f"[firecrawl] Formats requested: {formats}")

    # v2 scrape — JavaScript rendering, proxy rotation, bot-bypass all handled by Firecrawl
    doc = app.scrape(
        url,
        formats=formats,
        only_main_content=only_main_content,
    )

    if not doc:
        raise RuntimeError(f"Scrape returned empty result for {url}")

    # Normalise the Document object / dict into a plain dict
    def _get(key: str, default=None):
        """Fetch attribute from a Document object or a plain dict."""
        if hasattr(doc, key):
            return getattr(doc, key)
        if isinstance(doc, dict):
            return doc.get(key, default)
        return default

    markdown  = _get("markdown") or ""
    html      = _get("html") or ""
    links     = _get("links") or []
    raw_meta  = _get("metadata") or {}

    # Metadata may be a Pydantic model; serialise it to a plain dict
    if hasattr(raw_meta, "model_dump"):
        metadata = {k: v for k, v in raw_meta.model_dump().items() if v is not None}
    elif isinstance(raw_meta, dict):
        metadata = raw_meta
    else:
        metadata = {}

    result = {
        "url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "markdown": markdown,
        "html": html,
        "links": links,
        "metadata": metadata,
    }

    # -----------------------------------------------------------------------
    # Persist to disk
    # -----------------------------------------------------------------------
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Build a filesystem-safe slug from the URL
    slug = (
        url.removeprefix("https://")
           .removeprefix("http://")
           .rstrip("/")
           .replace("/", "_")
           .replace("?", "_")
           [:60]  # cap length
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Save Markdown
    md_path = Path(output_dir) / f"{slug}_{ts}.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"[firecrawl] Markdown saved : {md_path}")

    # Save HTML (optional)
    if include_html and html:
        html_path = Path(output_dir) / f"{slug}_{ts}.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"[firecrawl] HTML saved     : {html_path}")

    # Save metadata + links JSON sidecar
    sidecar = {
        "url": url,
        "scraped_at": result["scraped_at"],
        "metadata": metadata,
        "links": links[:20],  # top-20 to keep the file tidy
    }
    meta_path = Path(output_dir) / f"{slug}_{ts}_meta.json"
    meta_path.write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")
    print(f"[firecrawl] Metadata saved : {meta_path}")

    return result


# ---------------------------------------------------------------------------
# Console summary helper
# ---------------------------------------------------------------------------

def print_summary(result: dict) -> None:
    """Print a human-readable scrape summary to stdout."""
    md       = result.get("markdown", "")
    links    = result.get("links", [])
    metadata = result.get("metadata", {})

    word_count = len(md.split())

    print()
    print("=" * 60)
    print("SCRAPE SUMMARY")
    print("=" * 60)
    print(f"URL          : {result['url']}")
    print(f"Scraped at   : {result['scraped_at']}")
    print(f"Title        : {metadata.get('title', '(none)')}")
    desc = str(metadata.get("description", "(none)"))
    print(f"Description  : {desc[:100]}{'...' if len(desc) > 100 else ''}")
    print(f"Markdown len : {len(md):,} chars  (~{word_count:,} words)")
    print(f"Links found  : {len(links)}")

    print()
    print("--- Markdown preview (first 600 chars) ---")
    preview = md[:600]
    print(preview)
    if len(md) > 600:
        print(f"\n... [{len(md) - 600:,} more characters]")

    if links:
        print()
        print("--- Top 10 links ---")
        for link in links[:10]:
            print(f"  {link}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape a URL to Markdown using the Firecrawl SDK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="https://news.ycombinator.com",
        help="URL to scrape (default: https://news.ycombinator.com)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Also save raw HTML alongside Markdown",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Disable main-content stripping (include nav/footer/ads)",
    )
    parser.add_argument(
        "--output-dir",
        default="output/scrape",
        help="Directory to save output files (default: output/scrape)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    try:
        result = scrape_url(
            url=args.url,
            only_main_content=not args.full_page,
            include_html=args.html,
            include_links=True,
            output_dir=args.output_dir,
        )
        print_summary(result)

    except EnvironmentError as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"\n[ERROR] Scrape failed: {exc}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n[INFO] Scrape cancelled by user.")
        sys.exit(0)
