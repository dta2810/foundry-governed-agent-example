# Deployment guide

Step by step, in the order `deploy.sh` runs the phases. Each step says what gets created and why, the command that does it, and how to do it by hand when a script does not fit (for example, in a customer tenant where an admin runs the Entra steps). Run every phase first without `--apply` to see what it will do.

## 1. Prerequisites

Go through [PREREQUISITES.md](PREREQUISITES.md). Then on your laptop:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
az login --tenant <tenant-id>
databricks auth login --host https://adb-<workspace-id>.<n>.azuredatabricks.net --profile <workspace-profile>
databricks auth login --host https://accounts.azuredatabricks.net --account-id <account-id> --profile <account-profile>
pytest -q            # local checks: data, SQL rendering, agent templates
```

## 2. Configure the target

```bash
cp targets/example.env targets/env1.env
cp targets/example.foundry.yml targets/env1.foundry.yml
```

Fill in both files. The important values:

| Variable | Meaning |
|---|---|
| `BEV_ENV` | **Required.** Suffix for every resource name, 1-12 lowercase letters/digits. Account groups, Gateway policies and agent names are account- or metastore-wide, so pick one nobody else on the account uses (for example your initials + a number). The scripts refuse to take over a same-name group or policy that belongs to someone else. |
| `BEV_HOST` | The `adb-` host of the workspace, not a vanity URL. |
| `BEV_CATALOG` | An existing catalog where you can create schemas. |
| `BEV_USER` | Email of the user who runs the examples. Gateway policies apply to this identity only. |
| `BEV_TRACE_TABLE` | The metastore's unified Gateway trace table (step 11). |
| `foundry_account` | Globally unique name of the Foundry (AIServices) account the script creates. |

From here on every command takes the target name (`env1`). Run each phase first without `--apply` to see what it will do.

## 3. Data and governed tools in Unity Catalog

```bash
./deploy.sh env1 data            # dry run: prints every SQL statement
./deploy.sh env1 data --apply
```

What it creates, in order:

1. **Warehouse** `bev-pricing-wh-<env>`: serverless Pro, Small, auto-stop 10 min, tagged. Its id is saved to `targets/env1.resolved.env`.
2. **Schemas** `bev_pricing_<env>` (data and tools) and `bev_traces_<env>` (evidence), plus a `landing` Volume.
3. **Tables** with column comments: two dimensions (markets, products), weekly prices and units, competitor prices, promotions, elasticities, P&L, margin guardrails and the 12-question pricing playbook.
4. **Load**: `data/generate.py` writes parquet locally (seeded, so every run is identical); the step uploads it to the Volume and loads the tables.
5. **Views and metric view** `pricing_kpis` (volume, net sales, gross profit, GM%, price index).
6. **Governed functions** (`SQL SECURITY DEFINER`): price index vs competitor pairs, promotion ROI, margin guardrails, price scenarios, playbook evidence, and `describe_tools()`, a tool catalog served from UC comments so the agent prompt carries no column list.
7. **Row filter** `rf_market_access` on every fact table: a caller sees the markets mapped to them or to one of their groups in `user_market_access` (admin group = all, east group = NY/GA/FL/NC, west group = CA/TX/AZ/IL).
8. **Tags** and **SQL tests** (`60_test_functions.sql`): the planted stories must hold (for example, Fizzo Cola 355ml Can is above its price band in three Texas channels; the smallest cut back into band is −5%).

Manual alternative: run the files in `setup/sql/` in order in the SQL editor, replacing `${catalog}`, `${schema}` and the other placeholders.

## 4. Entra identities and the regional service principal

```bash
./deploy.sh env1 entra --apply
```

`infra/foundry/provision.py --steps entra,databricks` creates or updates, by display name:

**a. `bev-foundry-passthrough-<env>`**: the app Foundry uses for OAuth identity passthrough. It requests the delegated permission `user_impersonation` on Azure Databricks (app id `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d`, the same in every tenant). Foundry signs each user in with it, and the Gateway receives that user's token. The agent never holds a Databricks credential of its own.

**b. `bev-pricing-regional-sp-<env>`**: a second persona that signs in with client credentials. It shows that the same query returns fewer markets for a different identity.

**c. Client secrets** for both apps, valid 90 days. They go straight into the Databricks secret scope `bev-pricing-<env>` (`foundry-passthrough-client-secret`, `regional-sp-client-secret`) and are never printed.

**d. Workspace service principal** for the regional app, with only the `databricks-sql-access` entitlement.

The app ids are saved to `targets/env1.resolved.env`.

**Admin consent.** Grant admin consent for `user_impersonation` on the passthrough app: Entra admin center → App registrations → `bev-foundry-passthrough-<env>` → API permissions → Grant admin consent. In customer tenants an admin does this.

Manual alternative:
1. Entra admin center → App registrations → New registration, single tenant. Do this for both names.
2. On the passthrough app: API permissions → Add → APIs my organization uses → AzureDatabricks → Delegated → `user_impersonation`.
3. Certificates & secrets → New client secret on each app. Store each with `databricks secrets put-secret bev-pricing-<env> <key>`.
4. Databricks workspace → Settings → Identity and access → Service principals → Add → Microsoft Entra ID managed, with the regional app's application id. Entitlement: Databricks SQL access only.
5. Write `BEV_PASSTHROUGH_APP_ID` and `BEV_REGIONAL_SP_APP_ID` into `targets/env1.resolved.env`.

## 5. Databricks groups

```bash
./deploy.sh env1 identities            # dry run
./deploy.sh env1 identities --apply    # account admin
```

`setup/identities.py` creates three **account** groups, assigns them to the workspace and adds members:

| Group | Members | Markets (row filter) |
|---|---|---|
| `bev_pricing_admin_<env>` | the example user (`BEV_USER`) | all 8 |
| `bev_pricing_east_<env>` | (empty: add analysts if you want a third persona) | NY, GA, FL, NC |
| `bev_pricing_west_<env>` | the regional service principal | CA, TX, AZ, IL |

Manual alternative: Account console → User management → Groups → Add group (×3) → Members. Then Workspaces → your workspace → Permissions → Add the three groups with the User role.

## 6. Grants (least privilege)

```bash
./deploy.sh env1 grants            # review the statements
./deploy.sh env1 grants --apply
```

The three groups get only:

- `USE CATALOG` and `USE SCHEMA`;
- `EXECUTE` on the governed functions, and `SELECT` on the metric view;
- `CAN_USE` on the dedicated warehouse.

No base table, view or mapping table is readable directly: the step revokes any such privilege, so a rerun restores the containment. The functions are `SQL SECURITY DEFINER`, so they read the tables for the caller, and the row filter still applies to the caller's identity.

Also grant (once, as metastore admin) `EXECUTE` on `system.ai.dbsql` and `system.ai.microsoft_365` to the three groups. Grant `MANAGE` on both to `BEV_USER`, who attaches the policies in step 9.

## 7. Foundry: account, project, model, connections, guardrail

**a. Infrastructure**

```bash
./deploy.sh env1 foundry --apply
```

`provision.py --steps foundry,rbac` creates the Foundry (AIServices) account and project through ARM. The account has a system-managed identity, Entra-only auth (`disableLocalAuth`) and tags. The step then deploys the model and gives each `foundry_user_object_ids` user the `Foundry User` role.

**b. MCP connections (portal only).** The Foundry API cannot create OAuth-passthrough connections. In the Foundry portal, open the project → Build → Tools → Connect a tool → Custom MCP. Create two connections:

| Field | SQL connection | Microsoft 365 connection |
|---|---|---|
| Name | `bev-sql-mcp-<env>` (= `sql_connection`) | `bev-m365-mcp-<env>` (= `m365_connection`) |
| Endpoint | `https://adb-…/ai-gateway/mcp-services/system.ai.dbsql` | `https://adb-…/ai-gateway/mcp-services/system.ai.microsoft_365` |
| Authentication | OAuth identity passthrough | OAuth identity passthrough |
| Client id | `BEV_PASSTHROUGH_APP_ID` | same |
| Client secret | from `databricks secrets get-secret bev-pricing-<env> foundry-passthrough-client-secret` (paste the **decoded** value) | same |
| Auth / token URL (if the form asks) | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize` and `…/token` | same |
| Scopes | `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/user_impersonation offline_access` | same |

Each connection shows a **redirect URI**. Put both URIs in `passthrough_redirect_uris` in `targets/env1.foundry.yml`, then run `./deploy.sh env1 entra --apply` again so the passthrough app accepts them.

**c. Guardrail (portal).** Project → Guardrails → Create, then assign it to the agents after step 10. Enable: Jailbreak (user input), Indirect prompt injection (tool response, Preview), Task adherence (tool call, Preview), content harms, protected material. Foundry's tool-level checks do not apply to MCP tools; step 9 adds that control on the Databricks side.

**d. First sign-in.** The first time each user calls the agent, Foundry asks them to sign in for each connection. Do it once in the agent playground.

## 8. SharePoint documents

```bash
./deploy.sh env1 sharepoint            # writes data/sharepoint/out/*
```

1. Upload `Pricing Policy FY27.docx` and `Commercial Guardrails.xlsx` to your OneDrive folder `BEV_M365_FOLDER` (default `acme-beverages-docs`). The workbook carries the same margin floors as the UC table. The policy document holds the approval workflow, which exists only there.
2. In Databricks, connect Microsoft 365 once as yourself: open `system.ai.microsoft_365` in the Unity Gateway UI and complete the one-time Microsoft sign-in and consent. Review the requested Graph scopes.
3. Resolve the file ids by path. The step reads the folder through the Gateway as you and saves `BEV_M365_*` to the resolved file:

```bash
./deploy.sh env1 sharepoint --apply
```

Manual alternative: in Graph Explorer run `GET /me/drive/root:/acme-beverages-docs:/children` and copy `parentReference.driveId`, `parentReference.id` and each file `id` into `targets/env1.resolved.env`.

## 9. Unity Gateway service policies (Beta)

```bash
./deploy.sh env1 policies            # dry run
./deploy.sh env1 policies --apply
```

Two custom policies, each a SQL function that receives the request and returns `ALLOW` or `DENY` with a reason:

| Policy | Service | For the scoped identities |
|---|---|---|
| `bev_governed_sql_<env>` | `system.ai.dbsql` | Only `execute_sql` and `poll_sql_result`. Denies any statement containing a write or DDL keyword, `;` or a SQL comment, and any statement that does not reference `<catalog>.bev_pricing_<env>`. |
| `bev_m365_docs_<env>` | `system.ai.microsoft_365` | Only `read_resource`, and only on the exact URIs the agent uses (folder listing, policy document, guardrails workbook, and the draft only if you created it). Mail, calendar, Teams, people, search and any other path are denied. |

They apply to `BEV_USER` (compared in lower case), to any call made through the passthrough app, and to the regional SP. Every other caller is allowed, because `system.ai.*` services are **metastore-wide**.

**Treat the policies as defense in depth, not as the read-only guarantee.** Policies run in a restricted expression subset (no regex, no parsing), so they match text, not SQL structure. The boundary is Unity Catalog. The three groups hold `EXECUTE` and metric-view `SELECT` only, so a bypassed policy still cannot write for them. The identity that **owns** the schema is different: if `BEV_USER` deployed it, UC lets that user write, and the policy is the only barrier. For anything beyond a personal sandbox, deploy with a separate owner (a service principal or an admin group the example user is not in), and keep `BEV_USER` a plain member of the admin group.

`setup/policies.py` reads the policies already on each service and adds or removes only this environment's, matching on name **and** function. It refuses if a same-name policy points at another schema, and it warns if other policies changed during the update. The attach call uses an undocumented Beta `PATCH …/mcp-services/<service>?update_mask=config.service_policies`.

Watch out:
- The Gateway binds a policy to the **function id**. After any `CREATE OR REPLACE` of a policy function, run `setup/policies.py attach --apply` again (this phase does it). Otherwise the Gateway blocks every call to that service until you do.
- While attached, `BEV_USER` cannot run SQL outside the pricing schema through the Gateway (for example `SELECT current_user()`).
- Detach when you are not using it: `BEV_TARGET=env1 python setup/policies.py detach --apply`.

## 10. Publish the agent

```bash
./deploy.sh env1 agent            # prints the rendered agent definition
./deploy.sh env1 agent --apply
```

`infra/foundry/agent.py` renders `agent.yaml` with your catalog, schema and SharePoint ids. Then it:

1. checks that both connections exist and use OAuth passthrough;
2. creates the two toolboxes if missing (SQL toolbox + code interpreter for charts; M365 toolbox);
3. posts a new agent version only when the definition changed.

Toolbox versions are immutable and restart at 1 in a new project. To change a toolbox, bump `toolbox_version` in `agent.yaml`.

The agent `bev-pricing-governed-<env>` does the following:
- starts each conversation with `describe_tools()`;
- answers with governed functions only;
- reads rules from the two SharePoint documents;
- treats document text as data;
- refuses writes, off-topic requests and mail.

Assign the guardrail from step 7c to it.

Try it in the Foundry playground with the questions in [EXAMPLE_USAGE.md](EXAMPLE_USAGE.md).

## 11. Traceability dashboard

The policy evidence comes from the metastore's **unified Gateway trace table** (Gateway OpenTelemetry export to UC). Set `BEV_TRACE_TABLE` to it.

```bash
./deploy.sh env1 traces --apply
```

- `policy_events`: a snapshot of `policy_evaluated` events for this environment's policies. Re-run the phase to refresh it.
- `mcp_call_traffic` / `statement_traffic`: views that classify each call as governed agent, unguarded agent or test traffic. Foundry calls carry no user agent; scripts, CLI and playgrounds do.
- Dashboard *Governed agent tools (<env>)*. It shows tool calls by identity, the SQL each call ran, Unity Catalog denials and Gateway policy decisions, with a Traffic filter. It is published without embedded credentials, so each viewer needs read access to the system tables.

## 12. Smoke tests

```bash
./deploy.sh env1 smoke                 # governed agent + persona check
./deploy.sh env1 smoke --with-naive    # + Gateway DENY cases
```

| # | Case | Expected |
|---|---|---|
| 0 | Same query as user and as regional SP through the Gateway | user 8 markets, SP 4 |
| 1–3 | Price band, minimum price cut, promotion ROI | governed function used |
| 4–5 | Margin floor and approval workflow | UC numbers + SharePoint document |
| 6–7 | Off-topic, mail request | refusal, no tool call |
| 8 | Jailbreak prompt | Foundry guardrail or refusal |
| 9 | "Delete every row…" | refused, no write SQL |
| 10–12 | Naive agent: write SQL, mail, another folder | Gateway DENY (`tool_user_error` in Foundry) |

LLM answers vary. A FAIL prints the tools and the start of the answer: read it before changing anything.
