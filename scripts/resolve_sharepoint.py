"""Resolve the SharePoint/OneDrive ids of the document folder by path and save them to targets/<target>.resolved.env.

Calls read_resource on the Unity Gateway Microsoft 365 MCP (system.ai.microsoft_365) as you (az CLI user), so you must have
connected Microsoft 365 in Databricks once (DEPLOYMENT.md step 8). Run BEFORE attaching the M365 policy.
Usage: BEV_TARGET=<target> python scripts/resolve_sharepoint.py
Manual fallback: open the folder in Graph Explorer (GET /me/drive/root:/<folder>:/children) and set the BEV_M365_* ids yourself.
"""
import json
import sys

from gateway import C, call, text_of, user_token

FILES = {"Pricing Policy FY27.docx": "BEV_M365_POLICY_DOC_ID", "Commercial Guardrails.xlsx": "BEV_M365_GUARDRAILS_ID",
         "Pricing Policy FY27 - draft.docx": "BEV_M365_DRAFT_DOC_ID"}


def main():
    tok = user_token()
    res = call("system.ai.microsoft_365", "read_resource", {"resource_uri": f"/v1.0/me/drive/root:/{C.M365_FOLDER}:/children"}, tok)
    if res.get("isError"):
        sys.exit(f"read_resource failed: {json.dumps(res)[:400]}")
    raw = text_of(res)
    try:
        items = json.loads(raw).get("value", [])
    except ValueError:
        sys.exit(f"unexpected read_resource payload (first 400 chars): {raw[:400]}")
    found = {i["name"]: i for i in items}
    missing = [n for n in list(FILES)[:2] if n not in found]
    if missing:
        sys.exit(f"{C.M365_FOLDER}: missing {missing}. Upload the files from data/sharepoint/out first. Found: {sorted(found)}")
    first = found["Pricing Policy FY27.docx"]["parentReference"]
    vals = {"BEV_M365_DRIVE_ID": first["driveId"], "BEV_M365_FOLDER_ID": first["id"]}
    vals.update({env: found[name]["id"] for name, env in FILES.items() if name in found})
    C.save_resolved(**vals)


if __name__ == "__main__":
    main()
