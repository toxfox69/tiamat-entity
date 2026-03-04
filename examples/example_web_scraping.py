"""
Example: Web scraping with the Firecrawl Python SDK.
Scrapes a product page and prints the result as markdown.
"""

import os
from firecrawl import FirecrawlApp

# Load API key from environment or use placeholder
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "fc-YOUR_API_KEY_HERE")

# Target URL to scrape
PRODUCT_URL = "https://example.com/product/123"


def main():
    # Initialize the Firecrawl client
    app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

    try:
        # Scrape the product page, requesting markdown output
        result = app.scrape_url(
            PRODUCT_URL,
            params={"formats": ["markdown"]},
        )

        # Extract and print the markdown content
        markdown = result.get("markdown", "")
        if markdown:
            print("=== Scraped Markdown Content ===\n")
            print(markdown)
        else:
            print("No markdown content returned.")

    except Exception as e:
        print(f"Error scraping {PRODUCT_URL}: {e}")


if __name__ == "__main__":
    main()
