"""Minimal Unity Gateway MCP client (JSON-RPC tools/call) with an Entra token from the az CLI."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "setup"))
import config as C  # noqa: E402


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, check=True).stdout.strip()


def host():
    # vanity hosts redirect Entra tokens on /ai-gateway to /login: use the adb-<id>.<n> host
    if C.HOST:
        return C.HOST
    return json.loads(sh("databricks", "auth", "describe", "-p", C.PROFILE, "-o", "json"))["details"]["host"].rstrip("/")


def user_token():
    C.require("TENANT_ID")
    return sh("az", "account", "get-access-token", "--resource", C.ADB_RESOURCE_APP, "--tenant", C.TENANT_ID,
              "--query", "accessToken", "-o", "tsv")


def call(service, tool, args, tok, meta=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": args, **({"_meta": meta} if meta else {})}}
    req = urllib.request.Request(f"{host()}/ai-gateway/mcp-services/{service}", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream"})
    try:
        raw = urllib.request.urlopen(req, timeout=120).read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"{service} {tool}: HTTP {e.code} {e.read()[:300]!r}")
    if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):  # SSE framing
        raw = next(line[5:] for line in raw.splitlines() if line.startswith("data:"))
    msg = json.loads(raw)
    if "error" in msg:
        return {"isError": True, "error": msg["error"]}
    return msg.get("result", {})


def text_of(result):
    """Concatenate text parts of an MCP tool result (text content or embedded resource text)."""
    parts = []
    for c in result.get("content", []):
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif c.get("type") == "resource":
            parts.append((c.get("resource") or {}).get("text", ""))
    return "\n".join(parts)
