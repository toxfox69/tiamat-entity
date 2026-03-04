# Firecrawl Python SDK — Examples

Production-ready examples for the [Firecrawl](https://firecrawl.dev) Python SDK
(`firecrawl-py`). All examples require only `pip install firecrawl-py` and a
free API key — no extra dependencies unless noted.

Submitted for [Issue #616 — Python Example Bounty](https://github.com/mendableai/firecrawl/issues/616).

---

## Quick Start

```bash
pip install firecrawl-py
export FIRECRAWL_API_KEY="fc-your-key-here"
# Get a free key at https://firecrawl.dev/app/api-keys
```

---

## Examples

| File | What it does | Extra deps |
|------|-------------|------------|
| [`example_1_basic_scrape.py`](#example-1--basic-url-to-markdown-scraper) | Pass a URL → get clean Markdown | none |
| [`example_2_batch_scraping.py`](#example-2--async-batch-scraper-with-csv-export) | Scrape many URLs concurrently → CSV | none |
| [`example_01_web_scraper.py`](#example-01--web-scraper) | Scrape + save Markdown, HTML, metadata to disk | none |
| [`example_02_data_extractor.py`](#example-02--structured-data-extractor) | AI extraction with Pydantic schemas | `pydantic` |
| [`example_03_site_crawler.py`](#example-03--site-crawler--markdown-exporter) | Crawl entire site → markdown files | `tqdm` (optional) |

---

## Example 1 — Basic URL to Markdown Scraper

**File:** `example_1_basic_scrape.py`

The simplest possible Firecrawl workflow: pass a URL, get back clean Markdown.
Handles JavaScript-rendered pages and strips nav/ads/footers automatically.

### Run

```bash
# Scrape the default demo URL (Hacker News):
python example_1_basic_scrape.py

# Scrape any URL:
python example_1_basic_scrape.py https://docs.python.org/3/library/asyncio.html

# Keep nav/footer (disable boilerplate stripping):
python example_1_basic_scrape.py https://example.com --full-page
```

### Output

```
Scraping: https://news.ycombinator.com
Title : Hacker News
Words : 1,412  (8,231 characters)

────────────────────────────────────────────────────────────
Markdown preview (first 800 characters)
────────────────────────────────────────────────────────────
# Hacker News

1. [Some Article Title](https://example.com) (self.example) 312 points by user
...
```

### Use as a library

```python
from example_1_basic_scrape import scrape_to_markdown

result = scrape_to_markdown(
    url="https://docs.python.org/3/library/asyncio.html",
    only_main_content=True,   # strip nav/footer/ads (default)
)

print(result["title"])        # "asyncio — Asynchronous I/O"
print(result["word_count"])   # 3241
print(result["markdown"][:200])
```

---

## Example 2 — Async Batch Scraper with CSV Export

**File:** `example_2_batch_scraping.py`

Scrape a list of URLs concurrently using `asyncio` + `ThreadPoolExecutor`,
then write every result — including failures — to a CSV file. Ideal for
pipelines where you need to process 10–1000 URLs in one shot.

### Run

```bash
# Scrape the 5 built-in demo URLs:
python example_2_batch_scraping.py

# Pass your own URLs:
python example_2_batch_scraping.py https://url1.com https://url2.com https://url3.com

# Custom output file:
python example_2_batch_scraping.py --output my_results.csv https://url1.com https://url2.com
```

### Output (console)

```
Scraping 5 URLs (5 concurrent workers)...
[1/5] OK    https://news.ycombinator.com  (1,412 words)
[2/5] OK    https://www.python.org        (843 words)
[3/5] OK    https://github.com/trending   (2,105 words)
[4/5] OK    https://docs.firecrawl.dev    (997 words)
[5/5] ERROR https://invalid.example.test  (connection refused)

====================================================================
  URL                                            Words  Status
────────────────────────────────────────────────────────────────────
  https://news.ycombinator.com                   1,412  OK
  https://www.python.org                           843  OK
  https://github.com/trending                    2,105  OK
  https://docs.firecrawl.dev                       997  OK
  https://invalid.example.test                       —  ERROR: connection refused
====================================================================
  Done: 4/5 succeeded  |  1 failed  |  CSV: scrape_results.csv
```

### Output (CSV — `scrape_results.csv`)

```csv
url,title,word_count,char_count,scraped_at,status,error
https://news.ycombinator.com,Hacker News,1412,8231,2026-03-04T12:00:00+00:00,ok,
https://www.python.org,Welcome to Python.org,843,4921,2026-03-04T12:00:01+00:00,ok,
https://github.com/trending,Trending repositories,2105,12834,2026-03-04T12:00:02+00:00,ok,
https://docs.firecrawl.dev,Firecrawl Docs,997,5821,2026-03-04T12:00:01+00:00,ok,
https://invalid.example.test,,0,0,2026-03-04T12:00:03+00:00,error,connection refused
```

### Use as a library

```python
import asyncio
from example_2_batch_scraping import batch_scrape

urls = [
    "https://news.ycombinator.com",
    "https://www.python.org",
    "https://github.com/trending",
]

results = asyncio.run(batch_scrape(urls, output_csv="hacker_news.csv"))

for r in results:
    if r["status"] == "ok":
        print(f"{r['url']}  →  {r['word_count']:,} words")
```

---

## Example 01 — Web Scraper

**File:** `example_01_web_scraper.py`

Full-featured single-URL scraper that saves Markdown, raw HTML, and a JSON
metadata sidecar to disk. Includes a `--html` flag to also capture raw HTML.

```bash
python example_01_web_scraper.py
python example_01_web_scraper.py https://news.ycombinator.com
python example_01_web_scraper.py https://example.com --html --output-dir ./my-output
```

**Output files** (under `output/scrape/`):
```
news.ycombinator.com_20260304_120000.md         ← clean Markdown
news.ycombinator.com_20260304_120000.html       ← raw HTML (--html only)
news.ycombinator.com_20260304_120000_meta.json  ← metadata + top 20 links
```

---

## Example 02 — Structured Data Extractor

**File:** `example_02_data_extractor.py`
**Extra:** `pip install pydantic`

AI-powered extraction: define a Pydantic model describing the data you want,
Firecrawl's LLM fills every field from the page automatically.

```bash
python example_02_data_extractor.py
python example_02_data_extractor.py https://example.com/product
```

**Built-in schemas:** `JobPosting`, `ProductInfo`, `ArticleMetadata`

```python
from pydantic import BaseModel
from example_02_data_extractor import extract_structured_data

class RestaurantInfo(BaseModel):
    name: str
    cuisine: str
    rating: float | None
    top_dishes: list[str]

data = extract_structured_data("https://yelp.com/biz/some-restaurant", RestaurantInfo)
```

---

## Example 03 — Site Crawler & Markdown Exporter

**File:** `example_03_site_crawler.py`
**Extra:** `pip install tqdm` (optional — progress bar degrades gracefully)

Crawls an entire website and exports every page as a Markdown file with YAML
frontmatter. Ideal for building RAG knowledge bases or offline doc mirrors.

```bash
python example_03_site_crawler.py
python example_03_site_crawler.py https://docs.example.com \
    --max-pages 50 \
    --include "/docs/*" "/api/*" \
    --exclude "/tag/*" "/changelog/*"
```

**Output files** (under `output/crawl/`):
```markdown
---
url: "https://docs.example.com/getting-started"
title: "Getting Started"
crawled_at: "2026-03-04T12:00:00+00:00"
---

# Getting Started
...
```

---

## Requirements

```
firecrawl-py>=1.0.0   # required for all examples
pydantic>=2.0.0       # example_02_data_extractor.py only
tqdm>=4.66.0          # example_03_site_crawler.py (optional)
```

Install everything:

```bash
pip install -r requirements.txt
```

All examples require **Python 3.11+**.

---

## API Key Security

Never hardcode your API key. Use an environment variable:

```bash
# Temporary (current shell session)
export FIRECRAWL_API_KEY="fc-..."

# Permanent (add to ~/.bashrc or ~/.zshrc)
echo 'export FIRECRAWL_API_KEY="fc-..."' >> ~/.bashrc

# Or use python-dotenv
pip install python-dotenv
```

```python
from dotenv import load_dotenv
load_dotenv()  # reads FIRECRAWL_API_KEY from .env file
```

---

## Resources

- [Firecrawl Documentation](https://docs.firecrawl.dev)
- [Python SDK Reference](https://docs.firecrawl.dev/sdks/python)
- [firecrawl-py on PyPI](https://pypi.org/project/firecrawl-py/)
- [GitHub Repository](https://github.com/mendableai/firecrawl)
- [Example Bounty Issue #616](https://github.com/mendableai/firecrawl/issues/616)
