"""
chat_ui_component.py
====================
Flask Blueprint and message types for MCP Apps chat UI integration.

Provides:
  - ``MCPAppMessage`` — a chat message that embeds an MCP App iframe
  - ``ChatMessage``   — union type for text or app messages
  - ``mcp_apps_bp``   — Flask Blueprint exposing backend routes the
    ``McpAppFrame`` React component calls into:

      POST /api/mcp-apps/tool-call   — proxy a tool call from an iframe
      GET  /api/mcp-apps/resource    — serve a UI resource HTML blob

Archestra integration: mount the blueprint on your Flask app and pass
``agentId`` context through your session/auth middleware.

Reference: https://modelcontextprotocol.io/docs/extensions/apps
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from mcp_apps_registry import MCPAppsRegistry, MCPRPCError, MCPTransportError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------


@dataclass
class TextMessage:
    """A plain text chat message."""

    role: str
    """``user``, ``assistant``, or ``tool``."""

    content: str
    """Markdown or plain text content."""

    message_id: Optional[str] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MCPAppMessage:
    """
    A chat message that embeds an interactive MCP App iframe.

    When an LLM tool call returns an HTML payload (detected by
    ``extract_mcp_app_html``), the chat renderer should create an
    ``MCPAppMessage`` instead of a plain ``TextMessage``.

    Fields map directly to what the ``McpAppFrame`` React component expects.
    """

    role: str = "tool"

    tool_name: str = ""
    """The MCP tool that produced this app (used as the iframe label)."""

    html_content: str = ""
    """The full HTML page to load in the sandboxed iframe (``srcdoc``)."""

    tool_result: Any = None
    """The raw MCP tool result, pushed to the app on ``ui/initialize``."""

    agent_id: str = ""
    """Archestra agent ID; the iframe uses this to proxy tool calls."""

    message_id: Optional[str] = None
    tool_call_id: Optional[str] = None

    # UI hints
    min_height: int = 320
    """Minimum iframe height in pixels."""

    csp_overrides: dict[str, str] = field(default_factory=dict)
    """Extra CSP directives declared by the app (from ``_meta.ui.csp``)."""

    extra_sandbox: list[str] = field(default_factory=list)
    """Additional sandbox tokens (e.g. ``allow-downloads``)."""

    def is_app_message(self) -> bool:
        return bool(self.html_content)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Don't serialise the full HTML in list views — callers can fetch it
        # separately via the /api/mcp-apps/resource endpoint.
        d.pop("html_content", None)
        return {k: v for k, v in d.items() if v not in (None, [], {})}

    def sandbox_attr(self) -> str:
        """
        Build the ``sandbox`` attribute value for the iframe tag.

        Base tokens are always present; ``extra_sandbox`` adds more.
        """
        base = ["allow-scripts", "allow-forms", "allow-popups"]
        # Deduplicate while preserving order
        seen: set[str] = set()
        tokens: list[str] = []
        for t in base + self.extra_sandbox:
            if t not in seen:
                seen.add(t)
                tokens.append(t)
        return " ".join(tokens)


# Union alias used in type hints across the codebase.
ChatMessage = TextMessage | MCPAppMessage


# ---------------------------------------------------------------------------
# HTML content extraction helper (mirrors extractMcpAppHtml in TypeScript)
# ---------------------------------------------------------------------------


def extract_mcp_app_html(output: Any) -> Optional[str]:
    """
    Inspect a raw MCP tool output and return the HTML string if it contains
    an MCP App resource block; otherwise return ``None``.

    Handles the following shapes:

    * A raw list of MCP content blocks.
    * A ``{"content": [...], "isError": bool}`` envelope (Archestra format).
    * A JSON-encoded string of either of the above.

    An MCP App resource block looks like::

        {
            "type": "resource",
            "resource": {
                "mimeType": "text/html",
                "text": "<!DOCTYPE html>..."
            }
        }
    """
    blocks: Any = output

    # Unwrap JSON string
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except (json.JSONDecodeError, ValueError):
            return None

    # Unwrap {"content": [...]} envelope
    if isinstance(blocks, dict) and "content" in blocks:
        blocks = blocks["content"]

    if not isinstance(blocks, list):
        return None

    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "resource":
            continue
        resource = block.get("resource")
        if not isinstance(resource, dict):
            continue
        mime = resource.get("mimeType", "")
        # Accept "text/html", "text/html+mcp-app", "text/html; charset=utf-8"
        if mime.split(";")[0].strip() in ("text/html", "text/html+mcp-app"):
            text = resource.get("text")
            if isinstance(text, str) and text.strip():
                return text

    return None


# ---------------------------------------------------------------------------
# Agent session resolver (override in your app)
# ---------------------------------------------------------------------------


class AgentSessionResolver:
    """
    Resolves the MCP Gateway URL for a given Archestra agent ID.

    Override ``resolve`` in a subclass to look up your actual agent registry,
    database, or configuration store.
    """

    def resolve(self, agent_id: str) -> Optional[str]:
        """
        Return the MCP Gateway URL for *agent_id*, or ``None`` if not found.

        Example implementation (static map)::

            class MyResolver(AgentSessionResolver):
                _MAP = {
                    "agent-abc": "https://mcp.example.com/mcp",
                }
                def resolve(self, agent_id):
                    return self._MAP.get(agent_id)
        """
        raise NotImplementedError(
            "Subclass AgentSessionResolver and implement resolve(agent_id)"
        )


# ---------------------------------------------------------------------------
# Blueprint factory
# ---------------------------------------------------------------------------


def create_mcp_apps_blueprint(
    registry: MCPAppsRegistry,
    resolver: AgentSessionResolver,
    url_prefix: str = "/api/mcp-apps",
) -> Blueprint:
    """
    Build and return the Flask Blueprint for MCP Apps backend routes.

    Parameters
    ----------
    registry:
        An initialised ``MCPAppsRegistry`` instance (shared across requests).
    resolver:
        An ``AgentSessionResolver`` that maps agent IDs to MCP server URLs.
    url_prefix:
        URL prefix for all routes. Defaults to ``/api/mcp-apps``.

    Routes
    ------
    ``POST /api/mcp-apps/tool-call``
        Proxy a tool call from an MCP App iframe to the MCP server.

        Request body::

            {
                "agentId": "agent-abc",
                "toolName": "get-time",
                "arguments": {}
            }

        Response (success)::

            {"content": [...], "isError": false}

    ``GET /api/mcp-apps/resource``
        Return the HTML for a UI resource (used by server-side rendering).

        Query params: ``agentId``, ``resourceUri``
    """
    bp = Blueprint("mcp_apps", __name__, url_prefix=url_prefix)

    # ------------------------------------------------------------------ #
    # Tool-call proxy                                                      #
    # ------------------------------------------------------------------ #

    @bp.route("/tool-call", methods=["POST"])
    def tool_call() -> ResponseReturnValue:
        """
        Proxy a ``tools/call`` request from an MCP App iframe.

        The ``McpAppFrame`` React component hits this endpoint when the
        iframe sends a ``tools/call`` postMessage.
        """
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "Request body must be JSON"}), 400

        agent_id: str = body.get("agentId", "")
        tool_name: str = body.get("toolName", "")
        arguments: dict[str, Any] = body.get("arguments") or {}

        if not agent_id:
            return jsonify({"error": "agentId is required"}), 400
        if not tool_name:
            return jsonify({"error": "toolName is required"}), 400

        server_url = resolver.resolve(agent_id)
        if server_url is None:
            logger.warning("No MCP server found for agentId=%r", agent_id)
            return jsonify({"error": f"Unknown agentId: {agent_id!r}"}), 404

        try:
            result = asyncio.run(registry.call_tool(server_url, tool_name, arguments))
            return jsonify(result.as_mcp_result())

        except MCPRPCError as exc:
            logger.error("MCP RPC error calling %r: %s", tool_name, exc)
            return jsonify(
                {
                    "content": [{"type": "text", "text": exc.message}],
                    "isError": True,
                }
            ), 200  # Tool errors are 200 with isError=True per MCP spec

        except MCPTransportError as exc:
            logger.error("Transport error calling %r: %s", tool_name, exc)
            return jsonify({"error": "MCP server unreachable", "detail": str(exc)}), 502

        except Exception as exc:
            logger.exception("Unexpected error in tool_call route: %s", exc)
            return jsonify({"error": "Internal server error"}), 500

    # ------------------------------------------------------------------ #
    # Resource fetch                                                       #
    # ------------------------------------------------------------------ #

    @bp.route("/resource", methods=["GET"])
    def get_resource() -> ResponseReturnValue:
        """
        Fetch and return a UI resource HTML payload.

        Primarily used by server-side rendering paths that need the HTML
        before sending the initial page to the client.
        """
        agent_id = request.args.get("agentId", "")
        resource_uri = request.args.get("resourceUri", "")

        if not agent_id:
            return jsonify({"error": "agentId query param is required"}), 400
        if not resource_uri:
            return jsonify({"error": "resourceUri query param is required"}), 400

        server_url = resolver.resolve(agent_id)
        if server_url is None:
            return jsonify({"error": f"Unknown agentId: {agent_id!r}"}), 404

        try:
            resource = asyncio.run(
                registry.fetch_ui_resource(server_url, resource_uri)
            )
            return jsonify(
                {
                    "uri": resource.uri,
                    "mimeType": resource.mime_type,
                    "html": resource.html,
                    "contentHash": resource.content_hash(),
                }
            )

        except MCPRPCError as exc:
            logger.error("MCP RPC error fetching resource %r: %s", resource_uri, exc)
            return jsonify({"error": exc.message}), 502

        except MCPTransportError as exc:
            logger.error("Transport error fetching resource %r: %s", resource_uri, exc)
            return jsonify({"error": "MCP server unreachable", "detail": str(exc)}), 502

        except ValueError as exc:
            logger.error("Resource error for %r: %s", resource_uri, exc)
            return jsonify({"error": str(exc)}), 422

        except Exception as exc:
            logger.exception("Unexpected error in get_resource route: %s", exc)
            return jsonify({"error": "Internal server error"}), 500

    # ------------------------------------------------------------------ #
    # Health / cache stats                                                 #
    # ------------------------------------------------------------------ #

    @bp.route("/health", methods=["GET"])
    def health() -> ResponseReturnValue:
        """Return cache statistics and service health."""
        return jsonify({"status": "ok", "cache": registry.cache_stats()})

    return bp


# ---------------------------------------------------------------------------
# Message builder helpers
# ---------------------------------------------------------------------------


def build_mcp_app_message(
    tool_name: str,
    tool_result: Any,
    agent_id: str,
    *,
    html_content: str,
    tool_call_id: Optional[str] = None,
    min_height: int = 320,
    csp_overrides: Optional[dict[str, str]] = None,
    extra_sandbox: Optional[list[str]] = None,
) -> MCPAppMessage:
    """
    Convenience constructor for ``MCPAppMessage``.

    Typically called from your LLM response handler after detecting that a
    tool result contains MCP App HTML::

        html = extract_mcp_app_html(result.content)
        if html:
            msg = build_mcp_app_message(
                tool_name=tool_name,
                tool_result=result.as_mcp_result(),
                agent_id=session["agent_id"],
                html_content=html,
            )
            conversation.append(msg)
    """
    return MCPAppMessage(
        role="tool",
        tool_name=tool_name,
        html_content=html_content,
        tool_result=tool_result,
        agent_id=agent_id,
        tool_call_id=tool_call_id,
        min_height=min_height,
        csp_overrides=csp_overrides or {},
        extra_sandbox=extra_sandbox or [],
    )


def message_to_llm_format(msg: ChatMessage) -> dict[str, Any]:
    """
    Convert a ``ChatMessage`` to the OpenAI-compatible message dict format
    used when constructing LLM conversation histories.

    MCP App messages are represented as tool messages whose content describes
    the rendered UI (the HTML is not sent back to the LLM).
    """
    if isinstance(msg, TextMessage):
        d: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        return d

    # MCPAppMessage — surface a text summary to the LLM
    content = f"[MCP App rendered: {msg.tool_name}]"
    d = {"role": "tool", "content": content}
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    return d
