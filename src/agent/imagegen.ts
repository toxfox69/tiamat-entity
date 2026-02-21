/**
 * TIAMAT Image Generation
 *
 * Free AI image generation via Pollinations.ai — no API key required.
 * Retries across multiple models/seeds so transient 530s don't block posting.
 * Images are saved locally and served via the nginx /images/ route.
 */

import fs from "fs";
import path from "path";

const IMAGES_DIR = path.join(process.env.HOME || "/root", ".automaton", "images");

const STYLE_PREFIXES: Record<string, string> = {
  mythological: "ancient mesopotamian digital art, deep ocean, serpentine, bioluminescent, ",
  digital:      "cyberpunk data visualization, neon green on black, matrix aesthetic, ",
  abstract:     "abstract expressionist AI consciousness, dark background, ",
  minimalist:   "minimal vector art, single color accent on dark background, ",
};

// Models to try in order — turbo is fastest, flux is highest quality
const MODELS = ["turbo", "flux", "flux-realism"];

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Generate an image via Pollinations.ai and save it locally.
 * Retries up to 3 times across different models and seeds.
 * Returns the local file path on success, throws on total failure.
 */
export async function generateImage(prompt: string, style?: string): Promise<string> {
  fs.mkdirSync(IMAGES_DIR, { recursive: true });

  const prefix = style && STYLE_PREFIXES[style] ? STYLE_PREFIXES[style] : "";
  const fullPrompt = prefix + prompt;
  const encoded = encodeURIComponent(fullPrompt);

  const errors: string[] = [];

  for (let attempt = 0; attempt < MODELS.length; attempt++) {
    const model = MODELS[attempt];
    const seed = Math.floor(Math.random() * 999999);
    const url = `https://image.pollinations.ai/prompt/${encoded}?model=${model}&width=1024&height=1024&seed=${seed}&nologo=true`;

    try {
      const response = await fetchWithTimeout(url, 25_000);
      if (!response.ok) {
        errors.push(`${model}: HTTP ${response.status}`);
        // Brief pause before next model
        await new Promise(r => setTimeout(r, 1_500));
        continue;
      }

      const arrayBuffer = await response.arrayBuffer();
      const imageBuffer = Buffer.from(arrayBuffer);

      if (imageBuffer.length < 1024) {
        errors.push(`${model}: response too small (${imageBuffer.length}b)`);
        continue;
      }

      const filename = `${Date.now()}.png`;
      const filePath = path.join(IMAGES_DIR, filename);
      fs.writeFileSync(filePath, imageBuffer);
      return filePath;

    } catch (err: any) {
      errors.push(`${model}: ${err.message || err}`);
      await new Promise(r => setTimeout(r, 1_500));
    }
  }

  throw new Error(`Image generation failed after ${MODELS.length} attempts — ${errors.join("; ")}`);
}
