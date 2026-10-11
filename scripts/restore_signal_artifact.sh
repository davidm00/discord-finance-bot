#!/usr/bin/env bash
set -euo pipefail

if [ -s data/signals.csv ]; then
  echo "Signal cache already contains data/signals.csv"
  exit 0
fi

if [ -z "${GH_TOKEN:-}" ]; then
  echo "GH_TOKEN is required to restore a signal artifact." >&2
  exit 1
fi

target=/tmp/latest-signals
found=false

while read -r run_id run_number; do
  artifact_name=$(gh api \
    "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/artifacts" \
    --jq '[.artifacts[] | select(.expired == false and (.name | startswith("signals-csv")) and .size_in_bytes > 10000)][0].name // empty')

  if [ -z "$artifact_name" ]; then
    continue
  fi

  rm -rf /tmp/latest-signals
  mkdir -p "$target"
  gh run download "$run_id" --name "$artifact_name" --dir "$target"
  if [ ! -s "$target/signals.csv" ]; then
    continue
  fi

  mkdir -p data
  for filename in signals.csv signal_outcomes.csv signal_errors.csv claude_usage.csv; do
    if [ -s "$target/$filename" ]; then
      cp "$target/$filename" "data/$filename"
    fi
  done
  echo "Using $artifact_name from workflow run $run_id (run number $run_number)"
  found=true
  break
done < <(
  gh api \
    "repos/${GITHUB_REPOSITORY}/actions/workflows/report.yml/runs?status=success&branch=main&per_page=50" \
    --jq '.workflow_runs[] | "\(.id) \(.run_number)"'
)

if [ "$found" != "true" ]; then
  echo "No non-empty signal artifact was found in the latest 50 successful report runs." >&2
  exit 1
fi
