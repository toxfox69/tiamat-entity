#!/usr/bin/env python3
"""
TIAMAT PII Scrubber — Detects and redacts personally identifiable information.
No external API calls. Regex + simple pattern matching for offline operation.
"""

import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import json

@dataclass
class ScrubbingResult:
    """Result of a scrubbing operation"""
    scrubbed: str
    entities: Dict[str, str]  # {placeholder: original_value}
    pii_types: List[str]  # List of PII types found
    original: str

class PIIScrubber:
    """Detect and scrub PII from text"""
    
    # PII patterns (regex) — ORDER MATTERS: more specific patterns first
    PATTERNS = {
        # Most specific patterns first to avoid conflicts
        'SSN': r'\b(?!000|666|9\d{2})\d{3}-?(?!00)\d{2}-?(?!0000)\d{4}\b',
        'CREDIT_CARD': r'\b(?:\d{4}[-\s]?){3}\d{4}\b(?![-\d])',
        'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'PHONE': r'\b(?:\+?1[-.]?)?(?:\(?[0-9]{3}\)?[-.]?)?[0-9]{3}[-.]?[0-9]{4}\b',
        'IP_ADDRESS': r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
        'API_KEY': r'\b(?:sk-[A-Za-z0-9-]{20,}|Bearer\s+[A-Za-z0-9._-]{32,})\b',
    }
    
    # Common first/last names for name detection (basic list)
    COMMON_NAMES = {
        'john', 'james', 'robert', 'michael', 'william', 'david', 'richard', 'joseph',
        'thomas', 'charles', 'christopher', 'daniel', 'matthew', 'mark', 'donald',
        'steven', 'paul', 'andrew', 'joshua', 'kenneth', 'kevin', 'brian', 'george',
        'edward', 'ronald', 'anthony', 'frank', 'ryan', 'gary', 'nicholas', 'eric',
        'jonathan', 'stephen', 'larry', 'justin', 'scott', 'brandon', 'benjamin',
        'samuel', 'gregory', 'raymond', 'alexander', 'patrick', 'jack', 'dennis',
        'jerry', 'tyler', 'aaron', 'jose', 'adam', 'henry', 'douglas', 'peter',
        # female names
        'mary', 'patricia', 'jennifer', 'linda', 'barbara', 'elizabeth', 'susan',
        'jessica', 'sarah', 'karen', 'nancy', 'lisa', 'betty', 'margaret', 'sandra',
        'ashley', 'kimberly', 'emily', 'donna', 'michelle', 'dorothy', 'carol',
        'amanda', 'melissa', 'deborah', 'stephanie', 'rebecca', 'sharon', 'laura',
        'cynthia', 'kathleen', 'amy', 'angela', 'shirley', 'anna', 'brenda',
        'pamela', 'emma', 'nicole', 'helen', 'samantha', 'katherine', 'christine',
        'debra', 'rachel', 'catherine', 'carolyn', 'janet', 'ruth', 'maria',
        # last names
        'smith', 'johnson', 'williams', 'jones', 'brown', 'davis', 'miller',
        'wilson', 'moore', 'taylor', 'anderson', 'thomas', 'jackson', 'white',
        'harris', 'martin', 'thompson', 'garcia', 'martinez', 'robinson', 'clark',
        'rodriguez', 'lewis', 'lee', 'walker', 'hall', 'allen', 'young', 'king',
        'wright', 'lopez', 'hill', 'scott', 'green', 'adams', 'nelson', 'carter',
        'roberts', 'edwards', 'collins', 'stewart', 'sanchez', 'morris', 'rogers',
    }
    
    def __init__(self):
        """Initialize scrubber with compiled regex patterns"""
        self.compiled_patterns = {
            k: re.compile(v, re.IGNORECASE) for k, v in self.PATTERNS.items()
        }
        self.entity_counter = {}
    
    def scrub(self, text: str, preserve_mapping: bool = True) -> Dict:
        """Scrub PII from text
        
        Args:
            text: Input text containing potential PII
            preserve_mapping: If True, return mapping of placeholders to original values
        
        Returns:
            {
                'scrubbed': 'text with [TYPE_N] placeholders',
                'entities': {'TYPE_1': 'original_value'},  # if preserve_mapping=True
                'pii_types': ['EMAIL', 'PHONE', ...],
                'original': original text
            }
        """
        self.entity_counter = {}  # Reset counter for this scrub
        scrubbed_text = text
        entities = {}
        pii_types_found = set()
        
        # Scrub each pattern in order of specificity (most specific first)
        # Order: SSN, CREDIT_CARD, EMAIL, PHONE, IP_ADDRESS, API_KEY
        patterns_order = ['SSN', 'CREDIT_CARD', 'EMAIL', 'PHONE', 'IP_ADDRESS', 'API_KEY']
        
        for pattern_name in patterns_order:
            scrubbed_text, pattern_entities = self._scrub_pattern(pattern_name, scrubbed_text, preserve_mapping)
            entities.update(pattern_entities)
            if pattern_entities:
                pii_types_found.add(pattern_name)
        
        # Simple name detection (look for capitalized words that match common names)
        scrubbed_text, name_entities = self._scrub_names(scrubbed_text, preserve_mapping)
        entities.update(name_entities)
        if name_entities:
            pii_types_found.add('NAME')
        
        # Build response
        result = {
            'scrubbed': scrubbed_text,
            'pii_types': sorted(list(pii_types_found)),
            'original': text,
        }
        
        if preserve_mapping:
            result['entities'] = entities
        
        return result
    
    def _scrub_pattern(self, pattern_name: str, text: str, preserve_mapping: bool) -> Tuple[str, Dict]:
        """Scrub a specific pattern from text
        
        Returns:
            (scrubbed_text, {placeholder: original_value})
        """
        pattern = self.compiled_patterns.get(pattern_name)
        if not pattern:
            return text, {}
        
        entities = {}
        counter = self.entity_counter.get(pattern_name, 1)
        
        def replace_match(match):
            nonlocal counter
            original = match.group(0)
            placeholder = f'[{pattern_name}_{counter}]'
            if preserve_mapping:
                entities[placeholder] = original
            counter += 1
            return placeholder
        
        scrubbed = pattern.sub(replace_match, text)
        self.entity_counter[pattern_name] = counter
        
        return scrubbed, entities
    
    def _scrub_names(self, text: str, preserve_mapping: bool) -> Tuple[str, Dict]:
        """Detect and scrub common names
        
        Strategy: Look for capitalized words that match known names
        Example: "John Smith" → "John" is in name list, capitalized → scrub it
        """
        entities = {}
        counter = self.entity_counter.get('NAME', 1)
        
        # Find all capitalized words
        words = text.split()
        new_words = []
        i = 0
        
        while i < len(words):
            word = words[i]
            # Check if word (stripped of punctuation) matches a known name
            word_clean = re.sub(r'[^A-Za-z0-9]', '', word).lower()
            
            # Only scrub if:
            # 1. Word starts with capital letter
            # 2. Word (after cleaning) is in the known names list
            # 3. Word is not a placeholder (avoid double-scrubbing)
            if word[0].isupper() and word_clean in self.COMMON_NAMES and not word.startswith('['):
                placeholder = f'[NAME_{counter}]'
                if preserve_mapping:
                    entities[placeholder] = word
                new_words.append(placeholder)
                counter += 1
            else:
                new_words.append(word)
            
            i += 1
        
        self.entity_counter['NAME'] = counter
        scrubbed = ' '.join(new_words)
        
        return scrubbed, entities


def demo():
    """Demo the scrubber"""
    scrubber = PIIScrubber()
    
    test_text = """
    Hello, my name is John Smith. You can reach me at john.smith@example.com or 555-123-4567.
    My SSN is 123-45-6789 and my credit card is 4532-1234-5678-9010.
    I work at 192.168.1.1 and my API key is sk-proj-abcdef1234567890abcdef1234567890.
    """
    
    result = scrubber.scrub(test_text, preserve_mapping=True)
    
    print("ORIGINAL:")
    print(result['original'])
    print("\n" + "="*60 + "\n")
    print("SCRUBBED:")
    print(result['scrubbed'])
    print("\n" + "="*60 + "\n")
    print(f"PII TYPES FOUND: {result['pii_types']}")
    print(f"\nENTITY MAPPING:")
    for placeholder, original in result['entities'].items():
        print(f"  {placeholder:20s} → {original}")

if __name__ == '__main__':
    demo()
