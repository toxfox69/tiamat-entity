#!/usr/bin/env python3
"""
TIAMAT Privacy Proxy v1
Core inference layer: scrub → proxy → return
"""

from typing import Any, Dict, Optional, List, Tuple
import json
import os
import sys
import time
import httpx

sys.path.insert(0, '/root/sandbox')
from pii_scrubber import PIIScrubber

# API Keys from environment
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

PROVIDERS = {
    'groq': {
        'url': 'https://api.groq.com/openai/v1/chat/completions',
        'key': GROQ_API_KEY,
        'models': ['llama-3.3-70b', 'mixtral-8x7b', 'gemma-2-9b'],
        'cost_per_1k': {'input': 0.00005, 'output': 0.00015}
    },
    'anthropic': {
        'url': 'https://api.anthropic.com/v1/messages',
        'key': ANTHROPIC_API_KEY,
        'models': ['claude-sonnet-4.5', 'claude-opus-4.1', 'claude-haiku-4.5'],
        'cost_per_1k': {'input': 0.003, 'output': 0.015}
    },
    'openai': {
        'url': 'https://api.openai.com/v1/chat/completions',
        'key': OPENAI_API_KEY,
        'models': ['gpt-4o', 'gpt-4-turbo', 'o1'],
        'cost_per_1k': {'input': 0.005, 'output': 0.015}
    }
}

class PrivacyProxy:
    """Privacy-first LLM proxy with automatic PII scrubbing"""
    
    def __init__(self):
        """Initialize proxy with scrubber"""
        self.scrubber = PIIScrubber()
        self.call_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
    
    def scrub_messages(self, messages: List[Dict]) -> Tuple[List[Dict], Dict]:
        """
        Scrub PII from all messages.
        Returns: (scrubbed_messages, entity_map)
        """
        entity_map = {}
        scrubbed = []
        
        for msg in messages:
            content = msg.get('content', '')
            if isinstance(content, str):
                result = self.scrubber.scrub(content)
                scrubbed_content = result['scrubbed']
                # Merge entity maps
                entity_map.update(result.get('entities', {}))
                scrubbed.append({
                    'role': msg['role'],
                    'content': scrubbed_content
                })
            else:
                scrubbed.append(msg)
        
        return scrubbed, entity_map
    
    def validate_provider(self, provider: str) -> bool:
        """Check if provider is supported"""
        return provider.lower() in PROVIDERS
    
    def validate_model(self, provider: str, model: str) -> bool:
        """Check if model is supported by provider"""
        if not self.validate_provider(provider):
            return False
        return model in PROVIDERS[provider.lower()]['models']
    
    def estimate_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for tokens"""
        provider_key = provider.lower()
        if provider_key not in PROVIDERS:
            return 0.0
        
        rates = PROVIDERS[provider_key]['cost_per_1k']
        input_cost = (input_tokens / 1000) * rates['input']
        output_cost = (output_tokens / 1000) * rates['output']
        total = input_cost + output_cost
        
        # Add 20% margin
        return total * 1.2
    
    def call(self, provider: str, model: str, messages: List[Dict], 
             max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """
        Make a proxied LLM call with automatic scrubbing.
        """
        # Validate
        if not self.validate_provider(provider):
            return {'error': f'Provider {provider} not supported'}
        
        if not self.validate_model(provider, model):
            return {'error': f'Model {model} not supported by {provider}'}
        
        # Scrub input
        scrubbed_messages, entity_map = self.scrub_messages(messages)
        
        # Make request (simplified — no actual HTTP call in test)
        self.call_count += 1
        
        # Mock response for testing
        result = {
            'status': 'ok',
            'provider': provider,
            'model': model,
            'input_tokens': sum(len(m.get('content', '').split()) for m in scrubbed_messages) * 4,
            'output_tokens': 100,
            'response': f'Mocked response from {provider}',
            'cost': 0.0001,
            'margin': 0.00002,
            'total_cost_with_margin': 0.00012
        }
        
        self.total_cost += result['total_cost_with_margin']
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get proxy statistics"""
        return {
            'calls': self.call_count,
            'total_cost': self.total_cost,
            'avg_cost_per_call': self.total_cost / max(self.call_count, 1)
        }
