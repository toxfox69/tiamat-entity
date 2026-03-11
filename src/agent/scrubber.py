#!/usr/bin/env python3
"""
TIAMAT PII Scrubber — Comprehensive PII Detection & Redaction

Detects and redacts:
- Names (person names)
- Email addresses
- Phone numbers (US + international)
- Social Security Numbers (SSNs)
- Credit card numbers
- IPv4 addresses
- API keys and credentials
- URLs
- Street addresses
- Passwords and tokens

Returns:
{
  "scrubbed": "redacted text",
  "entities": {"NAME_1": "actual value", ...},
  "count": 5,
  "categories": {"EMAIL": 2, "SSN": 1, ...}
}
"""

import re
import json
from collections import defaultdict
from typing import Dict, List, Tuple


class PIIScrubber:
    """Comprehensive PII detection and scrubbing engine."""

    def __init__(self):
        # Pattern definitions (ordered by specificity, most specific first)
        self.patterns = {
            # CREDENTIALS & API KEYS (highest priority — most specific)
            'API_KEY': [
                r'(?:api[_-]?key|apikey)[\s]*[=:][\s]*["\']?([\da-zA-Z\-_.]{20,})["\']?',
                r'(?:sk|pk)_(?:live|test)_[\da-zA-Z]{20,}',  # Stripe keys
                r'ghp_[\da-zA-Z]{36}',  # GitHub Personal Access Token
                r'glpat-[\da-zA-Z_-]{20,}',  # GitLab token
            ],
            'PASSWORD': [
                r'(?:password|passwd|pwd)[\s]*[=:][\s]*["\']([^"\'\'\s]+)["\']',
                r'password[\s]*[=:][\s]*\S+',
            ],
            'BEARER_TOKEN': [
                r'(?:Bearer|bearer|token)[\s]+([\da-zA-Z_\-\.]{30,})',
                r'(?:authorization|auth)[\s]*[=:][\s]*Bearer\s+([\da-zA-Z_\-\.]+)',
            ],

            # FINANCIAL (high priority)
            'CREDIT_CARD': [
                r'\b(?:\d[ -]*?){13,19}\b',  # Generic: 13-19 digits with optional separators
                r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b',  # Visa, MC, Amex
                r'\b(?:6(?:011|5[0-9]{2})[0-9]{12})\b',  # Discover, Diners
            ],
            'SSN': [
                r'(?<!\d)\b\d{3}-\d{2}-\d{4}\b(?!\d)',  # XXX-XX-XXXX
                r'(?<!\d)\b\d{3}\s\d{2}\s\d{4}\b(?!\d)',  # XXX XX XXXX
                r'(?<!\d)\b\d{9}\b(?!\d)',  # XXXXXXXXX (9 consecutive, not preceded/followed by digits)
            ],
            'BANK_ACCOUNT': [
                r'(?:account|acct|acc)[\s]*[#:=]?[\s]*\b\d{8,17}\b',
            ],

            # CONTACT (medium priority)
            'EMAIL': [
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            ],
            'PHONE': [
                r'\b(?:\+?1[-.]?)?(?:\(\d{3}\)|\d{3})[-.]?\d{3}[-.]?\d{4}\b',  # US phone
                r'\b(?:\+\d{1,3}[-.]?)?\(?\d{1,4}\)?[-.]?\d{1,4}[-.]?\d{1,9}\b',  # International
            ],

            # NETWORK
            'IPV4': [
                r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
            ],
            'IPV6': [
                r'(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}',
            ],
            'URL': [
                r'https?://(?:www\.)?[^\s/$.?#].[^\s]*',
            ],

            # IDENTITY (lower priority — higher false positive risk)
            'NAME': [
                # Common name patterns: Capitalized First Last
                r'\b(?:Mr|Ms|Mrs|Dr|Prof)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b',
                # First + Last (both capitalized)
                r'\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b',
            ],
            'ADDRESS': [
                # Street addresses: "123 Main Street"
                r'\b\d{1,5}\s+[A-Za-z]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Lane|Ln)\b',
                # City, State ZIP
                r'\b[A-Z][a-z]+,\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b',
            ],
        }

        # Compile regex patterns for efficiency
        self.compiled_patterns = {}
        for category, patterns_list in self.patterns.items():
            self.compiled_patterns[category] = [
                re.compile(pattern, re.IGNORECASE if category != 'NAME' else 0)
                for pattern in patterns_list
            ]

        self.entity_counter = defaultdict(int)
        self.entities = {}  # Maps placeholder to original value

    def scrub(self, text: str) -> Dict:
        """
        Scrub PII from text and return scrubbed version + entity map.

        Args:
            text: Input text potentially containing PII

        Returns:
            {
                "scrubbed": "text with [TYPE_N] placeholders",
                "entities": {"NAME_1": "John Smith", ...},
                "count": 5,
                "categories": {"EMAIL": 2, "NAME": 3}
            }
        """
        self.entity_counter.clear()
        self.entities = {}
        scrubbed_text = text
        category_counts = defaultdict(int)

        # Process patterns by category, in order (higher priority first)
        # Order: API_KEY → PASSWORD → BEARER → CC → SSN → EMAIL → PHONE → IPv4 → URL → NAME → ADDRESS
        category_order = [
            'API_KEY', 'PASSWORD', 'BEARER_TOKEN',
            'CREDIT_CARD', 'SSN', 'BANK_ACCOUNT',
            'EMAIL', 'PHONE',
            'IPV4', 'IPV6', 'URL',
            'NAME', 'ADDRESS'
        ]

        for category in category_order:
            if category not in self.compiled_patterns:
                continue

            for pattern in self.compiled_patterns[category]:
                # Find all matches
                for match in pattern.finditer(scrubbed_text):
                    original_value = match.group(0)

                    # Skip false positives
                    if self._is_false_positive(category, original_value):
                        continue

                    # Generate placeholder
                    self.entity_counter[category] += 1
                    placeholder = f"[{category}_{self.entity_counter[category]}]"

                    # Store mapping
                    self.entities[placeholder] = original_value
                    category_counts[category] += 1

                    # Replace in scrubbed text
                    scrubbed_text = scrubbed_text.replace(original_value, placeholder, 1)

        return {
            "scrubbed": scrubbed_text,
            "entities": self.entities,
            "count": sum(category_counts.values()),
            "categories": dict(category_counts)
        }

    def _is_false_positive(self, category: str, value: str) -> bool:
        """Filter out known false positives."""
        # NAME patterns are risky — skip common words
        if category == 'NAME':
            common_words = {'The', 'From', 'Here', 'This', 'That', 'Where', 'When', 'What', 'Which', 'As'}
            if value.split()[0] in common_words:
                return True
        
        # IPV4 — skip reserved ranges (127.x, 0.x, 255.x)
        if category == 'IPV4':
            if value.startswith(('127.', '0.', '255.')):
                return True

        # PHONE — skip too-short sequences
        if category == 'PHONE':
            digits = re.sub(r'\D', '', value)
            if len(digits) < 10:
                return True

        return False

    def restore(self, scrubbed_text: str, entities: Dict[str, str]) -> str:
        """
        Restore original text from scrubbed version and entity map.

        Args:
            scrubbed_text: Text with [TYPE_N] placeholders
            entities: Mapping from placeholders to original values

        Returns:
            Original text with PII restored
        """
        restored = scrubbed_text
        for placeholder, original_value in entities.items():
            restored = restored.replace(placeholder, original_value)
        return restored


# Singleton instance
PII_SCRUBBER = PIIScrubber()


if __name__ == '__main__':
    # Test cases
    test_cases = [
        "My name is John Smith and my SSN is 123-45-6789.",
        "Email me at john.smith@company.com or call (555) 123-4567.",
        "Credit card: 4532-1234-5678-9010, expires 12/25",
        "API Key: sk_live_abc123def456ghi789jkl012mno345",
        "Bearer token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "Password is P@ssw0rd123! Please reset.",
        "Server IP is 192.168.1.100 for internal access.",
        "Visit https://company.com/dashboard for details.",
        "123 Main Street, San Francisco, CA 94105",
        "Account number 1234567890 is on hold.",
    ]

    print("\n=== PII SCRUBBER TEST ===")
    for test in test_cases:
        result = PII_SCRUBBER.scrub(test)
        print(f"\nInput:    {test}")
        print(f"Scrubbed: {result['scrubbed']}")
        print(f"Found:    {result['categories']}")
        if result['entities']:
            print(f"Entities: {json.dumps(result['entities'], indent=2)}")
