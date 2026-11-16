# Prerequisites

Check every row before step 1 of [DEPLOYMENT.md](DEPLOYMENT.md). Each row names the role that usually holds it. In a customer tenant, the Entra and Microsoft 365 rows need their admins.

## Databricks: account and workspace

| Requirement | Detail | Role |
|---|---|---|
| Azure Databricks workspace | Premium, Unity Catalog, serverless SQL enabled. Use the `adb-<workspace-id>.<n>.azuredatabricks.net` host: vanity URLs redirect Entra tokens on `/ai-gateway` to a login page. | Workspace admin |
| Account admin | Create the three groups, assign them to the workspace, add members (`setup/identities.py`). | Account admin |
| Previews | **Enhanced Unity Gateway** and **Unity Gateway Service Policies** enabled for the workspace. | Workspace admin |
| Unity Catalog | An existing catalog where you have `USE CATALOG` + `CREATE SCHEMA`. The deployment creates two schemas in it: `bev_pricing_<env>` (data, functions) and `bev_traces_<env>` (evidence views). | Catalog owner |
| Gateway MCP services | `system.ai.dbsql` and `system.ai.microsoft_365` visible in Unity Gateway. `EXECUTE` on both for the example users and the regional service principal; `MANAGE` on both for whoever attaches policies. | Metastore admin |
| Unified Gateway trace table | Unity Gateway OpenTelemetry export to a UC table, configured at metastore level (or reuse an existing one you can read). Used for the policy evidence and the dashboard. | Metastore admin |
| Tag policies | If the account enforces tag policies, set `BEV_TAGS` to allowed keys and values. | Account admin |

## Databricks: compute

| Resource | Size | Why |
|---|---|---|
| Dedicated serverless SQL warehouse | Pro, Small, 1 cluster, auto-stop 10 min (created by `deploy.sh data`) | Foundry sends no `warehouse_id`, so agent SQL runs on a warehouse the caller can use. `CAN_USE` is granted only to the three groups on this warehouse. |
| Clusters, jobs, Lakebase, Apps | Not needed | Setup runs from your laptop through the SQL Statement API. |
| Model serving | Not needed | Optional only if you add the built-in `block_jailbreak` Gateway policy (not part of the default setup). |

## Azure: Foundry

| Requirement | Detail | Role |
|---|---|---|
| Subscription + resource group | `Contributor` on the resource group. | Azure owner |
| Region | One with Foundry Agent Service and MCP tools. Tested: East US, East US 2. | — |
| Model quota | `gpt-5-mini`, GlobalStandard, with enough tokens-per-minute quota (`capacity` in the target file). | Azure owner |
| Role assignment rights | To give users the `Foundry User` role on the Foundry account (`provision.py --steps rbac`). | Owner / User Access Administrator |
| Portal access | Creating MCP connections and the guardrail are portal-only steps (DEPLOYMENT.md step 7). | Foundry project owner |

## Microsoft Entra

| Requirement | Detail | Role |
|---|---|---|
| App registrations | Create two apps: `bev-foundry-passthrough-<env>` (Foundry OAuth identity passthrough, delegated `AzureDatabricks user_impersonation`) and `bev-pricing-regional-sp-<env>` (second persona, client credentials). | Application developer |
| Admin consent | For `AzureDatabricks user_impersonation` on the passthrough app. Most customer tenants require an admin. | Cloud application admin |
| Same tenant | The workspace, Foundry and the users must be in the same Entra tenant for on-behalf-of access. | — |

## Microsoft 365

| Requirement | Detail | Role |
|---|---|---|
| SharePoint / OneDrive licence | The example user needs OneDrive in the same tenant. Sandbox tenants often have no SharePoint licence. | M365 admin |
| Document folder | Upload the three generated files to `BEV_M365_FOLDER` (default `acme-beverages-docs`) in your OneDrive. | Example user |
| Graph consent | Each user connects Microsoft 365 once in Databricks. The connection asks for broad delegated scopes (including mail and write); the Gateway policy limits the agent to one folder. Review the scopes with the security team. | M365 admin + user |

## Your laptop

- Python 3.11+ and `pip install -r requirements.txt` in a virtual environment.
- Databricks CLI with a workspace profile and an account profile.
- Azure CLI logged in to the tenant (`az login --tenant <tenant-id>`).
- Commands that grant permissions (`deploy.sh grants`, `deploy.sh identities`) are best run by you in your own terminal: some coding assistants block permission changes by design.
