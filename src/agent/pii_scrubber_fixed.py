#!/usr/bin/env python3
"""
PII Scrubber — Anonymize personally identifiable information
Built for TIAMAT Privacy Proxy

Fixed version with improved NAME detection
"""

import re
import json
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class EntityMatch:
    """Represents a matched PII entity"""
    entity_type: str
    value: str
    start: int
    end: int
    counter: int = 0

class PII_Scrubber:
    """Detect and anonymize PII in text"""
    
    # Regex patterns for common PII types
    PATTERNS = {
        'NAME': [
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b',  # John Smith, Alice Johnson, Mary Jane Watson
            r'\b((?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b',  # Mr. John Smith
        ],
        'EMAIL': [
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        ],
        'PHONE': [
            r'\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b',  # +1-555-123-4567 etc
            r'\b\d{3}-\d{3}-\d{4}\b',  # 555-123-4567
        ],
        'SSN': [
            r'\b\d{3}-\d{2}-\d{4}\b',  # 123-45-6789
            r'\b\d{9}\b',  # 123456789
        ],
        'CREDIT_CARD': [
            r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',  # 4532-1488-0343-6467
        ],
        'IP_ADDRESS': [
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',  # 192.168.1.1
        ],
        'API_KEY': [
            r'\b(?:sk_live_|sk_test_|pk_live_|pk_test_|sk-proj-)[A-Za-z0-9_-]{20,}\b',
            r'\b(?:key-)[A-Za-z0-9_-]{32,}\b',
        ],
        'POSTAL_CODE': [
            r'\b\d{5}(?:-\d{4})?\b',  # 90210 or 90210-1234
        ],
        'CREDIT_CARD_CVV': [
            r'\b\d{3,4}\b(?=\D|$)',  # CVV is usually 3-4 digits at end of line
        ],
    }
    
    def __init__(self):
        """Initialize scrubber and compile regex patterns."""
        self.compiled_patterns = {}
        for entity_type, patterns in self.PATTERNS.items():
            self.compiled_patterns[entity_type] = [
                re.compile(pattern, re.IGNORECASE if entity_type != 'NAME' else 0)
                for pattern in patterns
            ]
        self.counters = {}  # Track entity counts per type
    
    def scrub(self, text: str) -> Dict:
        """
        Scrub PII from text.
        
        Args:
            text: Input text to scrub
        
        Returns:
            Dict with:
            - scrubbed: Text with PII replaced by placeholders
            - entities: Mapping of placeholders to original values
            - count: Count of each entity type
        """
        self.counters = {}  # Reset counters
        entities = {}
        scrubbed = text
        
        # Track replacements to avoid double-scrubbing
        replacements = []
        
        # Process each entity type
        for entity_type in ['NAME', 'EMAIL', 'PHONE', 'SSN', 'CREDIT_CARD', 'IP_ADDRESS', 'API_KEY', 'POSTAL_CODE']:
            if entity_type not in self.compiled_patterns:
                continue
            
            patterns = self.compiled_patterns[entity_type]
            
            for pattern in patterns:
                matches = list(pattern.finditer(scrubbed))
                
                for match in matches:
                    value = match.group(0)
                    start, end = match.span()
                    
                    # Check if this match overlaps with existing replacements
                    overlaps = False
                    for (r_start, r_end, _) in replacements:
                        if (start < r_end and end > r_start):
                            overlaps = True
                            break
                    
                    if overlaps:
                        continue
                    
                    # Create placeholder
                    counter = self.counters.get(entity_type, 0) + 1
                    self.counters[entity_type] = counter
                    placeholder = f"[{entity_type}_{counter}]"
                    
                    # Track replacement
                    replacements.append((start, end, placeholder))
                    entities[placeholder] = value
        
        # Sort replacements by position (reverse order to maintain indices)
        replacements.sort(key=lambda x: x[0], reverse=True)
        
        # Apply replacements
        for start, end, placeholder in replacements:
            scrubbed = scrubbed[:start] + placeholder + scrubbed[end:]
        
        return {
            'scrubbed': scrubbed,
            'entities': entities,
            'count': self.counters,
        }
    
    def descrub(self, scrubbed_text: str, entities: Dict[str, str]) -> str:
        """
        Restore original values from scrubbed text.
        
        Args:
            scrubbed_text: Text with placeholders
            entities: Mapping of placeholders to original values
        
        Returns:
            Original text with PII restored
        """
        result = scrubbed_text
        for placeholder, value in entities.items():
            result = result.replace(placeholder, value)
        return result


if __name__ == '__main__':
    # Test the scrubber
    scrubber = PII_Scrubber()
    
    test_texts = [
        'My name is John Smith and my email is john@example.com',
        'Contact Alice Johnson at 555-123-4567 or alice@company.com',
        'SSN: 123-45-6789, Phone: 555-1234',
        'Credit card: 4532-1488-0343-6467, CVV: 123',
        'IP: 192.168.1.1, API Key: sk_live_abcdef123456',
        'Dr. Mary Jane Watson lives at 90210',
    ]
    
    print("\n" + "="*70)
    print("PII SCRUBBER TEST")
    print("="*70)
    
    for text in test_texts:
        result = scrubber.scrub(text)
        print(f"\nOriginal: {text}")
        print(f"Scrubbed: {result['scrubbed']}")
        print(f"Entities: {result['entities']}")
        print(f"Counts: {result['count']}")
    
    print("\n" + "="*70)
