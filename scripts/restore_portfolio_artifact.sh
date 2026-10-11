#!/usr/bin/env bash
set -euo pipefail

if [ -s data/paper_portfolio/forward/account.json ]; then
  echo "Portfolio cache already contains the forward account"
  exit 0
fi

if [ -z "${GH_TOKEN:-}" ]; then
  echo "GH_TOKEN is required to restore a portfolio artifact." >&2
  exit 1
fi

target=/tmp/latest-portfolio

while read -r run_id run_number; do
  artifact_names=$(gh api \
    "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/artifacts" \
    --jq '.artifacts[] | select(.expired == false and (.name | startswith("paper-portfolio-state-"))) | .name')

  while read -r artifact_name; do
    if [ -z "$artifact_name" ]; then
      continue
    fi

    rm -rf /tmp/latest-portfolio
    mkdir -p "$target"
    gh run download "$run_id" --name "$artifact_name" --dir "$target"
    account_path=$(find "$target" -type f -name 'account.json' -print -quit)
    if [ -z "$account_path" ]; then
      continue
    fi

    source_dir=$(dirname "$account_path")
    mkdir -p data/paper_portfolio/forward
    cp -R "$source_dir/." data/paper_portfolio/forward/
    echo "Restored forward portfolio from $artifact_name in run $run_id (run number $run_number)"
    exit 0
  done <<< "$artifact_names"
done < <(
  gh api \
    "repos/${GITHUB_REPOSITORY}/actions/workflows/report.yml/runs?status=success&branch=main&per_page=50" \
    --jq '.workflow_runs[] | "\(.id) \(.run_number)"'
)

echo "No prior forward portfolio artifact found; a new account may initialize on this run."
