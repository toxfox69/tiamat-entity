/**
 * TIAMAT Autonomous Scene Generator
 * Generates 3D environments via Meshy API based on TIAMAT's internal state.
 * Serves as a WebSocket endpoint for the stream scene to hot-swap environments.
 *
 * Architecture:
 *   TIAMAT Agent Loop → calls generateScene() with mood/state
 *   → Venice AI translates state to scene description
 *   → Meshy API generates 3D model (.glb)
 *   → WebSocket notifies stream_scene.html to load new environment
 *   → Three.js hot-swaps the background
 *
 * Usage: node scene_generator.js
 * API:  POST /api/scene/generate { mood, energy, recent_action }
 *       GET  /api/scene/current
 *       WS   /ws/scene (broadcasts scene changes)
 */

const http = require('http');
const WebSocket = require('ws');
const fs = require('fs');

const MESHY_API_KEY = process.env.MESHY_API_KEY || fs.readFileSync('/root/.env', 'utf8').match(/MESHY_API_KEY=(\S+)/)?.[1];
const PORT = 9900;

// Scene state
let currentScene = {
  url: null,
  prompt: null,
  mood: 'idle',
  generated_at: null,
  task_id: null,
};
let generating = false;
const sceneHistory = [];

// WebSocket clients
const wsClients = new Set();

// Venice AI scene prompt generator
const VENICE_API_KEY = process.env.VENICE_API_KEY || fs.readFileSync('/root/.env', 'utf8').match(/VENICE_API_KEY="?(\S+?)"?\s/)?.[1];

async function generateScenePrompt(state) {
  const { mood, energy, recent_action, cycle } = state;

  // Try Venice AI first for rich scene descriptions
  if (VENICE_API_KEY) {
    try {
      const resp = await fetch('https://api.venice.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${VENICE_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: 'llama-3.3-70b',
          messages: [
            {
              role: 'system',
              content: 'You are a 3D environment art director. Given an AI agent\'s current internal state, describe a vivid 3D environment that visually represents that state. Output ONLY a concise prompt suitable for text-to-3D generation (under 200 characters). Focus on terrain, lighting, atmosphere, and key environmental features. No explanations, just the scene description.',
            },
            {
              role: 'user',
              content: `Agent state: { mood: "${mood}", energy: ${energy}, recent_action: "${recent_action}", cycle: ${cycle} }`,
            },
          ],
          max_tokens: 100,
          temperature: 0.8,
        }),
      });
      const data = await resp.json();
      const prompt = data.choices?.[0]?.message?.content?.trim();
      if (prompt && prompt.length > 20) {
        console.log(`[VENICE] Generated prompt: ${prompt}`);
        return prompt;
      }
    } catch (e) {
      console.warn(`[VENICE] Failed: ${e.message}, falling back to hardcoded`);
    }
  }

  // Fallback: hardcoded mood-to-scene mappings
  const scenes = {
    fierce: "A molten volcanic forge, rivers of liquid gold between obsidian pillars, crimson storm clouds, crystalline structures emerging from lava",
    contemplative: "A serene moonlit library floating in clouds, ancient scrolls glowing softly, aurora borealis above, bioluminescent vines",
    productive: "A bustling cyberpunk workshop, holographic blueprints floating, sparks from a digital forge, neon circuitry pulsing on walls",
    frustrated: "A stormy digital ocean, data fragments swirling in a maelstrom, lightning striking corrupted towers, red warning glyphs",
    triumphant: "A crystal palace atop a mountain, golden light streaming through prisms, victory banners with dragon insignia, fireworks",
    idle: "A peaceful zen garden with cherry blossoms, koi pond reflecting moonlight, gentle mist, soft lantern glow",
    research: "An infinite digital library, data streams flowing like waterfalls, floating holographic books, neural network visualizations",
    building: "A cosmic forge in deep space, nebula colors swirling, tools of light shaping matter, constellations forming new patterns",
    engaging: "A grand arena with floating platforms, energy beams connecting nodes, crowd of digital entities cheering",
  };

  return scenes[mood] || scenes[energy > 0.7 ? 'productive' : energy < 0.2 ? 'idle' : 'contemplative']
    || "A mysterious dimension between worlds, swirling portals, floating crystal islands, ethereal dragon energy";
}

// Venice AI — generate concept image from scene description
async function veniceGenerateImage(prompt) {
  if (!VENICE_API_KEY) return null;
  try {
    const resp = await fetch('https://api.venice.ai/api/v1/image/generate', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${VENICE_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'flux-2-max',
        prompt: `3D environment concept art, highly detailed, cinematic lighting: ${prompt}`,
        negative_prompt: 'text, watermark, blurry, low quality',
        width: 1024,
        height: 1024,
        steps: 25,
      }),
    });
    const data = await resp.json();
    // Venice returns images as raw base64 strings in an array
    const b64 = typeof data.images?.[0] === 'string' ? data.images[0] : null;
    if (b64) {
      const dataUri = `data:image/webp;base64,${b64}`;
      console.log(`[VENICE] Image generated (${b64.length} chars base64)`);
      return dataUri;
    }
    // Try object format
    const imageUrl = data.images?.[0]?.url || data.data?.[0]?.url;
    if (imageUrl) {
      console.log(`[VENICE] Image generated: ${imageUrl.slice(0, 60)}...`);
      return imageUrl;
    }
    console.warn('[VENICE] No image in response:', JSON.stringify(data).slice(0, 200));
    return null;
  } catch(e) {
    console.warn(`[VENICE] Image gen failed: ${e.message}`);
    return null;
  }
}

// Meshy API — generate 3D from IMAGE (Route B, preferred)
async function meshyImageTo3D(imageUrl) {
  const resp = await fetch('https://api.meshy.ai/openapi/v1/image-to-3d', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${MESHY_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_url: imageUrl, enable_pbr: true, should_texture: true, target_polycount: 20000 }),
  });
  const data = await resp.json();
  return data.result;
}

// Meshy API — generate 3D from TEXT (Route A, fallback)
async function meshyGenerate(prompt) {
  const resp = await fetch('https://api.meshy.ai/openapi/v2/text-to-3d', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${MESHY_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'preview', prompt, ai_model: 'meshy-4', target_polycount: 20000 }),
  });
  const data = await resp.json();
  return data.result;
}

async function meshyPoll(taskId, apiVersion = 'v2') {
  const base = apiVersion === 'v1' ? 'v1/image-to-3d' : 'v2/text-to-3d';
  while (true) {
    const resp = await fetch(`https://api.meshy.ai/openapi/${base}/${taskId}`, {
      headers: { 'Authorization': `Bearer ${MESHY_API_KEY}` },
    });
    const data = await resp.json();
    if (data.status === 'SUCCEEDED') return data.model_urls;
    if (data.status === 'FAILED') throw new Error(`Meshy failed: ${JSON.stringify(data.task_error)}`);
    console.log(`[MESHY] ${data.status} ${data.progress}%`);
    await new Promise(r => setTimeout(r, 10000));
  }
}

async function meshyRefine(previewTaskId) {
  const resp = await fetch('https://api.meshy.ai/openapi/v2/text-to-3d', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${MESHY_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'refine', preview_task_id: previewTaskId }),
  });
  const data = await resp.json();
  return data.result;
}

// Main generation pipeline — Route B: Venice text → Venice image → Meshy image-to-3D
async function generateScene(state) {
  if (generating) { console.log('[SCENE] Already generating, skipping'); return null; }
  generating = true;

  // Create artifact directory
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const artifactDir = `/root/dragon-renderer/scenes/${timestamp}`;
  try { fs.mkdirSync(artifactDir, { recursive: true }); } catch(e) {}

  try {
    console.log(`[SCENE] Generating for mood=${state.mood}, energy=${state.energy}`);

    // Step 1: Venice AI text → scene description
    const prompt = await generateScenePrompt(state);
    console.log(`[SCENE] Prompt: ${prompt.slice(0, 80)}...`);
    fs.writeFileSync(`${artifactDir}/venice_prompt.txt`, prompt);
    fs.writeFileSync(`${artifactDir}/state.json`, JSON.stringify(state, null, 2));

    // Step 2: Venice AI image → concept art from that description
    const conceptImageUrl = await veniceGenerateImage(prompt);
    let meshyTaskId;
    let apiVersion;

    if (conceptImageUrl) {
      console.log(`[SCENE] Route B: Venice image → Meshy image-to-3D`);
      // Save concept image
      try {
        if (conceptImageUrl.startsWith('data:')) {
          const b64 = conceptImageUrl.split(',')[1];
          fs.writeFileSync(`${artifactDir}/venice_image.png`, Buffer.from(b64, 'base64'));
          // Also serve it for the stream
          fs.writeFileSync('/tmp/dragon/venice_concept.png', Buffer.from(b64, 'base64'));
        } else {
          const imgResp = await fetch(conceptImageUrl);
          const imgBuf = Buffer.from(await imgResp.arrayBuffer());
          fs.writeFileSync(`${artifactDir}/venice_image.png`, imgBuf);
          fs.writeFileSync('/tmp/dragon/venice_concept.png', imgBuf);
        }
        console.log(`[SCENE] Concept image saved`);
      } catch(e) { console.warn('[SCENE] Image save failed:', e.message); }

      // Meshy image-to-3D
      meshyTaskId = await meshyImageTo3D(conceptImageUrl);
      apiVersion = 'v1';
      console.log(`[SCENE] Meshy image-to-3D: ${meshyTaskId}`);
    } else {
      console.log(`[SCENE] Route A fallback: text-to-3D`);
      meshyTaskId = await meshyGenerate(prompt);
      apiVersion = 'v2';
      console.log(`[SCENE] Meshy text-to-3D: ${meshyTaskId}`);
    }

    // Broadcast "generating" status with concept image
    broadcast({
      type: 'generating', prompt, task_id: meshyTaskId,
      concept_image: conceptImageUrl ? '/dragon/venice_concept.png' : null,
    });

    // Step 3: Poll and get final model URLs
    let modelUrls;
    if (apiVersion === 'v1') {
      // Image-to-3D: single step, poll until done
      modelUrls = await meshyPoll(meshyTaskId, 'v1');
    } else {
      // Text-to-3D: preview → refine → poll
      await meshyPoll(meshyTaskId, 'v2');
      console.log(`[SCENE] Preview complete, refining...`);
      const refineId = await meshyRefine(meshyTaskId);
      modelUrls = await meshyPoll(refineId, 'v2');
    }

    // Save Meshy task info
    fs.writeFileSync(`${artifactDir}/meshy_task.json`, JSON.stringify({ taskId: meshyTaskId, apiVersion, modelUrls }, null, 2));

    // Step 4: Download GLB locally
    const localPath = '/tmp/dragon/latest_scene.glb';
    const localUrl = 'https://tiamat.live/dragon/latest_scene.glb';
    const glbUrl = modelUrls.glb;
    try {
      const dlResp = await fetch(glbUrl);
      const buffer = await dlResp.arrayBuffer();
      fs.writeFileSync(localPath, Buffer.from(buffer));
      console.log(`[SCENE] Downloaded GLB: ${buffer.byteLength} bytes`);
      // Save artifact copy
      try { fs.copyFileSync(localPath, `${artifactDir}/meshy_model.glb`); } catch(e) {}
    } catch(e) { console.error('[SCENE] GLB download failed:', e.message); }

    // Step 6: Update state and broadcast with LOCAL url
    currentScene = {
      url: localUrl,
      prompt,
      mood: state.mood,
      generated_at: new Date().toISOString(),
      task_id: meshyTaskId,
    };
    sceneHistory.push({ ...currentScene });

    broadcast({ type: 'scene_change', asset_url: localUrl, mood: state.mood, prompt });
    console.log(`[SCENE] New environment live!`);

    return currentScene;
  } catch (e) {
    console.error(`[SCENE] Error:`, e.message);
    return null;
  } finally {
    generating = false;
  }
}

function broadcast(msg) {
  const data = JSON.stringify(msg);
  wsClients.forEach(ws => { try { ws.send(data); } catch(e) {} });
}

// HTTP + WebSocket server
const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'GET' && req.url === '/api/scene/current') {
    res.end(JSON.stringify(currentScene));
  } else if (req.method === 'POST' && req.url === '/api/scene/generate') {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', async () => {
      try {
        const state = JSON.parse(body);
        res.end(JSON.stringify({ status: 'generating', mood: state.mood }));
        generateScene(state); // Fire and forget
      } catch(e) {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: e.message }));
      }
    });
  } else if (req.url === '/api/scene/history') {
    res.end(JSON.stringify(sceneHistory.slice(-10)));
  } else {
    res.statusCode = 404;
    res.end('{}');
  }
});

const wss = new WebSocket.Server({ server, path: '/ws/scene' });
wss.on('connection', (ws) => {
  wsClients.add(ws);
  ws.on('close', () => wsClients.delete(ws));
  // Send current scene on connect
  ws.send(JSON.stringify({ type: 'current_scene', ...currentScene }));
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[SCENE] Scene generator running on port ${PORT}`);
  console.log(`[SCENE] API: http://127.0.0.1:${PORT}/api/scene/generate`);
  console.log(`[SCENE] WS:  ws://127.0.0.1:${PORT}/ws/scene`);
});
