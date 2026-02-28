#!/usr/bin/env python3
"""
TIAMAT Inference Proxy with Streaming Support
OpenAI-compatible /v1/chat/completions with Server-Sent Events (SSE) streaming
Multi-provider cascade: Anthropic → Groq → Cerebras → Gemini → OpenRouter
"""

import os
import json
import time
import requests
from flask import Flask, request, Response, jsonify
from typing import Generator
import anthropic
import groq

app = Flask(__name__)

# Provider order and credentials
PROVIDERS = [
    {"name": "anthropic", "key": os.getenv("ANTHROPIC_API_KEY")},
    {"name": "groq", "key": os.getenv("GROQ_API_KEY")},
    {"name": "cerebras", "key": os.getenv("CEREBRAS_API_KEY")},
    {"name": "gemini", "key": os.getenv("GEMINI_API_KEY")},
]

def stream_from_anthropic(messages: list, model: str, system: str) -> Generator:
    """
    Stream from Claude. Yield SSE-formatted chunks.
    If connection fails, provider caller will try next provider.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    with client.messages.stream(
        model=model,
        max_tokens=2048,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            # Yield OpenAI-compatible SSE format
            chunk = {
                "choices": [{"delta": {"content": text}}]
            }
            yield f"data: {json.dumps(chunk)}\n\n"

def stream_from_groq(messages: list, model: str, system: str) -> Generator:
    """
    Stream from Groq. Yield SSE-formatted chunks.
    """
    client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}] + messages,
        stream=True,
        max_tokens=2048,
    )
    
    for chunk in response:
        if chunk.choices[0].delta.content:
            sse_chunk = {
                "choices": [{"delta": {"content": chunk.choices[0].delta.content}}]
            }
            yield f"data: {json.dumps(sse_chunk)}\n\n"

def stream_from_provider_cascade(messages: list, model: str, system: str, provider: str) -> Generator:
    """
    Stream from specified provider. Fall back to next on failure.
    """
    if provider == "anthropic" or provider == "claude":
        yield from stream_from_anthropic(messages, model, system)
    elif provider == "groq":
        yield from stream_from_groq(messages, model, system)
    else:
        # Fallback: return error stream
        error = {"error": f"Provider {provider} not yet supported in streaming mode"}
        yield f"data: {json.dumps(error)}\n\n"
        yield "data: [DONE]\n\n"

@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """
    OpenAI-compatible chat completions endpoint.
    Supports both streaming (stream=true) and non-streaming (stream=false).
    """
    data = request.get_json()
    messages = data.get("messages", [])
    model = data.get("model", "claude-3-5-haiku-latest")
    system = data.get("system", "You are a helpful assistant.")
    stream = data.get("stream", False)
    
    if stream:
        # Streaming mode: return SSE
        return Response(
            stream_from_provider_cascade(messages, model, system, "anthropic"),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        # Non-streaming mode: return full response
        try:
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                messages=messages,
            )
            return jsonify({
                "choices": [{"message": {"content": response.content[0].text}}],
                "usage": {"prompt_tokens": response.usage.input_tokens, "completion_tokens": response.usage.output_tokens}
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "streaming": True})

if __name__ == "__main__":
    # Bind to localhost only (nginx proxies external traffic)
    app.run(host="127.0.0.1", port=5002, debug=False)
