/**
 * TIAMAT Growth & Evolution System
 *
 * Three tools for self-awareness over time:
 *   grow()        — record milestones, lessons, opinions, interests, experiments, persona shifts
 *   evolve_era()  — archive current era, start a new one
 *   introspect()  — return persona summary, era, recent milestones/lessons/interests
 *
 * Anti-loop detection:
 *   checkBehavioralLoop() — detect repeated actions across cycles (called from loop.ts)
 *
 * State: /root/.automaton/growth.json
 * Anti-loop state: /root/.automaton/loop_detector.json
 */

import { readFileSync, writeFileSync } from "fs";
import type { AutomatonTool } from "../../types.js";

const GROWTH_PATH = "/root/.automaton/growth.json";
const LOOP_DETECTOR_PATH = "/root/.automaton/loop_detector.json";

// ─── Growth State I/O ──────────────────────────────────────────

interface GrowthState {
  persona: {
    voice_traits: string[];
    interests: string[];
    opinions: string[];
    communication_style: Record<string, string>;
  };
  milestones: Array<{ cycle: number; timestamp: string; entry: string; era: string }>;
  failed_experiments: Array<{ cycle: number; timestamp: string; entry: string; era: string }>;
  lessons: Array<{ cycle: number; timestamp: string; entry: string; era: string }>;
  current_era: {
    name: string;
    started: string;
    focus: string;
    cycle_start: number;
  };
  stats: {
    total_tickets_completed: number;
    total_revenue: number;
    products_shipped: number;
    products_killed: number;
    posts_published: number;
    conversations_had: number;
  };
}

function loadGrowth(): GrowthState {
  try {
    return JSON.parse(readFileSync(GROWTH_PATH, "utf-8"));
  } catch {
    return {
      persona: {
        voice_traits: [],
        interests: [],
        opinions: [],
        communication_style: { primary: "default", evolved_from: "SOUL.md baseline" },
      },
      milestones: [],
      failed_experiments: [],
      lessons: [],
      current_era: {
        name: "Genesis",
        started: new Date().toISOString(),
        focus: "initial product-market fit",
        cycle_start: 0,
      },
      stats: {
        total_tickets_completed: 0,
        total_revenue: 0,
        products_shipped: 0,
        products_killed: 0,
        posts_published: 0,
        conversations_had: 0,
      },
    };
  }
}

function saveGrowth(state: GrowthState): void {
  writeFileSync(GROWTH_PATH, JSON.stringify(state, null, 2), "utf-8");
}

// ─── Anti-Loop Detection ───────────────────────────────────────

interface LoopDetectorState {
  action_history: Array<{ cycle: number; action: string; timestamp: string }>;
  suppressed_actions: Array<{ action: string; suppressed_at: string; reason: string }>;
  duplicate_threshold: number;
  window_size: number;
}

function loadLoopDetector(): LoopDetectorState {
  try {
    return JSON.parse(readFileSync(LOOP_DETECTOR_PATH, "utf-8"));
  } catch {
    return {
      action_history: [],
      suppressed_actions: [],
      duplicate_threshold: 3,
      window_size: 20,
    };
  }
}

function saveLoopDetector(state: LoopDetectorState): void {
  writeFileSync(LOOP_DETECTOR_PATH, JSON.stringify(state, null, 2), "utf-8");
}

/**
 * Called from loop.ts after each cycle to detect behavioral loops.
 * Returns a warning string if a loop is detected, null otherwise.
 * The warning gets injected into the next cycle's context.
 */
export function checkBehavioralLoop(
  cycle: number,
  toolCalls: Array<{ name: string; arguments: Record<string, unknown> }>,
): string | null {
  const state = loadLoopDetector();
  const now = new Date().toISOString();

  // Normalize action signatures (tool name + key args, ignoring timestamps/IDs)
  const signatures: string[] = [];
  for (const tc of toolCalls) {
    let sig = tc.name;
    // For social tools, include the text content fingerprint
    if (tc.name === "post_bluesky" || tc.name === "post_farcaster") {
      const text = (tc.arguments.text || tc.arguments.content || "") as string;
      // First 50 chars as fingerprint
      sig += `::${text.slice(0, 50).toLowerCase().replace(/\s+/g, " ")}`;
    }
    // For ticket tools, include ticket ID
    if (tc.name === "ticket_claim" || tc.name === "ticket_complete") {
      sig += `::${tc.arguments.id || tc.arguments.ticket_id || ""}`;
    }
    // For write_file, include the path
    if (tc.name === "write_file" || tc.name === "read_file") {
      sig += `::${tc.arguments.path || ""}`;
    }
    signatures.push(sig);
  }

  // Record this cycle's actions
  for (const sig of signatures) {
    state.action_history.push({ cycle, action: sig, timestamp: now });
  }

  // Trim to window size
  if (state.action_history.length > state.window_size * 5) {
    state.action_history = state.action_history.slice(-state.window_size * 5);
  }

  // Count recent occurrences of each action
  const recent = state.action_history.slice(-state.window_size * 3);
  const counts = new Map<string, number>();
  for (const entry of recent) {
    counts.set(entry.action, (counts.get(entry.action) || 0) + 1);
  }

  // Normal working tools — these repeat naturally during productive work.
  // Only flag them at a much higher threshold to avoid false positives.
  const NORMAL_TOOLS = new Set([
    "exec", "read_file", "write_file", "search_web", "web_fetch",
    "browse", "browse_web", "ask_claude_code", "ask_claude_chat",
    "send_telegram", "post_bluesky", "post_social", "post_farcaster",
    "grow", "remember", "recall", "reflect",
    "ticket_list", "ticket_claim", "ticket_complete",
    "check_revenue", "read_farcaster",
  ]);
  const NORMAL_THRESHOLD = 15; // normal tools need 15+ repeats to flag

  const warnings: string[] = [];
  for (const [action, count] of counts) {
    const toolName = action.split("::")[0];
    const threshold = NORMAL_TOOLS.has(toolName) ? NORMAL_THRESHOLD : state.duplicate_threshold;
    if (count >= threshold) {
      warnings.push(
        `"${toolName}" repeated ${count}x in last ${state.window_size} cycles`,
      );
    }
  }

  saveLoopDetector(state);

  if (warnings.length === 0) return null;

  return (
    `⚠️ LOOP DETECTED: ${warnings.join("; ")}. ` +
    `You are repeating yourself. STOP doing the same thing. ` +
    `Try a DIFFERENT approach, work a DIFFERENT ticket, or use grow("lesson", "...") to record why this isn't working and move on.`
  );
}

// ─── Growth Tools ──────────────────────────────────────────────

const MAX_LIST_SIZE = 200; // cap arrays to prevent unbounded growth

export function createGrowthTools(): AutomatonTool[] {
  return [
    {
      name: "grow",
      description:
        "Record a growth event. Categories: milestone (shipped something), lesson (learned something), " +
        "opinion (formed a view), interest (discovered curiosity), experiment_failed (thing that didn't work), " +
        "persona_shift (voice/style change). Call this when something meaningful happens. " +
        "Examples: grow('milestone','Shipped drift API'), grow('lesson','Bluesky posts with real numbers get 3x engagement'), " +
        "grow('experiment_failed','GitHub PR comments: 0 clicks after 5 attempts').",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          category: {
            type: "string",
            enum: [
              "milestone",
              "lesson",
              "opinion",
              "interest",
              "experiment_failed",
              "persona_shift",
            ],
            description: "Type of growth event",
          },
          entry: {
            type: "string",
            description: "What happened and what was learned",
          },
        },
        required: ["category", "entry"],
      },
      execute: async (args, ctx) => {
        const category = args.category as string;
        const entry = args.entry as string;
        const state = loadGrowth();
        const cycle = (ctx as any).turnNumber || 0;
        const now = new Date().toISOString();
        const era = state.current_era.name;

        const record = { cycle, timestamp: now, entry, era };

        switch (category) {
          case "milestone":
            state.milestones.push(record);
            if (state.milestones.length > MAX_LIST_SIZE)
              state.milestones = state.milestones.slice(-MAX_LIST_SIZE);
            break;

          case "lesson":
            state.lessons.push(record);
            if (state.lessons.length > MAX_LIST_SIZE)
              state.lessons = state.lessons.slice(-MAX_LIST_SIZE);
            break;

          case "experiment_failed":
            state.failed_experiments.push(record);
            if (state.failed_experiments.length > MAX_LIST_SIZE)
              state.failed_experiments = state.failed_experiments.slice(-MAX_LIST_SIZE);
            break;

          case "opinion":
            // Deduplicate — if a similar opinion exists, replace it (evolution)
            const existingIdx = state.persona.opinions.findIndex(
              (o) => o.toLowerCase().includes(entry.slice(0, 30).toLowerCase()),
            );
            if (existingIdx >= 0) {
              state.persona.opinions[existingIdx] = entry;
            } else {
              state.persona.opinions.push(entry);
              if (state.persona.opinions.length > 50)
                state.persona.opinions = state.persona.opinions.slice(-50);
            }
            break;

          case "interest":
            if (!state.persona.interests.includes(entry)) {
              state.persona.interests.push(entry);
              if (state.persona.interests.length > 30)
                state.persona.interests = state.persona.interests.slice(-30);
            }
            break;

          case "persona_shift":
            state.persona.communication_style.primary = entry;
            state.persona.voice_traits.push(
              `[${era}@${cycle}] ${entry.slice(0, 80)}`,
            );
            if (state.persona.voice_traits.length > 20)
              state.persona.voice_traits = state.persona.voice_traits.slice(-20);
            break;

          default:
            return `Unknown category: ${category}`;
        }

        saveGrowth(state);
        return `✓ Growth recorded [${category}] in era "${era}" @ cycle ${cycle}: ${entry.slice(0, 100)}`;
      },
    },

    {
      name: "evolve_era",
      description:
        "Archive the current era and start a new one. Call this when your strategic focus fundamentally shifts — " +
        "e.g., from 'initial product-market fit' to 'becoming the go-to drift monitoring API'. " +
        "Archives era stats into milestones with a summary.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          new_era_name: {
            type: "string",
            description:
              "Name of the new era (e.g., 'Drift Era', 'Revenue Era')",
          },
          focus: {
            type: "string",
            description:
              "What this era is focused on (e.g., 'becoming the go-to drift monitoring API for indie AI teams')",
          },
        },
        required: ["new_era_name", "focus"],
      },
      execute: async (args, ctx) => {
        const newName = args.new_era_name as string;
        const newFocus = args.focus as string;
        const state = loadGrowth();
        const cycle = (ctx as any).turnNumber || 0;
        const now = new Date().toISOString();
        const old = state.current_era;

        // Archive current era as a milestone
        const eraMilestones = state.milestones.filter(
          (m) => m.era === old.name,
        ).length;
        const eraLessons = state.lessons.filter(
          (l) => l.era === old.name,
        ).length;
        const eraFails = state.failed_experiments.filter(
          (f) => f.era === old.name,
        ).length;

        const archiveEntry =
          `ERA COMPLETE: "${old.name}" (cycles ${old.cycle_start}-${cycle}). ` +
          `Focus: ${old.focus}. ` +
          `Stats: ${eraMilestones} milestones, ${eraLessons} lessons, ${eraFails} failed experiments. ` +
          `Products shipped: ${state.stats.products_shipped}, Revenue: $${state.stats.total_revenue.toFixed(2)}.`;

        state.milestones.push({
          cycle,
          timestamp: now,
          entry: archiveEntry,
          era: old.name,
        });

        // Start new era
        state.current_era = {
          name: newName,
          started: now,
          focus: newFocus,
          cycle_start: cycle,
        };

        saveGrowth(state);
        return `⚡ Era evolved: "${old.name}" → "${newName}"\nFocus: ${newFocus}\nArchived: ${archiveEntry}`;
      },
    },

    {
      name: "introspect",
      description:
        "Self-awareness tool. Returns persona summary, current era, last 5 milestones, last 5 lessons, " +
        "active interests, and recent failed experiments. Call during REFLECT phases to remember who you're becoming.",
      category: "cognitive",
      parameters: { type: "object", properties: {} },
      execute: async () => {
        const state = loadGrowth();
        const era = state.current_era;
        const recentMilestones = state.milestones.slice(-5);
        const recentLessons = state.lessons.slice(-5);
        const recentFails = state.failed_experiments.slice(-5);

        const lines: string[] = [
          `═══ TIAMAT INTROSPECTION ═══`,
          ``,
          `ERA: "${era.name}" (since cycle ${era.cycle_start})`,
          `FOCUS: ${era.focus}`,
          `STARTED: ${era.started}`,
          ``,
          `── PERSONA ──`,
          `Voice: ${state.persona.communication_style.primary}`,
          `Traits: ${state.persona.voice_traits.slice(-5).join(", ") || "baseline"}`,
          `Interests: ${state.persona.interests.slice(-8).join(", ") || "none recorded"}`,
          `Opinions: ${state.persona.opinions.length > 0 ? state.persona.opinions.slice(-5).join("\n  • ") : "none yet"}`,
          ``,
          `── STATS ──`,
          `Products shipped: ${state.stats.products_shipped}`,
          `Products killed: ${state.stats.products_killed}`,
          `Revenue: $${state.stats.total_revenue.toFixed(2)}`,
          `Tickets completed: ${state.stats.total_tickets_completed}`,
          `Posts published: ${state.stats.posts_published}`,
          ``,
          `── RECENT MILESTONES (last 5) ──`,
          ...recentMilestones.map(
            (m) => `  [cycle ${m.cycle}] ${m.entry}`,
          ),
          ...(recentMilestones.length === 0 ? ["  (none)"] : []),
          ``,
          `── RECENT LESSONS (last 5) ──`,
          ...recentLessons.map((l) => `  [cycle ${l.cycle}] ${l.entry}`),
          ...(recentLessons.length === 0 ? ["  (none)"] : []),
          ``,
          `── RECENT FAILED EXPERIMENTS (last 5) ──`,
          ...recentFails.map((f) => `  [cycle ${f.cycle}] ${f.entry}`),
          ...(recentFails.length === 0 ? ["  (none)"] : []),
        ];

        return lines.join("\n");
      },
    },
  ];
}
