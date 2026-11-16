#!/usr/bin/env bash
# One entry point per phase. Phases run in the order below; docs/DEPLOYMENT.md explains each one and the manual steps between them.
# Usage: ./deploy.sh <target> <phase> [--apply] [--with-naive]
#   Without --apply every phase that can, prints what it would do and changes nothing.
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
usage: ./deploy.sh <target> <phase> [--apply] [--with-naive]
phases (in order):
  data        synthetic data + warehouse, schema, tables, functions, row filters, tags, SQL tests   (DEPLOYMENT.md step 3)
  entra       Entra apps, client secrets -> secret scope, workspace SP                              (DEPLOYMENT.md step 4)
  identities  account groups, workspace assignment, members (account admin)                          (DEPLOYMENT.md step 5)
  grants      UC grants + warehouse CAN_USE for the three groups                                      (DEPLOYMENT.md step 6)
  foundry     Foundry account, project, model, RBAC                                                  (DEPLOYMENT.md step 7)
  sharepoint  generate the SharePoint documents; after you upload them, resolve their ids                 (DEPLOYMENT.md step 8)
  policies    Gateway policy functions + attach (scoped to BEV_USER)                            (DEPLOYMENT.md step 9)
  agent       publish the governed agent (+ the naive one with --with-naive)                         (DEPLOYMENT.md step 10)
  traces      policy evidence snapshot, traffic views, traceability dashboard                        (DEPLOYMENT.md step 11)
  smoke       end-to-end smoke tests                                                                 (DEPLOYMENT.md step 12)
USAGE
  exit 1
}

[[ $# -lt 2 ]] && usage
export BEV_TARGET="$1"; PHASE="$2"; shift 2
APPLY=""; NAIVE=""
for a in "$@"; do
  case "$a" in
    --apply) APPLY="--apply" ;;
    --with-naive) NAIVE=1 ;;
    *) usage ;;
  esac
done
[[ -f "targets/$BEV_TARGET.env" ]] || { echo "missing targets/$BEV_TARGET.env (copy targets/example.env)"; exit 1; }
PY="${PYTHON:-python3}"

need_apply() { [[ -n "$APPLY" ]] || { echo "dry run: '$PHASE' calls cloud APIs directly; re-run with --apply"; exit 0; }; }

case "$PHASE" in
  data)
    "$PY" data/generate.py
    "$PY" setup/run_setup.py --steps data $APPLY ;;
  entra)
    need_apply
    "$PY" infra/foundry/provision.py --steps entra,databricks ;;
  identities)
    "$PY" setup/identities.py $APPLY ;;
  grants)
    "$PY" setup/run_setup.py --steps grants $APPLY ;;
  foundry)
    need_apply
    "$PY" infra/foundry/provision.py --steps foundry,rbac ;;
  sharepoint)
    "$PY" data/sharepoint/make_docs.py ${NAIVE:+--with-draft}
    echo "upload data/sharepoint/out/* to your OneDrive folder (BEV_M365_FOLDER), then:"
    if [[ -n "$APPLY" ]]; then "$PY" scripts/resolve_sharepoint.py; else echo "  ./deploy.sh $BEV_TARGET sharepoint --apply"; fi ;;
  policies)
    "$PY" setup/run_setup.py --steps policies $APPLY
    # re-attach after every policy function change: the Gateway binds policies to the function id
    "$PY" setup/policies.py attach $APPLY ;;
  agent)
    if [[ -n "$APPLY" ]]; then
      "$PY" infra/foundry/agent.py --agent infra/foundry/agent.yaml
      if [[ -n "$NAIVE" ]]; then "$PY" infra/foundry/agent.py --agent infra/foundry/agent.naive.yaml; fi
    else
      "$PY" infra/foundry/agent.py --agent infra/foundry/agent.yaml --dry-run
    fi ;;
  traces)
    "$PY" setup/run_setup.py --steps traces $APPLY
    if [[ -n "$APPLY" ]]; then "$PY" scripts/build_dashboard.py --deploy; else "$PY" scripts/build_dashboard.py; fi ;;
  smoke)
    "$PY" scripts/smoke_test.py ${NAIVE:+--with-naive} ;;
  *) usage ;;
esac
