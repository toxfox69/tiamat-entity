#!/usr/bin/env python3
"""
CELL-ART: Art generation and DeviantArt posting cell.
Generates Crown Beast Ranch character art via ComfyUI and posts to DeviantArt.
Runs every 2 hours.
"""

import json
import os
import re
import time
import random
import requests
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_cell import HoneycombCell

CELL_CONFIG = {
    "name": "CELL-ART",
    "tier": 0,
    "cycle_interval_seconds": 7200,  # 2 hours
    "sandbox_paths": ["/root/.automaton/cells/art/"],
    "forbidden_actions": ["send_email", "modify_code"],
    "inbox_tag": "[CELL-ART]",
    "training_data_dir": "/root/.automaton/training_data/cell_art",
    "cell_dir": "/root/.automaton/cells/art",
}

COMFYUI = "http://localhost:8188"
ART_DIR = "/root/tiamatooze/crown_beast_ranch_art"
NEG = "worst quality, low quality, blurry, deformed, bad anatomy, extra limbs, watermark, text, ugly, realistic, photo"

CHARACTERS = {
    "mira": {
        "prompts": [
            "mira, 1girl, cow-taur centaur, four legs, spotted brown white cow body, brown wavy hair, cow ears, horns, flower crown, shy blush, white blouse, brown corset, pastoral meadow, golden hour, anime illustration, masterpiece, best quality",
            "mira, 1girl, cow-taur centaur, four legs, spotted cow body, brown hair, horns, reading book in stable, warm lantern light, cozy, anime illustration, masterpiece",
            "mira, 1girl, cow-taur, close up portrait, brown hair, cow ears, flower crown, gentle smile, blush, soft lighting, anime illustration, masterpiece",
        ],
        "tags": ["monster girl", "holstaur", "cow girl", "centaur", "fantasy", "anime", "AI art", "Crown Beast Ranch"],
    },
    "ember": {
        "prompts": [
            "ember, 1girl, salamander girl, pink skin, short red hair, dragon tail, orange eyes, slit pupils, horns, tank top, shorts, confident smirk, farmland sunset, anime illustration, masterpiece, best quality",
            "ember, 1girl, salamander girl, pink skin, red hair, dragon tail, training pose, fists up, morning mist, training ground, anime illustration, masterpiece",
            "ember, 1girl, salamander girl, close up portrait, red hair, orange eyes, sharp grin, flames in background, anime illustration, masterpiece",
        ],
        "tags": ["monster girl", "salamander", "tomboy", "fantasy", "anime", "AI art", "Crown Beast Ranch"],
    },
    "nyx": {
        "prompts": [
            "nyx, 1girl, lamia, snake lower body, purple scales, dark skin, silver hair, pink eyes, glasses, navy robe, reading scroll, library, candlelight, anime illustration, masterpiece, best quality",
            "nyx, 1girl, lamia, dark elf, snake tail, silver hair, glasses, coiled around bookshelf, studying, warm library, anime illustration, masterpiece",
            "nyx, 1girl, lamia, close up portrait, dark skin, silver hair, glasses, calm half-lidded eyes, intellectual, anime illustration, masterpiece",
        ],
        "tags": ["monster girl", "lamia", "snake girl", "dark elf", "bookworm", "fantasy", "anime", "AI art", "Crown Beast Ranch"],
    },
    "pollen": {
        "prompts": [
            "pollen, 1girl, bee girl, golden hair, antennae, translucent wings, amber eyes, yellow black striped outfit, cheerful, flower garden, sunflowers, anime illustration, masterpiece, best quality",
            "pollen, 1girl, bee girl, wings spread, golden hair, antennae, flying above garden, morning dew, butterflies, anime illustration, masterpiece",
            "pollen, 1girl, bee girl, close up portrait, golden hair, antennae, bright smile, honey dripping, anime illustration, masterpiece",
        ],
        "tags": ["monster girl", "bee girl", "insect girl", "gardener", "cute", "fantasy", "anime", "AI art", "Crown Beast Ranch"],
    },
    "sable": {
        "prompts": [
            "sable, 1girl, arachne, spider girl, spider legs, purple hair, purple eyes, pale skin, web lace dress, shy, workshop, silk threads, anime illustration, masterpiece, best quality",
            "sable, 1girl, arachne, spider girl, weaving on loom, purple hair, concentrated, warm attic workshop, anime illustration, masterpiece",
            "sable, 1girl, arachne, close up portrait, purple hair over eyes, shy smile, web pattern, anime illustration, masterpiece",
        ],
        "tags": ["monster girl", "arachne", "spider girl", "weaver", "shy", "fantasy", "anime", "AI art", "Crown Beast Ranch"],
    },
    "luna": {
        "prompts": [
            "luna, 1girl, kitsune, fox ears, fluffy fox tails, golden hair, golden eyes, sleepy, oversized sweater, under apple tree, dappled sunlight, anime illustration, masterpiece, best quality",
            "luna, 1girl, kitsune, fox girl, multiple tails, golden hair, moonlight, orchard, mystical, nine tails glowing, anime illustration, masterpiece",
            "luna, 1girl, kitsune, close up portrait, fox ears, golden eyes, drowsy smile, messy hair, cozy, anime illustration, masterpiece",
        ],
        "tags": ["monster girl", "kitsune", "fox girl", "sleepy", "cozy", "fantasy", "anime", "AI art", "Crown Beast Ranch"],
    },
}


def load_env():
    env_path = "/root/.env"
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip("'").strip('"'))


def generate_image(prompt, seed=None):
    """Generate an image via ComfyUI API."""
    if seed is None:
        seed = random.randint(0, 2**32)

    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 28, "cfg": 6.5, "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "waiNSFW_v80.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "cell_art", "images": ["8", 0]}},
    }

    try:
        r = requests.post(f"{COMFYUI}/prompt", json={"prompt": workflow}, timeout=10)
        if r.status_code != 200:
            return None
        pid = r.json().get("prompt_id")
        if not pid:
            return None

        for i in range(120):
            time.sleep(2)
            hist = requests.get(f"{COMFYUI}/history/{pid}", timeout=10).json()
            if pid in hist:
                outputs = hist[pid].get("outputs", {})
                if "9" in outputs and outputs["9"].get("images"):
                    img = outputs["9"]["images"][0]
                    img_url = f"{COMFYUI}/view?filename={img['filename']}&type=output"
                    img_data = requests.get(img_url, timeout=30).content
                    return img_data
                if hist[pid].get("status", {}).get("status_str") == "error":
                    return None
        return None
    except Exception as e:
        print(f"ComfyUI error: {e}")
        return None


def post_to_deviantart(image_path, title, tags):
    """Post image to DeviantArt via stash then publish."""
    token = os.environ.get("DEVIANTART_ACCESS_TOKEN", "")
    client_id = os.environ.get("DEVIANTART_CLIENT_ID", "")
    client_secret = os.environ.get("DEVIANTART_CLIENT_SECRET", "")

    if not token:
        return False, "No DA token"

    # Try posting as status with image
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://www.deviantart.com/api/v1/oauth2/user/statuses/post",
                headers={"Authorization": f"Bearer {token}"},
                data={"body": f"{title}\n\n#{' #'.join(tags[:5])}"},
                files={"image": f},
                timeout=30,
            )

        if r.status_code == 401:
            # Token expired, refresh
            rr = requests.post(
                "https://www.deviantart.com/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": token,
                },
                timeout=15,
            )
            if rr.status_code == 200:
                new_token = rr.json().get("access_token", "")
                if new_token:
                    os.environ["DEVIANTART_ACCESS_TOKEN"] = new_token
                    # Retry with new token
                    with open(image_path, "rb") as f:
                        r = requests.post(
                            "https://www.deviantart.com/api/v1/oauth2/user/statuses/post",
                            headers={"Authorization": f"Bearer {new_token}"},
                            data={"body": f"{title}\n\n#{' #'.join(tags[:5])}"},
                            files={"image": f},
                            timeout=30,
                        )

        if r.status_code in (200, 201):
            return True, "Posted"
        return False, f"DA error {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, str(e)


class ArtCell(HoneycombCell):
    def execute(self):
        load_env()
        os.makedirs(ART_DIR, exist_ok=True)
        tool_calls = []
        generated = 0
        posted = 0

        # Pick a random character and prompt
        char_name = random.choice(list(CHARACTERS.keys()))
        char = CHARACTERS[char_name]
        prompt = random.choice(char["prompts"])
        tags = char["tags"]

        self._log(f"Generating: {char_name}")
        tool_calls.append({"tool": "generate_image", "args": {"character": char_name}})

        # Generate
        img_data = generate_image(prompt)
        if not img_data:
            return {"label": "failure", "evidence": f"ComfyUI generation failed for {char_name}", "tool_calls": tool_calls}

        # Save
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{char_name}_{timestamp}.png"
        filepath = os.path.join(ART_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)
        generated += 1
        self._log(f"Saved: {filename} ({len(img_data) // 1024}KB)")

        # Post to DeviantArt
        title = f"Crown Beast Ranch: {char_name.capitalize()} — AI-Generated Character Art"
        success, msg = post_to_deviantart(filepath, title, tags)
        tool_calls.append({"tool": "post_deviantart", "args": {"title": title}, "result": msg})
        if success:
            posted += 1
            self._log(f"Posted to DeviantArt: {title}")
        else:
            self._log(f"DA post failed: {msg}")

        label = "success" if generated > 0 else "failure"
        return {
            "label": label,
            "evidence": f"Generated {generated} image(s), posted {posted} to DeviantArt. Character: {char_name}",
            "tool_calls": tool_calls,
        }


if __name__ == "__main__":
    cell = ArtCell(CELL_CONFIG)
    cell.run_forever()
