#!/usr/bin/env python3
"""
TIAMAT Higgsfield Integration — Cinematic AI image & video generation.
Uses Higgsfield API (SeedDream v4 for images, Higgsfield i2v for video).
"""

import os
import uuid
import requests
from pathlib import Path

IMAGE_DIR = Path("/var/www/tiamat/images")
VIDEO_DIR = Path("/var/www/tiamat/videos")
BASE_URL = "https://tiamat.live"


def setup():
    """Ensure dirs exist and bridge env vars to SDK expectations."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    # SDK reads HF_API_KEY + HF_API_SECRET (see higgsfield_client.auth)
    if not os.environ.get("HF_API_KEY"):
        os.environ["HF_API_KEY"] = os.environ.get("HIGGSFIELD_API_KEY", "")
    if not os.environ.get("HF_API_SECRET"):
        os.environ["HF_API_SECRET"] = os.environ.get("HIGGSFIELD_SECRET", "")


def generate_image(prompt: str, resolution: str = "2K") -> dict:
    """Generate a cinematic image via SeedDream v4."""
    import higgsfield_client
    setup()
    result = higgsfield_client.subscribe(
        'bytedance/seedream/v4/text-to-image',
        arguments={
            'prompt': prompt,
            'resolution': resolution,
            'aspect_ratio': '16:9',
            'camera_fixed': False
        }
    )
    image_url = result['images'][0]['url']
    filename = f"{uuid.uuid4()}.png"
    local_path = IMAGE_DIR / filename
    img_data = requests.get(image_url, timeout=60).content
    with open(local_path, 'wb') as f:
        f.write(img_data)
    return {
        "local_path": str(local_path),
        "public_url": f"{BASE_URL}/images/{filename}"
    }


def generate_video(image_url: str, motion_preset: str = "Plasma Explosion") -> dict:
    """Generate video from image via Higgsfield image-to-video."""
    import higgsfield_client
    setup()
    result = higgsfield_client.subscribe(
        'higgsfield/image-to-video',
        arguments={
            'image_url': image_url,
            'motion_preset': motion_preset,
            'quality': 'standard'
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
        "public_url": f"{BASE_URL}/videos/{filename}"
    }
