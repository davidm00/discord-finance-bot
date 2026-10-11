#!/usr/bin/env bash
set -euo pipefail

branch="${DATA_BACKUP_BRANCH:-data-backups}"

if ! git fetch --quiet origin "$branch"; then
  echo "No durable data branch found yet"
  exit 0
fi

backup_ref=FETCH_HEAD

if [ ! -s data/signals.csv ]; then
  mkdir -p data
  for relative_path in \
    data/signals.csv \
    data/signal_outcomes.csv \
    data/signal_errors.csv \
    data/claude_usage.csv; do
    if git cat-file -e "$backup_ref:$relative_path" 2>/dev/null; then
      temp_path="$relative_path.tmp"
      git show "$backup_ref:$relative_path" > "$temp_path"
      mv "$temp_path" "$relative_path"
    fi
  done
  if [ -s data/signals.csv ]; then
    echo "Restored signal history from $branch"
  fi
fi

if [ ! -s data/paper_portfolio/forward/account.json ] \
  && git cat-file -e "$backup_ref:data/paper_portfolio/forward/account.json" 2>/dev/null; then
  git archive "$backup_ref" data/paper_portfolio/forward | tar -xf -
  echo "Restored forward paper portfolio from $branch"
fi
