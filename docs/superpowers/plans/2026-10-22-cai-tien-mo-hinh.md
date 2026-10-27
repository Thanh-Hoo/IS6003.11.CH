# Cải tiến mô hình, đánh giá lại và đánh giá khả năng ứng dụng — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm ba phương pháp mới nhắm vào điểm yếu đã đo của V1, một giao thức đánh giá có độ mạnh thống kê cao hơn (cross-validation trên cả 161 issue, thêm hai loại mutant), rồi chạy trên dữ liệu thật, chọn phương án theo quy tắc khóa trước và viết báo cáo cho hội đồng bảo vệ / giảng viên.

**Architecture:** Mọi thuật toán nằm trong package `jira_ad` (encoder mới trong `features.py`, bộ chấm điểm mới trong `detector.py`, mutant mới trong `mutations.py`, giao thức CV trong `crossval.py`, điều phối + quyết định + phân tích ứng dụng trong `improvement.py`, lệnh `jira-ad improve`). Baseline V1 không bị sửa: các phương pháp và loại mutant mới chỉ được dùng khi file cấu hình liệt kê chúng, nên `config_hash` của `baseline.yaml` và mọi run cũ giữ nguyên.

**Tech Stack:** Python 3.12, NumPy, pandas, scikit-learn IsolationForest, Gensim (embedding sẵn có), pytest, ruff, uv.

**Spec:** [docs/superpowers/2026-10-16-jira-ad.md](../2026-10-16-jira-ad.md) (giữ nguyên mọi ràng buộc V1) + phần "Thiết kế" dưới đây (do người dùng giao: "đề xuất phương án và kế hoạch rồi làm luôn"; người đọc kết quả: hội đồng bảo vệ, giảng viên).

## Thiết kế (quyết định của tôi, người dùng chưa duyệt từng mục)

**Chẩn đoán đã đo (V1):** mutant một chỉnh sửa quá tinh vi; mean/max pooling mù thứ tự (`C_embedding` × swap = 0,500); 32/42 cột của `D_hybrid` là pooling và ở đối chứng dương `D_hybrid` 0,658 < `A_stats` 0,886 (nghi bị loãng); chỉ 31 parent test nên khoảng tin cậy rộng.

**Ba phương pháp mới** (mỗi phương pháp sửa một điểm yếu, không đổi baseline):

| ID | Đặc trưng | Bộ chấm điểm | Nhắm vào |
|---|---|---|---|
| `E_score_fusion` | như `D_hybrid` (pooling + H) | hai Isolation Forest riêng (cột H; cột pooling), mỗi điểm chuẩn hóa z theo phân bố điểm **train** của chính nó, điểm cuối = trung bình hai z | loãng do ghép cột |
| `F_edge_hybrid` | mean/max của vector **cạnh** `v_a ⊙ v_b` (Hadamard) trên mọi chuyển tiếp của trace kể cả `__START__`/`__END__`, + H | Isolation Forest | pooling mù thứ tự |
| `M_markov` | H | điểm = `mean_transition_surprisal` (−log P trung bình theo DFG train, không Isolation Forest) | đo trực tiếp thứ tự; mốc đơn giản nhất |

Token chưa thấy → vector 0 (cạnh chứa nó cũng 0). Không thêm SVD/scaler học được.

**Hai loại mutant mới** (chỉ dùng trong giao thức CV, không vào benchmark V1):
- `skip_status`: xóa một event nội bộ có activity bắt đầu bằng `STATUS_` (mô phỏng "bỏ qua một bước trạng thái", ví dụ bỏ `In Test`); không có thì `skipped` lý do `no_internal_status`.
- `multi_edit`: 3 chỉnh sửa liên tiếp, mỗi lần chọn ngẫu nhiên một trong swap/delete/duplicate(1 event) hợp lệ trên chuỗi hiện tại, event đầu/cuối luôn bảo vệ, độ dài luôn ≥ 3; thử tối đa 50 lần; trùng chuỗi gốc trong holdout bị loại.

**Giao thức 1 — chọn phương án (khóa trước, ngày 2026-10-22, trước mọi run):** split V1 (97/33/31), mutant V1, model seed 42/43/44, cấu hình = baseline + 3 phương pháp mới. Chỉ số chính: macro AUROC trên **validation**, trung bình 3 seed. Ứng viên cải thiện ⇔ khoảng bootstrap theo parent của (ứng viên − `D_hybrid`) nằm hoàn toàn trên 0 ở mức 1 − 0,05/3. Test chỉ xem sau phán quyết, ghi là khám phá (test đã được xem nhiều lần từ V1).

**Giao thức 2 — cross-validation (khám phá, độ mạnh cao hơn):** 5 fold theo issue trên cả 161 ca (chia vòng tròn trong từng nhánh `terminal_status` theo SHA-256 của `split.seed:cv:case_id`), mỗi fold fit chỉ trên 4 fold còn lại; 5 loại mutant; seed mutation = `mutation.test_seed + 100*fold` (giống nhau cho mọi phương pháp và model seed). Điểm mỗi fold chuẩn hóa z theo phân bố điểm train của chính mô hình fold đó rồi mới gộp 161 parent. Bootstrap theo parent, gộp 3 model seed trong từng lần resample.

**Tiêu chí ứng dụng (khóa trước):** cho mỗi phương pháp, trên CV:
- *Tự động cảnh báo*: cận dưới khoảng 95% của macro AUROC ≥ 0,80 **và** AUROC `skip_status` ≥ 0,80.
- *Bộ lọc ưu tiên rà soát*: cận dưới khoảng 95% của macro AUROC > 0,5 **và** Jaccard top-10% (16 ca) giữa các model seed ≥ 0,6 **và** thời gian chấm < 100 ms/ca.
- Còn lại: *chưa đủ để ứng dụng*.

**Không làm:** notebook 07 (bộ test hiện khóa đúng 6 notebook); trộn bug/story; dùng thời gian làm feature; sửa `baseline.yaml`/`actions.yaml`; chọn theo test.

## Global Constraints

- `dataset/` chỉ đọc; đơn vị là issue; chỉ fit trên train (trong CV: chỉ trên các fold train).
- Không bịa nhãn, không hardcode metric, không tuyên bố kết quả chưa đo; kết quả âm phải báo.
- Tham số nghiên cứu ở YAML (`configs/improvements.yaml`), quy tắc thuật toán trong `src/jira_ad/`.
- `config_hash` của `configs/baseline.yaml` phải giữ `930f8a85…`; sha256 `baseline.yaml` `2638fd50…`, `actions.yaml` `4a35ef7d…`.
- TDD: test → thấy fail đúng lý do → code → pass. Ghi kết quả thật vào `docs/PROGRESS.md`.
- Không Git (thư mục không phải repo): bỏ bước commit.

## Review Focus

1. Trace một event (không có chuyển tiếp nội bộ) với `F_edge_hybrid`/`M_markov`: phải hữu hạn, không chia 0 — test ở Task 2.
2. Trace không có event `STATUS_` nội bộ với `skip_status`: `skipped` có lý do, không lỗi — test ở Task 1.
3. Isolation Forest train cho std điểm = 0 (z không xác định) trong `E_score_fusion`/CV: dùng std thay thế 1,0, không NaN — test ở Task 3 và Task 4.
4. Bundle phương pháp mới qua save/load cho cùng điểm (atol 1e-8) — test ở Task 3.
5. Fold nào đó thiếu một nhánh `terminal_status`: fold vẫn chạy (gán vòng tròn theo nhánh nên không fold rỗng khi n ≥ số fold) — test ở Task 4.

---

### Task 1: Hai loại mutant mới và đăng ký tên phương pháp/loại

**Files:** Modify `src/jira_ad/config.py` (`FEATURE_METHODS` + `E_score_fusion`, `F_edge_hybrid`, `M_markov`; `MUTATION_TYPES` + `skip_status`, `multi_edit`), `src/jira_ad/mutations.py`; Test `tests/test_mutations.py`, `tests/test_config.py`.

**Interfaces — Produces:** `generate_mutations` hỗ trợ `"skip_status"`, `"multi_edit"`; hằng `STATUS_PREFIX = "STATUS_"`, `MULTI_EDIT_STEPS = 3`, `MULTI_EDIT_MAX_ATTEMPTS = 50`.

- [ ] Test: `test_skip_status_removes_one_internal_status_event` (độ dài −1, event bị xóa có activity bắt đầu `STATUS_`, đầu/cuối giữ nguyên, role/event_id đi cùng); `test_skip_status_without_internal_status_is_skipped` (`skip_reason == "no_internal_status"`); `test_multi_edit_changes_sequence_keeps_ends_and_lineage` (đầu/cuối giữ, mọi (activity, role, event_id) của mutant có trong parent, khác parent, độ dài ≥ 3, `edited_positions` là JSON list 3 thao tác); `test_multi_edit_is_reproducible_and_order_independent`; test config: baseline cũ cho đúng `config_hash` cũ khi thêm tên mới vào tuple (test sẵn có phải còn xanh).
- [ ] Chạy `uv run pytest tests/test_mutations.py -q` → FAIL (`Loại mutation không hỗ trợ`).
- [ ] Code: `_skip_status_candidates(activities)`; `_multi_edit(trace, rng, originals) -> (order, ops, n_attempts, n_rejected) | None` dùng trong `generate_mutations`.
- [ ] Chạy lại → PASS; toàn bộ `tests/test_mutations.py tests/test_config.py` xanh.

### Task 2: Encoder cho ba phương pháp mới

**Files:** Modify `src/jira_ad/features.py`, `src/jira_ad/embedding.py` (`pool_edges(tokens, embedding, add_boundaries) -> (mean, max)`); Test `tests/test_features.py`, `tests/test_embedding.py`.

**Interfaces — Produces:** `FeatureEncoder(method)` với `E_score_fusion` → tên cột giống `D_hybrid`; `F_edge_hybrid` → `edge_mean_00..`, `edge_max_00..` + H; `M_markov` → H. `EMBEDDING_METHODS = ("C_embedding", "D_hybrid", "E_score_fusion", "F_edge_hybrid")`.

- [ ] Test: `test_edge_pooling_sees_order` (hai chuỗi cùng histogram khác thứ tự → cột `edge_*` khác nhau, cột `emb_*` của D giống nhau); `test_edge_pooling_single_event_is_finite` (trace 1 event với boundaries → 2 cạnh, hữu hạn); `test_unseen_token_gives_zero_edges`; `test_fusion_encoder_matches_d_hybrid_features`; `test_markov_encoder_is_h_only`; các test fit-chỉ-train sẵn có tham số hóa thêm phương pháp mới nếu có tham số hóa.
- [ ] FAIL → code → PASS (`uv run pytest tests/test_features.py tests/test_embedding.py -q`).

### Task 3: Bộ chấm điểm mới trong detector

**Files:** Modify `src/jira_ad/detector.py` (lớp `ZScoreFusion`, `ColumnScore`; `fit_detector` chọn bộ chấm theo method; `DetectorBundle.model` là bất kỳ đối tượng có `score_samples(X)`), `src/jira_ad/plots.py` (màu 3 phương pháp mới); Test `tests/test_detector.py`.

**Interfaces — Produces:** `ZScoreFusion(groups: list[list[int]], forests, train_mean, train_std).score_samples(X) -> -mean_z`; `ColumnScore(index: int).score_samples(X) -> -X[:, index]`. `anomaly_score` vẫn = `-score_samples`.

- [ ] Test: `test_markov_score_is_mean_transition_surprisal`; `test_fusion_score_is_mean_of_train_standardised_forest_scores` (tính lại độc lập bằng hai IsolationForest cùng seed); `test_fusion_with_constant_train_scores_is_finite`; `test_new_bundles_roundtrip_scores` (save/load, atol 1e-8); `test_new_methods_fit_only_on_train` (sửa trace held-out không đổi `encoder_state_sha256`).
- [ ] FAIL → code → PASS (`uv run pytest tests/test_detector.py -q`).

### Task 4: Giao thức cross-validation

**Files:** Create `src/jira_ad/crossval.py`; Test `tests/test_crossval.py`.

**Interfaces — Produces:**
- `cv_folds(traces: list[Trace], folds: int, seed: int) -> dict[str, int]`
- `run_crossval(cfg: RunConfig, traces: list[Trace], *, methods: list[str], folds: int, model_seeds: list[int], mutation_types: list[str]) -> CrossvalResult` với dataclass `CrossvalResult(originals: DataFrame, mutants: DataFrame, ledger: DataFrame, paired: DataFrame, metrics: DataFrame, timings: DataFrame)`; cột điểm `anomaly_score` đã chuẩn hóa z theo train của fold, thêm `fold`, `model_seed`, `raw_score`.

- [ ] Test: fold cân bằng theo nhánh, tất định, độc lập thứ tự đầu vào; mỗi trace đúng một fold; `test_each_fold_model_never_sees_its_held_out_traces` (state fingerprint không đổi khi sửa trace của fold held-out); `test_crossval_scores_every_trace_exactly_once_per_seed_and_method`; `test_z_normalisation_uses_train_scores_only`; `test_folds_more_than_cases_is_rejected`.
- [ ] FAIL → code → PASS (`uv run pytest tests/test_crossval.py -q`).

### Task 5: Điều phối cải tiến, quyết định, phân tích ứng dụng, CLI

**Files:** Create `src/jira_ad/improvement.py`, `configs/improvements.yaml` (cấu hình đầy đủ = baseline + 7 phương pháp) và `configs/improvement_plan.yaml` (seeds, quyết định, CV, tiêu chí ứng dụng); Modify `src/jira_ad/cli.py` (lệnh `improve --plan PATH [--dry-run]`); Test `tests/test_improvement.py`.

**Interfaces — Produces:** `load_improvement_plan(path) -> ImprovementPlan`; `method_decision(paired_by_run: dict[str, DataFrame], *, reference, candidates, split, confidence, n_resamples, seed) -> DataFrame`; `applicability(cv: CrossvalResult, criteria) -> DataFrame`; `run_improvement(plan_path, *, now=None) -> Path` ghi `outputs/improvement/<UTC>-<hash8>/` gồm `manifest.json` (status, plan sha256, input sha256, run_ids giao thức 1, môi trường, thời gian), `decision_validation.csv`, `exploratory_test.csv`, `standard_metrics.csv`, `cv_metrics.csv`, `cv_bootstrap_intervals.csv`, `cv_bootstrap_differences.csv`, `applicability.csv`, `inference_profile.csv`, `figures/*.png`. Không ghi đè thư mục có sẵn.

- [ ] Test: plan sai khóa bị từ chối; `method_decision` trên dữ liệu tổng hợp (ứng viên tốt hơn rõ → "ứng viên cải thiện"; giống hệt → "không có bằng chứng"); `applicability` áp đúng ngưỡng khóa trước; E2E nhỏ trên dự án giả (2 seed, 3 fold, embedding nhỏ) cho `status: completed` và đủ file; `config_hash(baseline)` không đổi.
- [ ] FAIL → code → PASS; `uv run pytest -q` toàn bộ xanh; `uv run ruff check src tests scripts` sạch.

### Task 6: Chạy thật, báo cáo, cập nhật tài liệu

**Files:** Create `docs/BAO_CAO_CAI_TIEN.md`; Modify `docs/PROGRESS.md` (Task 18), `docs/DECISIONS.md`, `README.md` (lệnh `improve`).

- [ ] `uv run jira-ad improve --plan configs/improvement_plan.yaml` trên dữ liệu thật; ghi thư mục kết quả.
- [ ] Kiểm hash `baseline.yaml`, `actions.yaml`, `dataset/` không đổi; mở các hình và đọc lại.
- [ ] Viết báo cáo (người đọc: hội đồng/giảng viên): bối cảnh V1, chẩn đoán, phương pháp mới, hai giao thức, kết quả so với V1 (bảng + khoảng tin cậy), phân tích dữ liệu liên quan (độ dài, nhánh, độ phủ), kết quả inference và mức ứng dụng theo tiêu chí khóa trước, giới hạn, kết luận âm nếu có. Mọi số lấy từ artifact, đối chiếu tự động trước khi lưu.
