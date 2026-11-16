"""Ask a Foundry prompt agent via the Responses API as the az CLI user; auto-approve only allow-listed MCP tools.
usage: BEV_TARGET=<target> python scripts/ask_foundry_agent.py --agent <name> [--version N] "question"
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "infra", "foundry"))
from _common import load_cfg, project_endpoint  # noqa: E402

ALLOW = ("execute_sql", "poll_sql_result", "read_resource")


def ask(cfg, agent, question, version=None, allow=ALLOW, verbose=True):
    """Returns {tools: [(name, args, error)], answer, http_error, status}."""
    ep = project_endpoint(cfg)
    tok = subprocess.check_output(["az", "account", "get-access-token", "--resource", cfg["ai_audience"], "--tenant", cfg["tenant_id"],
                                   "--query", "accessToken", "-o", "tsv"], text=True).strip()
    ref = {"type": "agent_reference", "name": agent, **({"version": version} if version else {})}
    out = {"tools": [], "answer": "", "http_error": None, "status": None}

    def post(body):
        req = urllib.request.Request(f"{ep}/openai/v1/responses", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=300).read())
        except urllib.error.HTTPError as e:
            out["http_error"] = f"HTTP {e.code}: {e.read().decode()[:600]}"
            return None

    r = post({"agent_reference": ref, "input": question})
    for _ in range(12):
        if r is None:
            break
        approvals = []
        for o in r.get("output", []):
            t = o.get("type")
            if t == "mcp_call":
                out["tools"].append((o.get("name", ""), str(o.get("arguments")), str(o.get("error") or "")))
            elif t == "mcp_approval_request":
                ok = o.get("name", "").split("___")[-1] in allow
                approvals.append({"type": "mcp_approval_response", "approval_request_id": o["id"], "approve": ok})
            elif t == "message":
                out["answer"] += " ".join(c.get("text", "") for c in o.get("content", []))
        if not approvals:
            break
        r = post({"agent_reference": ref, "previous_response_id": r["id"], "input": approvals})
    out["status"] = (r or {}).get("status")
    if verbose:
        for name, args, err in out["tools"]:
            print(f"TOOL {name} args={args[:160]} error={err[:160]}")
        print(out["http_error"] or "ANSWER:\n" + out["answer"])
        print("status", out["status"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--version")
    ap.add_argument("question")
    a = ap.parse_args()
    ask(load_cfg(), a.agent, a.question, a.version)


if __name__ == "__main__":
    main()
