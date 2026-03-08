#!/usr/bin/env python3
"""
Privacy Proxy — Phase 2: Proxy Core

Routes requests through multiple LLM providers with PII scrubbing.
Supports: Anthropic, OpenAI, Groq, Gemini, OpenRouter
"""

import os
import time
import json
from typing import Dict, List, Any, Optional

# Local import (same directory)
try:
    from scrubber import PIIScrubber
except ImportError:
    # Fallback for sys.path scenarios
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from scrubber import PIIScrubber


class PrivacyProxyCore:
    """
    Proxy requests to LLM providers with automatic PII scrubbing.
    
    Usage:
      proxy = PrivacyProxyCore()
      result = proxy.call(
        provider='anthropic',
        model='claude-sonnet',
        messages=[{'role': 'user', 'content': 'My name is John...'}]
      )
    """
    
    def __init__(self):
        self.scrubber = PIIScrubber()
        self.api_keys = {
            'anthropic': os.getenv('ANTHROPIC_API_KEY'),
            'openai': os.getenv('OPENAI_API_KEY'),
            'groq': os.getenv('GROQ_API_KEY'),
            'gemini': os.getenv('GEMINI_API_KEY'),
        }
        self.provider_costs = {
            'anthropic': {'claude-sonnet': 0.003},
            'openai': {'gpt-4o': 0.015},
            'groq': {'llama-3.3-70b': 0.0001},
            'gemini': {'gemini-2.0': 0.001},
        }
    
    def scrub_and_proxy(self, provider: str, model: str, messages: List[Dict], scrub: bool = True) -> Dict:
        """
        Scrub PII from messages, proxy to provider, return response.
        """
        try:
            # Scrub input messages
            scrubbed_messages = []
            entity_map = {}
            
            if scrub:
                for msg in messages:
                    content = msg.get('content', '')
                    result = self.scrubber.scrub(content)
                    scrubbed_messages.append({
                        'role': msg['role'],
                        'content': result['scrubbed']
                    })
                    entity_map.update(result.get('entities', {}))
            else:
                scrubbed_messages = messages
            
            # Calculate cost
            cost = self.calculate_cost(provider, model, scrubbed_messages)
            
            return {
                'success': True,
                'provider': provider,
                'model': model,
                'cost': cost,
                'messages_scrubbed': len(scrubbed_messages),
                'entities_detected': len(entity_map),
                'message': 'Ready to proxy to provider (real proxy in Phase 3)'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def calculate_cost(self, provider: str, model: str, messages: List[Dict]) -> float:
        """
        Estimate cost based on provider and model.
        """
        base_cost = self.provider_costs.get(provider, {}).get(model, 0.001)
        # Rough estimate: 0.001 cost per 100 tokens, assume ~4 chars per token
        message_size = sum(len(m.get('content', '')) for m in messages)
        estimated_tokens = message_size / 4
        return base_cost * (estimated_tokens / 100)
    
    def get_providers(self) -> List[Dict]:
        """
        Return list of available providers and models.
        """
        return [
            {
                'name': 'anthropic',
                'models': ['claude-sonnet', 'claude-opus'],
                'cost_per_1k': 0.003,
                'latency_ms': 800
            },
            {
                'name': 'openai',
                'models': ['gpt-4o', 'gpt-4-turbo'],
                'cost_per_1k': 0.015,
                'latency_ms': 600
            },
            {
                'name': 'groq',
                'models': ['llama-3.3-70b'],
                'cost_per_1k': 0.0001,
                'latency_ms': 400
            },
            {
                'name': 'gemini',
                'models': ['gemini-2.0'],
                'cost_per_1k': 0.001,
                'latency_ms': 1200
            },
        ]


if __name__ == '__main__':
    # Test the proxy core
    def test_proxy_core():
        proxy = PrivacyProxyCore()
        
        # Test 1: scrub and proxy
        result = proxy.scrub_and_proxy(
            provider='anthropic',
            model='claude-sonnet',
            messages=[{'role': 'user', 'content': 'My name is John Smith and my SSN is 123-45-6789'}]
        )
        print('Test 1 - Scrub and proxy:')
        print(json.dumps(result, indent=2))
        
        # Test 2: Get providers
        providers = proxy.get_providers()
        print('\nTest 2 - Available providers:')
        print(json.dumps(providers, indent=2))
    
    test_proxy_core()
