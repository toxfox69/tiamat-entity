"""
mcp_apps_registry.py
====================
MCP Apps Registry — discovers, caches, and serves UI resources from MCP Gateway
endpoints.

An "MCP App" is an MCP tool whose description includes a ``_meta.ui.resourceUri``
field pointing to a ``ui://`` resource. When the LLM invokes such a tool the host
fetches the resource (an HTML page) and renders it in a sandboxed iframe that
communicates back via postMessage JSON-RPC 2.0.

Reference: https://modelcontextprotocol.io/docs/extensions/apps
           https://apps.extensions.modelcontextprotocol.io
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# The MIME type that MCP servers use for UI resource blobs.
# Both "text/html" and "text/html+mcp-app" appear in the wild; we accept both.
RESOURCE_MIME_TYPES: frozenset[str] = frozenset(
    {"text/html", "text/html+mcp-app", "text/html; charset=utf-8"}
)

# Default JSON-RPC protocol version used when talking to MCP servers.
JSONRPC_VERSION = "2.0"

# How many seconds to keep a discovery or resource result before re-fetching.
DEFAULT_CACHE_TTL = 300  # 5 minutes

# Maximum HTML payload accepted from a remote server (10 MB).
MAX_HTML_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MCPAppUIConfig:
    """Metadata from ``_meta.ui`` on a tool description."""

    resource_uri: str
    """``ui://`` URI that resolves to the iframe HTML."""

    csp: dict[str, Any] = field(default_factory=dict)
    """Content-Security-Policy overrides declared by the app."""

    permissions: list[str] = field(default_factory=list)
    """Extra sandbox permissions (e.g. ``allow-downloads``)."""

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> Optional["MCPAppUIConfig"]:
        """
        Parse ``_meta.ui`` from a raw tool description dict.

        Returns ``None`` if the tool is not an MCP App (no ``_meta.ui``).
        """
        ui: dict[str, Any] | None = (meta or {}).get("ui")
        if not ui or not ui.get("resourceUri"):
            return None
        return cls(
            resource_uri=ui["resourceUri"],
            csp=ui.get("csp") or {},
            permissions=ui.get("permissions") or [],
        )


@dataclass
class MCPAppTool:
    """A discovered MCP tool that supports the MCP Apps UI extension."""

    name: str
    """Tool name as declared by the MCP server."""

    description: str
    """Human-readable description."""

    input_schema: dict[str, Any]
    """JSON Schema describing accepted parameters (``inputSchema`` field)."""

    ui: MCPAppUIConfig
    """UI configuration extracted from ``_meta.ui``."""

    server_url: str
    """The MCP Gateway endpoint this tool was discovered from."""

    raw: dict[str, Any] = field(default_factory=dict)
    """Original tool descriptor as returned by the server (for pass-through)."""


@dataclass
class MCPAppResource:
    """A fetched and cached UI resource."""

    uri: str
    """The ``ui://`` URI that identifies this resource."""

    mime_type: str
    """MIME type from the server response (usually ``text/html``)."""

    html: str
    """The HTML payload to embed in the iframe (``srcdoc`` value)."""

    etag: Optional[str] = None
    """ETag returned by the server, used for conditional re-fetching."""

    fetched_at: float = field(default_factory=time.monotonic)
    """Monotonic timestamp when this entry was last refreshed."""

    def content_hash(self) -> str:
        """SHA-256 hex digest of the HTML content (useful for change detection)."""
        return hashlib.sha256(self.html.encode()).hexdigest()


@dataclass
class ToolCallResult:
    """Raw result from calling an MCP tool."""

    content: list[dict[str, Any]]
    """MCP content blocks (type ``text``, ``image``, ``resource``, …)."""

    is_error: bool = False
    """True when the MCP server reported a tool-level error."""

    def as_mcp_result(self) -> dict[str, Any]:
        """Return the canonical MCP result envelope."""
        return {"content": self.content, "isError": self.is_error}

    def text(self) -> Optional[str]:
        """Return the first text block's value, if any."""
        for block in self.content:
            if block.get("type") == "text":
                return block.get("text")
        return None


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


class MCPRPCError(Exception):
    """Raised when an MCP server returns a JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class MCPTransportError(Exception):
    """Raised when a network or HTTP-level error prevents an MCP call."""


def _make_request(method: str, params: dict[str, Any], req_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "method": method, "params": params}


def _parse_response(payload: dict[str, Any]) -> Any:
    """Extract ``result`` from a JSON-RPC response or raise ``MCPRPCError``."""
    if "error" in payload:
        err = payload["error"]
        raise MCPRPCError(
            code=err.get("code", -32603),
            message=err.get("message", "Unknown error"),
            data=err.get("data"),
        )
    return payload.get("result")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class MCPAppsRegistry:
    """
    Discovers and caches MCP App tools and their UI resources.

    Usage::

        async with MCPAppsRegistry() as registry:
            tools = await registry.discover_apps("https://my-mcp-server.example.com/mcp")
            resource = await registry.fetch_ui_resource(
                "https://my-mcp-server.example.com/mcp",
                "ui://my-tool/app.html",
            )
            print(resource.html)

    All network calls are made with ``httpx.AsyncClient``.  The registry keeps
    an in-memory LRU-style TTL cache keyed by ``(server_url, resource_uri)``.
    """

    def __init__(
        self,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        http_timeout: float = 30.0,
        max_retries: int = 2,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Parameters
        ----------
        cache_ttl:
            Seconds before a cached entry is considered stale.
        http_timeout:
            Per-request timeout in seconds.
        max_retries:
            Number of times to retry a failed request (exponential back-off).
        headers:
            Extra HTTP headers added to every request (e.g. Authorization).
        """
        self.cache_ttl = cache_ttl
        self.http_timeout = http_timeout
        self.max_retries = max_retries
        self._base_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        }

        # Cache: server_url -> list[MCPAppTool]
        self._tool_cache: dict[str, list[MCPAppTool]] = {}
        # Cache: (server_url, resource_uri) -> MCPAppResource
        self._resource_cache: dict[tuple[str, str], MCPAppResource] = {}
        # Timestamps: key -> monotonic time of last fetch
        self._cache_times: dict[Any, float] = {}

        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "MCPAppsRegistry":
        self._client = httpx.AsyncClient(
            timeout=self.http_timeout,
            headers=self._base_headers,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "Registry must be used as an async context manager "
                "(`async with MCPAppsRegistry() as r:`)"
            )
        return self._client

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def discover_apps(
        self,
        server_url: str,
        force_refresh: bool = False,
    ) -> list[MCPAppTool]:
        """
        Fetch all tools from *server_url* and return those that declare
        ``_meta.ui.resourceUri`` (i.e., are MCP Apps).

        Results are cached for ``self.cache_ttl`` seconds.

        Parameters
        ----------
        server_url:
            Full URL of the MCP Gateway endpoint (e.g.
            ``https://example.com/mcp``).
        force_refresh:
            Skip the cache and always re-fetch.

        Returns
        -------
        list[MCPAppTool]
            Possibly empty list of discovered MCP App tools.
        """
        cache_key = server_url
        if not force_refresh and self._is_cache_valid(cache_key):
            logger.debug("discover_apps cache HIT for %s", server_url)
            return self._tool_cache.get(cache_key, [])

        logger.info("Discovering MCP Apps at %s", server_url)
        raw_tools = await self._rpc(server_url, "tools/list", {})
        tools_list: list[dict[str, Any]] = raw_tools.get("tools", [])

        apps: list[MCPAppTool] = []
        for t in tools_list:
            ui_cfg = MCPAppUIConfig.from_meta(t.get("_meta") or {})
            if ui_cfg is None:
                continue  # plain tool, not an MCP App
            apps.append(
                MCPAppTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema") or {"type": "object", "properties": {}},
                    ui=ui_cfg,
                    server_url=server_url,
                    raw=t,
                )
            )

        self._tool_cache[cache_key] = apps
        self._cache_times[cache_key] = time.monotonic()
        logger.info("Found %d MCP App tool(s) at %s", len(apps), server_url)
        return apps

    async def fetch_ui_resource(
        self,
        server_url: str,
        resource_uri: str,
        force_refresh: bool = False,
    ) -> MCPAppResource:
        """
        Fetch the HTML payload for an MCP App UI resource.

        Parameters
        ----------
        server_url:
            MCP Gateway endpoint that owns the resource.
        resource_uri:
            The ``ui://`` URI declared in ``_meta.ui.resourceUri``.
        force_refresh:
            Skip the cache.

        Returns
        -------
        MCPAppResource
            The fetched (and cached) resource.

        Raises
        ------
        MCPRPCError
            If the server returns a JSON-RPC error.
        MCPTransportError
            If the HTTP call fails.
        ValueError
            If the response is not a recognised HTML MIME type.
        """
        cache_key = (server_url, resource_uri)
        if not force_refresh and self._is_cache_valid(cache_key):
            cached = self._resource_cache.get(cache_key)
            if cached is not None:
                logger.debug("fetch_ui_resource cache HIT for %s", resource_uri)
                return cached

        logger.info("Fetching UI resource %s from %s", resource_uri, server_url)
        result = await self._rpc(server_url, "resources/read", {"uri": resource_uri})

        contents: list[dict[str, Any]] = result.get("contents", [])
        if not contents:
            raise ValueError(f"Empty contents for resource {resource_uri!r}")

        # Pick the first matching HTML block.
        html_content: Optional[str] = None
        mime_type: str = "text/html"
        for block in contents:
            mt = block.get("mimeType", "")
            if mt.split(";")[0].strip() in RESOURCE_MIME_TYPES:
                html_content = block.get("text") or block.get("blob")
                mime_type = mt
                break

        if html_content is None:
            available = [b.get("mimeType") for b in contents]
            raise ValueError(
                f"No HTML content block for {resource_uri!r}. "
                f"Available MIME types: {available}"
            )

        if len(html_content.encode()) > MAX_HTML_BYTES:
            raise ValueError(
                f"HTML payload for {resource_uri!r} exceeds {MAX_HTML_BYTES // 1024} KB limit"
            )

        resource = MCPAppResource(
            uri=resource_uri,
            mime_type=mime_type,
            html=html_content,
        )
        self._resource_cache[cache_key] = resource
        self._cache_times[cache_key] = time.monotonic()
        logger.info(
            "Cached UI resource %s (%d bytes)", resource_uri, len(html_content)
        )
        return resource

    async def call_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        """
        Invoke an MCP tool on the given server.

        Parameters
        ----------
        server_url:
            MCP Gateway endpoint.
        tool_name:
            Name of the tool to call.
        arguments:
            Tool input parameters.

        Returns
        -------
        ToolCallResult
            Parsed result including content blocks and error flag.
        """
        logger.info("Calling tool %r on %s with args=%s", tool_name, server_url, arguments)
        result = await self._rpc(
            server_url, "tools/call", {"name": tool_name, "arguments": arguments}
        )
        return ToolCallResult(
            content=result.get("content", []),
            is_error=result.get("isError", False),
        )

    def invalidate(self, server_url: str, resource_uri: Optional[str] = None) -> None:
        """
        Remove entries from the cache.

        If *resource_uri* is given, only that resource is evicted; otherwise
        all entries for *server_url* are removed.
        """
        if resource_uri is not None:
            key: Any = (server_url, resource_uri)
            self._resource_cache.pop(key, None)
            self._cache_times.pop(key, None)
        else:
            self._tool_cache.pop(server_url, None)
            self._cache_times.pop(server_url, None)
            for k in list(self._resource_cache.keys()):
                if k[0] == server_url:
                    self._resource_cache.pop(k)
                    self._cache_times.pop(k, None)

    def cache_stats(self) -> dict[str, int]:
        """Return a snapshot of cache sizes for observability."""
        return {
            "tool_cache_servers": len(self._tool_cache),
            "tool_cache_entries": sum(len(v) for v in self._tool_cache.values()),
            "resource_cache_entries": len(self._resource_cache),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _is_cache_valid(self, key: Any) -> bool:
        ts = self._cache_times.get(key)
        if ts is None:
            return False
        return (time.monotonic() - ts) < self.cache_ttl

    async def _rpc(
        self, server_url: str, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Send a single JSON-RPC 2.0 request and return the ``result`` dict.

        Retries up to ``self.max_retries`` times on transient network errors.
        """
        client = self._get_client()
        body = _make_request(method, params)
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.post(server_url, json=body)
                resp.raise_for_status()
                payload: dict[str, Any] = resp.json()
                return _parse_response(payload)

            except MCPRPCError:
                raise  # don't retry protocol-level errors

            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "HTTP %d from %s (attempt %d/%d): %s",
                    exc.response.status_code,
                    server_url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                last_exc = MCPTransportError(str(exc))
                if exc.response.status_code < 500:
                    break  # 4xx — don't retry

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning(
                    "Network error calling %s (attempt %d/%d): %s",
                    server_url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                last_exc = MCPTransportError(str(exc))

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s, …

        raise last_exc or MCPTransportError(f"RPC call to {server_url} failed")
