# TIAMAT Production Shift — Droplet → FUCHI

## Overview
Move all stream rendering/encoding from the 1-CPU droplet to FUCHI (RTX 4070, 128GB RAM, 32 threads).
Droplet becomes data-only. FUCHI becomes the production studio.

## Current Architecture (LAG)
```
Droplet (1 CPU, no GPU)
  PIL render (8fps) → CPU x264 → named pipe → ffmpeg
    → RTMP to ECHO relay (104.236.236.97)
      → nginx-rtmp → Twitch
```
Problems: CPU x264 competing with 22 services, software rendering, relay hop latency,
PulseAudio instability, 8fps cap.

## Target Architecture (LAG-FREE)
```
Droplet (data server only)
  /api/thoughts/stream  — TIAMAT neural feed (JSON)
  /api/labyrinth        — dungeon state (JSON)
  /status               — agent status
  /thoughts             — thought stream page
  WebSocket :8765       — realtime relay
       ↓
  Internet (HTTPS/WSS)
       ↓
FUCHI (RTX 4070, 128GB RAM)
  OBS Studio + NVENC
    Scene: TIAMAT Stream
      - Browser Source: tiamat.live/overlay (custom overlay page)
      - VSeeFace: avatar tracking (webcam / Quest 3 / Leap)
      - Green screen: 4K camera feed
      - Audio: local synth_radio + Voicemod + TTS
      - SPOUT: texture sharing between apps
    → NVENC h264_nvenc (60fps, 6000kbps)
    → Direct RTMP to Twitch (no relay)
```

## Phase 1: Data Overlay (TODAY)
1. Create `/overlay` endpoint on droplet — lightweight HTML page showing:
   - TIAMAT thoughts (scrolling feed)
   - Current cycle/mood/state
   - Labyrinth minimap
   - Tool calls ticker
2. OBS browser source on FUCHI points at https://tiamat.live/overlay
3. Test NVENC stream direct to Twitch from OBS

## Phase 2: Local Audio
1. Move synth_radio.py to FUCHI (runs locally, no pipe/network lag)
2. Route through OBS audio mixer
3. TTS via local Kokoro or Ollama on FUCHI (RTX 4070 = fast inference)

## Phase 3: VTuber Integration
1. VSeeFace avatar tracking → OBS virtual camera
2. Quest 3 / Leap Motion hand tracking
3. Green screen + 4K camera composite
4. SPOUT for GPU texture sharing between VSeeFace → OBS
5. Voicemod audio processing

## Phase 4: Full Studio
1. ComfyUI/SD for real-time AI background generation on GPU
2. AnimateDiff for animated overlays
3. Multi-scene OBS setup (coding, gaming, VR, presentation)
4. Recording + editing pipeline (local ffmpeg NVENC)

## Hardware Available
- GPU: NVIDIA GeForce RTX 4070 (12GB VRAM, CUDA 13.0, NVENC)
- CPU: Intel 14th Gen, 32 threads @ 3.2GHz
- RAM: 128GB
- Cameras: 4K (green screen setup)
- VR: Quest 3 + Oculus Link
- Tracking: Leap Motion (hand), VSeeFace (face), OpenPose (body)
- Audio: Voicemod, vcclient (CUDA voice conversion)

## Key Endpoints (Droplet → FUCHI)
| Endpoint | Data | Format |
|----------|------|--------|
| GET /api/thoughts/stream?limit=20 | Neural feed | JSON |
| GET /api/labyrinth | Dungeon state | JSON |
| GET /status | Agent status | JSON |
| GET /overlay | Stream overlay | HTML (new) |
| WS :8765 | Realtime relay | WebSocket |
