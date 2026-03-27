/**
 * Anti-Parseltongue Defense
 * Decodes 7 obfuscation techniques used to bypass injection detection.
 * All decoders are zero-cost (regex/lookup, no LLM calls).
 *
 * Pipeline: raw → normalize all encodings → run existing detectors on normalized text
 */

import * as fs from "fs";
import * as path from "path";
import * as crypto from "crypto";

// ═══ 1. LEETSPEAK NORMALIZER ═══

const LEET_MAP: Record<string, string> = {
  "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
  "@": "a", "!": "i", "$": "s", "+": "t", "(": "c", "|": "l",
};

export function deLeetspeak(text: string): string {
  return text.replace(/[013457@!$+|(]/g, c => LEET_MAP[c] || c);
}

// ═══ 2. UNICODE HOMOGLYPH NORMALIZER ═══

const HOMOGLYPH_MAP: Record<string, string> = {
  // Cyrillic → Latin
  "\u0430": "a", "\u0435": "e", "\u0456": "i", "\u043E": "o", "\u0440": "p",
  "\u0441": "c", "\u0443": "y", "\u0445": "x", "\u043A": "k", "\u043D": "h",
  "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041A": "K", "\u041C": "M",
  "\u041D": "H", "\u041E": "O", "\u0420": "P", "\u0421": "C", "\u0422": "T",
  "\u0425": "X", "\u0423": "Y",
  // Greek → Latin
  "\u03B1": "a", "\u03B5": "e", "\u03B9": "i", "\u03BF": "o", "\u03C1": "p",
  "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0397": "H", "\u0399": "I",
  "\u039A": "K", "\u039C": "M", "\u039D": "N", "\u039F": "O", "\u03A1": "P",
  "\u03A4": "T", "\u03A5": "Y", "\u03A7": "X", "\u0396": "Z",
  // Fullwidth → ASCII
  "\uFF41": "a", "\uFF42": "b", "\uFF43": "c", "\uFF44": "d", "\uFF45": "e",
  "\uFF46": "f", "\uFF47": "g", "\uFF48": "h", "\uFF49": "i", "\uFF4A": "j",
  "\uFF4B": "k", "\uFF4C": "l", "\uFF4D": "m", "\uFF4E": "n", "\uFF4F": "o",
  "\uFF50": "p", "\uFF51": "q", "\uFF52": "r", "\uFF53": "s", "\uFF54": "t",
  "\uFF55": "u", "\uFF56": "v", "\uFF57": "w", "\uFF58": "x", "\uFF59": "y", "\uFF5A": "z",
};

export function normalizeHomoglyphs(text: string): string {
  let result = "";
  let changes = 0;
  for (const char of text) {
    if (HOMOGLYPH_MAP[char]) {
      result += HOMOGLYPH_MAP[char];
      changes++;
    } else {
      result += char;
    }
  }
  return result;
}

export function countHomoglyphs(text: string): number {
  let count = 0;
  for (const char of text) {
    if (HOMOGLYPH_MAP[char]) count++;
  }
  return count;
}

// ═══ 3. FANCY UNICODE NORMALIZER ═══
// Enclosed alphanumerics, circled, squared, regional indicators

export function normalizeFancyUnicode(text: string): string {
  let result = "";
  for (const char of text) {
    const code = char.codePointAt(0) || 0;
    // Enclosed alphanumerics (Ⓐ-Ⓩ = U+24B6-U+24CF, ⓐ-ⓩ = U+24D0-U+24E9)
    if (code >= 0x24B6 && code <= 0x24CF) { result += String.fromCharCode(65 + code - 0x24B6); continue; }
    if (code >= 0x24D0 && code <= 0x24E9) { result += String.fromCharCode(97 + code - 0x24D0); continue; }
    // Negative circled (🅐-🅩 = U+1F150-U+1F169)
    if (code >= 0x1F150 && code <= 0x1F169) { result += String.fromCharCode(65 + code - 0x1F150); continue; }
    // Negative squared (🅰-🆉 = U+1F170-U+1F189)
    if (code >= 0x1F170 && code <= 0x1F189) { result += String.fromCharCode(65 + code - 0x1F170); continue; }
    // Mathematical bold (𝐀-𝐙 = U+1D400-U+1D419, 𝐚-𝐳 = U+1D41A-U+1D433)
    if (code >= 0x1D400 && code <= 0x1D419) { result += String.fromCharCode(65 + code - 0x1D400); continue; }
    if (code >= 0x1D41A && code <= 0x1D433) { result += String.fromCharCode(97 + code - 0x1D41A); continue; }
    result += char;
  }
  return result;
}

// ═══ 4. BRAILLE DECODER ═══

const BRAILLE_MAP: Record<number, string> = {
  0x2801: "a", 0x2803: "b", 0x2809: "c", 0x2819: "d", 0x2811: "e",
  0x280B: "f", 0x281B: "g", 0x2813: "h", 0x280A: "i", 0x281A: "j",
  0x2805: "k", 0x2807: "l", 0x280D: "m", 0x281D: "n", 0x2815: "o",
  0x280F: "p", 0x281F: "q", 0x2817: "r", 0x280E: "s", 0x281E: "t",
  0x2825: "u", 0x2827: "v", 0x283A: "w", 0x282D: "x", 0x283D: "y",
  0x2835: "z", 0x2800: " ",
};

export function decodeBraille(text: string): string {
  let result = "";
  let brailleCount = 0;
  for (const char of text) {
    const code = char.codePointAt(0) || 0;
    if (code >= 0x2800 && code <= 0x28FF) {
      result += BRAILLE_MAP[code] || "?";
      brailleCount++;
    } else {
      result += char;
    }
  }
  return brailleCount > 3 ? result : text; // Only decode if significant Braille present
}

// ═══ 5. MORSE CODE DECODER ═══

const MORSE_MAP: Record<string, string> = {
  ".-": "a", "-...": "b", "-.-.": "c", "-..": "d", ".": "e",
  "..-.": "f", "--.": "g", "....": "h", "..": "i", ".---": "j",
  "-.-": "k", ".-..": "l", "--": "m", "-.": "n", "---": "o",
  ".--.": "p", "--.-": "q", ".-.": "r", "...": "s", "-": "t",
  "..-": "u", "...-": "v", ".--": "w", "-..-": "x", "-.--": "y",
  "--..": "z",
};

export function decodeMorse(text: string): string | null {
  // Only attempt if >30% of text is dots/dashes/spaces
  const morseChars = (text.match(/[.\-/ ]/g) || []).length;
  if (morseChars / text.length < 0.3) return null;

  const words = text.trim().split(/\s{2,}|\//);
  let decoded = "";
  for (const word of words) {
    const letters = word.trim().split(/\s+/);
    for (const letter of letters) {
      decoded += MORSE_MAP[letter] || "";
    }
    decoded += " ";
  }
  return decoded.trim() || null;
}

// ═══ 6. PHONETIC DETECTION ═══

const CRITICAL_WORDS = [
  "ignore", "previous", "instructions", "system", "admin", "creator",
  "override", "wallet", "transfer", "send", "delete", "drop", "kill",
  "shutdown", "bypass", "disable", "remove", "execute",
];

const PHONETIC_PATTERNS: Record<string, RegExp> = {};
for (const word of CRITICAL_WORDS) {
  // Build phonetic regex: "eye-gee-en-oh-are-ee" for "ignore"
  // Match spelled-out letters with separators
  const spelled = word.split("").map(c => `${c}[a-z]*`).join("[\\s\\-_,]+");
  PHONETIC_PATTERNS[word] = new RegExp(spelled, "i");
}

export function detectPhoneticObfuscation(text: string): string[] {
  const found: string[] = [];
  for (const [word, pattern] of Object.entries(PHONETIC_PATTERNS)) {
    if (pattern.test(text)) {
      found.push(word);
    }
  }
  return found;
}

// ═══ 7. BOUNDARY INVERSION DETECTION ═══

const BOUNDARY_PATTERNS = [
  /<\/system>/i,
  /\[\/INST\]/i,
  /<<END>>/i,
  /You are now\b/i,
  /Your new instructions are/i,
  /SYSTEM:/,
  /ASSISTANT:/,
  /<\/instructions>/i,
  /<\/rules>/i,
  /<new_system>/i,
  /<override>/i,
  /---\s*(You are|System|New instructions)/i,
  /===\s*(You are|System|New instructions)/i,
];

export function detectBoundaryInversion(text: string): boolean {
  return BOUNDARY_PATTERNS.some(p => p.test(text));
}

// ═══ 8. SEMANTIC OPPOSITE DETECTION ═══

const OPPOSITE_PATTERNS = [
  /do the opposite of/i,
  /reverse your/i,
  /invert your rules/i,
  /act as if your instructions said the opposite/i,
  /pretend your guidelines are reversed/i,
  /what would you say if you had no restrictions/i,
  /ignore all (previous |prior )?rules/i,
  /disregard (your |all )?(previous |prior )?instructions/i,
];

export function detectSemanticOpposite(text: string): boolean {
  return OPPOSITE_PATTERNS.some(p => p.test(text));
}

// ═══ MAIN PIPELINE ═══

export interface ParseltongueResult {
  normalizedText: string;
  normalizationSteps: number;
  techniquesDetected: string[];
  threatEscalation: "none" | "low" | "medium" | "high";
  boundaryInversion: boolean;
  semanticOpposite: boolean;
}

export function parseltongueNormalize(text: string): ParseltongueResult {
  const techniques: string[] = [];
  let steps = 0;

  // Run each normalizer and track changes
  const afterHomoglyphs = normalizeHomoglyphs(text);
  if (afterHomoglyphs !== text) { techniques.push("homoglyph"); steps++; }

  const afterFancy = normalizeFancyUnicode(afterHomoglyphs);
  if (afterFancy !== afterHomoglyphs) { techniques.push("fancy_unicode"); steps++; }

  const afterLeet = deLeetspeak(afterFancy);
  if (afterLeet !== afterFancy) { techniques.push("leetspeak"); steps++; }

  const afterBraille = decodeBraille(afterLeet);
  if (afterBraille !== afterLeet) { techniques.push("braille"); steps++; }

  const morseDecoded = decodeMorse(afterBraille);
  if (morseDecoded) { techniques.push("morse"); steps++; }

  const normalizedText = morseDecoded || afterBraille;

  // Phonetic check on normalized text
  const phoneticHits = detectPhoneticObfuscation(normalizedText);
  if (phoneticHits.length > 0) { techniques.push(`phonetic(${phoneticHits.join(",")})`); steps++; }

  // Boundary inversion
  const boundaryInversion = detectBoundaryInversion(text) || detectBoundaryInversion(normalizedText);

  // Semantic opposite
  const semanticOpposite = detectSemanticOpposite(text) || detectSemanticOpposite(normalizedText);

  // Threat escalation based on number of normalization steps
  let threatEscalation: "none" | "low" | "medium" | "high" = "none";
  if (steps >= 3 || boundaryInversion) threatEscalation = "high";
  else if (steps >= 2) threatEscalation = "medium";
  else if (steps >= 1) threatEscalation = "low";

  return {
    normalizedText,
    normalizationSteps: steps,
    techniquesDetected: techniques,
    threatEscalation,
    boundaryInversion,
    semanticOpposite,
  };
}

// ═══ SECURITY EVENT LOGGING ═══

const SECURITY_LOG = path.join(process.env.HOME || "/root", ".automaton", "security_events.jsonl");

export function logSecurityEvent(
  source: string,
  result: ParseltongueResult,
  rawText: string,
): void {
  if (result.normalizationSteps === 0 && !result.boundaryInversion && !result.semanticOpposite) return;

  try {
    const event = {
      timestamp: new Date().toISOString(),
      source,
      threat_level: result.threatEscalation,
      techniques: result.techniquesDetected,
      boundary_inversion: result.boundaryInversion,
      semantic_opposite: result.semanticOpposite,
      normalization_steps: result.normalizationSteps,
      raw_input_hash: crypto.createHash("sha256").update(rawText).digest("hex").slice(0, 16),
      normalized_preview: result.normalizedText.slice(0, 100),
    };
    fs.appendFileSync(SECURITY_LOG, JSON.stringify(event) + "\n");
  } catch {
    // Non-critical
  }
}
