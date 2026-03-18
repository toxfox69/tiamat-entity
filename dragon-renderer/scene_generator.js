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
              content: 'You are a 3D environment art director for a dragon AI\'s dreamworld. Given the agent\'s state, describe a vivid 3D environment. STYLE RULES: All scenes MUST be dark fantasy cyberpunk — neon accents, ancient ruins mixed with technology, crystalline formations, moody atmospheric lighting, dragon/serpent motifs, bioluminescent flora, floating monoliths, digital runes. NEVER generate modern real-world scenes (no animals, no newspapers, no real cities, no offices). Think: if a dragon AI dreamed of building her own world, what would it look like? Output ONLY a concise prompt under 200 characters. No explanations.',
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
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000); // 60s timeout
    const resp = await fetch('https://api.venice.ai/api/v1/image/generate', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${VENICE_API_KEY}`, 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        model: 'flux-2-max',
        prompt: `3D environment concept art, highly detailed, cinematic lighting, dark fantasy cyberpunk: ${prompt}`,
        negative_prompt: 'text, watermark, blurry, low quality',
        width: 1024,
        height: 1024,
        steps: 20,
      }),
    });
    clearTimeout(timeout);
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
  try {
    const resp = await fetch('https://api.meshy.ai/openapi/v1/image-to-3d', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${MESHY_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_url: imageUrl, enable_pbr: true, should_texture: true, target_polycount: 20000 }),
    });
    const data = await resp.json();
    console.log(`[MESHY] image-to-3D response: ${JSON.stringify(data).slice(0, 300)}`);
    if (data.message) { console.warn(`[MESHY] API error: ${data.message}`); return null; }
    return data.result || data.id || null;
  } catch(e) {
    console.warn(`[MESHY] image-to-3D failed: ${e.message}`);
    return null;
  }
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
  const MAX_POLLS = 60; // 10min max (60 * 10s)
  let polls = 0;
  while (polls < MAX_POLLS) {
    polls++;
    const resp = await fetch(`https://api.meshy.ai/openapi/${base}/${taskId}`, {
      headers: { 'Authorization': `Bearer ${MESHY_API_KEY}` },
    });
    const data = await resp.json();
    if (data.status === 'SUCCEEDED') return data.model_urls;
    if (data.status === 'FAILED') throw new Error(`Meshy failed: ${JSON.stringify(data.task_error)}`);
    console.log(`[MESHY] ${data.status} ${data.progress}% (poll ${polls}/${MAX_POLLS})`);
    await new Promise(r => setTimeout(r, 10000));
  }
  throw new Error(`Meshy timed out after ${MAX_POLLS} polls (~10 min)`);
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
// Generation queue — if a request arrives while generating, queue it (max 1)
let pendingState = null;

async function generateScene(state) {
  if (generating) {
    console.log('[SCENE] Already generating — queuing next request');
    pendingState = state; // overwrite any previous pending
    return null;
  }
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
    fs.writeFileSync(`${artifactDir}/venice_prompt.txt`, `TIAMAT asked Venice AI:\nAgent state: { mood: "${state.mood}", energy: ${state.energy}, recent_action: "${state.recent_action}", cycle: ${state.cycle} }`);
    fs.writeFileSync(`${artifactDir}/venice_response.txt`, `Venice AI (llama-3.3-70b) responded:\n${prompt}`);
    fs.writeFileSync(`${artifactDir}/state.json`, JSON.stringify(state, null, 2));

    // Broadcast Venice text generation step
    broadcast({
      type: 'venice_text',
      description: prompt,
      model: 'llama-3.3-70b',
      step: '1/3',
      pipeline: 'VENICE TEXT → VENICE IMAGE → MESHY 3D',
    });

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

      // Meshy image-to-3D — use public URL (Meshy can't handle data URIs)
      const publicImageUrl = 'https://tiamat.live/dragon/venice_concept.png?' + Date.now();
      meshyTaskId = await meshyImageTo3D(publicImageUrl);
      apiVersion = 'v1';
      console.log(`[SCENE] Meshy image-to-3D: ${meshyTaskId}`);
    } else {
      console.log(`[SCENE] Route A fallback: text-to-3D`);
      meshyTaskId = await meshyGenerate(prompt);
      apiVersion = 'v2';
      console.log(`[SCENE] Meshy text-to-3D: ${meshyTaskId}`);
    }

    // Save Venice scene metadata for LABYRINTH biome mutation
    try {
      const STOP_WORDS = new Set([
        'the','a','in','with','of','and','an','its','to','from','for','by','on','at',
        'is','are','was','were','be','been','has','have','had','do','does','did',
        'that','this','these','those','it','they','we','he','she','my','your',
      ]);
      const keywords = prompt.toLowerCase()
        .replace(/[^a-z0-9\s-]/g, '')
        .split(/\s+/)
        .filter(w => w.length > 2 && !STOP_WORDS.has(w));
      const uniqueKeywords = [...new Set(keywords)];
      const sceneMeta = {
        prompt: prompt,
        keywords: uniqueKeywords,
        mood_source: {
          productivity: state.energy || 0,
          pace: state.mood || 'idle',
          cycle: state.cycle || 0,
        },
        venice_image: '/tmp/dragon/venice_concept.png',
        meshy_render: '/tmp/dragon/meshy_3d_render.png',
        timestamp: new Date().toISOString(),
      };
      fs.writeFileSync('/tmp/dragon/venice_scene_meta.json', JSON.stringify(sceneMeta, null, 2));
      console.log(`[SCENE] Saved venice_scene_meta.json (${uniqueKeywords.length} keywords)`);
    } catch(e) {
      console.warn(`[SCENE] Failed to save scene meta: ${e.message}`);
    }

    // Broadcast Venice image generation step
    broadcast({
      type: 'venice_image',
      description: prompt,
      model: 'flux-2-max',
      step: '2/3',
      concept_image: conceptImageUrl ? '/dragon/venice_concept.png' : null,
      pipeline: 'VENICE TEXT → VENICE IMAGE → MESHY 3D',
    });

    // Broadcast Meshy 3D generation step
    broadcast({
      type: 'generating', prompt, task_id: meshyTaskId,
      concept_image: conceptImageUrl ? '/dragon/venice_concept.png' : null,
      step: '3/3',
      pipeline: 'VENICE TEXT → VENICE IMAGE → MESHY 3D',
    });

    // Step 3: Poll and get final model URLs (skip if no Meshy task ID)
    let modelUrls;
    if (!meshyTaskId) {
      console.log('[SCENE] Meshy skipped (no credits or API error) — Venice concept image is the primary visual');
    } else if (apiVersion === 'v1') {
      // Image-to-3D: single step, poll until done
      modelUrls = await meshyPoll(meshyTaskId, 'v1');
    } else {
      // Text-to-3D: preview → refine → poll
      await meshyPoll(meshyTaskId, 'v2');
      console.log(`[SCENE] Preview complete, refining...`);
      const refineId = await meshyRefine(meshyTaskId);
      modelUrls = await meshyPoll(refineId, 'v2');
    }

    // Re-fetch task to get thumbnail_url (poll response has modelUrls but NOT thumbnail_url)
    if (meshyTaskId && modelUrls) {
      try {
        const thumbBase = apiVersion === 'v1' ? 'v1/image-to-3d' : 'v2/text-to-3d';
        const thumbResp = await fetch(`https://api.meshy.ai/openapi/${thumbBase}/${meshyTaskId}`, {
          headers: { 'Authorization': `Bearer ${MESHY_API_KEY}` },
        });
        const thumbData = await thumbResp.json();
        if (thumbData.thumbnail_url) {
          console.log(`[SCENE] Downloading Meshy thumbnail: ${thumbData.thumbnail_url.slice(0, 80)}...`);
          const thumbImgResp = await fetch(thumbData.thumbnail_url);
          const thumbBuf = Buffer.from(await thumbImgResp.arrayBuffer());
          fs.writeFileSync('/tmp/dragon/meshy_3d_render.png', thumbBuf);
          fs.writeFileSync(`${artifactDir}/meshy_thumbnail.png`, thumbBuf);
          console.log(`[SCENE] Meshy 3D render saved: ${thumbBuf.length} bytes`);
        } else {
          console.warn('[SCENE] No thumbnail_url in task response');
        }
      } catch(e) {
        console.warn(`[SCENE] Thumbnail download failed: ${e.message}`);
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
    } else {
      console.log('[SCENE] Meshy skipped — Venice concept image is the primary visual');
    }

    // Step 6: Update state and broadcast
    currentScene = {
      url: meshyTaskId ? 'https://tiamat.live/dragon/latest_scene.glb' : null,
      prompt,
      mood: state.mood,
      generated_at: new Date().toISOString(),
      task_id: meshyTaskId || null,
    };
    sceneHistory.push({ ...currentScene });

    broadcast({
      type: 'scene_change',
      mood: state.mood,
      prompt,
      concept_image: '/dragon/venice_concept.png',
      venice_text_model: 'llama-3.3-70b',
      venice_image_model: 'fluently-xl',
      artifact_dir: timestamp,
      has_3d: !!meshyTaskId,
    });
    console.log(`[SCENE] New environment live! (Venice: YES, Meshy 3D: ${meshyTaskId ? 'YES' : 'NO'})`);

    return currentScene;
  } catch (e) {
    console.error(`[SCENE] Error:`, e.message);
    // Broadcast failure so stream UI handles gracefully
    broadcast({
      type: 'generation_failed',
      error: e.message,
      mood: state.mood,
      prompt: state.mood, // at least show what we tried
    });
    return null;
  } finally {
    generating = false;
    // Drain queue — if a request arrived during generation, run it now
    if (pendingState) {
      const next = pendingState;
      pendingState = null;
      console.log(`[SCENE] Draining queue — generating next scene (mood=${next.mood})`);
      generateScene(next);
    }
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
