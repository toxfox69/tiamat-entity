# Firecrawl Python SDK — Examples

Three production-ready examples demonstrating the core capabilities of the
[Firecrawl](https://firecrawl.dev) Python SDK: web scraping, structured data
extraction, and full-site crawling.

Submitted for [Issue #616 — Python Example Bounty](https://github.com/mendableai/firecrawl/issues/616).

---

## Examples

| File | What it does |
|------|-------------|
| [`example_01_web_scraper.py`](./example_01_web_scraper.py) | Scrape a single URL → clean markdown + HTML + links |
| [`example_02_data_extractor.py`](./example_02_data_extractor.py) | AI-powered structured data extraction with Pydantic schemas |
| [`example_03_site_crawler.py`](./example_03_site_crawler.py) | Crawl an entire site → per-page markdown files with YAML frontmatter |

---

## Setup

### 1. Get a Firecrawl API key

Sign up at [firecrawl.dev](https://firecrawl.dev) — free tier includes
hundreds of scrapes per month.

### 2. Install dependencies

```bash
pip install firecrawl-py pydantic tqdm
```

Or install from the requirements file:

```bash
pip install -r requirements.txt
```

### 3. Set your API key

```bash
export FIRECRAWL_API_KEY="fc-your-key-here"
```

Add it to your shell profile (`.bashrc`, `.zshrc`) to make it permanent.

---

## Example 1 — Web Scraper

Scrapes a single URL and returns clean, LLM-ready markdown. Automatically
strips navigation, ads, and boilerplate (`onlyMainContent=True`). Saves
markdown, HTML, and metadata to disk.

**Run:**
```bash
python example_01_web_scraper.py
# or with a custom URL:
python example_01_web_scraper.py https://news.ycombinator.com
```

**Output:**
```
[firecrawl] Scraping: https://news.ycombinator.com
[firecrawl] Markdown saved: output/scrape/news.ycombinator.com_20240315_120000.md
[firecrawl] Metadata saved: output/scrape/news.ycombinator.com_20240315_120000_meta.json

===========================================================
SCRAPE SUMMARY
===========================================================
URL:          https://news.ycombinator.com
Scraped at:   2024-03-15T12:00:00Z
Title:        Hacker News
Markdown len: 4,231 characters
Links found:  87
```

**Key function:**
```python
from example_01_web_scraper import scrape_to_markdown

result = scrape_to_markdown(
    url="https://example.com/article",
    only_main_content=True,  # strip nav/footer/ads
    include_html=False,       # also fetch raw HTML
)
print(result["markdown"])    # clean markdown string
print(result["links"])       # list of URLs found on page
print(result["metadata"])    # title, description, og tags, etc.
```

---

## Example 2 — Structured Data Extractor

Uses Firecrawl's AI extraction to pull typed fields from any web page.
You define a [Pydantic](https://docs.pydantic.dev/) model describing what
you want; Firecrawl's LLM populates every field automatically.

Three schemas are included out of the box:
- `JobPosting` — job board listings (title, company, salary, skills…)
- `ProductInfo` — e-commerce products (price, rating, features…)
- `ArticleMetadata` — news/blog posts (author, topics, summary…)

**Run:**
```bash
python example_02_data_extractor.py
# or with a custom URL:
python example_02_data_extractor.py https://example.com/product
```

**Output:**
```
[firecrawl] Extracting: https://firecrawl.dev
[firecrawl] Schema:     ArticleMetadata
[firecrawl] Result saved: output/extract/ArticleMetadata_firecrawl.dev_...json

===========================================================
EXTRACTED: ArticleMetadata
===========================================================
  title: Firecrawl — Web Data API for AI
  author: None
  publication: Firecrawl
  published_date: None
  topics:
    • web scraping
    • AI
    • LLM
    • API
  summary: Firecrawl is a web data API that converts any website into
            clean markdown or structured data ready for use with LLMs...
```

**Define a custom schema:**
```python
from pydantic import BaseModel
from typing import Optional
from example_02_data_extractor import extract_structured_data

class RestaurantInfo(BaseModel):
    name: str
    cuisine: str
    price_range: Optional[str]
    address: Optional[str]
    rating: Optional[float]
    top_dishes: list[str]

data = extract_structured_data(
    url="https://www.yelp.com/biz/some-restaurant",
    schema=RestaurantInfo,
    prompt="Extract restaurant details including menu highlights.",
)
print(data)  # validated dict matching RestaurantInfo
```

---

## Example 3 — Site Crawler & Markdown Exporter

Crawls an entire website (or subtree) and exports every page as a markdown
file with YAML frontmatter. Ideal for building RAG knowledge bases,
fine-tuning datasets, or offline documentation mirrors.

**Run:**
```bash
python example_03_site_crawler.py
# custom target with options:
python example_03_site_crawler.py https://docs.example.com \
    --max-pages 50 \
    --output ./my-docs \
    --include "/docs/*" "/api/*" \
    --exclude "/tag/*" "/page/*"
```

**Output:**
```
[firecrawl] Starting crawl: https://firecrawl.dev
[firecrawl] Max pages:      15
[firecrawl] Output dir:     /path/to/output/crawl
Saving pages: 100%|████████████████| 12/12 [00:02<00:00]
[firecrawl] Crawl complete. Pages collected: 12
[firecrawl] Index saved:    output/crawl/_crawl_index.json

===========================================================
CRAWL SUMMARY
===========================================================
Start URL:    https://firecrawl.dev
Pages saved:  12 / 12
Errors:       0
Total content:48,231 characters
Output dir:   /path/to/output/crawl
```

**Output file format (per page):**
```markdown
---
url: "https://firecrawl.dev/pricing"
title: "Pricing — Firecrawl"
description: "Transparent pricing for the Firecrawl web data API..."
crawled_at: "2024-03-15T12:00:00+00:00"
language: "en"
---

# Pricing

[... clean markdown content ...]
```

**Use as a library:**
```python
from example_03_site_crawler import crawl_site_to_markdown

result = crawl_site_to_markdown(
    start_url="https://docs.mycompany.com",
    output_dir="./knowledge-base",
    max_pages=100,
    include_paths=["/docs/*"],
    exclude_paths=["/blog/*", "/changelog/*"],
)
print(f"Saved {result['total_saved']} pages to {result['output_dir']}")
```

---

## Use Cases

| Example | Real-world use |
|---------|---------------|
| Web Scraper | Feed articles into an LLM or RAG pipeline |
| Data Extractor | Build a job board aggregator, price tracker, or lead gen tool |
| Site Crawler | Create a local knowledge base from documentation sites |

---

## Requirements

```
firecrawl-py>=1.0.0   # Firecrawl Python SDK
pydantic>=2.0.0       # Schema validation (example 2)
tqdm>=4.0.0           # Progress bars (example 3, optional)
```

All examples require Python 3.11+.

---

## API Key Security

Never hardcode your API key. Use environment variables:

```bash
# Good
export FIRECRAWL_API_KEY="fc-..."
python example_01_web_scraper.py

# Or use a .env file with python-dotenv
pip install python-dotenv
```

```python
from dotenv import load_dotenv
load_dotenv()  # reads FIRECRAWL_API_KEY from .env
```

---

## Resources

- [Firecrawl Documentation](https://docs.firecrawl.dev)
- [Python SDK Reference](https://docs.firecrawl.dev/sdks/python)
- [firecrawl-py on PyPI](https://pypi.org/project/firecrawl-py/)
- [GitHub Repository](https://github.com/mendableai/firecrawl)
- [Example Bounty Issue #616](https://github.com/mendableai/firecrawl/issues/616)
