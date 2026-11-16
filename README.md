# Governed Foundry agent on Databricks Unity Gateway

A Microsoft Foundry agent answers business questions from Unity Catalog data and SharePoint documents **as the signed-in user**. Databricks Unity Gateway governs and traces every tool call. The company, data and documents are fictitious (Acme Beverages, synthetic pricing data).

> Example code, not a product. Some features it uses are Preview or Beta and can change.

## Why

Agents often reach enterprise data through a shared token or an integration account. Then nobody can say which person asked for which data, row-level security does not apply, and the only guardrail is the prompt. This example keeps the agent in Foundry and moves identity, data rules and audit to the data platform:

1. **On-behalf-of access, no tokens in the agent.** Foundry calls the Gateway with the user's own Entra identity. Unity Catalog row filters decide what each person sees: same question, 8 markets for one user, 4 for another.
2. **Policies before the call.** Gateway service policies block writes, out-of-scope queries, mail and other folders before the tool runs, with a stated reason. Foundry's tool-level guardrails do not inspect MCP tools; the Gateway does.
3. **One audit trail.** Every call (who, what SQL or document, which policy decision) lands in system tables and a dashboard.

## Architecture

```
 user ──► Foundry agent (gpt-5-mini + Foundry guardrail)
              │  MCP over OAuth identity passthrough (the user's Entra token)
              ▼
        Databricks Unity Gateway ── service policies: ALLOW / DENY + reason
          ├─ system.ai.dbsql ─────────► Unity Catalog: governed functions, metric view, row filters
          └─ system.ai.microsoft_365 ─► SharePoint / OneDrive: one approved folder
              │
              └─► system.ai_gateway.usage · query history · audit · unified trace table ──► traceability dashboard
```

| Layer | Component | What it controls |
|---|---|---|
| Experience | Foundry prompt agent + guardrail | Conversation, topic, jailbreak screening on user input |
| Identity | Entra app with OAuth identity passthrough | Each call runs as the signed-in user; no shared credential |
| Tools | Unity Gateway MCP services (`system.ai.dbsql`, `system.ai.microsoft_365`) | One governed entry point for SQL and Microsoft 365 |
| Policy | Gateway service policies (SQL functions) | Read-only, one schema, one document folder, before the call |
| Data | UC functions (`SQL SECURITY DEFINER`), metric view, row filter | Users get `EXECUTE` only, never table reads; markets by group |
| Audit | System tables + unified trace table + AI/BI dashboard | Who asked what, as whom, with what outcome |

## How to start

```bash
git clone https://github.com/dta2810/foundry-governed-agent-example && cd foundry-governed-agent-example
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
pytest -q                                              # local checks, no cloud access
cp targets/example.env targets/env1.env               # fill in workspace, catalog, tenant, user
cp targets/example.foundry.yml targets/env1.foundry.yml
./deploy.sh env1 data                                 # dry run: prints what it would create
```

Then follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) phase by phase (`./deploy.sh env1 <phase> --apply`). Every resource name ends with your `BEV_ENV` suffix, so several environments can share one workspace.

## Docs

| Document | Read it to |
|---|---|
| [docs/PREREQUISITES.md](docs/PREREQUISITES.md) | Check workspace, compute, Azure, Entra and Microsoft 365 requirements, and who must grant each |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deploy step by step: what each phase creates, why, and how to do it by hand |
| [docs/EXAMPLE_USAGE.md](docs/EXAMPLE_USAGE.md) | Try it: example questions, expected answers, the optional unguarded agent |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Tear down, open and close policy windows, fix known gotchas, run the security checklist |

## Repository layout

| Path | Contents |
|---|---|
| `deploy.sh`, `teardown.sh` | Entry points (dry run unless `--apply`) |
| `targets/` | Target templates; your copies and generated ids are gitignored |
| `data/` | Synthetic data and SharePoint document generators |
| `setup/` | Databricks side: SQL steps, account groups, Gateway policies |
| `infra/foundry/` | Azure side: Entra, Foundry, agent as code |
| `scripts/` | SharePoint id resolver, persona query, smoke tests, dashboard, teardown |
| `dashboards/` | Traceability dashboard template |
| `tests/` | Local unit tests |
