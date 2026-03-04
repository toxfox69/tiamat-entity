"""
Firecrawl Python SDK — Example 2: Batch Scraper
================================================

Submits multiple URLs to Firecrawl's batch-scrape endpoint in a single API
call. Firecrawl processes them concurrently server-side, then this script
polls until the job completes and saves every result to disk.

Use this instead of looping over ``basic_web_scraper.py`` when you need to
process 5+ URLs — it is faster, cheaper (fewer round-trips), and handles
partial failures gracefully without stopping the whole batch.

Requirements:
    pip install firecrawl-py

Setup:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    # Get a free key at https://www.firecrawl.dev/app/api-keys

Usage:
    # Run with the built-in demo URLs:
    python batch_scraper.py

    # Pass your own space-separated URLs:
    python batch_scraper.py https://example.com https://python.org https://github.com

    # Save results to a custom directory:
    python batch_scraper.py --output-dir ./results

Output:
    Saved files under ./output/batch/<job_id>/:
        <slug>.md            — Markdown content for each URL
        <slug>_meta.json     — Metadata + links for each URL
        _summary.json        — Batch-level statistics
    Console table: per-URL status, markdown size, elapsed time.

Example output:
    [firecrawl] Submitting batch of 5 URLs...
    [firecrawl] Job ID: batch_abc123  (poll every 3s)
    [firecrawl] Status: scraping  [2/5 complete]
    [firecrawl] Status: scraping  [4/5 complete]
    [firecrawl] Status: completed [5/5 complete] — 8.4s elapsed

    ============================================================
    BATCH RESULTS  (job batch_abc123)
    ============================================================
     #  URL                                      Words    Status
    ----  ---------------------------------------- -------  --------
      1   https://news.ycombinator.com             1,412    OK
      2   https://python.org                         843    OK
      3   https://github.com/trending              2,105    OK
      4   https://docs.firecrawl.dev                 997    OK
      5   https://invalid.example.invalid             —     FAILED
    ============================================================
    Completed: 4 / 5   Failed: 1   Credits used: 4
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from firecrawl import FirecrawlApp

# ---------------------------------------------------------------------------
# Default demo URLs — a diverse mix that exercises real-world scraping
# ---------------------------------------------------------------------------

DEFAULT_URLS = [
    "https://news.ycombinator.com",        # Aggregator — lots of links
    "https://www.python.org",              # Docs site
    "https://github.com/trending",         # JS-heavy SPA
    "https://docs.firecrawl.dev",          # API docs
    "https://en.wikipedia.org/wiki/Web_scraping",  # Long article
]


# ---------------------------------------------------------------------------
# Core batch-scrape function
# ---------------------------------------------------------------------------

def batch_scrape(
    urls: list[str],
    *,
    only_main_content: bool = True,
    poll_interval: int = 3,
    timeout: int = 300,
    output_dir: str = "output/batch",
) -> dict:
    """
    Submit a list of URLs for concurrent scraping and wait for completion.

    Firecrawl's batch endpoint processes all URLs in parallel server-side.
    This function submits the job, polls for status, and saves every
    completed document to disk. Partial failures are captured per-URL so
    one bad URL never kills the whole batch.

    Args:
        urls:              List of URLs to scrape. Up to 1,000 per batch.
        only_main_content: Strip nav/footer/ads from each page.
        poll_interval:     Seconds between status-check polls (default: 3).
        timeout:           Max seconds to wait for job completion (default: 300).
        output_dir:        Base directory for output files.

    Returns:
        dict with keys:
            ``job_id``       — Firecrawl batch job ID
            ``status``       — Final job status (``completed`` / ``failed``)
            ``completed``    — Number of URLs successfully scraped
            ``total``        — Total URLs submitted
            ``credits_used`` — Credits consumed by this batch
            ``results``      — list of per-URL result dicts
            ``errors``       — list of per-URL error dicts

    Raises:
        EnvironmentError: FIRECRAWL_API_KEY not set.
        TimeoutError:     Job did not finish within *timeout* seconds.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FIRECRAWL_API_KEY is not set.\n"
            "Export it: export FIRECRAWL_API_KEY='fc-your-key-here'\n"
            "Get a free key at https://www.firecrawl.dev/app/api-keys"
        )

    if not urls:
        raise ValueError("urls list must not be empty")

    app = FirecrawlApp(api_key=api_key)

    # -----------------------------------------------------------------------
    # 1. Submit the batch job
    # -----------------------------------------------------------------------
    print(f"[firecrawl] Submitting batch of {len(urls)} URL(s)...")

    batch_response = app.start_batch_scrape(
        urls,
        formats=["markdown", "links"],  # type: ignore[arg-type]
        only_main_content=only_main_content,
    )

    job_id: str = batch_response.id
    print(f"[firecrawl] Job ID : {job_id}  (polling every {poll_interval}s)")

    # -----------------------------------------------------------------------
    # 2. Poll until the job finishes or we time out
    # -----------------------------------------------------------------------
    start = time.monotonic()
    job = None

    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise TimeoutError(
                f"Batch job {job_id} did not complete within {timeout}s. "
                f"Call app.get_batch_scrape_status('{job_id}') to resume."
            )

        job = app.get_batch_scrape_status(job_id)
        completed = getattr(job, "completed", 0) or 0
        total     = getattr(job, "total", len(urls)) or len(urls)
        status    = getattr(job, "status", "unknown") or "unknown"

        print(
            f"[firecrawl] Status: {status:<12} "
            f"[{completed}/{total} complete]  "
            f"({elapsed:.1f}s elapsed)"
        )

        if status in ("completed", "failed", "cancelled"):
            break

        time.sleep(poll_interval)

    elapsed_total = time.monotonic() - start
    print(f"[firecrawl] Finished in {elapsed_total:.1f}s")

    # -----------------------------------------------------------------------
    # 3. Collect results and save to disk
    # -----------------------------------------------------------------------
    documents = getattr(job, "data", []) or []
    credits   = getattr(job, "credits_used", None)
    job_status = getattr(job, "status", "unknown")

    job_dir = Path(output_dir) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    results = []
    errors  = []

    for doc in documents:
        # Each doc is a firecrawl Document object
        doc_url    = _attr(doc, "url") or _attr(doc, "metadata", {})
        if isinstance(doc_url, dict):
            doc_url = doc_url.get("url", "unknown")

        # Prefer the URL from metadata if the top-level url is missing
        meta_raw = _attr(doc, "metadata") or {}
        if hasattr(meta_raw, "model_dump"):
            metadata = {k: v for k, v in meta_raw.model_dump().items() if v is not None}
        elif isinstance(meta_raw, dict):
            metadata = meta_raw
        else:
            metadata = {}

        source_url = metadata.get("source_url") or metadata.get("url") or str(doc_url)
        error_msg  = metadata.get("error")

        if error_msg:
            # Firecrawl returns a Document even for failed URLs, with an error in metadata
            errors.append({"url": source_url, "error": error_msg})
            continue

        markdown = _attr(doc, "markdown") or ""
        links    = _attr(doc, "links") or []

        # Save Markdown
        slug = _slugify(source_url)
        md_path = job_dir / f"{slug}.md"
        md_path.write_text(markdown, encoding="utf-8")

        # Save metadata sidecar
        sidecar = {"url": source_url, "metadata": metadata, "links": links[:20]}
        meta_path = job_dir / f"{slug}_meta.json"
        meta_path.write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")

        results.append({
            "url":       source_url,
            "words":     len(markdown.split()),
            "chars":     len(markdown),
            "links":     len(links),
            "md_path":   str(md_path),
            "meta_path": str(meta_path),
        })

    # Batch summary JSON
    summary = {
        "job_id":      job_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s":   round(elapsed_total, 2),
        "status":      job_status,
        "completed":   len(results),
        "failed":      len(errors),
        "total":       len(urls),
        "credits_used": credits,
        "results":     results,
        "errors":      errors,
    }
    summary_path = job_dir / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"[firecrawl] Results saved to: {job_dir}/")

    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attr(obj, name: str, default=None):
    """Get attribute from a Pydantic model or dict, with a fallback default."""
    if hasattr(obj, name):
        val = getattr(obj, name)
        return val if val is not None else default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _slugify(url: str, max_len: int = 60) -> str:
    """Convert a URL to a filesystem-safe slug."""
    return (
        url.removeprefix("https://")
           .removeprefix("http://")
           .rstrip("/")
           .replace("/", "_")
           .replace("?", "_")
           .replace("&", "_")
           [:max_len]
    )


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def print_summary(summary: dict) -> None:
    """Print a formatted table of batch results."""
    job_id    = summary["job_id"]
    results   = summary["results"]
    errors    = summary["errors"]
    completed = summary["completed"]
    total     = summary["total"]
    credits   = summary["credits_used"]
    elapsed   = summary["elapsed_s"]

    col_url   = 42
    col_words = 8

    print()
    print("=" * 62)
    print(f"BATCH RESULTS  (job {job_id})")
    print("=" * 62)
    header = f"  #  {'URL':<{col_url}} {'Words':>{col_words}}  Status"
    print(header)
    print("-" * 62)

    idx = 1
    for r in results:
        url_display = r["url"][:col_url]
        words = f"{r['words']:,}"
        print(f"{idx:>3}  {url_display:<{col_url}} {words:>{col_words}}  OK")
        idx += 1

    for e in errors:
        url_display = e["url"][:col_url]
        err_short   = e["error"][:30]
        print(f"{idx:>3}  {url_display:<{col_url}} {'—':>{col_words}}  FAILED  ({err_short})")
        idx += 1

    print("=" * 62)
    print(
        f"Completed: {completed} / {total}   "
        f"Failed: {len(errors)}   "
        f"Credits used: {credits}   "
        f"Elapsed: {elapsed}s"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-scrape multiple URLs concurrently using the Firecrawl SDK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="URLs to scrape (space-separated). Defaults to built-in demo URLs.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/batch",
        help="Base directory for output files (default: output/batch)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=3,
        help="Seconds between status polls (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Max seconds to wait for job completion (default: 300)",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Disable main-content stripping (include nav/footer/ads)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    urls = args.urls if args.urls else DEFAULT_URLS

    try:
        summary = batch_scrape(
            urls,
            only_main_content=not args.full_page,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            output_dir=args.output_dir,
        )
        print_summary(summary)

    except TimeoutError as exc:
        # TimeoutError is a subclass of OSError — must come before EnvironmentError
        print(f"\n[TIMEOUT] {exc}", file=sys.stderr)
        sys.exit(2)
    except EnvironmentError as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Cancelled by user.")
        sys.exit(0)
