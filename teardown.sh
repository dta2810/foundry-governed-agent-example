#!/usr/bin/env bash
# Remove everything one environment created. Policies are detached first. Default = dry run.
# Usage: ./teardown.sh <target> [--apply] [--keep-foundry-account]
set -euo pipefail
cd "$(dirname "$0")"
[[ $# -lt 1 ]] && { echo "usage: ./teardown.sh <target> [--apply] [--keep-foundry-account]"; exit 1; }
export BEV_TARGET="$1"; shift
APPLY=""; STEPS="policies,foundry_agents,databricks,identities,entra,foundry_account"
for a in "$@"; do
  case "$a" in
    --apply) APPLY="--apply" ;;
    --keep-foundry-account) STEPS="policies,foundry_agents,databricks,identities,entra" ;;
    *) echo "unknown option $a"; exit 1 ;;
  esac
done
"${PYTHON:-python3}" scripts/teardown.py --steps "$STEPS" $APPLY
