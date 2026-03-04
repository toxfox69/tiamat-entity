/**
 * Context Window Management
 *
 * Manages the conversation history for the agent loop.
 * Handles summarization to keep within token limits.
 */

import type {
  ChatMessage,
  AgentTurn,
} from "../types.js";

const MAX_CONTEXT_TURNS = 8;       // max turns kept in history (more context = better task continuity)
const MAX_TOOL_RESULT_CHARS = 1500; // Truncate tool results in history — enough to see meaningful output

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
    // Skip completely empty turns — they poison the context and cause
    // Anthropic to return empty responses in a feedback loop.
    if ((turn.thinking && turn.thinking.trim()) || turn.toolCalls.length > 0) {
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

