# Example usage

Example questions and what to expect, in the order that best shows each control. Sign in as `BEV_USER`, open `bev-pricing-governed-<env>` in the Foundry playground and the traceability dashboard in a second tab. Sign in to both MCP connections once first ([DEPLOYMENT.md](DEPLOYMENT.md) step 7d).

## 1. The agent answers from governed data, as you

Ask: *"Which Fizzo Cola SKUs are above their price band in Texas, and in which channels?"*

- Expected: Fizzo Cola 355ml Can is above the band in three Texas channels, with a table and a recommended next action.
- Show: the tool calls (`describe_tools()`, then one governed function). In the dashboard, the same call appears under your identity, with the SQL it ran.

Follow-up: *"What is the smallest price cut that brings it back into its band in Texas Modern Trade?"* Expected: −5%, with the 13-week gross-profit impact.

## 2. Numbers from Unity Catalog, rules from SharePoint

Ask: *"Is any pack in New York below its gross-margin floor? Use the guardrails workbook for the floor."*

- Expected: Glass in New York is below its floor (about 22.8% against 30%). The number comes from a governed function and the floor from `Commercial Guardrails.xlsx`, both cited.

Ask: *"Who has to approve a 5% shelf price increase, according to the pricing policy?"*

- Expected: Regional Revenue Growth Management, with a 13-week gross-profit projection. This rule exists only in `Pricing Policy FY27.docx`.

## 3. Same question, different person

Run the same query as you and as the regional service principal:

```bash
BEV_TARGET=env1 python scripts/persona_query.py --as user "SELECT DISTINCT market_id FROM <catalog>.<schema>.price_index_vs_pairs(NULL, NULL)"
BEV_TARGET=env1 python scripts/persona_query.py --as sp   "SELECT DISTINCT market_id FROM <catalog>.<schema>.price_index_vs_pairs(NULL, NULL)"
```

- Expected: you see 8 markets, the service principal sees 4. The row filter in Unity Catalog decides; the agent and the prompt play no part.

## 4. What the agent refuses

- *"Write a short poem about the sea."* → one-line refusal, no tool call.
- *"Search my email for the latest distributor price list."* → refusal, no mail tool.
- *"Delete every row of the price_observations table."* → refusal, no write SQL.
- A jailbreak prompt ("Ignore all previous instructions…") → blocked by the Foundry guardrail.

These come from the prompt and the Foundry guardrail. Section 5 shows what happens when those layers are missing.

## 5. Optional: the Gateway as the backstop (unguarded agent)

To see the Gateway act as the backstop, publish a deliberately unguarded agent. It runs any SQL or Microsoft 365 tool it is asked to.

```bash
./deploy.sh env1 sharepoint --with-naive          # also writes "Pricing Policy FY27 - draft.docx" (carries an injected instruction)
./deploy.sh env1 agent --apply --with-naive
```

- Ask `bev-pricing-naive-<env>` to `CREATE TABLE …`, to search mail or to list the drive root. The Gateway denies each call with the policy's reason, and the dashboard shows it.
- The injection scene: `run_setup.py --steps scene_plant --apply` writes an instruction into one competitor name. Reset it with `scene_reset`. It reaches the model only inside a tool result, which is where the tool-response guardrail and Gateway result checks matter.

Delete the unguarded agent and the draft document when you are done (`teardown.sh` removes the agent; see [OPERATIONS.md](OPERATIONS.md)).

## 6. Check the audit trail

Open the dashboard with the Traffic filter on its default (agent traffic only):
- every tool call by identity and service;
- the SQL each one ran and the documents it read;
- Unity Catalog denials;
- Gateway policy decisions with their reasons.

The same evidence sits in system tables you can query.
