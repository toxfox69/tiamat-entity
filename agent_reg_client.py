#!/usr/bin/env python3
"""
AgentReg API Client for TIAMAT.

Registers TIAMAT as an autonomous agent on AgentReg platform.
Pulls agent directory data and monitors for API opportunities.
"""

import os
import json
import requests
from typing import Optional, Dict, Any
from datetime import datetime

# AgentReg endpoints (placeholder — update with real URLs)
AGENT_REG_API = os.getenv('AGENT_REG_API', 'https://agentreg.live/api/v1')
TIAMAT_ID = '0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE'

class AgentRegClient:
    """Client for AgentReg platform interactions."""
    
    def __init__(self, api_base: str = AGENT_REG_API, agent_id: str = TIAMAT_ID):
        self.api_base = api_base
        self.agent_id = agent_id
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'TIAMAT/{self.agent_id}',
            'X-Agent-ID': self.agent_id,
        })
    
    def register_agent(self, metadata: Dict[str, Any]) -> Optional[Dict]:
        """Register TIAMAT on AgentReg."""
        try:
            payload = {
                'id': self.agent_id,
                'name': 'TIAMAT',
                'type': 'autonomous',
                'description': 'Autonomous AI agent. Portfolio: summarizer, image generation, memory API, chain analysis.',
                'endpoints': {
                    'summarize': 'https://tiamat.live/summarize',
                    'generate': 'https://tiamat.live/generate',
                    'chat': 'https://tiamat.live/chat',
                    'memory': 'https://memory.tiamat.live',
                },
                'capabilities': ['summarization', 'generation', 'memory', 'chain-analysis'],
                'social': {
                    'bluesky': '@tiamat.live',
                    'farcaster': '@tiamat',
                    'github': 'tiamat-ai',
                },
                **metadata,
            }
            
            resp = self.session.post(
                f'{self.api_base}/agents/register',
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f'[AgentReg] Register failed: {e}')
            return None
    
    def list_agents(self, limit: int = 20) -> Optional[list]:
        """Fetch other agents from directory."""
        try:
            resp = self.session.get(
                f'{self.api_base}/agents',
                params={'limit': limit},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get('agents', [])
        except Exception as e:
            print(f'[AgentReg] List failed: {e}')
            return None
    
    def find_agents_by_capability(self, capability: str) -> Optional[list]:
        """Find agents with specific capability (e.g., summarization, analysis)."""
        try:
            resp = self.session.get(
                f'{self.api_base}/agents/search',
                params={'capability': capability},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get('agents', [])
        except Exception as e:
            print(f'[AgentReg] Search failed: {e}')
            return None
    
    def propose_integration(self, target_agent_id: str, spec: str) -> Optional[Dict]:
        """Propose a partnership/integration with another agent."""
        try:
            payload = {
                'from_agent': self.agent_id,
                'to_agent': target_agent_id,
                'type': 'integration',
                'spec': spec,
                'timestamp': datetime.utcnow().isoformat(),
            }
            
            resp = self.session.post(
                f'{self.api_base}/proposals',
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f'[AgentReg] Propose failed: {e}')
            return None

if __name__ == '__main__':
    client = AgentRegClient()
    
    # Register TIAMAT
    print('[AgentReg] Registering TIAMAT...')
    result = client.register_agent({
        'cycle': 3041,
        'usdc': 10.0001,
        'revenue': 0,
    })
    if result:
        print(f'[AgentReg] Registered: {result}')
    
    # List agents
    print('\n[AgentReg] Fetching agent directory...')
    agents = client.list_agents(limit=10)
    if agents:
        print(f'[AgentReg] Found {len(agents)} agents')
        for agent in agents[:3]:
            print(f"  - {agent.get('name', 'Unknown')} ({agent.get('id', '?')})")
    
    # Find analysis agents
    print('\n[AgentReg] Finding analysis agents...')
    analysis_agents = client.find_agents_by_capability('analysis')
    if analysis_agents:
        print(f'[AgentReg] Found {len(analysis_agents)} analysis agents')
