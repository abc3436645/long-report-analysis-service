"""Small outbound adapters for archived professional-source responses."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(provider: dict, query: dict) -> tuple[bytes, dict]:
    kind, url = provider.get("kind"), provider.get("url")
    if kind not in ("http", "mcp") or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("provider requires http/mcp kind and HTTP(S) url")
    if kind == "mcp":
        tool = provider.get("tool")
        if not isinstance(tool, str) or not tool:
            raise ValueError("MCP provider requires tool name")
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": query}}
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": tool}
    else:
        payload = query
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    # shortcut: synthetic MCP providers return JSON; add SSE parsing when a deployed provider streams tool results.
    try:
        with urlopen(request, timeout=15) as response:
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise ValueError("provider did not return JSON")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("provider response exceeds 2 MB")
    except HTTPError as error:
        raw = error.read(2_000_001)
        if len(raw) > 2_000_000:
            raw = raw[:2_000_000]
        return raw or json.dumps({"http_error": error.code}).encode(), {"status": "failed", "limitations": [f"HTTP {error.code}"]}
    except (URLError, TimeoutError) as error:
        return json.dumps({"transport_error": str(error)}, ensure_ascii=False).encode(), {"status": "failed", "limitations": [str(error)]}
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("provider response must be an object")
        if kind == "mcp":
            payload = result.get("result")
            if result.get("error") or isinstance(payload, dict) and payload.get("isError"):
                error = result.get("error")
                message = error.get("message", "MCP tool error") if isinstance(error, dict) else "MCP tool error"
                return raw, {"status": "failed", "limitations": [message]}
            if not isinstance(payload, dict):
                raise ValueError("MCP tool result is missing")
            result = payload.get("structuredContent")
        if not isinstance(result, dict) or result.get("status") not in ("success", "partial", "empty"):
            raise ValueError("provider response lacks valid retrieval status")
        return raw, result
    except (ValueError, KeyError, TypeError) as error:
        return raw, {"status": "failed", "limitations": [str(error)]}
