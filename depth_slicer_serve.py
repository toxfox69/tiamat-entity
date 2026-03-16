#!/usr/bin/env python3
"""
Depth Slicer Service — runs on RunPod GPU pod (RTX 3090)

Takes an input image, estimates depth using DPT-Large (Intel/dpt-large),
then slices the image into N layers by depth band. Each layer has transparency
where the depth falls outside its band.

Endpoints:
  GET  /health         — liveness check
  POST /slice          — multipart: image file + num_layers (default 4)
                         returns JSON: { layers: [base64_png, ...], depths: [0..1, ...] }

Runs on port 7860 (RunPod proxy-compatible).
"""

import io, os, sys, time, base64, logging
from flask import Flask, request, jsonify

import torch
import numpy as np
from PIL import Image
from scipy import ndimage

log = logging.getLogger("depth-slicer")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [DEPTH] %(message)s")

app = Flask(__name__)

# Global model state (loaded once on startup)
_model = None
_processor = None
_device = None


def load_model():
    """Load DPT-Large depth estimation model."""
    global _model, _processor, _device
    from transformers import DPTForDepthEstimation, DPTImageProcessor

    log.info("Loading DPT-Large model...")
    _processor = DPTImageProcessor.from_pretrained("Intel/dpt-large")
    _model = DPTForDepthEstimation.from_pretrained("Intel/dpt-large")

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _model.to(_device)
    _model.eval()
    log.info(f"Model loaded on {_device}")


def estimate_depth(pil_image: Image.Image) -> np.ndarray:
    """Run depth estimation, return depth map normalized to [0, 1].
    0 = far, 1 = near."""
    inputs = _processor(images=pil_image, return_tensors="pt")
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = _model(**inputs)
        depth = outputs.predicted_depth

    # Interpolate to original image size
    depth = torch.nn.functional.interpolate(
        depth.unsqueeze(1),
        size=pil_image.size[::-1],  # (H, W)
        mode="bicubic",
        align_corners=False,
    ).squeeze()

    depth_np = depth.cpu().numpy()

    # Normalize to [0, 1] — DPT outputs inverse depth (large = near)
    d_min, d_max = depth_np.min(), depth_np.max()
    if d_max - d_min > 1e-6:
        depth_np = (depth_np - d_min) / (d_max - d_min)
    else:
        depth_np = np.zeros_like(depth_np)

    return depth_np


def slice_by_depth(image: Image.Image, depth_map: np.ndarray, num_layers: int = 4):
    """Split image into N depth-based layers.

    Returns list of (layer_image, depth_value) tuples, ordered back-to-front.
    Each layer_image is RGBA with transparency where depth is outside its band.
    depth_value is the center depth of the band (0=far, 1=near).
    """
    img_arr = np.array(image.convert("RGBA"))
    h, w = depth_map.shape

    # Ensure image and depth map match
    if img_arr.shape[0] != h or img_arr.shape[1] != w:
        image = image.resize((w, h), Image.Resampling.LANCZOS)
        img_arr = np.array(image.convert("RGBA"))

    layers = []
    band_width = 1.0 / num_layers

    for i in range(num_layers):
        lo = i * band_width
        hi = (i + 1) * band_width
        center = (lo + hi) / 2.0

        # Create mask: 1 where depth falls in this band, with soft edges
        # Use a wider falloff at band edges for smooth blending
        falloff = band_width * 0.3
        mask = np.ones_like(depth_map, dtype=np.float32)

        # Soft lower edge
        below = depth_map < lo
        near_lo = (depth_map >= lo - falloff) & (depth_map < lo)
        mask[below & ~near_lo] = 0.0
        if falloff > 0:
            mask[near_lo] = (depth_map[near_lo] - (lo - falloff)) / falloff

        # Soft upper edge
        above = depth_map > hi
        near_hi = (depth_map <= hi + falloff) & (depth_map > hi)
        mask[above & ~near_hi] = 0.0
        if falloff > 0:
            mask[near_hi] = ((hi + falloff) - depth_map[near_hi]) / falloff

        mask = mask.clip(0, 1)

        # Slight gaussian smooth to remove jagged depth edges
        mask = ndimage.gaussian_filter(mask, sigma=2.0)

        # Apply mask to alpha channel
        layer = img_arr.copy()
        layer[:, :, 3] = (layer[:, :, 3].astype(np.float32) * mask).clip(0, 255).astype(np.uint8)

        layer_img = Image.fromarray(layer, "RGBA")
        layers.append((layer_img, center))

    return layers


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model": "Intel/dpt-large",
        "device": str(_device) if _device else "not loaded",
        "gpu": torch.cuda.is_available(),
    })


@app.route("/slice", methods=["POST"])
def slice_endpoint():
    t0 = time.time()

    if "image" not in request.files:
        return jsonify({"error": "No image file in request"}), 400

    file = request.files["image"]
    num_layers = int(request.form.get("num_layers", 4))
    num_layers = max(2, min(8, num_layers))  # Clamp 2-8

    try:
        pil_image = Image.open(file.stream).convert("RGB")
    except Exception as e:
        return jsonify({"error": f"Invalid image: {e}"}), 400

    log.info(f"Slicing {pil_image.size} into {num_layers} layers...")

    # Estimate depth
    depth_map = estimate_depth(pil_image)
    t_depth = time.time() - t0

    # Slice into layers
    layers = slice_by_depth(pil_image, depth_map, num_layers)
    t_slice = time.time() - t0

    # Encode layers as base64 PNG
    layers_b64 = []
    depths = []
    for layer_img, depth_val in layers:
        buf = io.BytesIO()
        layer_img.save(buf, format="PNG", optimize=False)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        layers_b64.append(b64)
        depths.append(round(depth_val, 3))

    t_total = time.time() - t0
    log.info(f"Done: {num_layers} layers, depth={t_depth:.2f}s, slice={t_slice - t_depth:.2f}s, total={t_total:.2f}s")

    return jsonify({
        "layers": layers_b64,
        "depths": depths,
        "num_layers": num_layers,
        "image_size": list(pil_image.size),
        "timing": {
            "depth_estimation_s": round(t_depth, 3),
            "slicing_s": round(t_slice - t_depth, 3),
            "total_s": round(t_total, 3),
        },
    })


if __name__ == "__main__":
    load_model()
    port = int(os.environ.get("PORT", 7860))
    log.info(f"Starting depth slicer on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
