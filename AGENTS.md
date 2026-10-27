# AGENTS.md

Guide for agents working in this repo. The full rules are in [CLAUDE.md](CLAUDE.md); this file does not duplicate them. Setup steps and the annotated folder tree are in
[README.md](README.md#repository-layout-standard-folder-structure). This file is in English; the rest of the repo (docs, notebooks, docstrings, CLI messages) is in Vietnamese.

## Start here

1. Read [CLAUDE.md](CLAUDE.md): the Invariant rules, the Approved decisions and the mandatory stop points override everything else.
2. **Check the standard folders before doing anything** (read-only preflight; the full contract is in CLAUDE.md → "Fresh-clone setup"):

   ```bash
   ls dataset outputs 2>&1
   for f in dataset/TIeventlogBug.csv dataset/TIeventlogStory.csv; do [ -f "$f" ] || echo "MISSING: $f"; done
   ```

   - **Where the dataset goes:** exactly `<repo root>/dataset/TIeventlogBug.csv` and `<repo root>/dataset/TIeventlogStory.csv`. `dataset/` is git-ignored, so a
     fresh clone does not have it. **The user provides these files (Zenodo record 8275679). Never download, replace or modify them yourself; if one is missing, stop and ask the
     user to copy it into `dataset/`.** You may create the *empty* `dataset/` folder so the user sees where the files go.
   - `outputs/runs/*` is git-ignored too. Regenerate artifacts only with the `jira-ad` commands, into new folders, never over an existing run, and only what the task needs.
3. On a **fresh clone**, then follow CLAUDE.md → "Fresh-clone setup" (full steps: README → "Setup from scratch"). In short:
   - Install: `uv sync --locked --all-extras --group dev` (the `process` extra brings pm4py; Graphviz `dot` is optional).
   - Verify: SHA-256 of the two CSVs (values in README) → `uv run jira-ad audit --config configs/baseline.yaml` → `uv run pytest -q` → `uv run ruff check src tests scripts`.
   - To re-run phase 2: `jira-ad run` (V1 run) → `jira-ad improve` only if `outputs/improvement/*-bb0fee9a` is missing → edit the two `paths.*` lines of
     `configs/process.yaml` → `jira-ad process`. To only read phase 2 results, a completed `outputs/process/<run>` is enough (no dataset, no V1 run).

## Folder map

```
<repo root>/
├── pyproject.toml  uv.lock  .python-version
├── configs/    LOCKED: baseline, actions, experiments, improvement_plan · others: improvements, smoke, process
├── dataset/    [YOU provide] ◀ TIeventlogBug.csv + TIeventlogStory.csv · read-only · git-ignored
├── src/jira_ad/  all logic        tests/  test_<module>.py        notebooks/  01–06 phase 1 · 07–12 phase 2
├── docs/       reports, PROGRESS, DECISIONS, superpowers/          scripts/
├── .venv/      [uv sync]
└── outputs/    append-only · analysis/ prepared/ improvement/ process/ · runs/ (git-ignored)
```

## Pointers

- **Spec + plan (the single deciding source):** [docs/superpowers/2026-10-16-jira-ad.md](docs/superpowers/2026-10-16-jira-ad.md); improvement-phase plan:
  [docs/superpowers/plans/2026-10-22-cai-tien-mo-hinh.md](docs/superpowers/plans/2026-10-22-cai-tien-mo-hinh.md).
- **Progress, evidence, Rulings, risks:** [docs/PROGRESS.md](docs/PROGRESS.md). When they conflict, the spec wins.
- **Phase 2 (course project):** plan [docs/superpowers/plans/2026-10-26-do-an-mon-hoc.md](docs/superpowers/plans/2026-10-26-do-an-mon-hoc.md), report
  [docs/BAO_CAO_MON_HOC.md](docs/BAO_CAO_MON_HOC.md); the approved decisions are in CLAUDE.md.
- **Phase 1 reports:** [docs/BAO_CAO_TONG_KET.md](docs/BAO_CAO_TONG_KET.md) (summary), [docs/BAO_CAO.md](docs/BAO_CAO.md) (V1),
  [docs/BAO_CAO_CAI_TIEN.md](docs/BAO_CAO_CAI_TIEN.md) (improvement).
- **Check commands:** `uv run pytest -q` and `uv run ruff check src tests scripts`.
