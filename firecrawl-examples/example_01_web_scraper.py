"""
Firecrawl Python SDK — Example 1: Web Scraper
==============================================

Demonstrates scraping a single URL to retrieve clean markdown and HTML output.
Useful for feeding web content into LLMs, RAG pipelines, or content archives.

Requirements:
    pip install firecrawl-py

Usage:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    python example_01_web_scraper.py

    # Or pass a custom URL:
    python example_01_web_scraper.py https://example.com
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone  # noqa: F401

from firecrawl import FirecrawlApp  # type: ignore[import-untyped]


def scrape_to_markdown(
    url: str,
    output_dir: str = "output",
    only_main_content: bool = True,
    include_html: bool = False,
) -> dict:
    """
    Scrape a URL and return its content as clean markdown.

    Args:
        url:               The URL to scrape.
        output_dir:        Directory to save output files.
        only_main_content: Strip nav, footer, ads — keeps just article body.
        include_html:      Also request raw HTML alongside markdown.

    Returns:
        dict with keys: 'markdown', 'html' (optional), 'metadata', 'links'

    Raises:
        ValueError: If the API key is missing or the scrape fails.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError(
            "FIRECRAWL_API_KEY environment variable not set.\n"
            "Get a free key at https://firecrawl.dev"
        )

    app = FirecrawlApp(api_key=api_key)

    # Build the formats list based on what we want back
    formats = ["markdown", "links"]
    if include_html:
        formats.append("html")

    print(f"[firecrawl] Scraping: {url}")
    print(f"[firecrawl] Options: only_main_content={only_main_content}, formats={formats}")

    result = app.scrape_url(
        url,
        params={
            "formats": formats,
            "onlyMainContent": only_main_content,
        },
    )

    # firecrawl-py returns a dict-like object; normalise it
    if not result:
        raise ValueError(f"Scrape returned empty result for {url}")

    output = {
        "url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat() + "Z",
        "markdown": result.get("markdown", ""),
        "links": result.get("links", []),
        "metadata": result.get("metadata", {}),
    }
    if include_html:
        output["html"] = result.get("html", "")

    # Persist to disk
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    slug = url.replace("https://", "").replace("http://", "").rstrip("/").replace("/", "_")[:60]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    md_path = Path(output_dir) / f"{slug}_{ts}.md"
    md_path.write_text(output["markdown"], encoding="utf-8")
    print(f"[firecrawl] Markdown saved: {md_path}")

    if include_html and output.get("html"):
        html_path = Path(output_dir) / f"{slug}_{ts}.html"
        html_path.write_text(output["html"], encoding="utf-8")
        print(f"[firecrawl] HTML saved:     {html_path}")

    meta_path = Path(output_dir) / f"{slug}_{ts}_meta.json"
    meta_path.write_text(
        json.dumps(
            {"url": url, "metadata": output["metadata"], "links": output["links"][:20]},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[firecrawl] Metadata saved: {meta_path}")

    return output


def print_summary(result: dict) -> None:
    """Print a human-readable summary of the scrape result."""
    md = result.get("markdown", "")
    links = result.get("links", [])
    meta = result.get("metadata", {})

    print("\n" + "=" * 60)
    print("SCRAPE SUMMARY")
    print("=" * 60)
    print(f"URL:          {result['url']}")
    print(f"Scraped at:   {result['scraped_at']}")
    print(f"Title:        {meta.get('title', '(none)')}")
    print(f"Description:  {meta.get('description', '(none)')[:100]}")
    print(f"Markdown len: {len(md):,} characters")
    print(f"Links found:  {len(links)}")
    print("\n--- Markdown preview (first 800 chars) ---")
    print(md[:800])
    if len(md) > 800:
        print(f"\n... [{len(md) - 800:,} more characters]")
    print("\n--- Top 10 links ---")
    for link in links[:10]:
        print(f"  {link}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com"

    result = scrape_to_markdown(
        url=target_url,
        output_dir="output/scrape",
        only_main_content=True,
        include_html=False,
    )

    print_summary(result)
