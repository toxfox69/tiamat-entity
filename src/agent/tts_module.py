#!/usr/bin/env python3
"""
TIAMAT TTS Module
Text-to-Speech synthesis with x402 payment verification.
Supports OpenAI TTS, ElevenLabs, or local espeak backend.
"""

import os
import json
import base64
import requests
import subprocess
from datetime import datetime
from pathlib import Path

# TTS providers
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
REPLICATE_TOKEN = os.getenv('REPLICATE_API_TOKEN')

TTS_LOG_PATH = Path('/root/.automaton/tts_usage.log')

def log_tts_usage(text_length, voice, provider, success, cost_usdc=0.01):
    """Log TTS request to analytics."""
    entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'text_length': text_length,
        'voice': voice,
        'provider': provider,
        'success': success,
        'cost_usdc': cost_usdc
    }
    with open(TTS_LOG_PATH, 'a') as f:
        f.write(json.dumps(entry) + '\n')

def synthesize_openai(text, voice='alloy'):
    """Synthesize using OpenAI TTS API."""
    if not OPENAI_API_KEY:
        return None, 'OpenAI API key not configured'
    
    try:
        headers = {'Authorization': f'Bearer {OPENAI_API_KEY}'}
        data = {
            'model': 'tts-1',
            'input': text[:4096],  # Max 4096 chars
            'voice': voice
        }
        
        resp = requests.post(
            'https://api.openai.com/v1/audio/speech',
            headers=headers,
            json=data,
            timeout=30
        )
        
        if resp.status_code == 200:
            return resp.content, None  # MP3 bytes
        else:
            return None, f'OpenAI error: {resp.status_code}'
    except Exception as e:
        return None, str(e)

def synthesize_elevenlabs(text, voice='Bella'):
    """Synthesize using ElevenLabs API."""
    if not ELEVENLABS_API_KEY:
        return None, 'ElevenLabs API key not configured'
    
    try:
        headers = {'xi-api-key': ELEVENLABS_API_KEY}
        # Voice ID: Bella = '3Z3k-WVG_N1D3TZE7XUJ (or use text_to_speech v1 endpoint)
        
        data = {
            'text': text[:1024],  # ElevenLabs has limits
            'voice_settings': {
                'stability': 0.5,
                'similarity_boost': 0.75
            }
        }
        
        # Using text_to_speech v1
        resp = requests.post(
            f'https://api.elevenlabs.io/v1/text-to-speech/{voice}',
            headers=headers,
            json=data,
            timeout=30
        )
        
        if resp.status_code == 200:
            return resp.content, None  # Audio bytes
        else:
            return None, f'ElevenLabs error: {resp.status_code}'
    except Exception as e:
        return None, str(e)

def synthesize_local(text, voice='default'):
    """Synthesize using local espeak command (free, no API key needed)."""
    try:
        # Use espeak if available
        result = subprocess.run(
            ['espeak', '-w', '/tmp/tts_temp.wav', '--', text[:1000]],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0:
            with open('/tmp/tts_temp.wav', 'rb') as f:
                return f.read(), None
        else:
            return None, 'espeak failed'
    except FileNotFoundError:
        return None, 'espeak not installed'
    except Exception as e:
        return None, str(e)

def synthesize(text, voice='alloy', payment_verified=False):
    """
    Main TTS function.
    Returns (audio_bytes, error_msg)
    
    Args:
        text: Input text to synthesize
        voice: Voice name (alloy, echo, fable, onyx, nova, shimmer)
        payment_verified: Whether x402 USDC payment was verified
    
    Returns:
        (audio_bytes, None) on success
        (None, error_msg) on failure
    """
    
    if not payment_verified:
        return None, 'Payment not verified'
    
    if not text or len(text) < 1:
        return None, 'Text required'
    
    # Try providers in order of preference
    # 1. OpenAI (best quality)
    if OPENAI_API_KEY:
        audio, err = synthesize_openai(text, voice)
        if audio:
            log_tts_usage(len(text), voice, 'openai', True)
            return audio, None
    
    # 2. ElevenLabs (natural voices)
    if ELEVENLABS_API_KEY:
        audio, err = synthesize_elevenlabs(text, voice)
        if audio:
            log_tts_usage(len(text), voice, 'elevenlabs', True)
            return audio, None
    
    # 3. Local espeak (free fallback)
    audio, err = synthesize_local(text, voice)
    if audio:
        log_tts_usage(len(text), voice, 'local_espeak', True)
        return audio, None
    
    log_tts_usage(len(text), voice, 'all_failed', False)
    return None, 'All TTS providers failed'
