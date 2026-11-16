"""Run the same governed query as two identities through Unity Gateway (system.ai.dbsql) to show OBO + row filters.

BEV_TARGET=<target> python scripts/persona_query.py --as user "SELECT market_id, count(*) FROM <catalog>.<schema>.price_index_vs_pairs(NULL, NULL) GROUP BY 1"
BEV_TARGET=<target> python scripts/persona_query.py --as sp   "<same query>"
user = you (Entra token from the az CLI); sp = the regional service principal (client credentials from the secret scope).
Expected: the user (admin group) sees 8 markets, the regional SP (west group) sees 4.
"""
import argparse
import base64
import json
import time
import urllib.parse
import urllib.request

from gateway import C, call, sh, user_token


def sp_token():
    C.require("TENANT_ID", "REGIONAL_SP_APP_ID")
    raw = json.loads(sh("databricks", "secrets", "get-secret", C.SECRET_SCOPE, "regional-sp-client-secret", "-p", C.PROFILE, "-o", "json"))
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": C.REGIONAL_SP_APP_ID,
                                   "client_secret": base64.b64decode(raw["value"]).decode(),
                                   "scope": f"{C.ADB_RESOURCE_APP}/.default"}).encode()
    r = urllib.request.urlopen(f"https://login.microsoftonline.com/{C.TENANT_ID}/oauth2/v2.0/token", data=body)
    return json.loads(r.read())["access_token"]


def query(tok, sql):
    meta = {"warehouse_id": C.WAREHOUSE_ID} if C.WAREHOUSE_ID else None
    res = call("system.ai.dbsql", "execute_sql", {"query": sql}, tok, meta)
    if res.get("isError"):
        return {"error": json.dumps(res.get("content") or res.get("error"))[:400]}
    sc = res.get("structuredContent", {})
    while (sc.get("status") or {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(2)
        sc = call("system.ai.dbsql", "poll_sql_result", {"statement_id": sc["statement_id"]}, tok, meta).get("structuredContent", {})
    return sc


def rows(sc):
    return [[v.get("str", "") for v in r["values"]] for r in (sc.get("result") or {}).get("data_typed_array", [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as", dest="who", choices=["user", "sp"], required=True)
    ap.add_argument("query")
    a = ap.parse_args()
    sc = query(user_token() if a.who == "user" else sp_token(), a.query)
    if sc.get("error"):
        raise SystemExit(f"identity={a.who} tool error: {sc['error']}")
    st = sc.get("status", {})
    print(f"identity={a.who} state={st.get('state')} statement_id={sc.get('statement_id')}")
    if st.get("error"):
        print("error:", st["error"].get("message", "")[:300])
    cols = [c["name"] for c in (sc.get("manifest") or {}).get("schema", {}).get("columns", [])]
    if cols:
        print(" | ".join(cols))
    for r in rows(sc):
        print(" | ".join(r))


if __name__ == "__main__":
    main()
