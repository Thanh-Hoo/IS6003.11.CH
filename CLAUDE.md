# CLAUDE.md

Master's thesis on the Jira event log in `dataset/`, in two phases:

- **Phase 1 (V1 + improvements, Tasks 1–18, done):** detect unusual Jira handling cases (Node2Vec + Isolation Forest, M_markov).
- **Phase 2 (in progress, Task 19 onwards):** the course project for **Advanced Enterprise Resource Planning** (Vietnamese: *Hoạch định nguồn lực doanh nghiệp nâng cao*) —
  apply the knowledge of the 6 lectures to the data, reusing phase 1 as much as possible.

> **Language and cross-references.** This file, `README.md` and `AGENTS.md` are in English; the rest of the repo (docs, notebooks, docstrings,
> CLI messages, YAML comments) is in Vietnamese. Vietnamese documents and code cite items of this file by their Vietnamese names:
> "Quyết định N" = Decision N, "điểm dừng N" = stop point N, "Quy tắc bất biến" = Invariant rules,
> "Quyết định đã duyệt" = Approved decisions, "Ruling N" = Ruling N (an agent decision recorded in `docs/PROGRESS.md` and `docs/DECISIONS.md`).

## Read before working

- **Phase 1 spec (the deciding source for Tasks 1–18):** [docs/superpowers/2026-10-16-jira-ad.md](docs/superpowers/2026-10-16-jira-ad.md)
- **Phase 2 plan (the deciding source for Task 19+):** [docs/superpowers/plans/2026-10-26-do-an-mon-hoc.md](docs/superpowers/plans/2026-10-26-do-an-mon-hoc.md)
- **Progress, verification evidence, Rulings, risks:** [docs/PROGRESS.md](docs/PROGRESS.md); decisions outside the plan: [docs/DECISIONS.md](docs/DECISIONS.md)
- **Setup, folder layout, commands for humans:** [README.md](README.md)

Do not copy rules from the spec/plans into this file. Priority order in case of conflict: **the "Approved decisions" section below > the phase 2 plan >
the phase 1 spec** (the phase 1 spec still wins for everything that belongs to Tasks 1–18).

## Invariant rules (both phases)

- `dataset/` is **read-only**: do not edit, rename, move, overwrite or re-download it.
- **Do not edit** `configs/baseline.yaml`, `configs/actions.yaml`, `configs/experiments.yaml`, `configs/improvement_plan.yaml`, nor any run that already
  exists in `outputs/runs/`, `outputs/improvement/`. The locked hashes must stay unchanged (re-check at the end of each task).
- The unit of analysis is the **issue (trace)**. Models that learn (graph, embedding, Markov) are **fitted on train only**; the phase 2 process
  description analysis (no learning step) may use all 161 issues.
- There are no real anomaly labels: do not invent labels, do not hard-code metrics, do not claim results that have not been measured.
- Parameters, paths, seeds and thresholds live in YAML (`configs/`); algorithms live in `src/jira_ad/`.

## Repository layout

Compact version; the annotated tree is in [README.md](README.md#repository-layout-standard-folder-structure). Paths in YAML are relative to the repo
root (the nearest directory containing `pyproject.toml`).

```
pyproject.toml  uv.lock  .python-version   package `jira-ad`, locked deps, Python 3.12 (supported 3.11–3.12)
configs/      baseline|actions|experiments|improvement_plan.yaml = LOCKED; improvements|smoke|process.yaml
dataset/      NOT in Git · read-only · provided by the user (TIeventlogBug.csv, TIeventlogStory.csv required)
src/jira_ad/  all logic: 34 modules + __init__.py (phase 1 and phase 2, flat)
tests/        test_<module>.py per module + conftest.py + helpers.py
notebooks/    01–06 phase 1 (need a V1 run) · 07–12 phase 2 (need a process run)
scripts/      execute_notebooks.py (wrapper of `jira-ad notebooks`)
docs/         reports, PROGRESS.md, DECISIONS.md, RESEARCH_NOTES.md, superpowers/{spec,plans}, figures/
outputs/      NOT in Git · generated · append-only: analysis/, prepared/, runs/, improvement/, process/<UTC>-<hash8>/
```

## Fresh-clone setup (read before running anything on a new checkout or machine)

The human-readable steps are in README, section "Setup from scratch". Rules for agents:

1. **Look before acting.** Run `ls dataset outputs`. Both folders are ignored by Git, so a fresh clone has neither.
2. **The dataset is provided by the user.** Never download, replace or regenerate it (see Invariant rules). If `dataset/TIeventlogBug.csv` or
   `dataset/TIeventlogStory.csv` is missing, **stop and ask the user** to place the files (source, for the user: Zenodo record 8275679). Once they are
   there, verify them before any analysis:
   - `shasum -a 256 dataset/TIeventlogBug.csv dataset/TIeventlogStory.csv` must give the SHA-256 values listed in README (they are the values
     recorded in the manifest of every existing run);
   - `uv run jira-ad audit --config configs/baseline.yaml` expects 5,126 events / 161 issues (bug) and 4,439 / 182 (story) and prints any difference.
   A mismatch is a data problem: stop and report it; do not edit configs to make it pass.
3. **Install from the lock:** `uv sync --locked --all-extras --group dev`. Plain `pip install -e '.[notebook,dev]'` lacks pm4py (extra `process`),
   which phase 2 step C needs (Decision 1). Do not change numpy/pandas versions. Graphviz `dot` is optional (without it only `.dot` files are written).
4. **A missing `outputs/` is normal.** Regenerate it with new folders only (never overwrite), in this order:
   `jira-ad run --config configs/baseline.yaml` → `jira-ad improve --plan configs/improvement_plan.yaml` → `jira-ad process --config configs/process.yaml`.
   `configs/process.yaml` hard-codes the author's timestamped folders in `paths.v1_run` and `paths.improvement_dir`; before `process`, change **only those
   two lines** to the folders just created. This is a setup step, not a stop point; record it as a new Ruling in `docs/PROGRESS.md` and `docs/DECISIONS.md`.
5. **A phase 2 run made without those two folders is degraded:** step E silently drops the Node2Vec comparison and the `M_markov` dimension (see
   `e_ranking/status.json`). Never present its ranking numbers as thesis results.
6. **Setup is done when** `uv run pytest -q` passes, `uv run ruff check src tests scripts` is clean, and the locked hashes are unchanged (see Commands).
   Existing reports quote the author's run `outputs/process/20261026T025412Z-399b0a40`; a regenerated run has a different timestamp and, because the two
   path lines changed, a different `<hash8>`.

## Phase 2 context

**Assignment premise:** the data in `dataset/` is real data of a software-bug-handling team at the author's company.

**Topic:** *Analysis, verification and redesign of the software bug-handling process based on a Jira event log.*

**Four management questions (every chapter must serve at least one):**
1. How does the process actually run?
2. Where does the time go, and which resource (role) is the bottleneck?
3. How many cases deviate from the standard process, and where?
4. How should it be redesigned, and which KPIs measure the effect?

**Mapping lecture → thesis chapter:**

| Lecture | Knowledge | Thesis chapter |
|---|---|---|
| B1 | Work System, BPMN 2.0 (pool/lane/gateway) | Ch1: Work System of the bug process, standard BPMN |
| B2 | CT = PT + WT, CTE, Little, capacity, FPY | Ch2: quantitative analysis |
| B3 | Event log, on-time/late norms, DFG, centrality | Ch3: norms, lateness by state/role/case, centrality measures |
| B4 | BPR, AS-IS/TO-BE, Ford/Mazda, KPI | Ch4: redesign, what-if, KPI table |
| B5 | Alpha/Heuristics/Inductive Miner, Petri net, token replay | Ch5: AS-IS discovery, conformance checking |
| B6 | Node2Vec/Graph2Vec | Ch6: reuse of V1 + review-priority ranking |

**Measured data facts (no need to re-measure; use them as cross-checks):** 161 bugs (83 DONE, 78 Rejected), 5,126 events, 43.5% of events by bots,
30 variants at status level, 22 `CREATE → Rejected` cases, 22 cases skipping the investigation phase, every DONE case passes through `In Test`,
165/553 status changes are less than 60 seconds apart, timestamps carry offsets −0700/−0800. The out-of-fold scores of the 161 cases are available in
`cv_original_scores.csv` of `outputs/improvement/20261022T151529Z-bb0fee9a/`.

## Approved decisions (phase 2)

1. **pm4py:** may be added as the extra `process` (edit `pyproject.toml`, `uv lock`). Do not change the existing numpy/pandas versions. The first step is a
   throw-away trial on pandas 3.0. If pm4py fails: **stop and report**, with 2–3 options (for example a separate venv for pm4py, or a minimal hand-written
   Alpha/replay); do not change the approach on your own.
2. **Classifying states as "work"/"wait":**
   - **Main option:** work = `In Progress`, `In Test`; wait = `Inbox`, `To Investigate`, `INVESTIGATED`, `To Do`. Reason: in Jira, "To …" states are queues;
     the log has no "Investigating" state, so the real investigation time cannot be measured.
   - **Mandatory sensitivity:** recompute with `To Investigate` as "work" (the agent's original proposal). Report PT, WT, CTE as an **interval** between the two
     options, plus the extra interval caused by back-fill updates.
3. **Norms:** the company has **no official SLA**. Use a statistical norm = the 0.75 percentile of historical dwell per state (working days), and keep the
   threshold in the config so that a real SLA can replace it. The report must say that the norm is interpolated from history.
4. **Conformance:** the three default proposed rules are **not enough**. Two rules always hold by how the data is built (every DONE case passes through In Test;
   the core view keeps only cases ending at DONE/Rejected) and the remaining one is almost trivial. Replace them with:
   - **Reference model** as a list of allowed arcs between states (Inbox → To Investigate → INVESTIGATED → To Do → In Progress → In Test → DONE; an XOR branch to
     `Rejected` from the states before `In Progress`; the loop `In Test → In Progress`). Token replay against the Petri net of this model.
   - **Flag rules (count, do not conclude a fault):** skipped investigation phase; direct `CREATE → Rejected`; `Rejected` after `In Progress` (abandoned effort);
     reopened after `DONE`; moved back to `Inbox` from a later state; entering `In Progress` without passing `To Do`; status changes inside a back-fill update burst.
   - If a rule yields 0 violating cases, report that as a **result** (the process is followed at that point); do not delete the rule.
   - The reference model is the **author's assumption**; show it to the user once before running the replay (see stop points).
5. **Graph2Vec:** **cut** from the main scope (161 small graphs, low value). Only write one "future work" paragraph in Ch6. Do it only if every other task is done
   and time remains.
6. **Report:** Markdown `docs/BAO_CAO_MON_HOC.md`; convert to Word/PDF later.
7. **Working days:** use the local date taken from `timestamp_raw` (the original offset) as the main option; UTC as sensitivity. Do not guess other timezones.
8. **Reference model (approved 26/10):** option (a) — keep assumption A1 (CREATE is an implicit entry to Inbox) and the list of arcs in `configs/process.yaml`,
   section `reference_model`. Additionally run a side replay with a "fast track" model = reference + `CREATE → To Do`, clearly marked as a **TO-BE candidate for Ch4**,
   not the reference model. Keep the arc `To Investigate → Rejected` even though it occurs 0 times.
9. **Notebooks are mandatory** for every phase 2 task (see "Mandatory notebooks"). You may edit the tests that lock the notebook count.

## Self-driven workflow (phase 2)

The agent carries out the tasks of the phase 2 plan sequentially and **does not ask between tasks**, except at the **mandatory stop points** below.
Order and minimum content:

| Step | Content | Main output |
|---|---|---|
| A. Status log + quantitative (Ch2) | Status log with a back-fill flag; dwell per state × DONE/Rejected (calendar days, working days); CT/PT/WT/CTE (intervals); Little per week (λ, throughput, measured WIP vs λ×CT); FPY, Rejected rate, issue-days consumed before Rejected; number of state changes by role and target state ("gate" roles); put Story next to Bug, do not mix | AS-IS KPI table |
| B. Norms + centrality (Ch3) | On-time/late against the norm by state, role (the role that moves out of the state) and case; top lateness events; centrality on the state DFG and the train activity DFG (degree in/out, betweenness, undirected closeness, eigenvector, PageRank d=0.85); centrality × delay table | Priority list for improvement, with evidence |
| C. Reference model + discovery + conformance (Ch1, Ch5) | Work System table with 8 components (each cell cites a real field/role); standard BPMN (.bpmn + figure); Petri net; Alpha/Heuristics/Inductive discovery on the status log, compare fitness/precision/generalization/simplicity; token replay per case; count the rule flags; enhancement (waiting time on arcs) | Mean fitness, % perfectly fitting cases, top deviations with issueKey |
| D. BPR (Ch4) | Table problem → evidence → heuristic; verify (true/false) the candidates: early check at Inbox, automatic state change from commit/MR, merge INVESTIGATED–To Do, reduce PO dependency, early duplicate detection; what-if recomputed on the log; AS-IS (measured) / TO-BE (target) KPI table; TO-BE BPMN; pilot plan | KPI table, TO-BE diagram |
| E. Representation learning + ranking (Ch6) | Use the embedding of run `20261017T081309Z-930f8a85` (do not refit): K-means K=2..6 + silhouette, ARI/NMI against the business groups of activities; compare Node2Vec with in/out degree + centrality on the same problem, with a majority-class baseline; multi-dimensional anomaly profile (conformance flags, number of late states, state regressions/reopens, assignee changes, back-fill bursts, length-adjusted M_markov surprisal, percentile within the DONE/Rejected × length group) → rank by the number of dimensions above p90; stability check (bootstrap top-k Jaccard), correlation with length/branch; blind table of 15 top + 15 random **for the user to review by hand** | Top 10% with reasons in words |
| F. Report + summary notebook | `docs/BAO_CAO_MON_HOC.md`; notebook `12_summary_report.ipynb` gathers KPIs and conclusions from notebooks 07–11; automatically cross-check every number in the report against the artifacts | Complete report |
| G. Independent review | Launch **one independent reviewer subagent** (the user has authorised it here) to check: figures recomputed with raw pandas without importing `jira_ad`; consistent definitions of PT/WT/norm; no TO-BE number presented as a measured result; every BPR proposal has evidence; BPMN ↔ Petri net and replay are right. The reviewer only reports, the agent fixes | List of fixed / unfixed items in PROGRESS |

### Mandatory notebooks

Each of steps A–E is **not considered done** until the notebook of that step has been created, run successfully and the executed copy saved. Do not leave
notebooks to the end.

| Step | Notebook | Lecture |
|---|---|---|
| A | `notebooks/07_quantitative.ipynb` | B2 |
| B | `notebooks/08_norms_centrality.ipynb` | B3 |
| C | `notebooks/09_conformance.ipynb` | B1 + B5 |
| D | `notebooks/10_bpr.ipynb` | B4 |
| E | `notebooks/11_ranking.ipynb` | B6 |
| F | `notebooks/12_summary_report.ipynb` | summary |

Structure of each notebook (in this order):
1. **Goal and lectures applied** (1 paragraph): which management question, which knowledge.
2. **Inputs**: which run in `outputs/process/`, config and hash; use a loader with a fingerprint check like `open_run`.
3. **Data and assumptions**: the chapter's assumptions (approximate PT/WT, back-fill, bots, role level).
4. **Results**: main tables and figures. The notebook **only reads artifacts and calls functions in `src/jira_ad/`**; do not rewrite calculation logic in cells.
5. **Research process**: what was tried, changed and why (point to the Ruling), including negative results and fixed errors (for example Ruling 80).
6. **Remarks generated from the numbers** (no hand-written numbers).
7. **Assumptions, limits, next steps.**

Run rules:
- Run with nbclient in the `.venv` kernel (extend `jira-ad notebooks` or an equivalent command for `outputs/process/<run>`), `allow_errors=False`, with a timeout.
- Save the executed copy next to the run (for example `outputs/process/<run>/notebooks_executed/`); the source in `notebooks/` is saved without output.
- It must open by hand in VSCode/Jupyter without setting environment variables (auto-pick the newest `process` run that matches the current config, as in Ruling 63).
- Tests: each notebook has a test that really runs on a small run; update the test that locks exactly 6 notebooks to the new notebook list.
- A progress report after each task must name the path of the executed notebook.

### Mandatory stop points (stop only here)

1. pm4py cannot run (Decision 1).
2. **Before running token replay:** present the reference model (list of arcs + diagram + which parts are assumptions) **once**, and wait for approval.
3. A result that changes the main story of the thesis (for example fitness close to 1.0 so that Ch5 has no deviations left to discuss; or data that contradicts the
   "measured data facts" above).
4. Having to edit a file forbidden by the Invariant rules, delete an artifact, or make a large change outside the plan.
5. Steps A–G are finished.

Outside these points: decide on your own, write a new Ruling in PROGRESS + DECISIONS (decision — reason — cost if wrong), then continue.

### Result presentation standards (phase 2)

- Every number in the report comes from code that was actually run; after writing the report, cross-check each number against the CSVs and report the ones that do not match.
- Resource analysis stops at the **role level**; do not rank or evaluate individuals.
- State the data assumptions in every chapter that has time measurements: Jira only has status-change timestamps (PT/WT are approximations); there is no headcount/labour
  hours (capacity is measured through throughput); back-fill updates; bots.
- Each chapter opens with 1–2 sentences naming which lecture's knowledge is being applied; write for a manager; statistical detail (bootstrap, pre-locked rules, ablation)
  goes to the appendix.
- A TO-BE number is always labelled "target / estimated scenario", with its assumptions.
- A "high score" in the ranking means "look at this first", not "violation"; `Rejected` is not an anomaly.

### Outputs and structure of phase 2

- New modules in `src/jira_ad/` (suggested: `process_metrics.py`, `norms.py`, `centrality.py`, `conformance.py`, `ranking.py`), with matching tests `tests/test_<module>.py`.
- New config: `configs/process.yaml` (back-fill threshold, work/wait classification, norm percentile, reference model, flag rules, working calendar).
- New CLI command (suggested `jira-ad process --config configs/process.yaml`) writing to `outputs/process/<run_id>/` with a manifest + fingerprint like the old runs; running again
  must give the same numbers (deterministic).
- Notebooks 07–12 as in "Mandatory notebooks"; you may edit the test that locks exactly 6 notebooks.
- Rename `docs/Untitled.md` → `docs/BAO_CAO_TONG_KET_export.md` (do not delete).

## Commands

```bash
# fresh clone (details: README → "Setup from scratch"); the dataset must already be in dataset/ (provided by the user)
uv sync --locked --all-extras --group dev
shasum -a 256 dataset/TIeventlogBug.csv dataset/TIeventlogStory.csv      # compare with the values in README
uv run jira-ad audit --config configs/baseline.yaml                      # expects 5,126/161 (bug), 4,439/182 (story)
uv run jira-ad run     --config configs/baseline.yaml                    # only if outputs/runs/ is missing
uv run jira-ad improve --plan configs/improvement_plan.yaml              # only if outputs/improvement/ is missing

# every task
uv run pytest -q
uv run ruff check src tests scripts

# phase 2
uv run jira-ad process --config configs/process.yaml
uv run jira-ad notebooks --run-dir outputs/process/<run_id>              # notebooks 07–12 (phase 1: outputs/runs/<run_id>, notebooks 01–06)

# check the locked hashes at the end of each task (expected values below are those recorded in the manifest of run outputs/process/20261026T025412Z-399b0a40)
shasum -a 256 configs/baseline.yaml configs/actions.yaml configs/experiments.yaml configs/improvement_plan.yaml dataset/TIeventlogBug.csv
```

Expected SHA-256 (prefix, first 16 hex): `configs/baseline.yaml` `2638fd50904a75eb`, `configs/actions.yaml` `4a35ef7d0f48052a`, `configs/experiments.yaml` `d7641ac840147eeb`,
`configs/improvement_plan.yaml` `98be18952f622e32`, `dataset/TIeventlogBug.csv` `cda16f1c5c4af641`.

## Way of working

- TDD: write the test → run it and see it fail for the right reason → implement → run it and see it pass. No test that only checks that a file exists. Use mutation testing
  for logic that computes numbers (dwell, norm, replay, ranking).
- Cross-check at least one main number per task with independent code (raw pandas, not importing `jira_ad`).
- After each task: record the files changed, the commands run, the real results and the remaining risks in `docs/PROGRESS.md`; end each task with `uv run pytest -q`, a clean `ruff`
  **and the task's notebook run successfully**.
- Give a short progress report after each task (1–3 lines: what is done, the main number, risks), then continue on your own.
- If Git is present: only `git add` the specific files of the task (never `git add .`), do not push, do not create remotes.
