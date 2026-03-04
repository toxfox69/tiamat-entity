"""
Firecrawl Python SDK — Example 3: Site Crawler & Markdown Exporter
===================================================================

Demonstrates crawling an entire website (or subtree) and converting every
page to clean markdown. Outputs a local mirror suitable for:
  • Building a RAG knowledge base
  • LLM fine-tuning datasets
  • Offline documentation archives
  • Site-wide content analysis

Supports async polling, progress bars, URL filtering, and per-page saving.

Requirements:
    pip install firecrawl-py tqdm

Usage:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    python example_03_site_crawler.py

    # Custom target:
    python example_03_site_crawler.py https://docs.example.com --max-pages 50

    # Save to specific directory:
    python example_03_site_crawler.py https://example.com --output ./my-crawl
"""

import os
import json
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone  # noqa: F401
from urllib.parse import urlparse

from firecrawl import FirecrawlApp  # type: ignore[import-untyped]

def _progress(iterable, **kw):  # noqa: ANN001, ANN202
    """Wrap iterable with tqdm if available, else pass through."""
    try:
        from tqdm import tqdm  # type: ignore[import-untyped]
        return tqdm(iterable, **kw)
    except ImportError:
        return iterable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def url_to_filename(url: str) -> str:
    """Convert a URL into a safe filesystem filename."""
    parsed = urlparse(url)
    # Use path segments, replacing slashes with double-underscore
    path = parsed.path.strip("/").replace("/", "__") or "index"
    # Strip query string from filename, keep it readable
    name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", path)
    return name[:120] + ".md"


def save_page(page: dict, output_dir: Path) -> Path:
    """Write a single crawled page to disk as a markdown file with YAML frontmatter."""
    url = page.get("url", "unknown")
    markdown = page.get("markdown", "")
    metadata = page.get("metadata", {})

    frontmatter = "---\n"
    frontmatter += f'url: "{url}"\n'
    frontmatter += f'title: "{metadata.get("title", "").replace(chr(34), chr(39))}"\n'
    frontmatter += f'description: "{metadata.get("description", "").replace(chr(34), chr(39))[:200]}"\n'
    frontmatter += f'crawled_at: "{datetime.now(timezone.utc).isoformat()}"\n'
    if metadata.get("language"):
        frontmatter += f'language: "{metadata["language"]}"\n'
    frontmatter += "---\n\n"

    content = frontmatter + markdown
    filename = url_to_filename(url)
    filepath = output_dir / filename
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Core crawl function
# ---------------------------------------------------------------------------

def crawl_site_to_markdown(
    start_url: str,
    output_dir: str = "output/crawl",
    max_pages: int = 25,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    poll_interval: int = 5,
) -> dict:
    """
    Crawl a website starting at start_url and save every page as markdown.

    Firecrawl handles JS rendering, bot protection, and robots.txt respect
    automatically. The crawl runs asynchronously on Firecrawl's servers;
    this function polls for completion and streams results as they arrive.

    Args:
        start_url:      Root URL to begin crawling.
        output_dir:     Local directory to write .md files into.
        max_pages:      Hard cap on total pages to crawl (default 25).
        include_paths:  Glob patterns — only crawl matching paths.
                        Example: ['/docs/*', '/blog/*']
        exclude_paths:  Glob patterns — skip matching paths.
                        Example: ['/tag/*', '/page/*']
        poll_interval:  Seconds between status checks (default 5).

    Returns:
        Summary dict with counts, output directory, and per-page stats.

    Raises:
        ValueError: API key missing or crawl startup failed.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError(
            "FIRECRAWL_API_KEY environment variable not set.\n"
            "Get a free key at https://firecrawl.dev"
        )

    app = FirecrawlApp(api_key=api_key)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Build crawl options
    crawl_params: dict = {
        "limit": max_pages,
        "scrapeOptions": {
            "formats": ["markdown"],
            "onlyMainContent": True,
        },
    }
    if include_paths:
        crawl_params["includePaths"] = include_paths
    if exclude_paths:
        crawl_params["excludePaths"] = exclude_paths

    print(f"[firecrawl] Starting crawl: {start_url}")
    print(f"[firecrawl] Max pages:      {max_pages}")
    print(f"[firecrawl] Output dir:     {out_path.resolve()}")
    if include_paths:
        print(f"[firecrawl] Include paths:  {include_paths}")
    if exclude_paths:
        print(f"[firecrawl] Exclude paths:  {exclude_paths}")

    # Kick off the async crawl job
    crawl_result = app.crawl_url(  # type: ignore[union-attr]
        start_url,
        params=crawl_params,
        wait_until_done=True,   # block until complete (simple mode)
        poll_interval=poll_interval,
    )

    # crawl_url(wait_until_done=True) returns the final result directly
    pages = []
    if isinstance(crawl_result, dict):
        pages = crawl_result.get("data", [])
    elif hasattr(crawl_result, "__iter__"):
        pages = list(crawl_result)

    total = len(pages)
    print(f"[firecrawl] Crawl complete. Pages collected: {total}")

    saved = []
    failed = []

    iter_pages = _progress(pages, desc="Saving pages", unit="page")

    for page in iter_pages:
        if not isinstance(page, dict):
            continue
        url = page.get("url", "")
        try:
            filepath = save_page(page, out_path)
            md_len = len(page.get("markdown", ""))
            saved.append({"url": url, "file": str(filepath), "chars": md_len})
        except Exception as exc:
            failed.append({"url": url, "error": str(exc)})

    # Write crawl index JSON
    index = {
        "start_url": start_url,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "max_pages": max_pages,
        "total_found": total,
        "total_saved": len(saved),
        "total_failed": len(failed),
        "output_dir": str(out_path.resolve()),
        "pages": saved,
        "errors": failed,
    }
    index_path = out_path / "_crawl_index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"[firecrawl] Index saved:    {index_path}")

    return index


def print_crawl_summary(result: dict) -> None:
    """Print a human-readable crawl summary."""
    saved = result["total_saved"]
    failed = result["total_failed"]
    total_chars = sum(p.get("chars", 0) for p in result.get("pages", []))

    print("\n" + "=" * 60)
    print("CRAWL SUMMARY")
    print("=" * 60)
    print(f"Start URL:    {result['start_url']}")
    print(f"Crawled at:   {result['crawled_at']}")
    print(f"Pages saved:  {saved} / {result['total_found']}")
    print(f"Errors:       {failed}")
    print(f"Total content:{total_chars:,} characters")
    print(f"Output dir:   {result['output_dir']}")

    if result.get("pages"):
        print("\n--- Saved pages ---")
        for page in result["pages"][:15]:
            print(f"  [{page['chars']:>6,} chars] {page['url']}")
        if saved > 15:
            print(f"  ... and {saved - 15} more (see _crawl_index.json)")

    if result.get("errors"):
        print("\n--- Errors ---")
        for err in result["errors"]:
            print(f"  {err['url']}: {err['error']}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl a website and export all pages as markdown files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="https://firecrawl.dev",
        help="Root URL to crawl (default: https://firecrawl.dev)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=15,
        help="Maximum number of pages to crawl (default: 15)",
    )
    parser.add_argument(
        "--output",
        default="output/crawl",
        help="Output directory (default: output/crawl)",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        help="URL path patterns to include (e.g. /docs/* /blog/*)",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        help="URL path patterns to exclude (e.g. /tag/* /page/*)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    result = crawl_site_to_markdown(
        start_url=args.url,
        output_dir=args.output,
        max_pages=args.max_pages,
        include_paths=args.include,
        exclude_paths=args.exclude,
    )

    print_crawl_summary(result)
