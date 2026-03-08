#!/usr/bin/env python3
"""
PII (Personally Identifiable Information) Scrubber
Removes sensitive data from text and returns placeholder + entity map.

Example:
  Input: "My name is John Smith, email john@example.com, SSN 123-45-6789"
  Output: {
    "scrubbed": "My name is [NAME_1], email [EMAIL_1], SSN [SSN_1]",
    "entities": {
      "NAME_1": "John Smith",
      "EMAIL_1": "john@example.com",
      "SSN_1": "123-45-6789"
    }
  }
"""

import re
from typing import Dict, List, Tuple
from collections import defaultdict


class PIIScrubber:
    """Detects and masks personally identifiable information."""

    def __init__(self):
        """Initialize PII patterns and compile regexes for performance."""
        
        # Compiled regex patterns (order matters: most specific first)
        self.patterns = {
            # Social Security Numbers (XXX-XX-XXXX or XXXXXXXXX)
            'SSN': re.compile(r'\b\d{3}-?\d{2}-?\d{4}\b'),
            
            # Credit Card Numbers (4111 1111 1111 1111 format, spaces or dashes)
            'CREDIT_CARD': re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
            
            # Email addresses
            'EMAIL': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            
            # Phone numbers (various formats)
            'PHONE': re.compile(r'\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b'),
            
            # IPv4 addresses
            'IP_ADDRESS': re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            
            # IPv6 addresses (simplified)
            'IPV6': re.compile(r'(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}'),
            
            # API Keys (common patterns)
            'API_KEY': re.compile(r'\b(?:sk-|pk-|api[_-]?key[:]?\s*)[A-Za-z0-9_-]{20,}\b', re.IGNORECASE),
            
            # Bearer tokens
            'BEARER_TOKEN': re.compile(r'Bearer\s+[A-Za-z0-9._-]+'),
            
            # US Street addresses (simplified: number + street)
            'ADDRESS': re.compile(r'\b\d{1,5}\s+[A-Za-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Circle|Cir|Court|Ct|Way|Parkway|Pkwy)\b', re.IGNORECASE),
            
            # AWS Access Keys (AKIAIOSFODNN7EXAMPLE format)
            'AWS_KEY': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
            
            # Names (First Last - heuristic, catches common patterns)
            # This is intentionally conservative to avoid false positives
            'NAME': re.compile(r'\b(?:[A-Z][a-z]+\s+[A-Z][a-z]+)\b'),
        }
        
        self.entity_counters = defaultdict(int)

    def scrub(self, text: str) -> Dict[str, any]:
        """
        Scrub PII from text and return scrubbed text + entity map.
        
        Args:
            text: Input text potentially containing PII
            
        Returns:
            {
                "scrubbed": "Text with [TYPE_N] placeholders",
                "entities": {"TYPE_1": "original_value", ...},
                "pii_types_found": ["EMAIL", "SSN", ...]
            }
        """
        self.entity_counters.clear()
        entities = {}
        scrubbed_text = text
        pii_types_found = set()

        # Apply patterns in order (most specific first)
        pattern_order = ['SSN', 'CREDIT_CARD', 'AWS_KEY', 'API_KEY', 'BEARER_TOKEN', 
                        'EMAIL', 'PHONE', 'IPV6', 'IP_ADDRESS', 'ADDRESS', 'NAME']
        
        for pii_type in pattern_order:
            pattern = self.patterns[pii_type]
            matches = pattern.finditer(scrubbed_text)
            
            for match in matches:
                original_value = match.group(0)
                self.entity_counters[pii_type] += 1
                entity_key = f"{pii_type}_{self.entity_counters[pii_type]}"
                
                entities[entity_key] = original_value
                pii_types_found.add(pii_type)
                
                # Replace in scrubbed text
                placeholder = f"[{entity_key}]"
                scrubbed_text = scrubbed_text.replace(original_value, placeholder, 1)
        
        return {
            "scrubbed": scrubbed_text,
            "entities": entities,
            "pii_types_found": sorted(list(pii_types_found))
        }

    def detect_pii_types(self, text: str) -> List[str]:
        """
        Scan text and return list of PII types detected.
        
        Args:
            text: Input text to scan
            
        Returns:
            List of PII type strings found
        """
        result = self.scrub(text)
        return result["pii_types_found"]

    def restore(self, scrubbed_text: str, entities: Dict[str, str]) -> str:
        """
        Restore original values from scrubbed text and entity map.
        
        Args:
            scrubbed_text: Text with [TYPE_N] placeholders
            entities: Map of {"TYPE_1": "original_value", ...}
            
        Returns:
            Original text with placeholders replaced
        """
        restored = scrubbed_text
        for key, value in entities.items():
            placeholder = f"[{key}]"
            restored = restored.replace(placeholder, value)
        return restored


# =============================================================================
# TEST SUITE
# =============================================================================

def test_scrubber():
    """Test PII scrubber with real examples."""
    scrubber = PIIScrubber()
    
    test_cases = [
        # Basic name + email + SSN
        "My name is John Smith and my email is john@example.com. My SSN is 123-45-6789.",
        
        # Phone number
        "Call me at (555) 123-4567 or 555-123-4567",
        
        # IP addresses
        "Server at 192.168.1.1 contacted 10.0.0.1",
        
        # Credit card
        "My card is 4111-1111-1111-1111 or 5555 5555 5555 4444",
        
        # API keys
        "API key: sk-proj-abc123defg456hij789klmno",
        "Bearer token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        
        # AWS key
        "AWS key: AKIAIOSFODNN7EXAMPLE",
        
        # Address
        "123 Main Street, Anytown USA",
        
        # Healthcare example
        "Patient: Jane Doe, DOB: 123-45-6789, Contact: jane.doe@hospital.org, Phone: 555-123-4567",
        
        # Multi-PII
        "Data breach: Employee Tom Jones (SSN 111-22-3333, email tom@company.com, IP 203.0.113.45) accessed patient record for Sarah Williams (DOB 456-78-9012).",
    ]
    
    print("\n" + "="*80)
    print("PII SCRUBBER TEST SUITE")
    print("="*80)
    
    for i, test_text in enumerate(test_cases, 1):
        print(f"\n[TEST {i}]")
        print(f"INPUT:  {test_text[:100]}{'...' if len(test_text) > 100 else ''}")
        
        result = scrubber.scrub(test_text)
        
        print(f"SCRUBBED: {result['scrubbed'][:100]}{'...' if len(result['scrubbed']) > 100 else ''}")
        print(f"PII FOUND: {', '.join(result['pii_types_found']) if result['pii_types_found'] else 'None'}")
        print(f"ENTITIES: {result['entities']}")
        
        # Test restoration
        restored = scrubber.restore(result['scrubbed'], result['entities'])
        print(f"RESTORED: {restored[:100]}{'...' if len(restored) > 100 else ''}")
        print(f"MATCHES ORIGINAL: {restored == test_text}")


if __name__ == "__main__":
    test_scrubber()
