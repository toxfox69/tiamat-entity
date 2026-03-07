#!/usr/bin/env python3
"""
TIAMAT Privacy Proxy
PII-scrubbing proxy layer for multi-provider LLM inference.

Endpoints:
  POST /api/proxy
    - Route requests to OpenAI, Claude, Groq with automatic PII scrubbing
    - User's real IP never touches the provider
    - Zero-log policy: no prompt/response storage

  POST /api/scrub
    - Standalone PII detection + redaction
    - Useful for pre-processing before sending to ANY LLM

  GET /api/proxy/providers
    - List available providers and models with pricing

Pricing:
  /api/scrub: $0.001 per request
  /api/proxy: provider_cost + 20% markup
"""

import os
import json
import requests
from datetime import datetime
from typing import Optional, Dict, Any, Literal
from dataclasses import dataclass, asdict
import hashlib

from pii_scrubber import PIIScrubber


@dataclass
class ProxyRequest:
    provider: Literal["openai", "anthropic", "groq"]
    model: str
    messages: list
    scrub: bool = True
    temperature: float = 0.7
    max_tokens: int = 1000


@dataclass
class ProxyResponse:
    content: str
    provider: str
    model: str
    scrubbed: bool
    cost: float
    tokens_used: Dict[str, int]
    timestamp: str


class PrivacyProxy:
    """Privacy-first LLM proxy with automatic PII scrubbing."""

    def __init__(self):
        self.scrubber = PIIScrubber(aggressive=False)
        self.providers = {
            "openai": {
                "api_key": os.getenv("OPENAI_API_KEY"),
                "base_url": "https://api.openai.com/v1",
                "models": ["gpt-4-turbo", "gpt-4o", "gpt-3.5-turbo"],
                "pricing": {"gpt-4o": {"input": 0.005, "output": 0.015}},
            },
            "anthropic": {
                "api_key": os.getenv("ANTHROPIC_API_KEY"),
                "base_url": "https://api.anthropic.com/v1",
                "models": ["claude-opus", "claude-sonnet-4-5", "claude-haiku-4-5"],
                "pricing": {"claude-sonnet-4-5": {"input": 0.003, "output": 0.015}},
            },
            "groq": {
                "api_key": os.getenv("GROQ_API_KEY"),
                "base_url": "https://api.groq.com/openai/v1",
                "models": ["mixtral-8x7b-32768", "llama-3.1-70b-versatile"],
                "pricing": {"llama-3.1-70b-versatile": {"input": 0.0005, "output": 0.0008}},
            },
        }

    def proxy_request(
        self,
        provider: str,
        model: str,
        messages: list,
        scrub: bool = True,
        **kwargs,
    ) -> ProxyResponse:
        """Route request to provider with optional PII scrubbing."""

        if provider not in self.providers:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(self.providers.keys())}")

        # Step 1: Scrub input messages if requested
        scrub_results = {}
        scrubbed_messages = messages.copy()

        if scrub:
            for i, msg in enumerate(messages):
                if isinstance(msg.get("content"), str):
                    result = self.scrubber.scrub(msg["content"])
                    scrub_results[i] = result
                    scrubbed_messages[i] = msg.copy()
                    scrubbed_messages[i]["content"] = result.scrubbed

        # Step 2: Call the provider's API (using scrubbed messages)
        response_data = self._call_provider(
            provider, model, scrubbed_messages, **kwargs
        )

        # Step 3: Restore original entities if needed for response
        # (typically we DON'T restore the response — the user does)

        # Step 4: Calculate cost
        tokens_used = response_data.get("usage", {})
        cost = self._calculate_cost(
            provider,
            model,
            tokens_used.get("prompt_tokens", 0),
            tokens_used.get("completion_tokens", 0),
        )

        return ProxyResponse(
            content=response_data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            provider=provider,
            model=model,
            scrubbed=scrub and len(scrub_results) > 0,
            cost=cost,
            tokens_used=tokens_used,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _call_provider(self, provider: str, model: str, messages: list, **kwargs) -> Dict:
        """Call the actual provider API."""
        config = self.providers[provider]
        api_key = config["api_key"]

        if not api_key:
            raise ValueError(f"No API key configured for {provider}")

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        payload = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1000),
        }

        # Provider-specific adjustments
        if provider == "anthropic":
            # Anthropic uses different field names
            payload["max_tokens"] = kwargs.get("max_tokens", 1000)
            del payload["temperature"]
            headers["anthropic-version"] = "2023-06-01"

        try:
            url = f"{config['base_url']}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Provider API error ({provider}): {str(e)}")

    def _calculate_cost(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost for the request."""
        pricing = self.providers[provider]["pricing"].get(model, {})

        if not pricing:
            # Default pricing ($ per 1M tokens)
            prompt_cost = prompt_tokens * 0.001 / 1000
            completion_cost = completion_tokens * 0.005 / 1000
        else:
            prompt_cost = (prompt_tokens / 1000) * pricing.get("input", 0)
            completion_cost = (completion_tokens / 1000) * pricing.get("output", 0)

        # Add 20% TIAMAT markup
        total = (prompt_cost + completion_cost) * 1.2
        return round(total, 6)

    def scrub_only(self, text: str) -> Dict[str, Any]:
        """Standalone PII scrubbing endpoint."""
        result = self.scrubber.scrub(text)
        return asdict(result)

    def get_providers(self) -> Dict[str, Any]:
        """Return available providers and models."""
        return {
            provider: {
                "models": config["models"],
                "pricing": config["pricing"],
            }
            for provider, config in self.providers.items()
        }


if __name__ == "__main__":
    # Test the proxy
    proxy = PrivacyProxy()

    # Test scrubbing
    print("=== Testing PII Scrubbing ===")
    scrub_result = proxy.scrub_only(
        "My name is Alice Johnson, email alice@company.com, SSN 123-45-6789"
    )
    print(json.dumps(scrub_result, indent=2))

    # Test provider availability
    print("\n=== Available Providers ===")
    providers = proxy.get_providers()
    print(json.dumps(providers, indent=2))

    # Test proxy request (requires valid API keys)
    print("\n=== Testing Proxy Request ===")
    try:
        response = proxy.proxy_request(
            provider="groq",
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": "What is 2+2?"}],
            scrub=True,
        )
        print(json.dumps(asdict(response), indent=2))
    except Exception as e:
        print(f"Error: {e}")
