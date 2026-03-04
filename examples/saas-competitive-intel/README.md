# SaaS Competitive Intelligence Analyzer

> Automatically research your competitors' pricing and positioning — powered by Firecrawl.

This example shows how to use the **Firecrawl Python SDK** to build a real-world competitive
intelligence tool. Given a list of SaaS competitor URLs, it discovers their pricing pages,
scrapes clean content, and generates structured comparison reports.

## What It Does

1. **`map()`** — Discovers pricing, plans, and features pages across each competitor's domain
2. **`scrape()`** — Fetches each relevant page as clean Markdown (no HTML noise)
3. **Parses** pricing tiers, price points, free trial availability, and key features
4. **Outputs** a JSON data dump, a Markdown comparison report, and a CSV pricing table

### Example Run

```
$ python competitive_intel.py https://notion.so https://obsidian.md https://craft.do

══════════════════════════════════════════════════════════════
  SAAS COMPETITIVE INTELLIGENCE ANALYZER
  Powered by Firecrawl  |  2024-11-14 09:22 UTC
══════════════════════════════════════════════════════════════
  Analyzing 3 competitor(s)...

── Analyzing: https://notion.so
  [map]    Discovering pages on https://notion.so
  [map]    Found 5 pricing-relevant pages (capped at 5)
  [scrape] https://notion.so  (4,821 chars)
  [scrape] https://notion.so/pricing  (6,340 chars)
  [scrape] https://notion.so/product/ai  (3,180 chars)

── Analyzing: https://obsidian.md
  [map]    Discovering pages on https://obsidian.md
  [map]    Found 3 pricing-relevant pages (capped at 5)
  [scrape] https://obsidian.md  (2,902 chars)
  [scrape] https://obsidian.md/pricing  (4,711 chars)

── Analyzing: https://craft.do
  [map]    Discovering pages on https://craft.do
  [map]    Found 4 pricing-relevant pages (capped at 5)
  [scrape] https://craft.do  (3,341 chars)
  [scrape] https://craft.do/pricing  (5,200 chars)

══════════════════════════════════════════════════════════════
  COMPETITIVE INTELLIGENCE SUMMARY
══════════════════════════════════════════════════════════════

  NOTION  (https://notion.so)
  │  Tagline:     The connected workspace where better, faster work happens.
  │  Free trial:  No
  │  Free tier:   Yes
  │  Prices:      $10  ·  $15  ·  $18
  └─ Tiers (3):
       [Free]
         • Collaborative workspace
         • Basic page analytics
       [Plus  $10]
         • Unlimited blocks for teams
         • Unlimited file uploads
       [Business  $15]
         • Private teamspaces
         • Bulk PDF export

  OBSIDIAN  (https://obsidian.md)
  │  Tagline:     Sharpen your thinking. Obsidian is the private and flexible note‑taking app
  │  Free trial:  No
  │  Free tier:   Yes
  │  Prices:      $4  ·  $8
  └─ Tiers (2):
       [Sync  $4]
         • End-to-end encrypted vault sync
       [Publish  $8]
         • Publish notes as a website

  CRAFT  (https://craft.do)
  │  Tagline:     The future of documents is here
  │  Free trial:  Yes
  │  Free tier:   No
  │  Prices:      $5  ·  $10
  └─ Tiers (2):
       [Personal  $5]
         • Unlimited documents
       [Business  $10]
         • Team collaboration

  Saved JSON:     ./output/analysis_20241114_092240.json
  Saved report:   ./output/report_20241114_092240.md
  Saved CSV:      ./output/pricing_20241114_092240.csv

  Done.
```

## Generated Outputs

### `report_*.md` — Markdown comparison table

```markdown
# SaaS Competitive Intelligence Report

| Company  | Free Trial | Free Tier | Price Range      | Tiers |
|----------|:----------:|:---------:|------------------|:-----:|
| Notion   |     ✗      |     ✓     | $10 · $15 · $18  |   3   |
| Obsidian |     ✗      |     ✓     | $4 · $8          |   2   |
| Craft    |     ✓      |     ✗     | $5 · $10         |   2   |
```

### `analysis_*.json` — Full structured data

```json
[
  {
    "url": "https://notion.so",
    "company_name": "Notion",
    "tagline": "The connected workspace where better, faster work happens.",
    "has_free_trial": false,
    "has_free_tier": true,
    "price_mentions": ["10", "15", "18"],
    "pricing_tiers": [
      {
        "name": "Free",
        "price": null,
        "features": ["Collaborative workspace", "Basic page analytics"]
      },
      {
        "name": "Plus",
        "price": "$10",
        "features": ["Unlimited blocks for teams", "Unlimited file uploads"]
      }
    ],
    "pages_analyzed": 3,
    "scraped_at": "2024-11-14T09:22:40.123456"
  }
]
```

### `pricing_*.csv` — Spreadsheet-friendly pricing table

```
company,url,free_trial,free_tier,price_mentions,tier_name,tier_price,tier_features
Notion,https://notion.so,False,True,"$10; $15; $18",Free,,Collaborative workspace; Basic analytics
Notion,https://notion.so,False,True,"$10; $15; $18",Plus,$10,Unlimited blocks; Unlimited file uploads
```

## Setup

### Prerequisites

- Python 3.9+
- A [Firecrawl](https://firecrawl.dev) API key (free tier available)

### Install

```bash
pip install -r requirements.txt
```

### Configure

```bash
export FIRECRAWL_API_KEY="fc-your-key-here"
```

Or pass it inline: `python competitive_intel.py ... --api-key fc-your-key`

## Usage

```bash
# Basic: analyze two competitors
python competitive_intel.py https://linear.app https://shortcut.com

# Multiple competitors with custom output dir
python competitive_intel.py \
  https://notion.so \
  https://obsidian.md \
  https://craft.do \
  --output ./competitive-research

# Quick summary only (no files saved)
python competitive_intel.py https://vercel.com https://netlify.com --no-save

# Pass API key inline
python competitive_intel.py https://stripe.com --api-key fc-abc123
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `urls` | required | One or more competitor URLs |
| `--output`, `-o` | `./output` | Directory for report files |
| `--api-key` | `$FIRECRAWL_API_KEY` | Firecrawl API key |
| `--no-save` | false | Print summary only; skip file output |

## How It Works

```
URL  ──► map()  ──► pricing pages (up to 5)
                         │
                         ▼
              scrape() each page
                         │
                         ▼
              parse markdown for:
              • tier headings (Free/Pro/Enterprise)
              • price patterns ($9/mo, $49/yr)
              • feature bullets
              • free-trial signals
                         │
                         ▼
          JSON  +  Markdown report  +  CSV
```

The scraper uses Firecrawl's `only_main_content=True` option to strip navigation,
footers, and ads — returning only the substantive page content. This dramatically
improves parsing accuracy on real-world pricing pages.

## Firecrawl SDK Features Used

| Feature | Method | What it does here |
|---------|--------|-------------------|
| Site mapping | `app.map(url, search="pricing plans")` | Discovers sub-pages matching a keyword hint |
| Page scraping | `app.scrape(url, formats=["markdown"])` | Returns clean, structured Markdown |
| Content focus | `only_main_content=True` | Strips nav/footer noise |
| Timeout control | `timeout=30_000` | Prevents hanging on slow sites (ms) |

## Extending This Example

**Add LLM-based extraction** for higher accuracy:
```python
import anthropic

client = anthropic.Anthropic()

def extract_with_llm(markdown_content: str) -> dict:
    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Extract pricing tiers as JSON from this SaaS page:\n\n{markdown_content[:4000]}"
        }]
    )
    return json.loads(msg.content[0].text)
```

**Track changes over time** — save timestamped snapshots and diff them to detect pricing changes.

**Add email alerts** — notify your team when a competitor changes pricing.

## License

MIT
