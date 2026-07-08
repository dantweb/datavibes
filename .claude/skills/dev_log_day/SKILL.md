---
name: dev_log_day
description: Scaffold today's dev-log day under docs/dev_log/<YYYYMMDD>/ — create the canonical subfolders (done/ reports/ sprints/ walkthrough/), seed the sprints/_engineering_requirements.md anchor, and draft status.md by carrying the previous day's backlog forward. Use when the user asks to "start the dev log", "create today's dev log / day log", "roll the dev log forward", or invokes /dev_log_day.
---

# dev_log_day

Bootstraps the day-log structure this repo uses under `docs/dev_log/YYYYMMDD/`,
then curates the carried-forward `status.md` into a clean draft.

## Layout this produces

```
docs/dev_log/<YYYYMMDD>/
├── status.md                         # forward backlog (carried from the last day that had one)
├── done/                             # finished sprint docs get moved here
├── reports/                          # per-feature reports authored during the day
├── sprints/                          # planned/active sprint docs
│   └── _engineering_requirements.md  # binding eng-req anchor (seeded from the previous day)
└── walkthrough/                      # screenshots / HTML walkthroughs / proof scripts
```

## Steps

1. **Run the bootstrap** (idempotent — never overwrites an existing `status.md`
   or `_engineering_requirements.md`):

   ```bash
   bash .claude/skills/dev_log_day/bootstrap.sh
   ```

   Pass an explicit `YYYYMMDD` as the first arg to backfill a specific day.
   It prints the resolved `today`, the `prev_day` it carried from, and what it
   created. If it reports `prev_day: <none found>` you get a fresh empty
   `status.md` skeleton instead of a carried draft.

2. **Curate the drafted `status.md`.** The bootstrap copies the previous day's
   `## Sprints` table and `## Carry-forward` section verbatim and marks them
   with `<!-- ... prune me -->` comments. Edit the new file to:
   - Update the H1 to today's date and keep the back-link blockquote.
   - **Drop the previous day's "Recently done" blocks** from the intro (they
     belong to that day). Add fresh `> **🟢 Recently done (<date>):**` lines
     only for work actually finished — grounded in commits / the working tree,
     not guessed.
   - **Prune the Sprints table:** remove rows whose sprint shipped (its doc
     moves to `done/`), refresh statuses, keep PLANNED/in-progress rows.
   - Rewrite `## Theme` to one honest paragraph on where things stand.
   - Trim `## Carry-forward / open` to still-open items; update the
     `## Dev-stack note` if the local stack state changed.
   - Remove the `<!-- ... -->` curation markers when done.

3. **Do not invent progress.** Before writing any "Recently done" or status
   change, check `git log` / `git status` and the relevant `done/` vs `sprints/`
   docs. If nothing shipped today, the day starts as a pure carry-forward — say
   so rather than fabricating accomplishments.

## Notes

- `done/`, `reports/`, `walkthrough/` are created empty; that is expected — they
  fill as the day's work lands. Empty dirs aren't tracked by git until they hold
  a file, which is fine for a freshly-started day.
- The engineering-requirements anchor is **binding** and must be restated /
  linked from every sprint doc created under `sprints/` (TDD-first · DevOps-first
  · SOLID · DI · DRY · Liskov · clean code · NO OVERENGINEERING, guarded by
  `bin/pre-commit-check.sh`).
- This skill only scaffolds + drafts docs. It does not commit anything.