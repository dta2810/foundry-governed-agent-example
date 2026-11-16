# Operations

Teardown, known gotchas and the security checklist for a deployed environment.

## Teardown

```bash
./teardown.sh env1            # dry run: lists what it would delete
./teardown.sh env1 --apply    # add --keep-foundry-account to keep the account
```

Order:
1. detach this environment's policies (first: dropping a policy function's schema while attached blocks the service for everyone; the schema step refuses to run while they are attached);
2. delete this environment's Foundry agents and toolboxes;
3. drop both schemas and trash the dashboard;
4. delete the warehouse, secret scope and workspace SP;
5. delete the account groups (only if their members are this environment's identities) and both Entra apps (only if tagged by this environment);
6. delete the Foundry account.

A deleted Foundry account is soft-deleted. Purge it to reuse the name. Delete the MCP connections in the portal if you keep the account, and remove the SharePoint files yourself.

## Gotchas

| Symptom | Cause / fix |
|---|---|
| `303` or a login page from `/ai-gateway` | You used a vanity host. Use `adb-<id>.<n>.azuredatabricks.net`. |
| Every call to a Gateway service fails with "…has been deleted or replaced" | A policy function was replaced. Run `setup/policies.py attach --apply`. |
| Agent SQL runs on an unexpected warehouse | Foundry sends no `warehouse_id`. Keep `CAN_USE` for the three groups on the dedicated warehouse only. |
| Foundry asks for approval on every tool call | `require_approval.never` needs the real `<toolbox>___<tool>` names (the templates do this). |
| Gateway DENY shows as `tool_user_error` in Foundry | Expected: Foundry does not show the policy reason. The dashboard does. |
| Foundry tool guardrails did not stop an MCP call | Foundry tool-call/tool-response checks do not cover MCP tools. The Gateway policy is the control. |
| `read_resource` 404 on `/me/drive/items/{id}/content` | Use `/drives/{driveId}/items/{id}/content` (the agent template does). |
| "policy … exists with handler …" or "group … already exists with other members" | Another environment uses your `BEV_ENV`. Pick a unique suffix. |
| Tag errors in the `tags` step | An account tag policy restricts values. Adjust `BEV_TAGS`; the step continues past errors. |
| Regional SP gets `403` on SQL | The workspace SP needs the `databricks-sql-access` entitlement and membership in the west group. |
| A `post_call` DENY still ran the SQL | Result-phase checks run after execution. Use request-phase policies to prevent writes. |

## Security checklist (before you share a deployment)

- [ ] The schema owner is not `BEV_USER` (or you accept that the policy is the only write barrier for that user).
- [ ] No personal access tokens anywhere. Users act through OAuth passthrough. Client secrets live only in the secret scope (stored through the SDK, never on a command line), valid 90 days; `--rotate` removes the old ones.
- [ ] The three groups hold `EXECUTE` on governed functions + `SELECT` on the metric view only. Running `deploy.sh grants` again restores this.
- [ ] `CAN_USE` on the dedicated warehouse only.
- [ ] Policies are scoped to the example identities and attached only while in use. They are detached in teardown.
- [ ] The Microsoft 365 connection's Graph scopes were reviewed with the tenant's security team. The policy limits the agent to one folder.
- [ ] The unguarded agent and the injected draft document are deleted when no longer needed.
- [ ] `targets/*.env`, `*.resolved.env` and `*.foundry.yml` stay out of version control (gitignored).
- [ ] The dashboard is published without embedded credentials.

## Policy windows (attach only while in use)

Gateway policies on `system.ai.*` services are metastore-wide. They are scoped to the example identities, but keep them attached only while you use them:

```bash
BEV_TARGET=env1 python setup/policies.py status
BEV_TARGET=env1 python setup/policies.py attach --apply    # before use (also after any policy function change)
BEV_TARGET=env1 python setup/policies.py detach --apply    # when done
```
