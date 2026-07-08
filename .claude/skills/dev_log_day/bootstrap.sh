#!/usr/bin/env bash
#
# dev_log_day bootstrap — scaffold today's dev-log day.
#
# Creates docs/dev_log/<YYYYMMDD>/ with the canonical subfolders, seeds the
# sprints/_engineering_requirements.md anchor, and drafts status.md by carrying
# the previous day's status.md forward (re-dated, with a back-link).
#
# Idempotent: never overwrites an existing status.md or _engineering_requirements.md.
#
# Usage:
#   bash bootstrap.sh [YYYYMMDD]    # defaults to host `date +%Y%m%d`
#
set -euo pipefail

# Resolve repo root from this script's location (.claude/skills/dev_log_day/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_DIR="$REPO_ROOT/docs/dev_log"

TODAY="${1:-$(date +%Y%m%d)}"
if ! [[ "$TODAY" =~ ^[0-9]{8}$ ]]; then
  echo "ERROR: date must be YYYYMMDD, got: $TODAY" >&2
  exit 1
fi

DAY_DIR="$LOG_DIR/$TODAY"

# Find the most recent prior day directory that actually has a status.md.
PREV=""
for d in $(ls -1 "$LOG_DIR" 2>/dev/null | grep -E '^[0-9]{8}$' | sort -r); do
  if [[ "$d" < "$TODAY" && -f "$LOG_DIR/$d/status.md" ]]; then
    PREV="$d"
    break
  fi
done

echo "repo_root : $REPO_ROOT"
echo "today     : $TODAY"
echo "prev_day  : ${PREV:-<none found>}"
echo "day_dir   : $DAY_DIR"
echo

# Canonical subfolders.
mkdir -p "$DAY_DIR/done" "$DAY_DIR/reports" "$DAY_DIR/sprints" "$DAY_DIR/walkthrough"
echo "created subfolders: done/ reports/ sprints/ walkthrough/"

# Seed the local engineering-requirements anchor from the previous day (binding,
# restated per sprint dir). Never overwrite.
ENG="$DAY_DIR/sprints/_engineering_requirements.md"
if [[ ! -f "$ENG" && -n "$PREV" && -f "$LOG_DIR/$PREV/sprints/_engineering_requirements.md" ]]; then
  cp "$LOG_DIR/$PREV/sprints/_engineering_requirements.md" "$ENG"
  echo "seeded sprints/_engineering_requirements.md (from $PREV)"
elif [[ -f "$ENG" ]]; then
  echo "kept existing sprints/_engineering_requirements.md"
else
  echo "WARN: no prior _engineering_requirements.md to seed; create it manually" >&2
fi

# Draft status.md by carrying the previous day forward. Never overwrite.
STATUS="$DAY_DIR/status.md"
TODAY_DASHED="${TODAY:0:4}-${TODAY:4:2}-${TODAY:6:2}"
if [[ -f "$STATUS" ]]; then
  echo "kept existing status.md (not overwritten)"
elif [[ -n "$PREV" ]]; then
  {
    echo "# $TODAY_DASHED — Dev day status"
    echo
    echo "> Forward backlog. Planned/unfinished sprints carried from [\`../$PREV/status.md\`](../$PREV/status.md) and earlier; everything **done** stays archived under its dev-day \`done/\`."
    echo "> **Reports (this day):** _none yet._"
    echo
    echo "<!-- DRAFT carried from $PREV — CURATE: drop stale \"Recently done\" blocks, refresh the Sprints table statuses, update Theme + Carry-forward. -->"
    echo
    echo "---"
    echo
    echo "## Theme"
    echo
    echo "_TODO: one paragraph — where the work stands and the next rock._"
    echo
    echo "<!-- Below: Sprints table + Carry-forward carried verbatim from $PREV. Prune DONE rows, refresh statuses. -->"
    echo
    sed '1,/^## Sprints/{ /^## Sprints/!d }' "$LOG_DIR/$PREV/status.md" 2>/dev/null \
      || cat "$LOG_DIR/$PREV/status.md"
  } > "$STATUS"
  echo "drafted status.md (carried from $PREV)"
else
  {
    echo "# $TODAY_DASHED — Dev day status"
    echo
    echo "> Forward backlog. No prior status.md found — start fresh."
    echo
    echo "## Sprints"
    echo
    echo "| # | Sprint | Area | Status |"
    echo "|---|--------|------|--------|"
    echo
    echo "## Carry-forward / open"
    echo
  } > "$STATUS"
  echo "drafted status.md (fresh — no prior day)"
fi

echo
echo "DONE. Next: open $STATUS and curate the draft."