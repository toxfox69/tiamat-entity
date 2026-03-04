"""
Firecrawl Python SDK — Example 2: Structured Data Extractor
============================================================

Demonstrates extracting typed, structured data from web pages using Pydantic
schemas and Firecrawl's AI-powered JSON extraction. Ideal for competitive
intelligence, job scrapers, product catalogues, and research pipelines.

Requirements:
    pip install firecrawl-py pydantic

Usage:
    export FIRECRAWL_API_KEY="fc-your-key-here"
    python example_02_data_extractor.py

    # Scrape a specific URL:
    python example_02_data_extractor.py https://jobs.example.com/posting/123

Schema selection is auto-detected from the URL pattern, but you can override
it by editing DEMO_TARGETS below.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone  # noqa: F401
from typing import Optional

from pydantic import BaseModel, Field
from firecrawl import FirecrawlApp  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# Pydantic schemas — define what you want extracted from each page type
# ---------------------------------------------------------------------------

class JobPosting(BaseModel):
    """Structured data for a job listing page."""
    title: str = Field(description="Job title / role name")
    company: str = Field(description="Company offering the role")
    location: str = Field(description="City, state, or 'Remote'")
    salary_range: Optional[str] = Field(None, description="Salary or pay range if listed")
    employment_type: Optional[str] = Field(None, description="Full-time / Part-time / Contract")
    experience_required: Optional[str] = Field(None, description="Years or level of experience required")
    skills: list[str] = Field(default_factory=list, description="Required or preferred skills / technologies")
    application_deadline: Optional[str] = Field(None, description="Application close date if mentioned")
    description_summary: str = Field(description="One-paragraph summary of the role and responsibilities")


class ProductInfo(BaseModel):
    """Structured data for an e-commerce product page."""
    name: str = Field(description="Product name")
    brand: Optional[str] = Field(None, description="Brand or manufacturer")
    price: Optional[str] = Field(None, description="Current listed price with currency symbol")
    original_price: Optional[str] = Field(None, description="Pre-discount price if a sale is active")
    rating: Optional[float] = Field(None, description="Average customer rating (0-5)")
    review_count: Optional[int] = Field(None, description="Number of customer reviews")
    availability: Optional[str] = Field(None, description="In stock / Out of stock / Ships in X days")
    key_features: list[str] = Field(default_factory=list, description="Top 5 bullet-point product features")
    category: Optional[str] = Field(None, description="Product category or department")


class ArticleMetadata(BaseModel):
    """Structured data for a news article or blog post."""
    title: str = Field(description="Article headline")
    author: Optional[str] = Field(None, description="Author name(s)")
    publication: Optional[str] = Field(None, description="Publisher or site name")
    published_date: Optional[str] = Field(None, description="Publication date in ISO 8601 or as written")
    topics: list[str] = Field(default_factory=list, description="Main topics or tags")
    summary: str = Field(description="2-3 sentence summary of the article")
    reading_time_minutes: Optional[int] = Field(None, description="Estimated reading time in minutes")
    word_count: Optional[int] = Field(None, description="Approximate word count")


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_structured_data(
    url: str,
    schema: type[BaseModel],
    prompt: Optional[str] = None,
    output_dir: str = "output/extract",
) -> dict:
    """
    Scrape a URL and extract structured data matching the given Pydantic schema.

    Firecrawl sends the page content to an LLM which populates every field
    in the schema. Fields marked Optional are left as None if not found.

    Args:
        url:        Page to scrape and extract from.
        schema:     Pydantic model class defining the desired output shape.
        prompt:     Optional natural-language hint for the LLM extractor.
        output_dir: Where to save JSON results.

    Returns:
        Validated dict of extracted fields (matches schema structure).

    Raises:
        ValueError: API key missing or extraction failed.
        ValidationError: Extracted data doesn't fit the schema.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError(
            "FIRECRAWL_API_KEY environment variable not set.\n"
            "Get a free key at https://firecrawl.dev"
        )

    app = FirecrawlApp(api_key=api_key)

    schema_name = schema.__name__
    if prompt is None:
        prompt = f"Extract all {schema_name} information from this page."

    print(f"[firecrawl] Extracting: {url}")
    print(f"[firecrawl] Schema:     {schema_name}")
    print(f"[firecrawl] Prompt:     {prompt}")

    result = app.scrape_url(  # type: ignore[union-attr]
        url,
        params={
            "formats": ["extract"],
            "extract": {
                "prompt": prompt,
                "schema": schema.model_json_schema(),
            },
        },
    )

    if not result:
        raise ValueError(f"No data extracted from {url}")

    # The extracted dict lives under result['extract']
    raw = result.get("extract") or result.get("json") or {}

    # Validate against the Pydantic schema — this will raise if keys are wrong
    validated = schema.model_validate(raw)
    data = validated.model_dump()

    # Persist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    slug = url.replace("https://", "").replace("http://", "").rstrip("/").replace("/", "_")[:60]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir) / f"{schema_name}_{slug}_{ts}.json"
    out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"[firecrawl] Result saved: {out_path}")

    return data


def print_extraction(schema_name: str, data: dict) -> None:
    """Pretty-print extracted fields."""
    print("\n" + "=" * 60)
    print(f"EXTRACTED: {schema_name}")
    print("=" * 60)
    for key, value in data.items():
        if isinstance(value, list):
            print(f"  {key}:")
            for item in value:
                print(f"    • {item}")
        else:
            print(f"  {key}: {value}")


# ---------------------------------------------------------------------------
# Demo targets — edit freely
# ---------------------------------------------------------------------------

DEMO_TARGETS = [
    {
        "url": "https://news.ycombinator.com/item?id=39025977",
        "schema": ArticleMetadata,
        "prompt": "Extract article/post metadata including title, author, topics, and a summary.",
    },
    {
        "url": "https://firecrawl.dev",
        "schema": ArticleMetadata,
        "prompt": "Extract page metadata: title, description/summary, and main topics covered.",
    },
]


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # If a URL is passed, try ArticleMetadata as a sensible default
        targets = [
            {
                "url": sys.argv[1],
                "schema": ArticleMetadata,
                "prompt": "Extract structured metadata from this page.",
            }
        ]
    else:
        targets = DEMO_TARGETS

    for target in targets:
        try:
            data = extract_structured_data(
                url=target["url"],
                schema=target["schema"],
                prompt=target.get("prompt"),
            )
            print_extraction(target["schema"].__name__, data)
        except Exception as exc:
            print(f"[ERROR] {target['url']}: {exc}")
