"""Account-level identities (needs an account admin profile, BEV_ACCOUNT_PROFILE).

Creates the three groups, assigns them to the workspace and adds members:
  admin group <- the example user (sees every market)
  west group  <- the regional service principal (sees four markets: CA, TX, AZ, IL)
Run after infra/foundry/provision.py (it creates the regional SP). Idempotent. Default = dry run.
Usage: BEV_TARGET=<target> python setup/identities.py [--apply]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--adopt", action="store_true", help="reuse a same-name group that has other members (normally refused)")
    a_ = ap.parse_args()
    apply = a_.apply
    C.require("ACCOUNT_PROFILE", "WORKSPACE_ID", "USER", "REGIONAL_SP_APP_ID")
    from databricks.sdk import AccountClient
    from databricks.sdk.service import iam
    a = AccountClient(profile=C.ACCOUNT_PROFILE)

    user = next(iter(a.users.list(filter=f'userName eq "{C.USER}"')), None)
    sp = next(iter(a.service_principals.list(filter=f'applicationId eq "{C.REGIONAL_SP_APP_ID}"')), None)
    if not user or not sp:
        sys.exit(f"not found in the account: {'user ' if not user else ''}{'regional SP (run provision.py first)' if not sp else ''}")
    members = {C.GROUP_ADMIN: [user.id], C.GROUP_EAST: [], C.GROUP_WEST: [sp.id]}

    for name, want in members.items():
        g = next((x for x in a.groups.list(filter=f'displayName eq "{name}"') if x.display_name == name), None)
        g = a.groups.get(g.id) if g else None
        have = {m.value for m in (g.members or [])} if g else set()
        # account groups are shared: a same-name group with other members belongs to someone else (it would get our markets)
        foreign = have - {user.id, sp.id}
        if foreign and not a_.adopt:
            sys.exit(f"group {name} already exists with {len(foreign)} other member(s): pick a unique BEV_ENV (or --adopt)")
        print(f"group {name}: {'exists' if g else 'create'}; members +{want}; workspace {C.WORKSPACE_ID} USER")
        if not apply:
            continue
        g = g or a.groups.create(display_name=name)
        add = [{"value": m} for m in want if m not in have]
        if add:
            a.groups.patch(id=g.id, operations=[iam.Patch(op=iam.PatchOp.ADD, path="members", value=add)],
                           schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP])
        a.workspace_assignment.update(workspace_id=int(C.WORKSPACE_ID), principal_id=int(g.id),
                                      permissions=[iam.WorkspacePermission.USER])
    if not apply:
        print("dry run: add --apply to write")


if __name__ == "__main__":
    main()
