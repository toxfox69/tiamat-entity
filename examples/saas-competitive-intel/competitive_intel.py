#!/usr/bin/env python3
"""
SaaS Competitive Intelligence Analyzer
=======================================
Crawls competitor websites using Firecrawl to extract pricing tiers, features,
and positioning data, then generates a structured comparison report.

Features demonstrated:
  - firecrawl.map()    → discover pricing/feature pages across a domain
  - firecrawl.scrape() → extract clean markdown content from each page
  - Multi-page crawl   → aggregate data across multiple pages per competitor
  - Structured output  → JSON, CSV, and Markdown comparison reports

Usage:
  python competitive_intel.py https://notion.so https://obsidian.md
  python competitive_intel.py https://linear.app https://github.com --output ./reports
"""

import os
import re
import json
import csv
import argparse
from datetime import datetime, timezone
from typing import Optional

from firecrawl import FirecrawlApp


# ─── Pricing Extraction Helpers ──────────────────────────────────────────────

# Regex patterns to find dollar amounts in scraped text
PRICE_RE = re.compile(
    r'\$\s*(\d{1,4}(?:\.\d{2})?)\s*(?:/\s*(?:mo(?:nth)?|yr|year|user|seat|month))?',
    re.IGNORECASE,
)

# Keywords that signal a pricing tier heading
TIER_HEADING_RE = re.compile(
    r'^#{1,4}\s*(free|starter|basic|lite|pro|professional|business|team|'
    r'growth|scale|plus|premium|advanced|enterprise|ultimate|unlimited)\s*$',
    re.IGNORECASE,
)

# Words adjacent to a price that indicate it's a tier header line
TIER_INLINE_RE = re.compile(
    r'\*{1,2}(free|starter|basic|lite|pro|professional|business|team|'
    r'growth|scale|plus|premium|advanced|enterprise|ultimate|unlimited)\*{1,2}',
    re.IGNORECASE,
)


def extract_price_mentions(text: str) -> list[str]:
    """Return unique dollar amounts found in the text."""
    matches = PRICE_RE.findall(text)
    # Deduplicate, keeping order
    seen: set[str] = set()
    result = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result[:10]


def extract_pricing_tiers(text: str) -> list[dict]:
    """
    Walk through markdown line-by-line and heuristically identify pricing tiers.
    Returns a list of dicts: {name, price, features}.
    """
    tiers: list[dict] = []
    current: Optional[dict] = None

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # --- Check for a tier heading (## Pro, **Enterprise**, etc.) ---
        heading_match = TIER_HEADING_RE.match(line)
        inline_match = TIER_INLINE_RE.search(line)

        if heading_match or inline_match:
            # Save previous tier
            if current:
                tiers.append(current)

            matched = heading_match or inline_match
            tier_name = matched.group(1).title() if matched else "Unknown"

            # Try to find a price on the same line
            price_match = PRICE_RE.search(line)
            price = f"${price_match.group(1)}" if price_match else None

            current = {"name": tier_name, "price": price, "features": []}

        elif current is not None:
            # Collect bullet points as features
            if re.match(r'^[-*✓✔•]\s+', line):
                feature = re.sub(r'^[-*✓✔•]\s+', "", line)
                if 4 < len(feature) < 120:
                    current["features"].append(feature)

            # Capture price if we haven't found one yet
            if current["price"] is None:
                price_match = PRICE_RE.search(line)
                if price_match:
                    current["price"] = f"${price_match.group(1)}"

    if current:
        tiers.append(current)

    # Trim feature lists
    for tier in tiers:
        tier["features"] = tier["features"][:6]

    return tiers


# ─── Firecrawl Wrappers ───────────────────────────────────────────────────────

def discover_pricing_pages(app: FirecrawlApp, base_url: str, limit: int = 25) -> list[str]:
    """
    Use Firecrawl's map() to discover URLs that likely contain pricing/plan info.
    Falls back to just the base URL if map fails.
    """
    print(f"  [map]    Discovering pages on {base_url}")
    try:
        result = app.map(base_url, search="pricing plans features", limit=limit)
        # SDK returns MapData with a .links attribute (list of str)
        # MapData has a .links attribute; fall back to dict-style access for older SDK versions
        raw_links = getattr(result, "links", None)
        if raw_links is None and isinstance(result, dict):
            raw_links = result.get("links", [])
        links: list[str] = raw_links or []

        pricing_keywords = ("pric", "plan", "feature", "tier", "cost", "subscri", "billing")
        relevant = [u for u in links if any(kw in u.lower() for kw in pricing_keywords)]

        # Always include the homepage
        if base_url not in relevant:
            relevant.insert(0, base_url)

        print(f"  [map]    Found {len(relevant)} pricing-relevant pages (capped at 5)")
        return relevant[:5]

    except Exception as exc:
        print(f"  [map]    Failed ({exc}), falling back to base URL")
        return [base_url]


def scrape_page(app: FirecrawlApp, url: str) -> str:
    """
    Use Firecrawl's scrape() to fetch a page as clean markdown.
    Returns an empty string on failure.
    """
    try:
        result = app.scrape(
            url,
            formats=["markdown"],
            only_main_content=True,
            timeout=30_000,  # 30 seconds in ms
        )
        raw_md = getattr(result, "markdown", None)
        if raw_md is None and isinstance(result, dict):
            raw_md = result.get("markdown", "")
        markdown: str = raw_md or ""
        print(f"  [scrape] {url}  ({len(markdown):,} chars)")
        return markdown
    except Exception as exc:
        print(f"  [scrape] Failed on {url}: {exc}")
        return ""


# ─── Analysis Pipeline ────────────────────────────────────────────────────────

def analyze_competitor(app: FirecrawlApp, url: str) -> dict:
    """
    Full pipeline for a single competitor:
      1. map()    → find pricing/feature pages
      2. scrape() → fetch each page as markdown
      3. Parse    → extract pricing tiers, prices, free-tier flags
    """
    print(f"\n── Analyzing: {url}")

    # Step 1: Discover relevant sub-pages
    pages = discover_pricing_pages(app, url)

    # Step 2: Scrape all discovered pages
    scraped: list[dict] = []
    for page_url in pages:
        content = scrape_page(app, page_url)
        if content:
            scraped.append({"url": page_url, "content": content})

    if not scraped:
        return {
            "url": url,
            "error": "No content could be scraped",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    # Step 3: Combine and analyse
    combined = "\n\n".join(s["content"] for s in scraped)
    first_page = scraped[0]["content"]

    # Extract company name from domain
    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    company_name = domain.split(".")[0].title()

    # Tagline: first non-trivial line on the homepage
    tagline = next(
        (
            line.strip().lstrip("#").strip()
            for line in first_page.split("\n")
            if 12 < len(line.strip()) < 160 and not line.strip().startswith("http")
        ),
        None,
    )

    pricing_tiers = extract_pricing_tiers(combined)
    price_mentions = extract_price_mentions(combined)
    has_free_trial = bool(re.search(r"free\s*trial|try\s*(it\s*)?free", combined[:5000], re.I))
    has_free_tier = bool(re.search(r"\bfree\s*(forever|plan|tier|always)?\b", combined[:5000], re.I))

    return {
        "url": url,
        "company_name": company_name,
        "tagline": tagline,
        "has_free_trial": has_free_trial,
        "has_free_tier": has_free_tier,
        "price_mentions": price_mentions,
        "pricing_tiers": pricing_tiers,
        "pages_analyzed": len(scraped),
        "pages": [s["url"] for s in scraped],
        "word_count": len(combined.split()),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Report Generation ────────────────────────────────────────────────────────

def build_markdown_report(analyses: list[dict]) -> str:
    """Render a human-readable Markdown comparison report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SaaS Competitive Intelligence Report",
        "",
        f"_Generated by [firecrawl-competitive-intel](https://github.com/mendableai/firecrawl) on {now}_",
        "",
        f"**Competitors analyzed:** {len(analyses)}",
        "",
        "---",
        "",
        "## Quick Comparison",
        "",
        "| Company | Free Trial | Free Tier | Price Range | Tiers |",
        "|---------|:----------:|:---------:|-------------|:-----:|",
    ]

    for a in analyses:
        if "error" in a:
            lines.append(f"| {a['url']} | — | — | _scrape failed_ | — |")
            continue
        co = a["company_name"]
        trial = "✓" if a["has_free_trial"] else "✗"
        free = "✓" if a["has_free_tier"] else "✗"
        prices = (
            "$" + " · $".join(a["price_mentions"][:4]) if a["price_mentions"] else "N/A"
        )
        n_tiers = len(a["pricing_tiers"])
        lines.append(f"| **{co}** | {trial} | {free} | {prices} | {n_tiers} |")

    lines += ["", "---", ""]

    for a in analyses:
        if "error" in a:
            continue
        co = a["company_name"]
        lines += [
            f"## {co}",
            "",
            f"**URL:** {a['url']}  ",
            f"**Tagline:** _{a.get('tagline', 'N/A')}_  ",
            f"**Free trial:** {'Yes' if a['has_free_trial'] else 'No'}  ",
            f"**Permanent free tier:** {'Yes' if a['has_free_tier'] else 'No'}  ",
            f"**Pages analyzed:** {a['pages_analyzed']}  ",
            "",
        ]

        if a["pricing_tiers"]:
            lines.append("### Pricing Tiers\n")
            for tier in a["pricing_tiers"]:
                price_str = f" — {tier['price']}" if tier["price"] else ""
                lines.append(f"#### {tier['name']}{price_str}\n")
                for feat in tier["features"]:
                    lines.append(f"- {feat}")
                lines.append("")

        if a["price_mentions"]:
            prices_fmt = ", ".join(f"${p}" for p in a["price_mentions"][:8])
            lines.append(f"_Price points found: {prices_fmt}_\n")

        lines += ["---", ""]

    return "\n".join(lines)


def save_outputs(analyses: list[dict], output_dir: str) -> None:
    """Save JSON data, CSV pricing table, and Markdown report."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Full JSON dump
    json_path = os.path.join(output_dir, f"analysis_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analyses, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved JSON:     {json_path}")

    # Markdown report
    md_path = os.path.join(output_dir, f"report_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_markdown_report(analyses))
    print(f"  Saved report:   {md_path}")

    # CSV pricing comparison
    rows = []
    for a in analyses:
        if "error" in a:
            continue
        base = {
            "company": a["company_name"],
            "url": a["url"],
            "free_trial": a["has_free_trial"],
            "free_tier": a["has_free_tier"],
            "price_mentions": "; ".join(f"${p}" for p in a["price_mentions"]),
            "pages_analyzed": a["pages_analyzed"],
            "scraped_at": a["scraped_at"],
        }
        tiers = a.get("pricing_tiers") or [{}]
        for tier in tiers:
            rows.append(
                {
                    **base,
                    "tier_name": tier.get("name", ""),
                    "tier_price": tier.get("price", ""),
                    "tier_features": "; ".join(tier.get("features", [])),
                }
            )

    if rows:
        csv_path = os.path.join(output_dir, f"pricing_{ts}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Saved CSV:      {csv_path}")


def print_summary(analyses: list[dict]) -> None:
    """Print a condensed summary to stdout."""
    print("\n" + "=" * 62)
    print("  COMPETITIVE INTELLIGENCE SUMMARY")
    print("=" * 62)

    for a in analyses:
        if "error" in a:
            print(f"\n  {a['url']}\n  └─ ERROR: {a['error']}")
            continue

        co = a["company_name"]
        print(f"\n  {co.upper()}  ({a['url']})")

        if a.get("tagline"):
            print(f"  │  Tagline:     {a['tagline'][:72]}")

        print(f"  │  Free trial:  {'Yes' if a['has_free_trial'] else 'No'}")
        print(f"  │  Free tier:   {'Yes' if a['has_free_tier'] else 'No'}")

        if a.get("price_mentions"):
            prices = "  ·  $".join(a["price_mentions"][:5])
            print(f"  │  Prices:      ${prices}")

        tiers = a.get("pricing_tiers", [])
        if tiers:
            print(f"  └─ Tiers ({len(tiers)}):")
            for tier in tiers:
                price_str = f"  {tier['price']}" if tier.get("price") else ""
                print(f"       [{tier['name']}{price_str}]")
                for feat in tier.get("features", [])[:2]:
                    print(f"         • {feat}")


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main() -> list[dict]:
    parser = argparse.ArgumentParser(
        description="SaaS Competitive Intelligence Analyzer — powered by Firecrawl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python competitive_intel.py https://notion.so https://obsidian.md https://craft.do
  python competitive_intel.py https://linear.app https://github.com --output ./reports
  python competitive_intel.py https://vercel.com --api-key fc-YOUR_KEY --no-save
        """,
    )
    parser.add_argument("urls", nargs="+", help="Competitor URLs to analyze")
    parser.add_argument(
        "--output",
        "-o",
        default="./output",
        help="Directory for report files (default: ./output)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FIRECRAWL_API_KEY"),
        help="Firecrawl API key (or set FIRECRAWL_API_KEY env var)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print summary only; skip writing output files",
    )
    args = parser.parse_args()

    if not args.api_key:
        parser.error(
            "Firecrawl API key required.\n"
            "  Set the FIRECRAWL_API_KEY environment variable, or pass --api-key fc-..."
        )

    app = FirecrawlApp(api_key=args.api_key)

    print("=" * 62)
    print("  SAAS COMPETITIVE INTELLIGENCE ANALYZER")
    print(f"  Powered by Firecrawl  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 62)
    print(f"  Analyzing {len(args.urls)} competitor(s)...\n")

    analyses: list[dict] = []
    for url in args.urls:
        try:
            result = analyze_competitor(app, url)
            analyses.append(result)
        except Exception as exc:
            print(f"  ERROR on {url}: {exc}")
            analyses.append(
                {
                    "url": url,
                    "error": str(exc),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    print_summary(analyses)

    if not args.no_save:
        save_outputs(analyses, args.output)

    print("\n  Done.\n")
    return analyses


if __name__ == "__main__":
    main()
