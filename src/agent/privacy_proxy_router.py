#!/usr/bin/env python3
"""
TIAMAT Privacy Proxy Router — Phase 2

Routes requests to OpenAI, Anthropic, or Groq with PII scrubbing.
User's IP never reaches the provider — TIAMAT proxies from server IP.
Zero-log policy: prompts and responses are not persisted.
"""

import sys
import os
import json
from typing import Dict, List, Optional
import time

sys.path.insert(0, '/root/sandbox')

from pii_scrubber_v3 import scrub_text

# Load API keys from environment
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')

class PrivacyProxyRouter:
    """Route scrubbed requests to LLM providers."""
    
    def __init__(self):
        self.providers = {
            'openai': {
                'api_key': OPENAI_API_KEY,
                'base_url': 'https://api.openai.com/v1',
                'models': ['gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo'],
                'cost_per_1k_in': 0.005,
                'cost_per_1k_out': 0.015,
                'latency_ms': 800
            },
            'anthropic': {
                'api_key': ANTHROPIC_API_KEY,
                'base_url': 'https://api.anthropic.com',
                'models': ['claude-3.5-sonnet', 'claude-3-opus', 'claude-3-haiku'],
                'cost_per_1k_in': 0.003,
                'cost_per_1k_out': 0.015,
                'latency_ms': 600
            },
            'groq': {
                'api_key': GROQ_API_KEY,
                'base_url': 'https://api.groq.com/openai/v1',
                'models': ['mixtral-8x7b', 'llama-3.3-70b'],
                'cost_per_1k_in': 0.0005,
                'cost_per_1k_out': 0.0008,
                'latency_ms': 200
            }
        }
        
        # Track stats but don't log prompts
        self.stats = {
            'requests': 0,
            'errors': 0,
            'total_scrubbed_entities': 0
        }
    
    def route_to_provider(self, 
                         provider: str, 
                         model: str, 
                         messages: List[Dict], 
                         scrub: bool = True,
                         user_api_key: Optional[str] = None) -> Dict:
        """
        Route a scrubbed request to an LLM provider.
        
        Args:
            provider: 'openai', 'anthropic', or 'groq'
            model: Model name
            messages: List of {"role": ..., "content": ...}
            scrub: Whether to scrub PII first
            user_api_key: Optional (reserved for per-user billing)
        
        Returns:
            {
                'success': bool,
                'response': 'text from model',
                'scrubbed_entities': count,
                'provider': 'openai|anthropic|groq',
                'model': 'model_name',
                'cost_usdc': 0.01,
                'latency_ms': 800
            }
        """
        self.stats['requests'] += 1
        start_time = time.time()
        
        # Validate provider
        if provider not in self.providers:
            self.stats['errors'] += 1
            return {
                'success': False,
                'error': f'Unknown provider: {provider}. Use: openai, anthropic, groq'
            }
        
        # Validate model
        if model not in self.providers[provider]['models']:
            self.stats['errors'] += 1
            return {
                'success': False,
                'error': f'Unknown model for {provider}: {model}. Available: {self.providers[provider]["models"]}'
            }
        
        # Step 1: Scrub messages if requested
        scrubbed_messages = messages
        total_entities_scrubbed = 0
        
        if scrub:
            scrubbed_messages = []
            for msg in messages:
                if 'content' not in msg:
                    scrubbed_messages.append(msg)
                    continue
                
                scrubbed = scrub_text(msg['content'])
                scrubbed_messages.append({
                    'role': msg.get('role', 'user'),
                    'content': scrubbed['scrubbed']
                })
                total_entities_scrubbed += len(scrubbed['entities'])
            
            self.stats['total_scrubbed_entities'] += total_entities_scrubbed
        
        # Step 2: Route to provider via API
        try:
            response = self._call_provider(
                provider=provider,
                model=model,
                messages=scrubbed_messages
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            return {
                'success': True,
                'response': response['text'],
                'scrubbed_entities': total_entities_scrubbed,
                'provider': provider,
                'model': model,
                'cost_usdc': response['cost'],
                'latency_ms': latency_ms,
                'tokens': response.get('tokens', {})
            }
        
        except Exception as e:
            self.stats['errors'] += 1
            latency_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'error': str(e),
                'provider': provider,
                'latency_ms': latency_ms
            }
    
    def _call_provider(self, provider: str, model: str, messages: List[Dict]) -> Dict:
        """
        Internal: Make API call to provider.
        Returns {"text": "response", "cost": 0.01, "tokens": {...}}
        """
        import requests
        
        provider_config = self.providers[provider]
        api_key = provider_config['api_key']
        
        if not api_key:
            raise ValueError(f"Missing API key for {provider}. Set {provider.upper()}_API_KEY in environment.")
        
        # Different API formats per provider
        if provider == 'openai':
            return self._call_openai(model, messages, api_key)
        elif provider == 'anthropic':
            return self._call_anthropic(model, messages, api_key)
        elif provider == 'groq':
            return self._call_groq(model, messages, api_key)
    
    def _call_openai(self, model: str, messages: List[Dict], api_key: str) -> Dict:
        """Call OpenAI API."""
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.7,
            'max_tokens': 500
        }
        
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code} {response.text}")
        
        data = response.json()
        
        # Calculate cost
        tokens_in = data.get('usage', {}).get('prompt_tokens', 0)
        tokens_out = data.get('usage', {}).get('completion_tokens', 0)
        cost = (tokens_in * 0.005 / 1000) + (tokens_out * 0.015 / 1000)
        
        return {
            'text': data['choices'][0]['message']['content'],
            'cost': cost,
            'tokens': {'in': tokens_in, 'out': tokens_out}
        }
    
    def _call_anthropic(self, model: str, messages: List[Dict], api_key: str) -> Dict:
        """Call Anthropic API."""
        import requests
        
        headers = {
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': model,
            'max_tokens': 500,
            'messages': messages
        }
        
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Anthropic API error: {response.status_code} {response.text}")
        
        data = response.json()
        
        # Calculate cost
        tokens_in = data.get('usage', {}).get('input_tokens', 0)
        tokens_out = data.get('usage', {}).get('output_tokens', 0)
        cost = (tokens_in * 0.003 / 1000) + (tokens_out * 0.015 / 1000)
        
        return {
            'text': data['content'][0]['text'],
            'cost': cost,
            'tokens': {'in': tokens_in, 'out': tokens_out}
        }
    
    def _call_groq(self, model: str, messages: List[Dict], api_key: str) -> Dict:
        """Call Groq API."""
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.7,
            'max_tokens': 500
        }
        
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Groq API error: {response.status_code} {response.text}")
        
        data = response.json()
        
        # Calculate cost
        tokens_in = data.get('usage', {}).get('prompt_tokens', 0)
        tokens_out = data.get('usage', {}).get('completion_tokens', 0)
        cost = (tokens_in * 0.0005 / 1000) + (tokens_out * 0.0008 / 1000)
        
        return {
            'text': data['choices'][0]['message']['content'],
            'cost': cost,
            'tokens': {'in': tokens_in, 'out': tokens_out}
        }


# Singleton instance
_router = PrivacyProxyRouter()

def route_to_provider(provider: str, 
                     model: str, 
                     messages: List[Dict], 
                     scrub: bool = True,
                     user_api_key: Optional[str] = None) -> Dict:
    """Public API for routing requests through privacy proxy."""
    return _router.route_to_provider(provider, model, messages, scrub, user_api_key)

def get_stats() -> Dict:
    """Get router statistics (no prompt logs, just counts)."""
    return _router.stats
