"""
gateway_adapter.py
==================
Protocol adapter between the MCP Gateway protocol and the LLM Gateway protocol
(OpenAI-compatible function-calling format).

Responsibilities
----------------
1. **MCPToLLMAdapter** — converts MCP tool descriptors into OpenAI
   ``tools`` array entries so the LLM can call them.

2. **LLMToMCPAdapter** — converts OpenAI ``tool_calls`` in an assistant message
   into ``tools/call`` JSON-RPC requests for the MCP server.

3. **ToolResultAdapter** — converts MCP tool results into the correct OpenAI
   ``tool`` role message, and detects when the result contains MCP App HTML so
   the caller can build an ``MCPAppMessage``.

4. **MCPAppsGatewayAdapter** (high-level) — orchestrates all three adapters and
   the registry, providing a single ``handle_tool_calls`` coroutine that:
   - Calls every LLM-requested tool on the MCP server.
   - Returns ``(llm_messages, mcp_app_messages)`` so the caller can append them
     to the conversation and render any iframes.

Reference
---------
MCP spec: https://spec.modelcontextprotocol.io/specification/2024-11-05/server/tools/
LLM Gateway (OpenAI): https://platform.openai.com/docs/api-reference/chat/object
MCP Apps: https://apps.extensions.modelcontextprotocol.io
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from mcp_apps_registry import MCPAppTool, MCPAppsRegistry, ToolCallResult
from chat_ui_component import (
    MCPAppMessage,
    build_mcp_app_message,
    extract_mcp_app_html,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: OpenAI-format tool descriptor (one entry in the ``tools`` array)
LLMToolDef = dict[str, Any]

#: OpenAI-format tool_call object inside an assistant message
LLMToolCall = dict[str, Any]

#: OpenAI-format message dict
LLMMessage = dict[str, Any]


# ---------------------------------------------------------------------------
# Name sanitisation
# ---------------------------------------------------------------------------

_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitise_tool_name(name: str) -> str:
    """
    Map an MCP tool name to a valid OpenAI function name.

    OpenAI requires names to match ``^[a-zA-Z0-9_-]+$``.  We replace any
    other characters with ``_`` and truncate to 64 characters.
    """
    sanitised = _INVALID_CHARS.sub("_", name)
    return sanitised[:64]


def _restore_tool_name(sanitised: str, known_tools: dict[str, str]) -> str:
    """
    Reverse ``_sanitise_tool_name`` using the ``known_tools`` lookup built
    by ``MCPToLLMAdapter.build_tools_array``.

    Falls back to the sanitised name if not found.
    """
    return known_tools.get(sanitised, sanitised)


# ---------------------------------------------------------------------------
# 1. MCP → LLM adapter
# ---------------------------------------------------------------------------


class MCPToLLMAdapter:
    """
    Converts MCP tool descriptors to the OpenAI ``tools`` array format.

    Also maintains a reverse-lookup map so tool names can be restored when
    the LLM returns a ``tool_calls`` message.
    """

    def convert_tool(self, tool: MCPAppTool) -> tuple[LLMToolDef, str]:
        """
        Convert a single ``MCPAppTool`` to an OpenAI function definition.

        Returns
        -------
        tuple[LLMToolDef, str]
            ``(tool_def, sanitised_name)`` — the definition and the name key
            used in the reverse-lookup map.
        """
        sanitised = _sanitise_tool_name(tool.name)
        description = tool.description
        if tool.ui.resource_uri:
            description = (
                f"{description}\n\n"
                "⚡ This tool renders an interactive UI in the chat. "
                "After calling it, an embedded application will appear."
            ).strip()

        tool_def: LLMToolDef = {
            "type": "function",
            "function": {
                "name": sanitised,
                "description": description,
                "parameters": _normalise_json_schema(tool.input_schema),
            },
        }
        return tool_def, sanitised

    def build_tools_array(
        self, tools: list[MCPAppTool]
    ) -> tuple[list[LLMToolDef], dict[str, str]]:
        """
        Convert a list of ``MCPAppTool`` objects to the OpenAI ``tools`` array.

        Parameters
        ----------
        tools:
            Tools returned by ``MCPAppsRegistry.discover_apps()``, or any
            mix of plain MCP tools.

        Returns
        -------
        tuple[list[LLMToolDef], dict[str, str]]
            ``(tools_array, name_map)`` where *name_map* maps each sanitised
            name back to the original MCP tool name.
        """
        tools_array: list[LLMToolDef] = []
        name_map: dict[str, str] = {}

        for tool in tools:
            tool_def, sanitised = self.convert_tool(tool)
            tools_array.append(tool_def)
            name_map[sanitised] = tool.name

        logger.debug(
            "Built tools array with %d entries (name_map=%s)",
            len(tools_array),
            name_map,
        )
        return tools_array, name_map


def _normalise_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure the input schema is a valid JSON Schema object accepted by OpenAI.

    OpenAI requires ``{"type": "object", "properties": {...}}``.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    if schema.get("type") != "object":
        return {"type": "object", "properties": schema}
    return schema


# ---------------------------------------------------------------------------
# 2. LLM → MCP adapter
# ---------------------------------------------------------------------------


@dataclass
class ParsedToolCall:
    """A tool call extracted from an OpenAI assistant message."""

    call_id: str
    """OpenAI ``tool_calls[].id``."""

    mcp_name: str
    """Original MCP tool name (after reverse-lookup)."""

    sanitised_name: str
    """The name as seen by the LLM."""

    arguments: dict[str, Any]
    """Parsed arguments dict (from the JSON string)."""


class LLMToMCPAdapter:
    """
    Parses OpenAI ``tool_calls`` from an assistant message and produces
    MCP ``tools/call`` payloads.
    """

    def parse_tool_calls(
        self,
        assistant_message: LLMMessage,
        name_map: dict[str, str],
    ) -> list[ParsedToolCall]:
        """
        Extract and parse all tool calls from an OpenAI assistant message.

        Parameters
        ----------
        assistant_message:
            An OpenAI chat completion message dict with ``role == "assistant"``
            and a ``tool_calls`` list.
        name_map:
            Reverse-lookup from sanitised name → original MCP tool name, as
            returned by ``MCPToLLMAdapter.build_tools_array``.

        Returns
        -------
        list[ParsedToolCall]
            One entry per tool call. Empty list if the message has no tool
            calls.
        """
        raw_calls: list[dict[str, Any]] = assistant_message.get("tool_calls") or []
        result: list[ParsedToolCall] = []

        for tc in raw_calls:
            call_id = tc.get("id", "")
            fn = tc.get("function") or {}
            sanitised_name: str = fn.get("name", "")
            mcp_name = _restore_tool_name(sanitised_name, name_map)

            raw_args: str = fn.get("arguments", "{}")
            try:
                arguments: dict[str, Any] = json.loads(raw_args)
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse arguments JSON for tool %r: %r",
                    sanitised_name,
                    raw_args,
                )
                arguments = {}

            result.append(
                ParsedToolCall(
                    call_id=call_id,
                    mcp_name=mcp_name,
                    sanitised_name=sanitised_name,
                    arguments=arguments,
                )
            )

        return result

    def make_rpc_body(self, call: ParsedToolCall, req_id: int = 1) -> dict[str, Any]:
        """Build the MCP JSON-RPC ``tools/call`` request body for *call*."""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": call.mcp_name, "arguments": call.arguments},
        }


# ---------------------------------------------------------------------------
# 3. Tool result adapter
# ---------------------------------------------------------------------------


@dataclass
class AdaptedToolResult:
    """
    The result of adapting a single MCP tool call result.

    Contains both the LLM-facing message (for the conversation history) and,
    if the result was an MCP App, the ``MCPAppMessage`` for the chat renderer.
    """

    llm_message: LLMMessage
    """The ``{"role": "tool", ...}`` message to add to the LLM history."""

    app_message: Optional[MCPAppMessage] = None
    """
    Set when the tool result contained MCP App HTML.
    The chat renderer should display this as an interactive iframe instead of
    (or in addition to) the raw tool content.
    """

    tool_name: str = ""
    mcp_result: Optional[ToolCallResult] = None


class ToolResultAdapter:
    """
    Converts MCP ``ToolCallResult`` objects into LLM-compatible message dicts
    and optionally into ``MCPAppMessage`` objects for iframe rendering.
    """

    def adapt(
        self,
        call: ParsedToolCall,
        result: ToolCallResult,
        agent_id: str,
        tool_meta: Optional[MCPAppTool] = None,
    ) -> AdaptedToolResult:
        """
        Adapt a single tool result.

        Parameters
        ----------
        call:
            The parsed tool call that produced *result*.
        result:
            Raw MCP tool result from ``MCPAppsRegistry.call_tool()``.
        agent_id:
            Archestra agent ID — forwarded to ``MCPAppMessage`` so the iframe
            can proxy further tool calls.
        tool_meta:
            Optional ``MCPAppTool`` providing UI metadata (CSP, permissions).
            If not provided, defaults are used.

        Returns
        -------
        AdaptedToolResult
        """
        mcp_result_envelope = result.as_mcp_result()

        # Build the LLM message (text summary of the result).
        llm_content = self._result_to_llm_content(result)
        llm_message: LLMMessage = {
            "role": "tool",
            "tool_call_id": call.call_id,
            "content": llm_content,
        }

        # Check whether the result contains MCP App HTML.
        app_message: Optional[MCPAppMessage] = None
        html = extract_mcp_app_html(mcp_result_envelope)
        if html:
            csp = tool_meta.ui.csp if tool_meta else {}
            extra_sandbox = list(tool_meta.ui.permissions) if tool_meta else []
            app_message = build_mcp_app_message(
                tool_name=call.mcp_name,
                tool_result=mcp_result_envelope,
                agent_id=agent_id,
                html_content=html,
                tool_call_id=call.call_id,
                csp_overrides=csp,
                extra_sandbox=extra_sandbox,
            )
            logger.info(
                "MCP App HTML detected for tool %r (%d bytes)",
                call.mcp_name,
                len(html),
            )

        return AdaptedToolResult(
            llm_message=llm_message,
            app_message=app_message,
            tool_name=call.mcp_name,
            mcp_result=result,
        )

    def _result_to_llm_content(self, result: ToolCallResult) -> str:
        """
        Produce a compact text summary of an MCP tool result for the LLM.

        Resource blocks (HTML) are replaced with a placeholder so we don't
        flood the context window with kilobytes of HTML.
        """
        if result.is_error:
            text = result.text()
            return f"[Tool error] {text or 'Unknown error'}"

        parts: list[str] = []
        for block in result.content:
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "resource":
                resource = block.get("resource", {})
                mime = resource.get("mimeType", "unknown")
                uri = resource.get("uri", "")
                if "html" in mime:
                    parts.append(f"[Interactive UI rendered: {uri}]")
                else:
                    parts.append(f"[Resource: {mime} — {uri}]")
            elif btype == "image":
                parts.append("[Image returned]")
            else:
                parts.append(json.dumps(block))

        return "\n".join(parts) if parts else "[No content]"


# ---------------------------------------------------------------------------
# 4. High-level orchestrator
# ---------------------------------------------------------------------------


@dataclass
class HandleToolCallsResult:
    """Return value from ``MCPAppsGatewayAdapter.handle_tool_calls``."""

    llm_messages: list[LLMMessage]
    """
    Tool-role messages to append to the LLM conversation.
    One entry per tool call, regardless of whether it was an MCP App.
    """

    app_messages: list[MCPAppMessage]
    """
    MCP App iframe messages produced by tool calls that returned HTML.
    Typically rendered by the ``McpAppFrame`` React component.
    """

    errors: list[dict[str, Any]]
    """
    Per-tool error records (if any calls failed).  Each entry has keys
    ``tool_name``, ``call_id``, and ``error``.
    """

    def has_apps(self) -> bool:
        return bool(self.app_messages)

    def has_errors(self) -> bool:
        return bool(self.errors)


class MCPAppsGatewayAdapter:
    """
    High-level adapter that orchestrates tool discovery and execution.

    Combines ``MCPToLLMAdapter``, ``LLMToMCPAdapter``, ``ToolResultAdapter``,
    and ``MCPAppsRegistry`` into a single cohesive interface.

    Typical usage::

        async with MCPAppsRegistry() as registry:
            adapter = MCPAppsGatewayAdapter(registry, server_url="https://…/mcp")

            # 1. Get tool definitions for the LLM
            tools_array, name_map = await adapter.get_llm_tools()

            # 2. Call the LLM with those tools
            completion = await llm_client.chat(messages=[…], tools=tools_array)

            # 3. Handle any tool calls the LLM made
            result = await adapter.handle_tool_calls(
                assistant_message=completion.choices[0].message,
                name_map=name_map,
                agent_id="agent-abc",
            )

            # 4. Append LLM messages and render app messages
            messages.extend(result.llm_messages)
            for app_msg in result.app_messages:
                chat_ui.render_iframe(app_msg)
    """

    def __init__(
        self,
        registry: MCPAppsRegistry,
        server_url: str,
        include_non_app_tools: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        registry:
            Initialised ``MCPAppsRegistry`` (must be used inside ``async with``).
        server_url:
            MCP Gateway endpoint to discover and call tools on.
        include_non_app_tools:
            When ``True`` (default), plain MCP tools (without ``_meta.ui``)
            returned by the server are also included in the LLM tools array.
            Set to ``False`` to expose only MCP App tools.
        """
        self.registry = registry
        self.server_url = server_url
        self.include_non_app_tools = include_non_app_tools

        self._mcp_to_llm = MCPToLLMAdapter()
        self._llm_to_mcp = LLMToMCPAdapter()
        self._result_adapter = ToolResultAdapter()

        # Cache: mcp_tool_name → MCPAppTool (populated by get_llm_tools)
        self._tool_index: dict[str, MCPAppTool] = {}

    async def get_llm_tools(
        self, force_refresh: bool = False
    ) -> tuple[list[LLMToolDef], dict[str, str]]:
        """
        Discover tools and return the OpenAI-format tools array.

        Parameters
        ----------
        force_refresh:
            Re-fetch from the server even if cached.

        Returns
        -------
        tuple[list[LLMToolDef], dict[str, str]]
            ``(tools_array, name_map)`` — pass both to ``handle_tool_calls``.
        """
        app_tools = await self.registry.discover_apps(
            self.server_url, force_refresh=force_refresh
        )

        # Rebuild the name index
        self._tool_index = {t.name: t for t in app_tools}

        tools_for_llm: list[MCPAppTool] = app_tools

        if self.include_non_app_tools:
            # In a real implementation you would also call tools/list on the
            # server and convert plain tools.  For now we expose only app tools
            # (which are a superset of what we've fetched).
            pass

        return self._mcp_to_llm.build_tools_array(tools_for_llm)

    async def handle_tool_calls(
        self,
        assistant_message: LLMMessage,
        name_map: dict[str, str],
        agent_id: str,
    ) -> HandleToolCallsResult:
        """
        Execute every tool call in *assistant_message* and return results.

        Parameters
        ----------
        assistant_message:
            An OpenAI ``role == "assistant"`` message dict that may contain
            ``tool_calls``.
        name_map:
            Reverse-lookup from ``get_llm_tools()``.
        agent_id:
            Archestra agent ID forwarded to iframe messages.

        Returns
        -------
        HandleToolCallsResult
        """
        parsed_calls = self._llm_to_mcp.parse_tool_calls(assistant_message, name_map)
        if not parsed_calls:
            return HandleToolCallsResult(
                llm_messages=[], app_messages=[], errors=[]
            )

        llm_messages: list[LLMMessage] = []
        app_messages: list[MCPAppMessage] = []
        errors: list[dict[str, Any]] = []

        for call in parsed_calls:
            try:
                mcp_result = await self.registry.call_tool(
                    self.server_url, call.mcp_name, call.arguments
                )
            except Exception as exc:
                logger.error(
                    "Error calling tool %r (call_id=%r): %s",
                    call.mcp_name,
                    call.call_id,
                    exc,
                )
                errors.append(
                    {
                        "tool_name": call.mcp_name,
                        "call_id": call.call_id,
                        "error": str(exc),
                    }
                )
                # Produce an error tool message so the LLM knows the call failed.
                llm_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "content": f"[Tool call failed] {exc}",
                    }
                )
                continue

            tool_meta = self._tool_index.get(call.mcp_name)
            adapted = self._result_adapter.adapt(
                call=call,
                result=mcp_result,
                agent_id=agent_id,
                tool_meta=tool_meta,
            )
            llm_messages.append(adapted.llm_message)
            if adapted.app_message is not None:
                app_messages.append(adapted.app_message)

        return HandleToolCallsResult(
            llm_messages=llm_messages,
            app_messages=app_messages,
            errors=errors,
        )

    async def preload_ui_resource(self, tool_name: str) -> Optional[str]:
        """
        Eagerly fetch and cache the UI HTML for *tool_name*.

        Call this when you know the LLM is likely to invoke the tool soon
        (e.g., after intent classification) to reduce perceived latency.

        Returns the cached HTML string, or ``None`` if the tool doesn't
        exist or has no UI.
        """
        tool = self._tool_index.get(tool_name)
        if tool is None or not tool.ui.resource_uri:
            return None
        try:
            resource = await self.registry.fetch_ui_resource(
                self.server_url, tool.ui.resource_uri
            )
            return resource.html
        except Exception as exc:
            logger.warning("Failed to preload UI for %r: %s", tool_name, exc)
            return None


# ---------------------------------------------------------------------------
# Standalone helper: convert a raw MCP tools/list response
# ---------------------------------------------------------------------------


def mcp_tools_list_to_llm_tools(
    tools_list_result: dict[str, Any],
    server_url: str = "",
) -> tuple[list[LLMToolDef], dict[str, str], list[MCPAppTool]]:
    """
    Convert a raw ``tools/list`` JSON-RPC result dict to LLM tool definitions.

    Useful when you already have the raw MCP response and don't want to use
    the registry.

    Parameters
    ----------
    tools_list_result:
        The ``result`` field from a ``tools/list`` response:
        ``{"tools": [...]}``
    server_url:
        Optional server URL stored on returned ``MCPAppTool`` objects.

    Returns
    -------
    tuple[list[LLMToolDef], dict[str, str], list[MCPAppTool]]
        ``(tools_array, name_map, app_tools)``
    """
    raw_tools: list[dict[str, Any]] = tools_list_result.get("tools", [])
    app_tools: list[MCPAppTool] = []

    for t in raw_tools:
        from mcp_apps_registry import MCPAppUIConfig  # avoid circular at module level

        ui_cfg = MCPAppUIConfig.from_meta(t.get("_meta") or {})
        if ui_cfg is None:
            # Create a stub UI config so we can still convert the tool
            ui_cfg = MCPAppUIConfig(resource_uri="")
        app_tools.append(
            MCPAppTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema") or {"type": "object", "properties": {}},
                ui=ui_cfg,
                server_url=server_url,
                raw=t,
            )
        )

    adapter = MCPToLLMAdapter()
    tools_array, name_map = adapter.build_tools_array(app_tools)
    return tools_array, name_map, app_tools
