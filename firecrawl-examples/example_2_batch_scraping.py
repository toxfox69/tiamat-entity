"""
Firecrawl Python SDK — Example: Async Batch Scraper with CSV Export
====================================================================

Scrapes multiple URLs concurrently using asyncio + ThreadPoolExecutor,
then writes every result (including failures) to a CSV file.

Concurrency model: the sync FirecrawlApp runs in a thread pool so the
main event loop stays free. Increase MAX_WORKERS for larger batches —
Firecrawl's servers handle the heavy lifting server-side.

Requirements:
    pip install firecrawl-py

Setup:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    # Free key: https://firecrawl.dev/app/api-keys

Usage:
    python example_2_batch_scraping.py
    python example_2_batch_scraping.py https://url1.com https://url2.com
    python example_2_batch_scraping.py --output my_results.csv

Output:
    scrape_results.csv  — one row per URL: title, word_count, status, …
    Summary table printed to stdout.

Example output:
    Scraping 5 URLs (5 concurrent workers)...
    [1/5] OK    https://news.ycombinator.com  (1,412 words)
    [2/5] OK    https://www.python.org        (843 words)
    [3/5] OK    https://github.com/trending   (2,105 words)
    [4/5] OK    https://docs.firecrawl.dev    (997 words)
    [5/5] ERROR https://invalid.example.test  (connection refused)
    ================================================================
    Done: 4/5 succeeded | 1 failed | CSV: scrape_results.csv
"""

import asyncio
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from firecrawl import FirecrawlApp

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_WORKERS = 5          # concurrent threads (tune to your rate limit)
DEFAULT_OUTPUT = "scrape_results.csv"
CSV_FIELDS = ["url", "title", "word_count", "char_count", "scraped_at", "status", "error"]

DEFAULT_URLS = [
    "https://news.ycombinator.com",
    "https://www.python.org",
    "https://github.com/trending",
    "https://docs.firecrawl.dev",
    "https://en.wikipedia.org/wiki/Web_scraping",
]


# ---------------------------------------------------------------------------
# Per-URL scrape (runs in a worker thread)
# ---------------------------------------------------------------------------

def _scrape_one(app: FirecrawlApp, url: str, index: int, total: int) -> dict:
    """Scrape a single URL synchronously (called from the thread pool)."""
    try:
        doc = app.scrape(url, formats=["markdown"], only_main_content=True)
        if not doc:
            raise RuntimeError("empty response")

        # Normalise Document object / plain dict (handles all SDK versions)
        def _get(key: str):
            if hasattr(doc, key):
                return getattr(doc, key)
            return doc.get(key) if isinstance(doc, dict) else None

        md = _get("markdown") or ""
        if not md:
            raise RuntimeError("no markdown in response")

        raw_meta = _get("metadata") or {}
        meta = (
            raw_meta.model_dump()
            if hasattr(raw_meta, "model_dump")
            else (raw_meta if isinstance(raw_meta, dict) else {})
        )

        result = {
            "url": url,
            "title": meta.get("title", ""),
            "word_count": len(md.split()),
            "char_count": len(md),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "error": "",
        }
        print(f"[{index}/{total}] OK    {url}  ({result['word_count']:,} words)")
        return result

    except Exception as exc:
        err = str(exc)[:200]
        print(f"[{index}/{total}] ERROR {url}  ({err[:60]})")
        return {
            "url": url,
            "title": "",
            "word_count": 0,
            "char_count": 0,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error": err,
        }


# ---------------------------------------------------------------------------
# Async orchestrator
# ---------------------------------------------------------------------------

async def batch_scrape(
    urls: list[str],
    output_csv: str = DEFAULT_OUTPUT,
    max_workers: int = MAX_WORKERS,
) -> list[dict]:
    """Scrape URLs concurrently and save results to CSV.

    Args:
        urls:        List of URLs to scrape. No hard upper limit.
        output_csv:  Path for the output CSV file.
        max_workers: Number of concurrent scraper threads.

    Returns:
        List of result dicts, one per URL (successes and failures).

    Raises:
        EnvironmentError: FIRECRAWL_API_KEY is not set.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FIRECRAWL_API_KEY is not set.\n"
            "  export FIRECRAWL_API_KEY='fc-your-key-here'\n"
            "  Free key: https://firecrawl.dev/app/api-keys"
        )

    app = FirecrawlApp(api_key=api_key)
    total = len(urls)
    print(f"Scraping {total} URLs ({min(max_workers, total)} concurrent workers)...")

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        tasks = [
            loop.run_in_executor(pool, _scrape_one, app, url, i + 1, total)
            for i, url in enumerate(urls)
        ]
        results = await asyncio.gather(*tasks)

    # Write CSV (including failed rows so nothing is silently lost)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    return list(results)


# ---------------------------------------------------------------------------
# Summary table + CLI
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], output_csv: str) -> None:
    ok     = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "error"]

    print()
    print("=" * 68)
    print(f"  {'URL':<46} {'Words':>6}  Status")
    print("─" * 68)
    for r in results:
        words  = f"{r['word_count']:,}" if r["status"] == "ok" else "—"
        status = "OK" if r["status"] == "ok" else f"ERROR: {r['error'][:20]}"
        print(f"  {r['url'][:46]:<46} {words:>6}  {status}")
    print("=" * 68)
    print(f"  Done: {len(ok)}/{len(results)} succeeded  |  {len(failed)} failed  |  CSV: {output_csv}")


def _parse_args():
    """Minimal arg parsing without argparse dependency."""
    urls = []
    output = DEFAULT_OUTPUT
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--output", "-o") and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        elif args[i].startswith(("http://", "https://")):
            urls.append(args[i])
            i += 1
        else:
            i += 1
    return urls or DEFAULT_URLS, output


async def main() -> None:
    urls, output_csv = _parse_args()
    try:
        results = await batch_scrape(urls, output_csv=output_csv)
        print_summary(results, output_csv)
    except EnvironmentError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
