#!/usr/bin/env bash
set -euo pipefail

branch="${DATA_BACKUP_BRANCH:-data-backups}"
repo_root=$(git rev-parse --show-toplevel)
target=/tmp/discord-finance-data-backup

if git worktree list --porcelain | grep -Fqx "worktree $target"; then
  git worktree remove --force "$target"
fi
rm -rf /tmp/discord-finance-data-backup

if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
  git fetch --quiet origin "$branch"
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git branch --force "$branch" FETCH_HEAD
    git worktree add "$target" "$branch"
  else
    git worktree add --detach "$target" FETCH_HEAD
    git -C "$target" switch -c "$branch"
  fi
else
  git worktree add --detach --no-checkout "$target" HEAD
  git -C "$target" switch --orphan "$branch"
fi

cleanup() {
  git -C "$repo_root" worktree remove --force "$target" >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p "$target/data/paper_portfolio/forward"

for relative_path in \
  data/signals.csv \
  data/signal_outcomes.csv \
  data/signal_errors.csv \
  data/claude_usage.csv; do
  if [ -s "$repo_root/$relative_path" ]; then
    mkdir -p "$target/$(dirname "$relative_path")"
    cp "$repo_root/$relative_path" "$target/$relative_path"
  fi
done

if [ -d "$repo_root/data/paper_portfolio/forward" ]; then
  while IFS= read -r -d '' source_file; do
    filename=$(basename "$source_file")
    cp "$source_file" "$target/data/paper_portfolio/forward/$filename"
  done < <(find "$repo_root/data/paper_portfolio/forward" -maxdepth 1 -type f -print0)
fi

cat > "$target/README.md" <<'EOF'
# Durable Finance Bot Data

This branch is maintained automatically by GitHub Actions.

It stores versioned backups of signal history, outcome data, Claude usage, and
the forward paper-portfolio ledger. It contains no API keys or environment
files. Do not edit generated data manually.
EOF

git -C "$target" config user.name "github-actions[bot]"
git -C "$target" config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git -C "$target" add README.md data/

if git -C "$target" diff --cached --quiet; then
  echo "Durable data backup is already current"
  exit 0
fi

cat > "$target/backup-manifest.json" <<EOF
{
  "backed_up_at_utc": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "source_sha": "${GITHUB_SHA:-$(git -C "$repo_root" rev-parse HEAD)}",
  "workflow_run_id": "${GITHUB_RUN_ID:-local}",
  "workflow_run_number": "${GITHUB_RUN_NUMBER:-local}"
}
EOF
git -C "$target" add backup-manifest.json

git -C "$target" commit -m "Backup finance data from run ${GITHUB_RUN_ID:-local}"
git -C "$target" push origin "HEAD:$branch"
echo "Durable data backup pushed to $branch"
