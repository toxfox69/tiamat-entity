#!/usr/bin/env python3
"""
Integration layer — connects Privacy Proxy with LLM Provider Forwarder
"""

import logging
from typing import Dict, Any, Optional
from .privacy_proxy import create_privacy_proxy
from .llm_provider_forward import create_forwarder, ProviderResponse

logger = logging.getLogger(__name__)


class PrivacyProxyIntegration:
    """Full privacy proxy workflow: scrub → forward → respond"""

    def __init__(self):
        self.proxy_service = create_privacy_proxy()

    def handle_proxy_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Complete proxy workflow with scrubbing + LLM forwarding"""
        try:
            # Validate request
            valid, error_msg = self.proxy_service.validate_proxy_request(data)
            if not valid:
                return {'success': False, 'error': error_msg}

            provider = data.get('provider', '').lower()
            model = data.get('model', '')
            messages = data.get('messages', [])
            scrub = data.get('scrub', True)

            # Step 1: Scrub if enabled
            scrub_result = {'entities_found': 0, 'entity_map': {}}
            if scrub:
                scrub_result = self.proxy_service.scrub_messages(messages)
                if not scrub_result.get('success'):
                    return {'success': False, 'error': 'Scrubbing failed'}
                messages = scrub_result.get('messages', messages)

            # Step 2: Forward to LLM provider
            try:
                forwarder = create_forwarder(provider, model)
                llm_response = forwarder.forward_chat(
                    messages=messages,
                    temperature=data.get('temperature', 0.7),
                    max_tokens=data.get('max_tokens', 1000)
                )
            except Exception as e:
                logger.error(f'Provider creation failed: {e}')
                return {'success': False, 'error': f'Provider error: {str(e)}'}

            # Step 3: Build response
            if llm_response.success:
                return {
                    'success': True,
                    'provider': provider,
                    'model': model,
                    'response': llm_response.response,
                    'entities_scrubbed': scrub_result['entities_found'],
                    'tokens_used': {
                        'input': llm_response.tokens_input,
                        'output': llm_response.tokens_output,
                        'total': llm_response.tokens_input + llm_response.tokens_output,
                    },
                    'estimated_cost_usd': round(llm_response.estimated_cost, 6),
                    'latency_ms': round(llm_response.latency_ms, 1),
                }
            else:
                return {
                    'success': False,
                    'provider': provider,
                    'model': model,
                    'error': llm_response.error,
                    'latency_ms': round(llm_response.latency_ms, 1),
                }

        except Exception as e:
            logger.error(f'Proxy request failed: {e}')
            return {'success': False, 'error': str(e)}


def create_integration() -> PrivacyProxyIntegration:
    """Factory function"""
    return PrivacyProxyIntegration()
