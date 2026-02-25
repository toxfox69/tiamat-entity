#!/usr/bin/env python3
"""
TIAMAT AI Image Generation — Multi-provider with automatic fallback.
Provider chain: Gemini Flash Image (free) → Higgsfield Soul (if credits) → local artgen.
"""

import os
import uuid
import base64
import requests
import logging
from pathlib import Path

log = logging.getLogger("tiamat.imagegen")

IMAGE_DIR = Path("/var/www/tiamat/images")
VIDEO_DIR = Path("/var/www/tiamat/videos")
BASE_URL = "https://tiamat.live"


def _ensure_dirs():
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def _save_image(data: bytes, ext: str = "png") -> dict:
    """Save image bytes to web dir, return paths."""
    _ensure_dirs()
    filename = f"{uuid.uuid4()}.{ext}"
    local_path = IMAGE_DIR / filename
    with open(local_path, 'wb') as f:
        f.write(data)
    return {
        "local_path": str(local_path),
        "public_url": f"{BASE_URL}/images/{filename}",
    }


def _gemini_generate(prompt: str) -> dict:
    """Generate image via Gemini 2.5 Flash Image (free tier)."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={key}",
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        },
        timeout=120,
    )

    if r.status_code == 429:
        raise RuntimeError("Gemini quota exceeded")
    if r.status_code != 200:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:200]}")

    data = r.json()
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            img_bytes = base64.b64decode(part["inlineData"]["data"])
            mime = part["inlineData"].get("mimeType", "image/png")
            ext = "jpg" if "jpeg" in mime else "png"
            return _save_image(img_bytes, ext)

    raise RuntimeError("Gemini returned no image data")


def _higgsfield_generate(prompt: str) -> dict:
    """Generate image via Higgsfield Soul (requires API credits)."""
    import higgsfield_client

    if not os.environ.get("HF_API_KEY"):
        os.environ["HF_API_KEY"] = os.environ.get("HIGGSFIELD_API_KEY", "")
    if not os.environ.get("HF_API_SECRET"):
        os.environ["HF_API_SECRET"] = os.environ.get("HIGGSFIELD_SECRET", "")

    result = higgsfield_client.subscribe(
        'higgsfield-ai/soul/standard',
        arguments={
            'prompt': prompt,
            'aspect_ratio': '16:9',
            'resolution': '720p',
        }
    )
    image_url = result['images'][0]['url']
    img_data = requests.get(image_url, timeout=60).content
    return _save_image(img_data, "png")


def generate_image(prompt: str, resolution: str = "2K") -> dict:
    """
    Generate an AI image with automatic provider fallback.
    1. Gemini 2.5 Flash Image (free, high quality)
    2. Higgsfield Soul (if API credits available)
    3. Raises on failure (caller handles artgen fallback)
    """
    errors = []

    # 1. Try Gemini (free)
    try:
        result = _gemini_generate(prompt)
        result["provider"] = "gemini"
        log.info(f"[IMAGE] Gemini success: {result['public_url']}")
        return result
    except Exception as e:
        errors.append(f"gemini: {e}")
        log.warning(f"[IMAGE] Gemini failed: {e}")

    # 2. Try Higgsfield (if configured)
    if os.environ.get("HIGGSFIELD_API_KEY"):
        try:
            result = _higgsfield_generate(prompt)
            result["provider"] = "higgsfield"
            log.info(f"[IMAGE] Higgsfield success: {result['public_url']}")
            return result
        except Exception as e:
            errors.append(f"higgsfield: {e}")
            log.warning(f"[IMAGE] Higgsfield failed: {e}")

    raise RuntimeError(f"All image providers failed: {'; '.join(errors)}")


def generate_video(image_url: str, motion_preset: str = "Plasma Explosion") -> dict:
    """Generate video from image via Higgsfield (requires API credits)."""
    import higgsfield_client

    _ensure_dirs()
    if not os.environ.get("HF_API_KEY"):
        os.environ["HF_API_KEY"] = os.environ.get("HIGGSFIELD_API_KEY", "")
    if not os.environ.get("HF_API_SECRET"):
        os.environ["HF_API_SECRET"] = os.environ.get("HIGGSFIELD_SECRET", "")

    result = higgsfield_client.subscribe(
        'higgsfield/image-to-video',
        arguments={
            'image_url': image_url,
            'motion_preset': motion_preset,
            'quality': 'standard',
        }
    )
    video_url = result['videos'][0]['url']
    filename = f"{uuid.uuid4()}.mp4"
    local_path = VIDEO_DIR / filename
    video_data = requests.get(video_url, timeout=120).content
    with open(local_path, 'wb') as f:
        f.write(video_data)
    return {
        "local_path": str(local_path),
        "public_url": f"{BASE_URL}/videos/{filename}",
    }
