# pii_scrubber.py — Lightweight PII detection and scrubbing
import re
from typing import Dict, List
from collections import defaultdict

class PIIScrubber:
    """Lightweight PII detection without heavy ML dependencies"""
    
    PATTERNS = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b(?:\+?1[-\.\s]?)?\(?[0-9]{3}\)?[-\.\s]?[0-9]{3}[-\.\s]?[0-9]{4}\b',
        'ssn': r'\b(?!000|666|9\d{2})\d{3}-?\d{2}-?\d{4}\b',
        'credit_card': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11})\b',
        'ipv4': r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
        'api_key_sk': r'\bsk[_-]?[a-zA-Z0-9]{20,}\b',
        'api_key_pk': r'\bpk[_-]?[a-zA-Z0-9]{20,}\b',
        'bearer_token': r'\bbearer\s+[a-zA-Z0-9\-._~+/]+=*\b',
        'aws_key': r'\bAKIA[0-9A-Z]{16}\b',
        'github_token': r'\bghp_[a-zA-Z0-9]{36}\b',
    }
    
    def __init__(self):
        self.compiled_patterns = {k: re.compile(v, re.IGNORECASE) for k, v in self.PATTERNS.items()}
        self.entity_counter = defaultdict(int)
    
    def detect_pii(self, text: str) -> Dict:
        """Detect PII in text"""
        entities = []
        
        for pii_type, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                entities.append({
                    'type': pii_type,
                    'value': match.group(0),
                    'start': match.start(),
                    'end': match.end(),
                    'confidence': 0.95
                })
        
        # Sort and deduplicate overlaps
        entities = sorted(entities, key=lambda x: x['start'])
        entities = self._deduplicate_overlaps(entities)
        
        return {
            'pii_found': len(entities) > 0,
            'entity_count': len(entities),
            'entities': entities
        }
    
    def _deduplicate_overlaps(self, entities: List[Dict]) -> List[Dict]:
        """Remove overlapping entities, keep highest confidence"""
        if not entities:
            return entities
        
        deduped = [entities[0]]
        for entity in entities[1:]:
            if entity['start'] < deduped[-1]['end']:
                if entity['confidence'] > deduped[-1]['confidence']:
                    deduped[-1] = entity
            else:
                deduped.append(entity)
        
        return deduped
    
    def scrub_text(self, text: str, keep_type: bool = True) -> Dict:
        """Scrub PII from text, return scrubbed + mappings"""
        detection = self.detect_pii(text)
        entities = detection['entities']
        
        if not entities:
            return {
                'scrubbed': text,
                'replacements': {},
                'pii_count': 0,
                'high_confidence_count': 0
            }
        
        # Replace from end to start to preserve positions
        entities_sorted = sorted(entities, key=lambda x: x['start'], reverse=True)
        scrubbed = text
        replacements = {}
        high_confidence = 0
        
        for entity in entities_sorted:
            pii_type = entity['type']
            original_value = entity['value']
            confidence = entity['confidence']
            
            self.entity_counter[pii_type] += 1
            token = f'[{pii_type.upper()}_{self.entity_counter[pii_type]}]' if keep_type else '[REDACTED]'
            
            start, end = entity['start'], entity['end']
            scrubbed = scrubbed[:start] + token + scrubbed[end:]
            
            replacements[token] = {
                'original': original_value,
                'type': pii_type,
                'confidence': confidence
            }
            
            if confidence >= 0.9:
                high_confidence += 1
        
        return {
            'scrubbed': scrubbed,
            'replacements': replacements,
            'pii_count': len(entities),
            'high_confidence_count': high_confidence
        }
    
    def reset_counter(self):
        """Reset entity counter for fresh scrubbing"""
        self.entity_counter = defaultdict(int)


# Global instance
scrubber = PIIScrubber()

def detect_pii(text: str) -> Dict:
    return scrubber.detect_pii(text)

def scrub_text(text: str, keep_type: bool = True) -> Dict:
    scrubber.reset_counter()
    return scrubber.scrub_text(text, keep_type)
