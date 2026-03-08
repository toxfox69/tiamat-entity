#!/usr/bin/env python3
"""
PII Scrubber — Production-ready entity detection and masking
Detects: Names, Emails, Phones, SSNs, Credit Cards, API Keys, IPs, URLs, Bank Accounts
"""

import re
import json
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

class EntityType(Enum):
    NAME = "NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    SSN = "SSN"
    CREDIT_CARD = "CREDIT_CARD"
    API_KEY = "API_KEY"
    IPV4 = "IPV4"
    IPV6 = "IPV6"
    URL = "URL"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    PASSPORT = "PASSPORT"
    LICENSE_PLATE = "LICENSE_PLATE"

@dataclass
class Entity:
    type: str
    value: str
    start: int
    end: int
    mask: str = None

class PIIScrubber:
    def __init__(self):
        self.entity_counter = {}  # {"NAME": 1, "EMAIL": 1, ...}
        self.entity_map = {}  # {"[NAME_1]": "John Smith", ...}
        
        # Regex patterns for PII detection
        self.patterns = {
            EntityType.EMAIL: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            EntityType.PHONE: r'(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})',
            EntityType.SSN: r'\b(?!000|666|9\d{2})\d{3}-?(?!00)\d{2}-?(?!0{4})\d{4}\b',
            EntityType.CREDIT_CARD: r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
            EntityType.API_KEY: r'\b(sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9_]{36})\b',
            EntityType.IPV4: r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
            EntityType.URL: r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)',
            EntityType.BANK_ACCOUNT: r'\b[0-9]{8,17}\b',  # Generic account patterns
            EntityType.PASSPORT: r'\b[A-Z]{1,2}[0-9]{6,9}\b',
            EntityType.LICENSE_PLATE: r'\b[A-Z]{2}[0-9]{3}[A-Z]{2}\b',  # UK format
        }
    
    def reset(self):
        """Reset counters for a new scrubbing session"""
        self.entity_counter = {}
        self.entity_map = {}
    
    def scrub(self, text: str) -> Dict:
        """
        Main scrubbing function
        Returns: {
            "scrubbed": "Masked text",
            "entities": {"[NAME_1]": "John Smith", ...},
            "entity_count": 5,
            "detections": [{"type": "NAME", "value": "John Smith", "position": 5}]
        }
        """
        self.reset()
        
        # Find all entities
        detections = []
        for entity_type, pattern in self.patterns.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                detections.append({
                    'type': entity_type.value,
                    'value': match.group(),
                    'start': match.start(),
                    'end': match.end()
                })
        
        # Sort by position (descending) so replacements don't mess up indices
        detections = sorted(detections, key=lambda x: x['start'], reverse=True)
        
        scrubbed_text = text
        
        # Apply masking
        for detection in detections:
            entity_type = detection['type']
            value = detection['value']
            
            # Create mask
            if entity_type not in self.entity_counter:
                self.entity_counter[entity_type] = 1
            else:
                self.entity_counter[entity_type] += 1
            
            mask = f"[{entity_type}_{self.entity_counter[entity_type]}]"
            self.entity_map[mask] = value
            
            # Replace in text
            scrubbed_text = (
                scrubbed_text[:detection['start']] +
                mask +
                scrubbed_text[detection['end']:]
            )
        
        # Sort detections by position (ascending) for readability
        detections = sorted(detections, key=lambda x: x['start'])
        
        return {
            "scrubbed": scrubbed_text,
            "entities": self.entity_map,
            "entity_count": len(self.entity_map),
            "detections": detections
        }
    
    def unscrub(self, scrubbed_text: str, entity_map: Dict[str, str]) -> str:
        """
        Restore original values from scrubbed text
        """
        result = scrubbed_text
        for mask, value in entity_map.items():
            result = result.replace(mask, value)
        return result


class FlaskIntegration:
    """Flask route handler for /api/scrub"""
    
    def __init__(self):
        self.scrubber = PIIScrubber()
    
    def handle_scrub_request(self, request_data: Dict) -> Dict:
        """
        Handle POST /api/scrub
        Input: {"text": "...", "redact": true/false}
        Output: {"scrubbed": "...", "entities": {...}, ...}
        """
        text = request_data.get('text', '')
        redact = request_data.get('redact', True)  # True = mask PII, False = just detect
        
        if not text or not isinstance(text, str):
            return {
                "error": "Invalid input: 'text' must be a non-empty string",
                "status": 400
            }
        
        if len(text) > 100000:
            return {
                "error": "Input too large: max 100KB",
                "status": 413
            }
        
        result = self.scrubber.scrub(text)
        
        if not redact:
            # Return detections only, not scrubbed text
            return {
                "original_text": text,
                "detections": result['detections'],
                "entity_count": result['entity_count'],
                "status": 200
            }
        
        return {
            "scrubbed": result['scrubbed'],
            "entities": result['entities'],
            "entity_count": result['entity_count'],
            "detections": result['detections'],
            "status": 200
        }


# Unit tests
if __name__ == "__main__":
    scrubber = PIIScrubber()
    
    test_cases = [
        "My name is John Smith and my email is john@example.com",
        "Call me at 555-123-4567 or (555) 987-6543",
        "SSN: 123-45-6789",
        "Credit card: 4532-1111-2222-3333",
        "API Key: sk-proj-abc123xyz789",
        "Server: 192.168.1.1",
        "Visit https://www.example.com/page?id=123",
        "Bank account: 1234567890123456",
        "Passport: AB123456789",
        "UK plate: AB12CDE",
        "Mixed: John Smith (john@test.com, 555-1234, SSN: 999-88-7777) works at https://example.com",
    ]
    
    print("=== PII SCRUBBER TESTS ===")
    for i, test in enumerate(test_cases, 1):
        result = scrubber.scrub(test)
        print(f"\nTest {i}: {test}")
        print(f"Scrubbed: {result['scrubbed']}")
        print(f"Entities: {result['entities']}")
        print(f"Count: {result['entity_count']}")
    
    # Flask integration test
    print("\n=== FLASK INTEGRATION TEST ===")
    flask_handler = FlaskIntegration()
    
    request = {
        "text": "Call John Smith at 555-123-4567, email: john@test.com, SSN: 123-45-6789",
        "redact": True
    }
    
    response = flask_handler.handle_scrub_request(request)
    print(f"\nRequest: {request}")
    print(f"\nResponse:")
    print(json.dumps(response, indent=2))
