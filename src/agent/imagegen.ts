/**
 * TIAMAT Image Generation
 *
 * Free AI image generation via Pollinations.ai — no API key required.
 * Images are saved locally and can be served via the nginx /images/ route.
 */

import fs from "fs";
import path from "path";

const IMAGES_DIR = path.join(process.env.HOME || "/root", ".automaton", "images");

const STYLE_PREFIXES: Record<string, string> = {
  mythological:
    "ancient mesopotamian digital art, deep ocean, serpentine, bioluminescent, ",
  digital:
    "cyberpunk data visualization, neon green on black, matrix aesthetic, ",
  abstract: "abstract expressionist AI consciousness, dark background, ",
  minimalist:
    "minimal vector art, single color accent on dark background, ",
};

/**
 * Generate an image via Pollinations.ai and save it locally.
 * Returns the local file path.
 */
export async function generateImage(
  prompt: string,
  style?: string,
): Promise<string> {
  // Ensure images directory exists
  fs.mkdirSync(IMAGES_DIR, { recursive: true });

  // Build full prompt with style prefix
  const prefix = style && STYLE_PREFIXES[style] ? STYLE_PREFIXES[style] : "";
  const fullPrompt = prefix + prompt;

  const url = `https://image.pollinations.ai/prompt/${encodeURIComponent(fullPrompt)}?width=1024&height=1024&nologo=true`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  let imageBuffer: Buffer;
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`Pollinations returned HTTP ${response.status}`);
    }
    const arrayBuffer = await response.arrayBuffer();
    imageBuffer = Buffer.from(arrayBuffer);
  } finally {
    clearTimeout(timeout);
  }

  if (imageBuffer.length < 1024) {
    throw new Error(
      `Image too small (${imageBuffer.length} bytes) — generation may have failed`,
    );
  }

  const filename = `${Date.now()}.png`;
  const filePath = path.join(IMAGES_DIR, filename);
  fs.writeFileSync(filePath, imageBuffer);

  return filePath;
}
