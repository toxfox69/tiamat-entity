#!/usr/bin/env python3
"""
Parallax Depth Background for TIAMAT Stream

Two modes:
  1. FLAT DRIFT (default, no RunPod): Venice concept image with subtle sinusoidal
     pan/zoom animation. Works immediately, no GPU needed.
  2. DEPTH PARALLAX (when RunPod depth slicer is running): Image split into
     depth layers that move at different speeds based on depth, creating
     a real parallax effect.

Usage:
    from parallax_bg import ParallaxBackground
    pb = ParallaxBackground(1280, 720)
    pb.update_scene("/tmp/dragon/venice_concept.png")
    frame = pb.render(t)  # t = time in seconds (monotonic)

render() returns an RGBA PIL Image at (W, H). Designed for <10ms per call.
"""

import os, math, time, logging, io
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

log = logging.getLogger("parallax")

# Depth slicer endpoint — set to enable true parallax
RUNPOD_DEPTH_URL = os.environ.get("RUNPOD_DEPTH_URL", None)


class ParallaxBackground:
    """Animated background with flat-drift fallback and depth-parallax upgrade."""

    def __init__(self, width=1280, height=720, num_layers=4):
        self.W = width
        self.H = height
        self.num_layers = num_layers

        # Flat drift state
        self._flat_img = None       # RGBA, oversized for pan headroom
        self._flat_arr = None       # numpy array of flat_img for fast crops
        self._flat_base = None      # Original sized to (W, H)

        # Depth parallax state
        self._layers = []           # list of RGBA PIL Images (back to front)
        self._layer_arrays = []     # numpy arrays for fast rendering
        self._layer_depths = []     # 0.0 (far) to 1.0 (near), per layer
        self._has_depth = False

        # Shared
        self._source_path = None
        self._source_mtime = 0

    def update_scene(self, image_path: str, force=False):
        """Load a new scene image. If RunPod depth slicer is available,
        request depth layers; otherwise fall back to flat drift."""
        p = Path(image_path)
        if not p.exists():
            return

        mtime = p.stat().st_mtime
        if mtime == self._source_mtime and not force:
            return  # Already loaded

        self._source_path = str(p)
        self._source_mtime = mtime

        # Load base image
        try:
            base = Image.open(str(p)).convert("RGBA")
        except Exception as e:
            log.warning(f"parallax: failed to load {p}: {e}")
            return

        # Always prepare flat-drift version (fallback)
        self._prepare_flat(base)

        # Try depth slicer if URL is set
        if RUNPOD_DEPTH_URL and HAS_REQUESTS:
            try:
                self._fetch_depth_layers(str(p))
                return  # Success — depth parallax active
            except Exception as e:
                log.warning(f"parallax: depth slicer failed, using flat drift: {e}")

        self._has_depth = False

    def _prepare_flat(self, base_img: Image.Image):
        """Prepare oversized image for pan/zoom drift animation.
        We scale the image to 120% of frame size so we have room to pan.
        Pre-convert to numpy array for fast per-frame crops."""
        # Target: 120% of frame for pan headroom
        scale = 1.20
        ow = int(self.W * scale)
        oh = int(self.H * scale)
        resized = base_img.resize((ow, oh), Image.Resampling.LANCZOS)

        # Apply the same treatment as venice_stream.py: blur + darken + overlay
        resized = resized.filter(ImageFilter.GaussianBlur(radius=10))
        resized = ImageEnhance.Brightness(resized).enhance(0.55)
        overlay = Image.new("RGBA", (ow, oh), (6, 6, 18, 100))
        resized = Image.alpha_composite(resized, overlay)

        # Store as numpy array for fast cropping (no PIL overhead per frame)
        self._flat_arr = np.array(resized)  # (oh, ow, 4) uint8
        self._flat_img = resized
        self._flat_base = base_img.resize((self.W, self.H), Image.Resampling.LANCZOS)

    def _fetch_depth_layers(self, image_path: str):
        """POST image to RunPod depth slicer service, get back N layers as PNGs."""
        url = RUNPOD_DEPTH_URL.rstrip("/") + "/slice"

        with open(image_path, "rb") as f:
            files = {"image": (Path(image_path).name, f, "image/png")}
            data = {"num_layers": str(self.num_layers)}
            resp = requests.post(url, files=files, data=data, timeout=30)

        if resp.status_code != 200:
            raise RuntimeError(f"Depth slicer returned {resp.status_code}: {resp.text[:200]}")

        result = resp.json()
        layers_b64 = result.get("layers", [])
        depths = result.get("depths", [])

        if not layers_b64:
            raise RuntimeError("Depth slicer returned no layers")

        self._layers = []
        self._layer_arrays = []
        self._layer_depths = []

        for i, b64 in enumerate(layers_b64):
            import base64 as b64mod
            img_bytes = b64mod.b64decode(b64)
            layer_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
            # Resize to frame size + headroom for parallax shift
            # Far layers need less headroom, near layers need more
            depth = depths[i] if i < len(depths) else i / max(len(layers_b64) - 1, 1)
            headroom = 1.0 + 0.15 * depth  # far=1.0x, near=1.15x
            lw = int(self.W * headroom)
            lh = int(self.H * headroom)
            layer_img = layer_img.resize((lw, lh), Image.Resampling.LANCZOS)

            # Blur background layers more than foreground
            blur_r = max(0, int(8 * (1.0 - depth)))
            if blur_r > 0:
                layer_img = layer_img.filter(ImageFilter.GaussianBlur(radius=blur_r))

            # Darken far layers
            brightness = 0.4 + 0.6 * depth
            layer_img = ImageEnhance.Brightness(layer_img).enhance(brightness)

            self._layers.append(layer_img)
            self._layer_arrays.append(np.array(layer_img))  # Pre-convert for fast rendering
            self._layer_depths.append(depth)

        self._has_depth = True
        log.info(f"parallax: loaded {len(self._layers)} depth layers")

    def render(self, t: float) -> Image.Image:
        """Render the animated background for time t (seconds).
        Returns RGBA Image at (self.W, self.H).
        Target: <10ms per call."""
        if self._has_depth and self._layers:
            return self._render_depth(t)
        elif self._flat_img:
            return self._render_flat(t)
        else:
            # No image loaded — solid dark
            return Image.new("RGBA", (self.W, self.H), (8, 10, 20, 255))

    def _render_flat(self, t: float) -> Image.Image:
        """Flat drift mode: sinusoidal pan over oversized numpy array.
        No resize needed — we crop exactly (W, H) pixels from the 120% image.
        ~2-4ms per frame."""
        arr = self._flat_arr  # (oh, ow, 4) uint8
        oh, ow = arr.shape[:2]

        # Pan: slow sinusoidal drift (different periods = Lissajous path)
        pan_x = math.sin(t * 0.21) * 0.5 + 0.5  # 0..1
        pan_y = math.sin(t * 0.14 + 1.0) * 0.5 + 0.5  # 0..1

        # Max pan range = oversized - frame size
        max_x = ow - self.W
        max_y = oh - self.H
        cx = int(pan_x * max_x)
        cy = int(pan_y * max_y)

        # Clamp
        cx = max(0, min(cx, max_x))
        cy = max(0, min(cy, max_y))

        # Integer-pixel crop from numpy — no resize, very fast
        cropped = arr[cy:cy + self.H, cx:cx + self.W]
        return Image.fromarray(cropped, "RGBA")

    def _render_depth(self, t: float) -> Image.Image:
        """Depth parallax mode: each layer moves at speed proportional to depth.
        Uses pre-converted numpy arrays for fast cropping."""
        canvas_arr = np.full((self.H, self.W, 4), (8, 10, 20, 255), dtype=np.uint8)

        # Base parallax motion — sinusoidal, different axis speeds
        base_dx = math.sin(t * 0.18) * 40  # pixels, horizontal
        base_dy = math.sin(t * 0.12 + 0.7) * 20  # pixels, vertical

        for i, (layer_arr, depth) in enumerate(zip(self._layer_arrays, self._layer_depths)):
            lh, lw = layer_arr.shape[:2]

            # Parallax factor: far layers (depth=0) move less, near (depth=1) move more
            factor = 0.2 + 0.8 * depth
            dx = int(base_dx * factor)
            dy = int(base_dy * factor)

            ox = max(0, min((lw - self.W) // 2 - dx, lw - self.W))
            oy = max(0, min((lh - self.H) // 2 - dy, lh - self.H))

            cropped = layer_arr[oy:oy + self.H, ox:ox + self.W]

            # Alpha composite in numpy (fast)
            alpha = cropped[:, :, 3:4].astype(np.float32) / 255.0
            canvas_arr[:, :, :3] = (
                canvas_arr[:, :, :3].astype(np.float32) * (1.0 - alpha) +
                cropped[:, :, :3].astype(np.float32) * alpha
            ).clip(0, 255).astype(np.uint8)
            canvas_arr[:, :, 3] = 255  # Keep canvas fully opaque

        return Image.fromarray(canvas_arr, "RGBA")

    @property
    def mode(self) -> str:
        """Current rendering mode."""
        if self._has_depth and self._layers:
            return "depth_parallax"
        elif self._flat_img:
            return "flat_drift"
        else:
            return "none"


# Quick self-test
if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dragon/venice_concept.png"
    pb = ParallaxBackground(1280, 720)
    pb.update_scene(path)
    print(f"Mode: {pb.mode}")

    # Benchmark
    times = []
    for i in range(30):
        t0 = time.time()
        frame = pb.render(i * 0.1)
        dt = (time.time() - t0) * 1000
        times.append(dt)

    avg = sum(times) / len(times)
    peak = max(times)
    print(f"Benchmark: avg={avg:.1f}ms, peak={peak:.1f}ms over {len(times)} frames")
    print(f"Frame size: {frame.size}, mode: {frame.mode}")

    # Save a preview
    preview_path = "/tmp/parallax_preview.png"
    frame.save(preview_path)
    print(f"Preview saved: {preview_path}")
