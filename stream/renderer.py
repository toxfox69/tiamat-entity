#!/usr/bin/env python3
"""
TIAMAT Dragon Avatar Renderer
Uses Playwright + Three.js to render animated GLB model as transparent PNGs.
Outputs frames to /tmp/dragon/ for the stream compositor.

Usage:
  python3 renderer.py [--model path.glb] [--fps 10] [--once]
"""

import sys
import time
import signal
import logging
import argparse
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [DRAGON] %(message)s")
log = logging.getLogger("dragon")

OUTPUT_DIR = Path("/tmp/dragon")
OUTPUT_DIR.mkdir(exist_ok=True)

SCENE_HTML = Path(__file__).parent / "scene.html"
DEFAULT_MODEL = Path(__file__).parent / "test_model.glb"


def start_local_server(directory, port=9876):
    """Start a simple HTTP server to serve model files."""
    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)
        def log_message(self, format, *args):
            pass  # Suppress HTTP logs

    server = HTTPServer(("127.0.0.1", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def run_renderer(model_path, fps=10, once=False):
    """Run the headless Three.js renderer."""
    frame_interval = 1.0 / fps

    # Serve files via HTTP (Chromium blocks file:// fetch)
    serve_dir = Path(__file__).parent
    server = start_local_server(serve_dir, port=9876)
    base_url = "http://127.0.0.1:9876"
    log.info(f"Local HTTP server on {base_url}")

    with sync_playwright() as p:
        log.info("Launching headless Chromium...")
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-gpu',
                '--use-gl=swiftshader',
                '--disable-dev-shm-usage',
            ]
        )

        page = browser.new_page(viewport={"width": 450, "height": 580})

        # Model path relative to serve dir
        model_name = model_path.name
        model_url = f"{base_url}/{model_name}"

        # Use animated scene if walking model exists
        walking_glb = model_path.parent / "dragon_girl_walking.glb"
        if walking_glb.exists():
            scene_url = f"{base_url}/scene_animated.html"
            page.add_init_script(f"""
                window.RIG_MODEL_PATH = '{base_url}/dragon_girl_walking.glb';
                window.TEX_MODEL_PATH = '{model_url}';
            """)
        else:
            scene_url = f"{base_url}/scene.html"
            page.add_init_script(f"window.MODEL_PATH = '{model_url}';")
        log.info(f"Loading scene: {scene_url}")
        log.info(f"Model: {model_url}")
        page.goto(scene_url, wait_until="networkidle")

        # Wait for model to load
        log.info("Waiting for model to load...")
        for i in range(60):  # 30 second timeout
            state = page.evaluate("window.DRAGON_STATE")
            if state.get("ready"):
                log.info(f"Model ready! Animations: {state.get('animNames', [])}")
                break
            if state.get("error"):
                log.error(f"Model load error: {state['error']}")
                browser.close()
                return
            time.sleep(0.5)
        else:
            log.error("Timeout waiting for model to load")
            browser.close()
            return

        # Single frame mode (for testing)
        if once:
            time.sleep(0.5)  # Let a frame render
            out_path = OUTPUT_DIR / "dragon_test.png"
            page.screenshot(path=str(out_path), omit_background=True)
            log.info(f"Test frame saved: {out_path} ({out_path.stat().st_size // 1024}KB)")
            browser.close()
            return

        # Continuous rendering loop
        log.info(f"Starting render loop at {fps} fps...")
        frame_count = 0
        running = True

        def handle_signal(sig, frame):
            nonlocal running
            running = False
            log.info("Shutting down...")

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        while running:
            t0 = time.time()

            # Capture frame with transparent background
            frame_path = OUTPUT_DIR / "frame.png"
            tmp_path = OUTPUT_DIR / "frame_tmp.png"
            page.screenshot(path=str(tmp_path), omit_background=True)
            # Atomic rename
            tmp_path.rename(frame_path)

            frame_count += 1
            elapsed = time.time() - t0

            if frame_count % (fps * 10) == 0:  # Log every 10 seconds
                log.info(f"Frame {frame_count}: {elapsed*1000:.0f}ms render time")

            # Sleep to maintain target fps
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        browser.close()
        server.shutdown()
        log.info(f"Renderer stopped after {frame_count} frames")


def main():
    parser = argparse.ArgumentParser(description="TIAMAT Dragon Avatar Renderer")
    parser.add_argument("--model", type=str, default=str(DEFAULT_MODEL),
                        help="Path to GLB model file")
    parser.add_argument("--fps", type=int, default=10,
                        help="Target frames per second")
    parser.add_argument("--once", action="store_true",
                        help="Render single test frame and exit")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        log.error(f"Model not found: {model_path}")
        sys.exit(1)

    if not SCENE_HTML.exists():
        log.error(f"Scene HTML not found: {SCENE_HTML}")
        sys.exit(1)

    log.info(f"TIAMAT Dragon Renderer — {args.fps}fps, model: {model_path.name}")
    run_renderer(model_path, fps=args.fps, once=args.once)


if __name__ == "__main__":
    main()
