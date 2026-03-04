"""
Firecrawl Python SDK — Example 3: Structured Data Extraction
=============================================================

Extracts typed, structured JSON from web pages using Firecrawl's
AI-powered extraction endpoint.  You define exactly what fields you
want (as a JSON Schema dict or a Pydantic model) and Firecrawl's
backend reads the page, understands the content, and returns a clean
JSON object matching your schema — no selectors, no XPath, no brittle
scraper maintenance.

Real-world use cases demonstrated:
    • JobPosting   — extract job listings from any careers page
    • ProductInfo  — extract product details from any e-commerce page
    • ArticleMeta  — extract article metadata from any news/blog URL
    • CompanyInfo  — extract company facts from any "About" page

Requirements:
    pip install firecrawl-py pydantic

Setup:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    # Get a free key at https://www.firecrawl.dev/app/api-keys

Usage:
    # Run all four demo extractions:
    python structured_extraction.py

    # Extract from a custom URL (uses ArticleMeta schema by default):
    python structured_extraction.py https://example.com/blog/some-post

    # Choose a specific schema:
    python structured_extraction.py https://shop.example.com/product --schema product
    python structured_extraction.py https://careers.example.com/job/123  --schema job
    python structured_extraction.py https://example.com/about           --schema company

Output:
    Saved files under ./output/extract/:
        <SchemaName>_<slug>_<timestamp>.json — validated extraction result
    Console: formatted field-by-field display of extracted values.

Example output (ArticleMeta):
    [firecrawl] Extracting: https://en.wikipedia.org/wiki/Web_scraping
    [firecrawl] Schema    : ArticleMeta
    [firecrawl] Result saved: output/extract/ArticleMeta_en.wikipedia.org_...json

    ============================================================
    EXTRACTED: ArticleMeta
    ============================================================
      title         : Web scraping
      author        : Wikipedia contributors
      published_date: (none)
      topics        :
        • Computer science
        • Internet
        • Data collection
      summary       : Web scraping is the automated extraction of data from
                      websites. It is used in research, price monitoring,
                      and machine learning dataset construction.
      word_count    : 4218
      reading_time  : 17 min
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field
from firecrawl import FirecrawlApp


# ---------------------------------------------------------------------------
# Schema definitions — edit or add your own Pydantic models here
# ---------------------------------------------------------------------------

class JobPosting(BaseModel):
    """Structured data extracted from a job listing page."""

    title: str = Field(description="Job title / role name")
    company: str = Field(description="Company offering the position")
    location: str = Field(description="City, state/province, country, or 'Remote'")
    salary_range: Optional[str] = Field(
        None, description="Salary or compensation range with currency, if listed"
    )
    employment_type: Optional[str] = Field(
        None, description="Full-time, Part-time, Contract, Internship, etc."
    )
    experience_required: Optional[str] = Field(
        None, description="Years of experience or seniority level required"
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Required or preferred technical skills and technologies",
    )
    application_deadline: Optional[str] = Field(
        None, description="Application close date, if mentioned"
    )
    description_summary: str = Field(
        description="One-paragraph summary of the role and key responsibilities"
    )


class ProductInfo(BaseModel):
    """Structured data extracted from a product or e-commerce page."""

    name: str = Field(description="Full product name")
    brand: Optional[str] = Field(None, description="Brand or manufacturer name")
    price: Optional[str] = Field(
        None, description="Current listed price, including currency symbol"
    )
    original_price: Optional[str] = Field(
        None, description="Original pre-discount price, if a sale is active"
    )
    rating: Optional[float] = Field(
        None, description="Average customer rating on a 0–5 scale"
    )
    review_count: Optional[int] = Field(
        None, description="Total number of customer reviews"
    )
    availability: Optional[str] = Field(
        None, description="Stock status: In stock / Out of stock / Ships in X days"
    )
    key_features: list[str] = Field(
        default_factory=list,
        description="Top product features or highlights (up to 6 bullet points)",
    )
    category: Optional[str] = Field(
        None, description="Product category or department"
    )
    sku: Optional[str] = Field(
        None, description="Product SKU, ASIN, or other identifier if visible"
    )


class ArticleMeta(BaseModel):
    """Structured metadata extracted from a news article or blog post."""

    title: str = Field(description="Article headline or title")
    author: Optional[str] = Field(None, description="Author name(s), comma-separated if multiple")
    publication: Optional[str] = Field(None, description="Publisher, site name, or outlet")
    published_date: Optional[str] = Field(
        None, description="Publication date (ISO 8601 preferred, or as written on page)"
    )
    topics: list[str] = Field(
        default_factory=list,
        description="Main topics, tags, or categories covered by the article",
    )
    summary: str = Field(
        description="2–3 sentence plain-language summary of the article's main argument"
    )
    word_count: Optional[int] = Field(
        None, description="Approximate word count of the article body"
    )
    reading_time: Optional[str] = Field(
        None, description="Estimated reading time (e.g. '5 min')"
    )


class CompanyInfo(BaseModel):
    """Structured data extracted from a company website or About page."""

    name: str = Field(description="Company legal or trading name")
    tagline: Optional[str] = Field(None, description="Company slogan or tagline")
    industry: Optional[str] = Field(None, description="Primary industry or sector")
    founded: Optional[str] = Field(None, description="Year or date the company was founded")
    headquarters: Optional[str] = Field(
        None, description="City and country of headquarters"
    )
    employee_count: Optional[str] = Field(
        None, description="Approximate headcount or range (e.g. '500–1,000')"
    )
    products_or_services: list[str] = Field(
        default_factory=list,
        description="Main products or services the company offers (up to 5)",
    )
    mission: Optional[str] = Field(
        None, description="Company mission statement or one-sentence description"
    )
    website: Optional[str] = Field(None, description="Primary website URL")


# Registry maps CLI names → schema classes
SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "job":     JobPosting,
    "product": ProductInfo,
    "article": ArticleMeta,
    "company": CompanyInfo,
}

# ---------------------------------------------------------------------------
# Demo targets — illustrate each schema with a stable public URL
# ---------------------------------------------------------------------------

DEMO_TARGETS = [
    {
        "url": "https://en.wikipedia.org/wiki/Web_scraping",
        "schema": ArticleMeta,
        "prompt": (
            "Extract structured article metadata: title, author(s), "
            "publication date, main topics, a 2-3 sentence summary, "
            "word count, and estimated reading time."
        ),
    },
    {
        "url": "https://www.anthropic.com/about",
        "schema": CompanyInfo,
        "prompt": (
            "Extract company information: name, tagline, industry, "
            "founding year, HQ location, employee count, main products "
            "or services, and mission statement."
        ),
    },
]


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_structured(
    url: str,
    schema: type[BaseModel],
    *,
    prompt: Optional[str] = None,
    system_prompt: Optional[str] = None,
    output_dir: str = "output/extract",
) -> dict[str, Any]:
    """
    Scrape *url* and extract structured data conforming to *schema*.

    Firecrawl fetches the page, converts it to Markdown, then passes it
    to an LLM along with the JSON Schema derived from *schema*.  The LLM
    fills every field it can find; Optional fields become ``null`` when
    absent.  The result is validated by Pydantic before being returned.

    Args:
        url:           Page to extract from.
        schema:        Pydantic ``BaseModel`` subclass defining the output shape.
        prompt:        Natural-language extraction hint for the LLM.
                       Defaults to ``"Extract <SchemaName> information from this page."``.
        system_prompt: Optional system-level instruction for the LLM extractor.
        output_dir:    Directory to save the JSON result file.

    Returns:
        Validated dict matching the *schema* field structure.

    Raises:
        EnvironmentError:       FIRECRAWL_API_KEY not set.
        RuntimeError:           Extraction returned no data.
        pydantic.ValidationError: Extracted data doesn't conform to schema.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "FIRECRAWL_API_KEY is not set.\n"
            "Export it: export FIRECRAWL_API_KEY='fc-your-key-here'\n"
            "Get a free key at https://www.firecrawl.dev/app/api-keys"
        )

    app = FirecrawlApp(api_key=api_key)
    schema_name = schema.__name__

    if prompt is None:
        prompt = f"Extract all {schema_name} information visible on this page."

    print(f"[firecrawl] Extracting : {url}")
    print(f"[firecrawl] Schema     : {schema_name}")
    print(f"[firecrawl] Prompt     : {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

    # Build extraction kwargs; system_prompt is optional
    extract_kwargs: dict[str, Any] = {
        "urls": [url],
        "prompt": prompt,
        "schema": schema.model_json_schema(),
    }
    if system_prompt:
        extract_kwargs["system_prompt"] = system_prompt

    # v2 extract — handles crawling, rendering, and AI-powered field extraction
    response = app.extract(**extract_kwargs)

    # The extract endpoint returns an ExtractResponse; .data holds the dict
    raw: Any = None
    if hasattr(response, "data"):
        raw = response.data
    elif isinstance(response, dict):
        raw = response.get("data") or response

    if not raw:
        raise RuntimeError(
            f"Extraction returned no data for {url}. "
            "The page may require authentication or block crawlers."
        )

    # If Firecrawl returns a list (multi-URL mode), take the first item
    if isinstance(raw, list):
        raw = raw[0] if raw else {}

    # Validate against the Pydantic schema — raises ValidationError on mismatch
    validated = schema.model_validate(raw)
    data: dict[str, Any] = validated.model_dump()

    # -----------------------------------------------------------------------
    # Persist to disk
    # -----------------------------------------------------------------------
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    slug = (
        url.removeprefix("https://")
           .removeprefix("http://")
           .rstrip("/")
           .replace("/", "_")
           .replace("?", "_")
           [:50]
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir) / f"{schema_name}_{slug}_{ts}.json"
    out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"[firecrawl] Result saved: {out_path}")

    return data


# ---------------------------------------------------------------------------
# Console output helper
# ---------------------------------------------------------------------------

def print_extraction(schema_name: str, data: dict[str, Any]) -> None:
    """Pretty-print extracted fields with list indentation."""
    print()
    print("=" * 60)
    print(f"EXTRACTED: {schema_name}")
    print("=" * 60)
    for key, value in data.items():
        label = f"  {key:<18}"
        if isinstance(value, list):
            if value:
                print(f"{label}:")
                for item in value:
                    print(f"    • {item}")
            else:
                print(f"{label}: (none)")
        elif isinstance(value, str) and len(value) > 80:
            # Wrap long strings
            print(f"{label}: {value[:80]}")
            remaining = value[80:]
            while remaining:
                print(f"  {'':18}  {remaining[:80]}")
                remaining = remaining[80:]
        else:
            print(f"{label}: {value if value is not None else '(none)'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract structured JSON from a web page using the Firecrawl SDK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL to extract from. Runs all demo targets if omitted.",
    )
    parser.add_argument(
        "--schema",
        choices=list(SCHEMA_REGISTRY.keys()),
        default="article",
        help="Schema to use when a custom URL is provided (default: article)",
    )
    parser.add_argument(
        "--prompt",
        help="Custom extraction prompt (overrides default for --schema)",
    )
    parser.add_argument(
        "--output-dir",
        default="output/extract",
        help="Directory to save JSON results (default: output/extract)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.url:
        # Single custom URL
        chosen_schema = SCHEMA_REGISTRY[args.schema]
        targets = [{"url": args.url, "schema": chosen_schema, "prompt": args.prompt}]
    else:
        targets = DEMO_TARGETS

    all_ok = True
    for target in targets:
        url        = target["url"]
        tgt_schema = target["schema"]
        tgt_prompt = target.get("prompt")

        try:
            data = extract_structured(
                url,
                tgt_schema,
                prompt=tgt_prompt,
                output_dir=args.output_dir,
            )
            print_extraction(tgt_schema.__name__, data)

        except EnvironmentError as exc:
            print(f"\n[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as exc:
            print(f"\n[EXTRACT ERROR] {url}: {exc}", file=sys.stderr)
            all_ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERROR] {url}: {exc}", file=sys.stderr)
            all_ok = False

    sys.exit(0 if all_ok else 3)
