#!/usr/bin/env python3
"""
PII Scrubber for Privacy Proxy

Detects and masks personally identifiable information:
- Emails, phone numbers, SSNs, credit cards
- IP addresses, API keys, crypto wallets
- Names (via spaCy NER if available, else regex)
- Medical info, URLs, account numbers

Returns scrubbed text with placeholder->original mapping.
"""

import re
import json
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict


@dataclass
class ScrubbingResult:
    """Result of PII scrubbing operation."""
    scrubbed: str  # Text with PII replaced by [TYPE_N]
    entities: Dict[str, str]  # {"[EMAIL_1]": "john@example.com", ...}
    pii_detected: List[str]  # ["EMAIL", "SSN", "PHONE", ...]
    count: int  # Total PII items found
    
    def to_json(self):
        return json.dumps(asdict(self))


class PIIScrubber:
    """Regex + NER-based PII detector and scrubber."""
    
    # Regex patterns for common PII types
    PATTERNS = {
        'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'PHONE': r'(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b|\d{3}-\d{3}-\d{4}',
        'SSN': r'\b\d{3}-\d{2}-\d{4}\b',
        'CREDIT_CARD': r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        'IP_ADDRESS': r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        'API_KEY_OPENAI': r'sk-[A-Za-z0-9]{20,}',
        'API_KEY_STRIPE': r'(?:pk|rk|sk)_live_[A-Za-z0-9]{20,}',
        'API_KEY_GENERIC': r'(?:api[_-]?)?key[_-]?[A-Za-z0-9]{16,}',
        'CRYPTO_WALLET_ETH': r'0x[a-fA-F0-9]{40}\b',
        'CRYPTO_WALLET_BTC': r'\b[13][a-zA-Z0-9]{25,34}\b',
        'URL': r'https?://[^\s]+',
        'MEDICAL_ICD': r'\b[A-Z]\d{2}(?:\.\d{1,2})?\b',  # ICD-10 format
        'MEDICAL_CPT': r'\b\d{5}[A-Z]?\b',  # CPT code
    }
    
    # Common first/last names (subset for regex fallback)
    COMMON_NAMES_PATTERN = r'\b(?:John|Mary|James|Robert|Michael|William|David|Richard|Joseph|Thomas|Charles|Christopher|Daniel|Matthew|Anthony|Donald|Mark|Steven|Paul|Andrew|Joshua|Kenneth|Kevin|Brian|George|Edward|Ronald|Timothy|Jason|Jeffrey|Ryan|Jacob|Gary|Nicholas|Eric|Jonathan|Stephen|Larry|Justin|Scott|Brandon|Benjamin|Samuel|Frank|Gregory|Alexander|Raymond|Patrick|Jack|Dennis|Jerry|Tyler|Aaron|Jose|Adam|Henry|Douglas|Zachary|Peter|Kyle|Walter|Harold|Keith|Christian|Terry|Sean|Austin|Gerald|Carl|Roger|Arthur|Ryan|Billy|Bruce|Louis|Joe|John|Emma|Olivia|Ava|Sophia|Isabella|Mia|Charlotte|Amelia|Harper|Evelyn|Abigail|Elizabeth|Emily|Avery|Ella|Scarlett|Victoria|Madison|Luna|Grace|Chloe|Penelope|Layla|Riley|Zoey|Nora|Lily|Eleanor)[\s]+(?:Smith|Johnson|Williams|Jones|Brown|Davis|Miller|Wilson|Moore|Taylor|Anderson|Thomas|Jackson|White|Harris|Martin|Thompson|Garcia|Martinez|Robinson|Clark|Rodriguez|Lewis|Lee|Walker|Hall|Allen|Young|Hernandez|King|Wright|Lopez|Hill|Scott|Green|Adams|Nelson|Carter|Mitchell|Roberts|Phillips|Campbell|Parker|Evans|Edwards|Collins|Reeves|Stewart|Morris|Rogers|Rogers|Morgan|Peterson|Cooper|Reed|Bell|Gomez|Murray|Freeman|Wells|Webb|Simpson|Stevens|Tucker|Porter|Hunter|Hicks|Crawford|Henry|Boyd|Mason|Moreno|Kennedy|Warren|Dixon|Ramos|Reeves|Burns|Gordon|Shelton|Nicholson|Malone|Humphreys|Hicks|Crawford|Henry|Boyd|Mason|Moreno|Kennedy|Warren|Dixon|Ramos)\b',
    
    def __init__(self):
        self.entity_counter = {}  # Track count per type
        self.placeholder_map = {}  # {placeholder: original_value}
        self.detected_types = set()  # Types found
        
    def scrub(self, text: str) -> ScrubbingResult:
        """Scrub PII from text and return result with mappings."""
        if not text:
            return ScrubbingResult(
                scrubbed=text,
                entities={},
                pii_detected=[],
                count=0
            )
        
        scrubbed_text = text
        findings = []  # (type, start, end, value)
        
        # Find all PII matches
        for pii_type, pattern in self.PATTERNS.items():
            for match in re.finditer(pattern, scrubbed_text, re.IGNORECASE):
                original = match.group(0)
                findings.append((pii_type, match.start(), match.end(), original))
                self.detected_types.add(pii_type)
        
        # Try NER for names if spaCy available
        try:
            import spacy
            nlp = spacy.load('en_core_web_sm')
            doc = nlp(text)
            for ent in doc.ents:
                if ent.label_ == 'PERSON':
                    findings.append(('NAME', ent.start_char, ent.end_char, ent.text))
                    self.detected_types.add('NAME')
        except (ImportError, OSError):
            # spaCy not available or model not loaded
            # Fall back to regex patterns for names
            for match in re.finditer(self.COMMON_NAMES_PATTERN, text):
                findings.append(('NAME', match.start(), match.end(), match.group(0)))
                self.detected_types.add('NAME')
        
        # Sort by position (reverse order to avoid offset issues)
        findings.sort(key=lambda x: x[1], reverse=True)
        
        # Replace findings with placeholders
        total_found = 0
        for pii_type, start, end, original_value in findings:
            # Create placeholder
            if pii_type not in self.entity_counter:
                self.entity_counter[pii_type] = 0
            self.entity_counter[pii_type] += 1
            
            placeholder = f"[{pii_type}_{self.entity_counter[pii_type]}]"
            self.placeholder_map[placeholder] = original_value
            
            # Replace in text
            scrubbed_text = scrubbed_text[:start] + placeholder + scrubbed_text[end:]
            total_found += 1
        
        return ScrubbingResult(
            scrubbed=scrubbed_text,
            entities=self.placeholder_map,
            pii_detected=sorted(list(self.detected_types)),
            count=total_found
        )


def scrub_pii(text: str) -> Dict:
    """Convenience function: scrub text and return as dict."""
    scrubber = PIIScrubber()
    result = scrubber.scrub(text)
    return asdict(result)


if __name__ == '__main__':
    # Test examples
    test_cases = [
        "My name is John Doe, email john@example.com, SSN 123-45-6789, API key sk-abc123xyz",
        "Contact: jane.smith@company.org, phone (555) 123-4567, CC 4532-1234-5678-9010",
        "Server IP 192.168.1.1, wallet 0x742d35Cc6634C0532925a3b844Bc9e7595f42cA0",
        "Patient ID: A123456, ICD: E11.9, medical condition diabetes, bill to account 98765432",
        "No PII here, just a regular sentence about privacy",
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n=== Test {i} ===")
        print(f"Input:  {test}")
        result = scrub_pii(test)
        print(f"Output: {result['scrubbed']}")
        print(f"Found:  {result['pii_detected']} (count={result['count']})")
        if result['entities']:
            print(f"Mapping: {result['entities']}")
