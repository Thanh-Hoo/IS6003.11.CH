# Đồ án môn "Hoạch định nguồn lực doanh nghiệp nâng cao" — Implementation Plan (giai đoạn 2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps dùng checkbox (`- [ ]`). Tự làm tuần tự Task 19 → 25, **chỉ dừng ở các điểm dừng bắt buộc** trong `CLAUDE.md` (mục "Quy trình tự làm"). Sau mỗi Task: báo 1–3 dòng rồi làm tiếp.

**Goal:** Áp dụng 6 buổi học (B1 Work System + BPMN; B2 CT = PT + WT, CTE, Little, năng lực, FPY; B3 định mức đúng/trễ, DFG, centrality; B4 BPR AS-IS/TO-BE + KPI; B5 Alpha/Heuristics/Inductive, Petri net, token replay; B6 Node2Vec) lên event log Jira bug, trả lời bốn câu hỏi quản trị: (1) quy trình thực tế chạy thế nào; (2) thời gian đi đâu, vai trò nào là điểm nghẽn; (3) bao nhiêu ca lệch chuẩn, lệch ở đâu; (4) tái thiết kế ra sao, đo bằng KPI gì.

**Architecture:** Module phẳng mới trong `src/jira_ad/` (theo gợi ý CLAUDE.md) đọc dữ liệu qua loader, chuẩn hóa action, core view, split, DFG **đã có**. Tham số ở `configs/process.yaml`. Một lệnh `jira-ad process --config configs/process.yaml` ghi `outputs/process/<UTC>-<hash8>/` (manifest + fingerprint, tất định: chạy lại cho cùng bảng); mỗi bước A–E là một thư mục con. Báo cáo `docs/BAO_CAO_MON_HOC.md` và notebook `notebooks/07_process_analysis.ipynb` đọc từ thư mục run; mọi số trong báo cáo được đối chiếu tự động với CSV.

**Tech Stack:** Python 3.12, pandas, NetworkX, scikit-learn (K-means, ARI/NMI, silhouette), pm4py (extra `process`), Graphviz `dot`, pytest, ruff, uv.

**Nguồn quyết định:** `CLAUDE.md` mục "Quyết định đã duyệt" > kế hoạch này > spec giai đoạn 1 ([2026-10-16-jira-ad.md](../2026-10-16-jira-ad.md)). Ledger: [PROGRESS.md](../../PROGRESS.md) (Task 19+, Ruling 67+), [DECISIONS.md](../../DECISIONS.md).

## Quyết định đã duyệt (tóm tắt để tra; bản gốc ở CLAUDE.md)

| # | Quyết định | Ảnh hưởng trong kế hoạch |
|---|---|---|
| 1 | pm4py = extra `process`; chạy thử bỏ đi trước; lỗi ⇒ dừng, báo 2–3 phương án | Task 21 Step 1 |
| 2 | **Làm** = `In Progress`, `In Test`; **chờ** = `Inbox`, `To Investigate`, `INVESTIGATED`, `To Do`. Độ nhạy bắt buộc: `To Investigate` là làm. PT/WT/CTE báo thành **khoảng** (hai phân loại × cập nhật bù) | Task 19 |
| 3 | Không có SLA: định mức = **phân vị 0,75 của dwell theo trạng thái, đơn vị ngày làm việc**, trên lịch sử; YAML cho thay bằng SLA thật | Task 20 |
| 4 | Conformance = mô hình chuẩn dạng danh sách cung (giả định của tác giả, trình bày trước khi replay) + 7 cờ quy tắc (đếm, không kết luận lỗi); quy tắc 0 vi phạm vẫn giữ và ghi là kết quả | Task 21 |
| 5 | Graph2Vec **cắt** (chỉ một đoạn "hướng mở rộng" ở Ch6) | Task 23 |
| 6 | Báo cáo `docs/BAO_CAO_MON_HOC.md` | Task 24 |
| 7 | Ngày làm việc theo **ngày địa phương từ `timestamp_raw`** (chính); UTC là độ nhạy | Task 19 |

## Định nghĩa số đo (cố định trước khi chạy)

- **Ca** = trace core view (CREATE → trạng thái kết thúc cuối). Phân tích mô tả dùng cả 161 ca (CLAUDE.md: không có bước học). Mô hình có học (DFG activity cho centrality, embedding) chỉ dùng train/run V1.
- **Status log**: mỗi event core có `status_value` mở một *lượt* trạng thái, kết thúc ở event trạng thái kế tiếp. Đoạn CREATE → lần đổi trạng thái đầu là `__CREATED__` (loại *chờ*). Trạng thái kết thúc không có dwell. `exit_role` = vai trò của event rời khỏi lượt.
- **Đồng hồ**: `cal` = giây thực; `work` = giây thuộc T2–T6 tính theo **giờ địa phương với offset của event mở lượt** (chu kỳ 24 giờ, không giờ hành chính, không ngày lễ); độ nhạy `work_utc` = như trên nhưng theo UTC.
- **Cập nhật bù**: một lần đổi trạng thái cách lần trước < `backfill_threshold_seconds` (60). *Đợt bù* = chuỗi liên tiếp các lần đổi như vậy.
- **PT/WT/CTE**: `PT` = Σ dwell ở trạng thái *làm*; `WT = CT − PT`; `CTE = PT/CT` (CT = 0 ⇒ không xác định, đếm riêng). Bốn biến thể tạo **khoảng**: {phân loại chính, `To Investigate` là làm} × {nguyên trạng, *cận trên do bù*: dwell của lượt ngay trước một đợt bù có đi qua trạng thái *làm* được tính là *làm*}.
- **Little theo tuần** (tuần ISO theo ngày địa phương): λ = số ca tạo/tuần, throughput = số ca kết thúc/tuần, WIP đo = số ca mở trung bình theo thời gian trong tuần, so với λ_tuần × CT trung bình toàn kỳ. Trên cả cửa sổ, `L = λ·W` là đồng nhất thức (chỉ có ca đã đóng) ⇒ ghi rõ; độ lệch theo tuần mới mang thông tin (tính dừng).
- **Lùi trạng thái** = sang trạng thái có thứ tự nhỏ hơn trạng thái trước theo `states.order`; **mở lại** = rời DONE/Rejected. **FPY** = tỉ lệ ca không lùi, không mở lại (bản *strict*) và bản bỏ qua lần lùi nằm trong đợt bù (*adjusted*).
- **Định mức**: `norm(s)` = phân vị 0,75 của `dwell_work` các lượt trạng thái `s` (161 ca). Lượt trễ ⇔ dwell_work > norm. Trễ theo vai trò = theo `exit_role`; theo ca = số lượt trễ và `CT_work` > phân vị 0,75 của nhánh.
- **Vai trò**: chỉ vai trò con người xác định; `bot`, `unknown`, thiếu role được báo riêng, không xếp hạng.

## Global Constraints

- Không sửa `dataset/`, `configs/{baseline,actions,experiments,improvement_plan}.yaml`, `outputs/runs/`, `outputs/improvement/`. Hash cuối mỗi Task: `baseline.yaml` `2638fd50…`, `actions.yaml` `4a35ef7d…`, `TIeventlogBug.csv` `cda16f1c…`.
- Được sửa có Ruling: `pyproject.toml` + `uv.lock` (extra `process`), `src/jira_ad/cli.py` (lệnh `process`), test khóa 6 notebook (cho notebook 07), `README.md`, `AGENTS.md`; đổi tên `docs/Untitled.md` → `docs/BAO_CAO_TONG_KET_export.md`.
- Tái sử dụng: `data.load_raw_events`, `preprocess.normalize_events/build_core_view`, `splits.make_case_splits`, `graph.build_dfg/transition_surprisal`, `config._build/_require/ConfigError`, embedding của run `20261017T081309Z-930f8a85` (`node_vectors.parquet`, không fit lại), điểm out-of-fold `cv_original_scores.csv`.
- TDD; kiểm đột biến cho logic tính số (dwell, định mức, replay, xếp hạng); kiểm chéo ít nhất một số chính mỗi Task bằng pandas thô (không import `jira_ad`), so với "sự thật đã đo" trong CLAUDE.md.
- Mọi số từ code chạy thật; số TO-BE luôn ghi "mục tiêu / kịch bản ước tính" kèm giả định; nguồn lực dừng ở vai trò; "điểm cao" = "nên xem trước".
- Kết thúc mỗi Task: `uv run pytest -q`, `uv run ruff check src tests scripts` sạch, kiểm hash, ghi PROGRESS. Không Git ⇒ bỏ commit.

## Review Focus

1. Ca `CREATE → Rejected` (22 ca): chỉ có `__CREATED__`; `PT = 0`, `CTE = 0`, không chia 0 — test Task 19.
2. Đổi trạng thái trùng timestamp hoặc < 60 s: dwell ≥ 0, thứ tự ổn định, gắn cờ bù, không tính là lùi trong FPY adjusted — Task 19.
3. Lượt nằm trọn trong cuối tuần địa phương: `dwell_work = 0`, CTE_work của ca có `CT_work = 0` không xác định và được đếm — Task 19.
4. Trạng thái không khai trong YAML (`Triage`, `OPEN`) và role `bot`/`unknown`/thiếu: loại `other` được liệt kê; không xuất hiện trong bảng vai trò — Task 19, 20.
5. Ca có trạng thái ngoài mô hình chuẩn hoặc biến thể chưa thấy: replay ghi lệch, không ném lỗi; log rỗng ném lỗi rõ — Task 21.

## Cấu trúc file

| File | Trách nhiệm |
|---|---|
| `configs/process.yaml` | Đường dẫn base config/run V1/improvement, cohort, lịch, ngưỡng bù, phân loại trạng thái, định mức, mô hình chuẩn, cờ quy tắc, khai phá, BPR, xếp hạng, bootstrap |
| `src/jira_ad/process_config.py` | `ProcessConfig` nghiêm ngặt (dùng lại `_build` của `config.py`), `process_config_hash` |
| `src/jira_ad/worktime.py` | Giây ngày làm việc theo offset địa phương / UTC |
| `src/jira_ad/status_log.py` | Status log từ event chuẩn hóa + core view; cờ bù, lùi, mở lại |
| `src/jira_ad/process_metrics.py` | CT/PT/WT/CTE (khoảng), Little theo tuần, FPY, chi phí Rejected, vai trò cổng, bảng KPI AS-IS |
| `src/jira_ad/norms.py` | Định mức, trễ theo trạng thái/vai trò/ca, top lần trễ |
| `src/jira_ad/centrality.py` | DFG trạng thái, centrality, bảng centrality × độ trễ |
| `src/jira_ad/conformance.py` | Mô hình chuẩn → Petri net + BPMN, khai phá, token replay, cờ quy tắc, enhancement, Work System |
| `src/jira_ad/bpr.py` | Vấn đề → bằng chứng → thủ pháp; kiểm chứng ứng viên; what-if; KPI TO-BE |
| `src/jira_ad/ranking.py` | Clustering embedding V1, so với centrality, hồ sơ bất thường nhiều chiều, xếp hạng, ổn định, bảng mù |
| `src/jira_ad/process_run.py` | Điều phối, thư mục run, manifest, fingerprint đầu vào khóa |
| `src/jira_ad/process_report.py` | Đối chiếu số trong báo cáo với CSV |

---

### Task 19 — Bước A: status log + phân tích định lượng (Ch2; B2)

**Files:** Create `configs/process.yaml`, `src/jira_ad/{process_config,worktime,status_log,process_metrics,process_run}.py`, `tests/test_{process_config,worktime,status_log,process_metrics,process_run}.py`; Modify `src/jira_ad/cli.py` (lệnh `process`); đổi tên `docs/Untitled.md`.

**Interfaces — Produces:**
- `load_process_config(path) -> ProcessConfig`; `process_config_hash(cfg) -> str`
- `work_seconds(start_utc: pd.Timestamp, end_utc: pd.Timestamp, offset_minutes: int, workdays: tuple[int, ...]) -> float`; `parse_offset_minutes(timestamp_raw: str) -> int`
- `load_cohort(cfg: ProcessConfig, cohort: str) -> CohortData(events, traces, splits)` (events = bảng chuẩn hóa thu hẹp về event core, giữ `timestamp_raw`)
- `build_status_log(events, traces, cfg) -> DataFrame[case_id, terminal_status, visit_index, state, state_class, t_enter, t_exit, offset_min, dwell_cal_s, dwell_work_s, dwell_work_utc_s, enter_role, exit_role, is_backfill_exit, burst_id, is_back, is_reopen]`
- `case_table(status_log, traces) -> DataFrame[case_id, terminal_status, n_events, ct_cal_s, ct_work_s, ct_work_utc_s, reached_in_progress, n_back, n_reopen, n_backfill]`
- `time_split(status_log, cases, work_states, backfill_upper: bool, clock: str) -> DataFrame[case_id, pt_s, wt_s, cte]`; `pt_wt_ranges(status_log, cases, cfg) -> DataFrame` (4 biến thể × 2 đồng hồ; tổng hợp trung vị/trung bình + khoảng min–max giữa biến thể)
- `dwell_by_state(status_log) -> DataFrame` (trạng thái × nhánh × đồng hồ: n, mean, median, p75, p90)
- `weekly_little(cases, events) -> DataFrame[week, arrivals, completions, wip_measured, lambda_x_ct]`; `little_window(cases) -> dict`
- `fpy(status_log, cases) -> dict`; `rejected_cost(cases) -> DataFrame`; `gate_roles(status_log) -> DataFrame[role, target_state, n]`
- `kpi_asis(...) -> DataFrame[kpi, value, unit, scope, note]`
- `run_process(config_path, *, now=None) -> Path`; `frozen_fingerprint(root) -> dict`

- [ ] **Step 1 (RED)** — test chính: `test_work_seconds_friday_noon_to_monday_noon` (offset −420: 259 200 s lịch, 86 400 s làm việc); `test_work_seconds_inside_local_weekend_is_zero`; `test_local_and_utc_weekday_boundary_differ` (Thứ Sáu 20:00 −0700 = Thứ Bảy 03:00Z); `test_parse_offset_minutes` (−0700 → −420, −0800 → −480); `test_status_log_visits_and_created_segment` (ca `CREATE, To Do, In Progress, In Test, DONE`: 5 dòng, Σ dwell = CT); `test_backfill_flag_and_burst`; `test_same_timestamp_dwell_zero`; `test_back_and_reopen_flags`; `test_unknown_state_is_other`; `test_create_then_rejected_has_zero_pt`; `test_pt_wt_identity_and_cte`; `test_backfill_upper_reassigns_previous_dwell`; `test_fpy_strict_vs_adjusted`; `test_little_window_identity` (3 ca 2/4/6 ngày trong 10 ngày ⇒ L = 1,2); `test_gate_roles_exclude_bot_unknown_missing`; `test_config_rejects_unknown_keys`; `test_run_refuses_overwrite_and_checks_frozen_inputs`; `test_process_cli_end_to_end` (dự án giả).
- [ ] **Step 2** chạy `uv run pytest tests/test_worktime.py tests/test_status_log.py tests/test_process_metrics.py tests/test_process_config.py tests/test_process_run.py -q` ⇒ FAIL `ModuleNotFoundError`.
- [ ] **Step 3** implement; **Step 4** test xanh + toàn bộ suite + ruff; đột biến dwell/work_seconds/FPY phải bị bắt.
- [ ] **Step 5** chạy thật `uv run jira-ad process --config configs/process.yaml` ⇒ `a_quant/` (`status_log.parquet`, `cases.csv`, `dwell_by_state.csv`, `pt_wt_ranges.csv`, `weekly_little.csv`, `little.json`, `fpy.json`, `rejected_cost.csv`, `gate_roles.csv`, `kpi_asis.csv`, cùng các bảng cho `story` đặt cạnh, không trộn). Chạy lại lần hai: bảng giống hệt.
- [ ] **Step 6** kiểm chéo bằng pandas thô: 161 ca, 83/78, 30 biến thể trạng thái, 22 `CREATE → Rejected`, 165/553 lần đổi < 60 s (trên full view), CT trung vị. Ghi PROGRESS Task 19.

### Task 20 — Bước B: định mức + centrality (Ch3; B3)

**Files:** Create `src/jira_ad/{norms,centrality}.py`, tests tương ứng; Modify `process_run.py` (bước `b_norms`).

**Interfaces:** `fit_norms(status_log, percentile, explicit_days) -> DataFrame[state, norm_work_s, source, n]`; `late_visits(status_log, norms) -> DataFrame`; `late_by(late, key)` cho `state`, `exit_role`, `case_id`; `top_late(late, k)`; `status_dfg(status_log) -> nx.DiGraph` (count, median wait); `activity_dfg_train(cohort) -> nx.DiGraph` (bọc `build_dfg` trên train, khớp `graph.graphml` của run V1: 51 nút, 386 cạnh); `centrality_table(graph, pagerank_alpha) -> DataFrame[node, in_degree, out_degree, betweenness, closeness_undirected, eigenvector_undirected, pagerank]`; `centrality_vs_delay(centrality, late_by_state) -> DataFrame`; `improvement_priorities(...) -> DataFrame` (quy tắc trong YAML).

- [ ] **Step 1 (RED):** `test_norm_is_p75_of_work_dwell`; `test_explicit_sla_overrides`; `test_late_strictly_greater`; `test_late_by_role_uses_exit_role_and_excludes_non_human`; `test_centrality_star_and_chain` (sao vô hướng 4 nút: betweenness tâm = 3,0 chưa chuẩn hóa); `test_pagerank_sums_to_one`; `test_activity_dfg_train_matches_v1_graphml`.
- [ ] **Step 2–4** RED → implement → xanh + đột biến (phân vị, so sánh `>`).
- [ ] **Step 5** chạy thật ⇒ `b_norms/` (`norms.csv`, `late_by_state.csv`, `late_by_role.csv`, `late_by_case.csv`, `top_late.csv`, `centrality_status.csv`, `centrality_activity.csv`, `centrality_vs_delay.csv`, `priorities.csv`, hình DFG trạng thái có chú thích thời gian chờ).
- [ ] **Step 6** kiểm chéo norm của một trạng thái bằng pandas thô; PROGRESS Task 20.

### Task 21 — Bước C: Work System, mô hình chuẩn, khai phá, kiểm định (Ch1, Ch5; B1, B5)

**Files:** Modify `pyproject.toml`, `uv.lock`; Create `src/jira_ad/conformance.py`, `tests/test_conformance.py`; Modify `process_run.py` (bước `c_conformance`).

**Interfaces:** `work_system_table(cohort, status_log) -> DataFrame[component, content, evidence]` (8 thành phần: khách hàng, sản phẩm/dịch vụ, quy trình/hoạt động, người tham gia, thông tin, công nghệ, môi trường, hạ tầng; ô không có trong dữ liệu ghi rõ "giả định đề bài"); `reference_net(cfg) -> (net, im, fm)` (mỗi activity một transition; cung A→B thành transition ẩn nối place sau A với place trước B, nên nhãn không trùng); `reference_bpmn(cfg, gate_roles) -> (bpmn_xml: str, graphviz_source: str)` (lane theo vai trò cổng); `status_event_log(status_log)` (activity = `CREATE` + tên trạng thái); `discover(log, miner, params)`; `quality(model, log) -> {fitness, precision, generalization, simplicity}`; `replay_cases(net, im, fm, log) -> DataFrame[case_id, fitness, missing, remaining, is_fit]`; `deviation_hotspots(...)`; `flag_rules(status_log, cfg) -> DataFrame[case_id, flag, n]`; `arc_waits(status_log) -> DataFrame` (enhancement).

- [ ] **Step 1** chạy thử bỏ đi pm4py bằng `uv run --with pm4py python <scratchpad>/spike.py` (inductive, token replay, precision, BPMN, vẽ). Lỗi ⇒ **điểm dừng 1**. Đạt ⇒ `uv add --optional process pm4py`, kiểm numpy/pandas không đổi.
- [ ] **Step 2 (RED):** `test_reference_net_replays_conforming_trace_with_fitness_one`; `test_reference_net_flags_skipped_state`; `test_replay_handles_unknown_activity_without_raising`; `test_empty_log_raises`; một test cho mỗi cờ trong 7 cờ (kể cả trường hợp 0 vi phạm); `test_sequential_log_inductive_fitness_precision_one`; `test_bpmn_xml_has_lanes_gateways_and_flows`; `test_work_system_has_eight_components_with_evidence`.
- [ ] **Step 3–4** implement → xanh + đột biến (fitness, cờ).
- [ ] **Step 5** chạy thật phần **không** replay mô hình chuẩn: Work System, BPMN chuẩn (.bpmn + hình), Petri net (hình), khai phá Alpha/Heuristics/Inductive + chất lượng của chúng trên status log, cờ quy tắc, enhancement.
- [ ] **Step 6 — ĐIỂM DỪNG 2:** trình bày mô hình chuẩn (danh sách cung, sơ đồ, chỗ nào là giả định, điểm dữ liệu cho thấy có thể lệch) **một lần**, chờ duyệt. Sau khi duyệt: replay từng ca, fitness trung bình, % ca khớp hoàn toàn, top sai lệch kèm issueKey. Nếu fitness gần 1,0 hoặc kết quả mâu thuẫn "sự thật đã đo" ⇒ **điểm dừng 3**.
- [ ] **Step 7** kiểm chéo một số đếm cờ bằng pandas thô; PROGRESS Task 21.

### Task 22 — Bước D: BPR (Ch4; B2 heuristics, B4)

**Ghi chú của người dùng (26/10), bắt buộc đưa vào bảng vấn đề → bằng chứng → thủ pháp:**
- PT 16,7%–59,2% cho thấy công sức điều tra không hiện trong Jira ⇒ ứng viên đề xuất thêm trạng thái `Investigating` (tách hàng đợi khỏi việc điều tra).
- `To Do` chiếm 48% ngày vượt định mức và PO là cổng của 4/7 trạng thái chờ ⇒ **kiểm chứng** chờ ở `To Do` có gắn với PO không (vd so dwell `To Do` theo vai trò chuyển ra; ca PO chuyển ra so với vai trò khác), trước khi đề xuất "giảm phụ thuộc PO".
- Mô hình "luồng nhanh" (chuẩn + `CREATE → To Do`) là ứng viên TO-BE: giải thích thêm 25 ca (Task 21); cần điều kiện áp dụng (loại bug nào được bỏ điều tra).
- Notebook bắt buộc: `notebooks/10_bpr.ipynb` (Quyết định 9).

**Files:** Create `src/jira_ad/bpr.py`, `tests/test_bpr.py`; mục `bpr` trong YAML (khóa trước khi chạy).

**Interfaces:** `problem_evidence_table(results) -> DataFrame[problem, evidence, value, heuristic]`; `check_candidates(status_log, cases, cfg) -> DataFrame[candidate, test, value, verdict {ủng hộ, không ủng hộ, không đủ dữ liệu}]` cho 5 ứng viên: kiểm tra sớm ở Inbox; tự chuyển trạng thái theo commit/MR; gộp INVESTIGATED–To Do; giảm phụ thuộc PO; phát hiện trùng sớm; `what_if(status_log, scenario) -> DataFrame` (tính lại dwell/CT trên log, không đổi số ca); `kpi_tobe(asis, scenarios) -> DataFrame[kpi, asis_measured, tobe_target, scenario, assumption, label="mục tiêu / kịch bản ước tính"]`; `tobe_bpmn(...)`; `pilot_plan(cfg) -> DataFrame`.

- [ ] **Step 1 (RED):** `test_what_if_never_increases_ct_and_keeps_case_count`; `test_merge_states_removes_one_state_and_preserves_total_time`; `test_candidate_verdict_follows_rule_in_yaml`; `test_every_tobe_value_is_labelled_target`; `test_problem_table_values_come_from_inputs`.
- [ ] **Step 2–4** RED → implement → xanh + đột biến.
- [ ] **Step 5** chạy thật ⇒ `d_bpr/` (`problems.csv`, `candidates.csv`, `what_if.csv`, `kpi_asis_tobe.csv`, `bpmn_tobe.{bpmn,png}`, `pilot.csv`). Kiểm chéo một what-if bằng pandas thô; PROGRESS Task 22.

### Task 23 — Bước E: học biểu diễn + xếp hạng ưu tiên rà soát (Ch6; B6)

Notebook bắt buộc: `notebooks/11_ranking.ipynb`.

**Files:** Create `src/jira_ad/ranking.py`, `tests/test_ranking.py`.

**Interfaces:** `load_v1_vectors(run_dir) -> DataFrame` (qua `analysis.open_run`, kiểm fingerprint); `cluster_embeddings(vectors, k_range=(2..6), seed) -> DataFrame[k, silhouette, ari, nmi]` (nhóm nghiệp vụ activity khai trong YAML); `compare_with_structure(vectors, centrality, groups) -> DataFrame` (Node2Vec vs bậc vào/ra + centrality, có baseline lớp phổ biến, cùng phép đánh giá); `anomaly_profile(...) -> DataFrame` (cờ conformance, số lượt trễ, lùi/mở lại, đổi assignee, đợt bù, surprisal M_markov khử độ dài, phân vị trong nhóm nhánh × độ dài); `rank_cases(profile, p=0.90) -> DataFrame` (số chiều vượt p90, lý do bằng chữ); `bootstrap_topk_jaccard(...)`; `blind_review_table(ranked, n_top=15, n_random=15, seed) -> (blinded, key)`.

- [ ] **Step 1 (RED):** `test_length_adjusted_surprisal_is_uncorrelated_with_length_on_fixture`; `test_rank_counts_dimensions_above_p90`; `test_reasons_text_matches_flags`; `test_blind_table_hides_rank_and_group`; `test_cluster_metrics_hand_example`; `test_majority_baseline`.
- [ ] **Step 2–4** RED → implement → xanh + đột biến (xếp hạng).
- [ ] **Step 5** chạy thật ⇒ `e_ranking/` (`clusters.csv`, `embedding_vs_structure.csv`, `profile.csv`, `ranking.csv`, `top10.csv`, `stability.csv`, `correlations.csv`, `blind_review.csv`, `blind_review_key.csv`). Graph2Vec không làm (Quyết định 5). PROGRESS Task 23.

### Task 24 — Bước F: báo cáo + notebook tổng hợp `12_summary_report.ipynb` (notebook 07–11 đã làm theo từng bước, Quyết định 9)

**Files:** Create `src/jira_ad/process_report.py`, `tests/test_process_report.py`, `docs/BAO_CAO_MON_HOC.md`, `notebooks/07_process_analysis.ipynb`; Modify test khóa 6 notebook, `README.md`, `AGENTS.md`.

- [ ] **Step 1 (RED):** `test_extract_numbers_handles_vietnamese_decimal_comma`; `test_report_check_flags_number_absent_from_artifacts`; `test_notebook_07_runs_on_small_process_run`.
- [ ] **Step 2–4** implement → xanh.
- [ ] **Step 5** viết báo cáo (mỗi chương mở bằng buổi học áp dụng; văn phong cho người quản lý; giả định dữ liệu ở mọi chương có số thời gian; chi tiết thống kê ở phụ lục). Chạy `jira-ad process-check-report` ⇒ danh sách số chưa khớp phải rỗng hoặc được giải thích. PROGRESS Task 24.

### Task 25 — Bước G: rà soát độc lập

- [ ] Khởi chạy **một** subagent reviewer độc lập (đã được cho phép trong CLAUDE.md): tính lại số chính bằng pandas thô không import `jira_ad`; kiểm định nghĩa PT/WT/định mức nhất quán; không số TO-BE nào trình bày như kết quả đo; mỗi đề xuất BPR có bằng chứng; BPMN ↔ Petri net và replay đúng.
- [ ] Sửa các điểm reviewer báo; ghi đã sửa / chưa sửa vào PROGRESS. **ĐIỂM DỪNG 5.**
