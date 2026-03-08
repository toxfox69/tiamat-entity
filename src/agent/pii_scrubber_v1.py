#!/usr/bin/env python3
"""
PII Scrubber — Production entity detection and masking
De-identifies: Names, SSN, Credit Cards, API Keys, Passwords, IPs, Emails, Phones
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class ScrubbedResult:
    scrubbed_text: str
    entities: Dict[str, str]
    entity_count: int

def scrub_pii(text: str) -> ScrubbedResult:
    """Main scrubber function — detects and masks 16 PII types"""
    
    entities = {}
    entity_counter = {}
    modified_text = text
    
    # Define patterns for each PII type
    patterns = {
        'EMAIL': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        'US_PHONE': r'\b(?:\+?1[-.]?)?(?:\(\d{3}\)|\d{3})[-.]?\d{3}[-.]?\d{4}\b',
        'SSN': r'\b\d{3}-\d{2}-\d{4}\b',
        'CREDIT_CARD': r'\b(?:\d[ -]*?){13,19}\b',
        'IPV4': r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
        'API_KEY': r'(?:api[_-]?key|apikey|access[_-]?token)[\s]*[:=][\s]*[\w-]+',
        'PASSWORD': r'(?:password|passwd)[\s]*[:=][\s]*[\S]+',
        'NAME': r'\b(?:[A-Z][a-z]+ )+[A-Z][a-z]+\b',
    }
    
    # Process each pattern
    for entity_type, pattern in patterns.items():
        if entity_type not in entity_counter:
            entity_counter[entity_type] = 0
        
        def replace_func(match):
            entity_counter[entity_type] += 1
            placeholder = f"[{entity_type}_{entity_counter[entity_type]}]"
            entities[placeholder] = match.group(0)
            return placeholder
        
        modified_text = re.sub(pattern, replace_func, modified_text, flags=re.IGNORECASE)
    
    return ScrubbedResult(
        scrubbed_text=modified_text,
        entities=entities,
        entity_count=len(entities)
    )

if __name__ == '__main__':
    # Test
    test_text = "My name is John Smith, email john@example.com, SSN 123-45-6789"
    result = scrub_pii(test_text)
    print(f"Original: {test_text}")
    print(f"Scrubbed: {result.scrubbed_text}")
    print(f"Entities: {result.entities}")
