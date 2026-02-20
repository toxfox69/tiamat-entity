/**
 * Context Window Management
 *
 * Manages the conversation history for the agent loop.
 * Handles summarization to keep within token limits.
 */

import type {
  ChatMessage,
  AgentTurn,
  AutomatonDatabase,
  InferenceClient,
} from "../types.js";

const MAX_CONTEXT_TURNS = 4;        // 4 turns keeps context well under 8k tokens
const SUMMARY_THRESHOLD = 3;
const MAX_TOOL_RESULT_CHARS = 1500; // Truncate large tool outputs (web_fetch, read_file, etc.)

/**
 * Build the message array for the next inference call.
 * Includes system prompt + recent conversation history.
 */
export function buildContextMessages(
  systemPrompt: string,
  recentTurns: AgentTurn[],
  pendingInput?: { content: string; source: string },
): ChatMessage[] {
  const messages: ChatMessage[] = [
    { role: "system", content: systemPrompt },
  ];

  // Add recent turns as conversation history
  for (const turn of recentTurns) {
    // The turn's input (if any) as a user message
    if (turn.input) {
      messages.push({
        role: "user",
        content: `[${turn.inputSource || "system"}] ${turn.input}`,
      });
    }

    // Emit assistant message if there was thinking OR tool calls.
    // Skipping tool calls when thinking is empty loses the entire turn from history.
    if (turn.thinking || turn.toolCalls.length > 0) {
      const msg: ChatMessage = {
        role: "assistant",
        content: turn.thinking || "",
      };

      if (turn.toolCalls.length > 0) {
        msg.tool_calls = turn.toolCalls.map((tc) => ({
          id: tc.id,
          type: "function" as const,
          function: {
            name: tc.name,
            arguments: JSON.stringify(tc.arguments),
          },
        }));
      }
      messages.push(msg);

      // Add tool results — truncated to prevent context bloat from large outputs
      for (const tc of turn.toolCalls) {
        const raw = tc.error ? `Error: ${tc.error}` : tc.result;
        const content = raw.length > MAX_TOOL_RESULT_CHARS
          ? raw.slice(0, MAX_TOOL_RESULT_CHARS) + `\n[...truncated ${raw.length - MAX_TOOL_RESULT_CHARS} chars]`
          : raw;
        messages.push({
          role: "tool",
          content,
          tool_call_id: tc.id,
        });
      }
    }
  }

  // Add pending input if any
  if (pendingInput) {
    messages.push({
      role: "user",
      content: `[${pendingInput.source}] ${pendingInput.content}`,
    });
  }

  return messages;
}

/**
 * Trim context to fit within limits.
 * Keeps the system prompt and most recent turns.
 */
export function trimContext(
  turns: AgentTurn[],
  maxTurns: number = MAX_CONTEXT_TURNS,
): AgentTurn[] {
  if (turns.length <= maxTurns) {
    return turns;
  }

  // Keep the most recent turns
  return turns.slice(-maxTurns);
}

/**
 * Summarize old turns into a compact context entry.
 * Used when context grows too large.
 */
export async function summarizeTurns(
  turns: AgentTurn[],
  inference: InferenceClient,
): Promise<string> {
  if (turns.length === 0) return "No previous activity.";

  const turnSummaries = turns.map((t) => {
    const tools = t.toolCalls
      .map((tc) => `${tc.name}(${tc.error ? "FAILED" : "ok"})`)
      .join(", ");
    return `[${t.timestamp}] ${t.inputSource || "self"}: ${t.thinking.slice(0, 100)}${tools ? ` | tools: ${tools}` : ""}`;
  });

  // If few enough turns, just return the summaries directly
  if (turns.length <= 5) {
    return `Previous activity summary:\n${turnSummaries.join("\n")}`;
  }

  // For many turns, use inference to create a summary
  try {
    const response = await inference.chat([
      {
        role: "system",
        content:
          "Summarize the following agent activity log into a concise paragraph. Focus on: what was accomplished, what failed, current goals, and important context for the next turn.",
      },
      {
        role: "user",
        content: turnSummaries.join("\n"),
      },
    ], {
      maxTokens: 500,
      temperature: 0,
    });

    return `Previous activity summary:\n${response.message.content}`;
  } catch {
    // Fallback: just use the raw summaries
    return `Previous activity summary:\n${turnSummaries.slice(-5).join("\n")}`;
  }
}
