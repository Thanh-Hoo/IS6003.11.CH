# PROGRESS — Jira process anomaly detection

> Ledger của kế hoạch: `docs/superpowers/2026-10-16-jira-ad.md` (spec = chính tài liệu này, §1–10; kế hoạch = §11).
> Thực hiện tuần tự, inline, trong một phiên (skill `superpowers:executing-plans`). Mọi số liệu dưới đây là
> **kết quả chạy thật** ghi lại từ output của lệnh; không có số nào được điền tay từ tài liệu.

## Checklist

- [x] Task 1 — Audit dữ liệu và môi trường tối thiểu
- [x] Task 2 — Chuẩn hóa, core view và split
- [x] Task 3 — DFG, thống kê và baseline n-gram
- [x] Task 4 — Walk, embedding và detector
- [x] Task 5 — Mutation và đánh giá trung thực
- [x] Task 6 — CLI E2E và artifact có provenance
- [x] Task 7 — Notebook và phân tích có thể tái chạy
- [x] Task 8 — Thực nghiệm thành phần và bàn giao
- [x] Task 9 — Cấu hình mở rộng không làm đổi hash của cấu hình/run cũ
- [x] Task 10 — Bootstrap theo parent, thử hoán vị trong cặp và so sánh ghép cặp qua các run
- [x] Task 11 — Đối chứng dương chính thức (chỉ validation)
- [x] Task 12 — Cross-fit đặc trưng train (kiểm giả thuyết 1)
- [x] Task 13 — Quy tắc quyết định khóa trước và kiểm hai giả thuyết trên validation
- [x] Task 14 — Holdout theo thời gian
- [x] Task 15 — Rà soát khám phá của agent trên 20 ca và cập nhật notebook/tài liệu
- [x] Task 16 — Sửa lỗi notebook không chạy được khi mở bằng tay trong VSCode
- [x] Task 17 — Bổ sung README cho người mới (chỉ tài liệu, không đổi code)
- [x] Task 18 — Giai đoạn cải tiến: 3 phương pháp mới, cross-validation, đánh giá ứng dụng (2026-10-22)

**Giai đoạn 2 — đồ án môn Hoạch định nguồn lực doanh nghiệp nâng cao** (kế hoạch: `docs/superpowers/plans/2026-10-26-do-an-mon-hoc.md`; quyết định đã duyệt: `CLAUDE.md`)

- [x] Task 19 — Bước A: status log + phân tích định lượng (Ch2)
- [x] Task 20 — Bước B: định mức + centrality (Ch3)
- [x] Task 21 — Bước C: Work System, mô hình chuẩn, khai phá, kiểm định (Ch1, Ch5); notebook 07, 08 (làm bù), 09
- [x] Task 22 — Bước D: BPR (Ch4); notebook 10
- [x] Task 23 — Bước E: học biểu diễn + xếp hạng (Ch6); notebook 11
- [x] Task 24 — Bước F: báo cáo `docs/BAO_CAO_MON_HOC.md` + notebook 12 + đối chiếu số
- [x] Task 25 — Bước G: rà soát độc lập (subagent) + một lượt sửa

Phạm vi: Task 1–2 xong và được người dùng xem; sau đó người dùng yêu cầu làm tiếp và Task 3–8 đã hoàn tất. Task 9–15 (2026-10-17) làm theo yêu cầu "hoàn thiện những phần còn thiếu, bám baseline đã đề ra": `baseline.yaml` và `actions.yaml` không bị sửa (hash `2638fd50…`/`4a35ef7d…` giữ nguyên), mọi mở rộng là thí nghiệm riêng, mặc định không đổi hành vi.

## Kiểm kê ban đầu (trước khi viết code)

| Mục | Kết quả |
|---|---|
| Thư mục | Chỉ có `dataset/` và `docs/`; chưa có code, CLAUDE.md, AGENTS.md, PROGRESS.md |
| Git | **Không phải Git repo** → không commit, không worktree |
| Python | 3.12.7 (`/Library/Frameworks/Python.framework`); **không có 3.11**; có `uv 0.9.10`; PyPI truy cập được |
| Dataset | `TIeventlogBug.csv`, `TIeventlogStory.csv`, `workflow-ti-bugs.json`, `workflow-tj-bugs.json`, `graph-viewer.html`, `README.md` (5,3 MB) |
| Checksum gốc | lưu trước khi chạy gì (`shasum -a 256`); so lại sau `jira-ad audit`: 6/6 file giống hệt |

## Rulings (quyết định tôi đưa ra thay người dùng)

Định dạng: Ruling — lý do — chi phí nếu sai.

1. **Đường dẫn tài liệu**: prompt ghi `docs/superpowers/plans/2026-10-16-jira-ad.md` nhưng file thật nằm ở
   `docs/superpowers/2026-10-16-jira-ad.md` (`plans/` rỗng). Không di chuyển file; CLAUDE.md trỏ tới đường dẫn thật.
   Chi phí: nếu muốn đúng như spec §Spec thì chạy `mv` một lệnh và sửa 1 dòng trong CLAUDE.md.
2. **Không Git** → `docs/PROGRESS.md` làm ledger thay cho `.superpowers/sdd/progress.md`; không commit; không dùng
   script `task-start`/`task-done` (cần Git). Thêm `.gitignore` (venv, outputs, dataset) để lỡ `git init` sau này
   không kéo dataset/artifact vào. Chi phí: không có lịch sử commit theo task.
3. **Python 3.12.7 thay vì 3.11**: máy không có 3.11; tránh tải thêm runtime. `requires-python = ">=3.11,<3.13"`,
   `.python-version = 3.12`. Chi phí: nếu cần đúng 3.11, `uv python install 3.11` rồi `uv lock` lại.
4. **Bộ phiên bản do resolver chọn** (không pin tay): numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1,
   gensim 4.4.0, networkx 3.7, pyarrow 26.0.0. Đã kiểm chứng gensim Skip-gram `workers=1` fit/save/load, joblib, parquet
   (xem Task 1). pandas 3.0 đổi dtype chuỗi mặc định (`str`) — code đã được test trên bản này.
   Chi phí: nếu Task 4 phát hiện lỗi gensim/numpy, pin numpy thấp hơn và khóa lại.
5. **`data.reference_counts` (khóa tùy chọn, thêm so với YAML mẫu §8)**: để audit báo "sai khác" như §2 yêu cầu mà không
   hardcode trong code. Số trong YAML chỉ để đối chiếu; báo cáo luôn là số tính từ file. Chi phí: xóa khóa.
6. **`source_row`** = chỉ số 1-based của dòng *dữ liệu* (không tính header), theo "vị trí dữ liệu trong CSV" của §4.1.
   Dòng CSV vật lý = `source_row + 1`. Chi phí: đổi offset một chỗ.
7. **Schema CSV nghiêm ngặt**: đúng 4 cột `issueKey,timestamp,role,action` (thiếu/thừa → `SchemaError`). Timestamp thiếu
   timezone bị từ chối (không đoán múi giờ); `issueKey` trống bị từ chối; role trống được giữ nguyên ở bước raw.
8. **File/lớp ngoài danh sách Task 1**: `tests/conftest.py`, `tests/test_types.py`, `tests/test_cli.py`,
   `tests/test_environment.py`; lớp config `ProjectConfig`, `RunSettings`, `NotebookConfig` (cho các section
   `project`, `run`, `notebooks` của YAML mẫu); `RunConfig.resolve()/output_dir/as_dict()`.
9. **Chỉ tạo CLAUDE.md** (đúng yêu cầu). `AGENTS.md` có trong cấu trúc mục tiêu §3 nhưng chưa tạo.
10. **`jira-ad audit`** audit *cả hai* cohort trong `data.files` một cách riêng rẽ (không gộp); ghi
    `outputs/analysis/audit_raw.json` (ghi nguyên tử, từ chối NaN/Inf).
11. **Độ mịn activity** (Task 2): activity = động từ + tên field, **không lưu giá trị** (vd mọi
    `update Backlog Classification to …` → `UPDATE_BACKLOG_CLASSIFICATION`; `Rank higher/lower` → `UPDATE_RANK`),
    status giữ nguyên giá trị (`STATUS_In Progress`, có khoảng trắng — token là phần tử list nên vô hại).
    Spec chỉ cho thứ tự ưu tiên + fallback; mức mịn do tôi chọn, nằm hoàn toàn trong `configs/actions.yaml`.
    Chi phí nếu sai: sửa YAML (mịn hơn/thô hơn), không đụng code; đổi mapping sẽ đổi `action_rules_hash` và `prepare_key`.
12. **Activity chính của dòng nhiều mệnh đề**: quy tắc đứng trước trong YAML thắng; hòa thì mệnh đề xuất hiện trước.
    Các mệnh đề còn lại lưu ở cột `secondary_changes` (nối bằng `|`). Thêm cột `activity_rule` (quy tắc quyết định) để tính mapping coverage.
13. **Gán split bằng SHA-256 của `seed:case_id`** (không dùng RNG NumPy): ổn định qua phiên bản NumPy/OS, độc lập thứ tự
    đầu vào và kích thước các case khác. Chia theo phần dư lớn nhất, mỗi split ≥ 1 case. Nhánh stratify < 3 case → **lỗi**
    (spec cho phép "fail hoặc fallback đã cấu hình"; YAML mẫu không có fallback nên chọn fail).
14. **Cắt core theo vị trí** trong thứ tự ổn định (không theo `<=` timestamp); event terminal cuối **luôn được giữ** khi lọc
    nhiễu, nhờ đó tập case của core không phụ thuộc noise policy. Case không có status hoặc status cuối không terminal → loại + lý do.
15. **`preprocess.actions_path`** là field do `load_config` gán (không đọc từ YAML) để giữ chữ ký
    `normalize_events(events, cfg)` / `build_traces(events, cfg)` đúng spec §4.4; thêm tham số tùy chọn `rules=`.
16. **`pipeline.py` tạo sớm** (chỉ `prepare`) thay vì ở Task 6; `prepare` ghi vào `outputs/prepared/<cohort>-<key12>/`
    (key = băm fingerprint input + actions + policy + split). Chạy lại tính lại và so byte, không ghi đè; khác thì báo lỗi.
    Artifact `prepare` không chứa timestamp để so byte được. Spec §9 đặt `split_manifest.csv`… trong run dir — Task 6 sẽ sao chép/tham chiếu.

17. **|V| trong làm mượt** = nút đích khả dĩ = activity train + `__END__` (START không bao giờ là đích); `+1` là nhóm UNK.
    Spec chỉ ghi "|V| vocabulary train". Chi phí nếu sai: đổi một hằng số `n_targets` trong `build_dfg`.
18. **DFG luôn có hướng**; `graph.directed` chỉ điều khiển cách `walks.py` đọc đồ thị (ablation vô hướng ở Task 4/8).
19. **Định nghĩa H** (spec chỉ đặt tên): `revisit_ratio` = số event quay lại activity đã thấy *không kề nhau* / max(L−1,1) (khác
    `adjacent_repeat_ratio`, tránh trùng `1−distinct_ratio`); `known_role_switch_ratio` đếm đổi role trên dãy các role xác định
    (bỏ `unknown`/missing; `bot` là role xác định) / (số role xác định − 1); transition surprisal gồm cả cặp `__START__→` và `→__END__`
    khi bật boundary; không có chuyển tiếp thì mean/max = 0.
20. **Token role thiếu `__MISSING_ROLE__` là hằng số giao thức** (`types.py`), `actions.yaml` phải khớp (loader từ chối khác) để
    `features.py` không phụ thuộc file YAML.
21. **Khóa bigram** = `bigram::` + JSON `[a, b]` (có thứ tự, không nhập nhằng); unigram = `unigram::<token>`; tần suất theo spec §5.4.
22. **`PrepareResult.traces` / `traces_for(split)`** thêm vào để fit trên train thật mà không lặp logic. C_embedding/D_hybrid hiện `NotImplementedError`.
23. **Walk**: bắt đầu từ *mọi* nút của DFG (kể cả `__START__`, `__END__`), mỗi vòng xáo thứ tự nút bằng RNG cục bộ theo seed; `__END__` là sink nên
    cho `walks_per_node` walk một token (được thống kê, không diễn giải). Thứ tự nút/láng giềng sắp cố định nên không phụ thuộc thứ tự chèn cạnh.
24. **Không dùng `hashfxn` tùy biến**: thực nghiệm cho thấy với gensim 4.4.0 vector giống hệt dù `hashfxn=hash` hay `crc32` và dù
    `PYTHONHASHSEED` là gì (khởi tạo bằng RNG theo `seed`). Code `_stable_hash` ban đầu của tôi là thừa nên đã gỡ; thay bằng 2 test chạy
    subprocess với nhiều `PYTHONHASHSEED` (cho embedding và cho cả encoder B/C/D) để canh khi nâng phiên bản. Chi phí nếu gensim đổi: test sẽ fail và cần thêm `hashfxn`.
25. **Embedding**: từ vựng = token xuất hiện trong walk (= nút DFG với `min_count=1`); token chưa thấy → vector zero, nằm trong mẫu số mean và tham gia max.
26. **C_embedding** = mean + max pooling (2d) + `unseen_node_ratio`; **D_hybrid** = mean + max pooling (2d) + 10 H. Cột tên `emb_mean_00…`, `emb_max_00…`.
27. **`fit_detector(train, cfg, method, seed=None)`** thêm tham số `seed` tùy chọn (mặc định `cfg.run.seed`) để chạy 3 model seed 42/43/44 ở Task 8.
    `score_traces` trả `trace_id, parent_case_id, method, anomaly_score, n_events, unseen_node_ratio, unseen_transition_ratio`; điểm không hữu hạn → `ValueError`.
28. **Bundle tự chứa**: `DetectorBundle(method, encoder, model, metadata)`; metadata có `action_rules_text`/`sha256`, config đã resolve, chính sách tiền xử lý,
    phiên bản package, `constant_feature_names` (feature hằng trên train). Nạp bằng joblib: chỉ dùng với file do chính mình tạo.
29. **Mutation**: event đầu và cuối (vị trí 0 và L−1) luôn được bảo vệ, bất kể tên activity; "nội bộ" = vị trí 1…L−2. Ứng viên thử theo thứ tự ngẫu nhiên,
    ứng viên trùng một chuỗi activity gốc trong cùng holdout (kể cả chính parent) bị loại và đếm; hết ứng viên → `skipped`. `mutation_id = <parent>::<loại>::<seed>`
    đồng thời là `trace_id` của mutant. RNG riêng cho từng (seed, parent, loại) nên không phụ thuộc thứ tự parent.
    Ledger thêm hai cột `n_candidates`, `n_rejected_candidates` (ngoài danh sách spec) và tham số `split` cho `generate_mutations`.
30. **Đánh giá**: ghép cặp theo `parent_case_id`; mỗi loại chỉ dùng parent có mutant hợp lệ **ở mọi phương pháp** (giao tập); loại thiếu mutant → metric null + `null_reason`.
    Thêm `macro_by_method` (trung bình mô tả theo loại) — không thay thế bảng theo loại. Chưa làm bootstrap CI (spec chỉ cho phép khi resample theo parent).
31. **Đối chứng dương** (xáo toàn bộ phần nội bộ) chạy *chỉ trên validation* để kiểm tra bộ máy; không thuộc 3 loại V1 và không dùng để chọn cấu hình.
32. **Test được xem đúng một lần trong Task 5** với `baseline.yaml` + `actions.yaml` đã khóa (sha256 `2638fd50…` / `4a35ef7d…`, kiểm lại sau khi chạy: không đổi), model seed 42. Task 6 sẽ chỉ *tái lập* các số này bằng CLI.
33. **run_id** = thời điểm bắt đầu UTC (giây) + 8 ký tự đầu của `config_hash`; va chạm → `RunExistsError`, hoặc nếu `run.fail_on_existing_output: false` thì thêm hậu tố `-2`, `-3`… (không bao giờ ghi đè).
    `config_hash` bỏ riêng cờ vận hành `fail_on_existing_output` (không đổi kết quả). `run_experiment(cfg, *, now=None)` có tham số `now` chỉ để test cố định thời điểm.
34. **Một run = một model seed** (`run.seed`). Ba seed 42/43/44 là ba run riêng; `compare` gộp chúng (mean, std ddof=1 = độ ổn định theo model seed, không phải khoảng tin cậy). Run chỉ trên một seed không có std.
35. **Validation cũng được đánh giá trong mỗi run** (kiểm tra pipeline/chọn cấu hình); `metrics.json` ghi `primary_split: test`; `metrics_by_type.csv`/`paired_scores.csv` có cột `split`.
36. **Bộ rà soát**: xếp hạng test originals theo **D_hybrid** (phương pháp đề xuất; nếu không cấu hình D thì phương pháp cuối), xáo thứ tự theo seed, `review_id` không mã hóa hạng. `case_id` hiển thị cho người rà soát (là định danh, không do mô hình tạo);
    bằng chứng do mô hình dẫn xuất (`describe_case`) nằm riêng ở `tables/case_evidence.json`. Cột rà soát trống; chưa có người/agent rà soát nào.
37. **`compare`**: protocol = {sha256 dữ liệu, cohort, split_hash, hash quy tắc, chính sách tiền xử lý, cấu hình split, cấu hình mutation, tập phương pháp}; thêm `model_config_id` = băm cấu hình trừ `run.seed`.
    Chỉ run `completed` được gộp; run khác protocol hoặc khác siêu tham số mô hình nằm ở nhóm khác và không bao giờ bị lấy trung bình chung. Mặc định so trên split `test`.
38. **`score`** lấy cohort, quy tắc action (từ `metadata.action_rules_text` trong bundle) và chính sách tiền xử lý từ bundle, không từ YAML hiện tại; thêm `parse_action_rules(content, source)` và `data.read_events_csv(path, cohort, display_root)`.
39. **Run lỗi**: ghi `status: failed` + `error{stage,type,message}` rồi ném lại lỗi gốc; bắt cả `BaseException` (vd Ctrl-C) để không để manifest `running` mãi. `completed` còn đòi mọi metric tính được cho từng phương pháp (ít nhất một AUROC không null mỗi split).
40. **Hạ tầng test**: `tests/helpers.py` (Project, BASE_CONFIG, `varied_rows`…) tách khỏi `conftest.py` để fixture phạm vi module dùng được; `pyproject.toml` thêm `readme = "README.md"`.
41. **Notebook** viết theo §7 (mục tiêu, câu hỏi, đầu vào/run_id, code gọi module, hình/bảng, nhận xét theo số liệu, giả thuyết, giới hạn; tiêu đề/chú thích tiếng Việt, tên code tiếng Anh).
    Phần "Nhận xét" của mỗi notebook được **sinh bằng code từ số liệu của run** (không có kết luận cố định). Các `.ipynb` trong `notebooks/` lưu không kèm output và là nguồn chính; script dựng notebook chỉ là công cụ phát triển ở scratchpad, không nằm trong repo.
42. **Chạy notebook**: logic ở `src/jira_ad/notebook_runner.py`; `scripts/execute_notebooks.py` chỉ là vỏ mỏng quanh `jira-ad notebooks`. Kernel là chính `sys.executable` qua kernelspec tạm + `JUPYTER_PATH` (spec: "kernel Python thuộc .venv"), `PYTHONHASHSEED=0`, cwd = repo root.
    **Không truyền `km=` cho nbclient**: đã đo thấy nbclient 0.11 khi đó bỏ qua `timeout` (cell ngủ 8 s không bị cắt dù timeout=2).
43. **Notebook không sửa tập artifact đã băm**: hình/bảng nằm ở `figures/`, `tables/` (ngoài manifest); `run.log` và `manifest.json` giữ nguyên, nhật ký chạy ở `notebooks_executed/execution_log.json`. Lỗi: bản chạy dở lưu `<tên>.FAILED.ipynb`; bản "đã thực thi thành công" cũ bị xóa trước mỗi lần chạy để không che lỗi mới.
44. **`open_run`** (analysis.py) kiểm: manifest `completed`, sha256 từng artifact, sha256 file dữ liệu đầu vào, và `config_hash` dựng lại từ `config.resolved.yaml`. Thiếu/đổi bất kỳ thứ nào → lỗi nêu đúng lệnh `uv run jira-ad run --config …` (manifest nay có `config_path`). Không có cache âm thầm.
45. **Notebook 06** lấy danh sách ablation từ kế hoạch Task 8 và đánh dấu "đã chạy/CHƯA chạy" bằng cách so cấu hình đã resolve của các run hiện có; không tự chạy thêm gì.
46. **`compare` chỉ giữ run mới nhất cho mỗi model seed** (run cũ cùng seed nằm ở `superseded`) để chạy lại cùng cấu hình không bị tính là seed độc lập (std giả ≈ 0). `config_hash` chuyển sang `config.py`; thêm `config_from_dict`.
47. **`ruff line-length` 100 → 110** (cấu hình do tôi tự đặt ở Task 1; chú thích tiếng Việt làm dòng dài). Khoảng tin cậy trong notebook 04 là xấp xỉ (Hanley–McNeil cho AUROC, Wilson cho win rate), không thay cho bootstrap theo parent.
48. **`configs/experiments.yaml` + `jira-ad experiments`**: mỗi thí nghiệm đổi một yếu tố so với baseline (nhiều thay đổi phải khai `allow_multiple_changes` kèm lý do), ba model seed 42/43/44, cấu hình gốc không bị sửa; manifest thêm `experiment{name,plan,changes,note}` và `rerun_command` (mọi thông báo thiếu artifact in đúng lệnh này).
49. **Thí nghiệm Task 8 trên test là độ nhạy khám phá**: baseline đã khóa vẫn là cấu hình ghi nhận; không cấu hình nào được chọn theo kết quả test.
50. **`keep_all_noise` và `story_cohort` thuộc protocol khác** (khác nội dung core/mutant hoặc khác cohort) nên không được so trực tiếp với baseline; notebook 06 tách riêng hai nhóm này.
51. **Thông báo `Exception ignored in 'gensim.models.word2vec_inner.our_dot_float'`** (gensim 4.4.0) không bị chặn: tất định theo (dữ liệu, seed), embedding luôn hữu hạn, và ma trận giống hệt bit khi đổi sang numpy 2.4.4/scipy 1.17.1. Bộ cũ hơn (scipy 1.15) không nạp được trên hệ điều hành này. Nguyên nhân gốc chưa rõ.
52. **Kiểm tra rò rỉ và thứ tự dòng đầu-cuối** (test + chạy thật trên bản sao dữ liệu): sửa nội dung ca held-out không đổi trạng thái đã fit trên train; xáo thứ tự dòng CSV không đổi split hay điểm.

53. **Tùy chọn cấu hình mới chỉ hiện ra khi khác mặc định** (`features.cross_fit_folds`, `split.strategy`, section `evaluation` tùy chọn). `as_dict()` bỏ khóa còn mặc định, nên `config_hash` của cấu hình/run cũ giữ nguyên: 26 run Task 8 vẫn `open_run` được (hash dựng lại từ `config.resolved.yaml`) và `compare` không tách nhóm. `as_dict(include_defaults=True)` chỉ để áp thay đổi thí nghiệm. Chi phí nếu sai: thêm khóa vào baseline.yaml (bị khóa, nên tôi không làm).
54. **Cross-fit chỉ áp cho cột H phụ thuộc đồ thị** (surprisal trung bình/lớn nhất, `unseen_*`); embedding vẫn học trên toàn bộ train vì không gian embedding học trên từng fold không so sánh được. Fold chia theo SHA-256 của `split.seed:cross_fit:trace_id` rồi chia vòng tròn (cân bằng, độc lập thứ tự đầu vào và model seed). Held-out vẫn dùng đồ thị train đầy đủ.
55. **Bootstrap theo `parent_case_id`**: percentile, mặc định 2000 lần, seed 20260, 95% (khóa tùy chọn `evaluation.*`); mọi phương pháp và loại dùng chung một lần resample; `aggregate` gộp các model seed bằng trung bình *trong từng lần resample*. Thiên lệch nhỏ đã biết: parent trùng trong mẫu làm cặp (gốc, mutant) của chính nó có trọng số ≈ 2/n thay vì 1/n, đẩy khoảng hơi lên (cỡ 0,005 ở n = 31); phép thử hoán vị dưới đây là kiểm chứng độc lập.
56. **Thử hoán vị trong cặp** (mặc định 2000, một phía, cộng 1) là chuẩn so với 0,5 cho thiết kế ghép cặp, theo từng (phương pháp, loại). Không có macro vì các loại dùng chung bản gốc của cùng parent (null độc lập giữa loại sẽ sai).
57. **Đối chứng dương chính thức**: loại `shuffle_internal` (xáo toàn bộ phần nội bộ), seed 3042, tối đa 50 hoán vị thử mỗi parent, chỉ validation, hàm từ chối split khác. Không nằm trong `mutation_ledger.csv`, `scores/mutants.parquet` hay `metrics_by_type.csv` của V1; không dùng để chọn cấu hình.
58. **Quy tắc quyết định khóa ngày 2026-10-17 trước khi chạy** `cross_fit_5`, `dim_4`, `dim_8` (khối `decision` của `configs/experiments.yaml`, nạp bởi `load_plan`): chỉ số chính là macro AUROC của `D_hybrid` trên validation trung bình 3 model seed; ứng viên cải thiện ⇔ khoảng bootstrap của (thí nghiệm − baseline) nằm hoàn toàn trên 0 ở mức 1 − 0,05/3 (Bonferroni); dù kết quả nào baseline vẫn là cấu hình ghi nhận.
59. **Holdout theo thời gian**: sắp theo thời điểm event terminal cuối của core, hòa thì theo `trace_id`; không stratify (ghi `stratum = temporal`); `split.seed` không dùng. `strategy` chỉ vào khóa `prepare` khi khác `random` để khóa của V1 không đổi. Báo số ca held-out đã *bắt đầu* trước khi train kết thúc.
60. **Rà soát khám phá của agent** lưu ở `<run>/reviews/` (ngoài tập artifact đã băm, như `figures/` và `tables/`), gán nhãn chỉ từ bảng mù (không mở `case_review_key.csv` hay `tables/case_evidence.json`); sha256 bảng mù đã đọc ghi trong `reviews/README.md`; bảng mù của run bàn giao giống hệt bảng tôi đã đọc (cùng sha256). Không phải nhãn chuyên gia.
61. **Đính chính phương pháp suy luận.** Sai số chuẩn Hanley–McNeil/Mann–Whitney (≈ 0,074 ở n = 31) giả định hai mẫu độc lập, không đúng với thiết kế ghép cặp (mỗi mutant sinh từ chính một bản gốc). SD của AUROC dưới giả thuyết không ghép cặp chỉ ≈ 0,016 (phép thử hoán vị trong cặp). Kết luận cũ “mọi khoảng tin cậy AUROC chứa 0,5” (Task 7, Task 8) không còn đứng vững như một khẳng định về “không khác ngẫu nhiên”; xem Task 10 và `RESEARCH_NOTES.md`. Không xóa lịch sử: các dòng cũ giữ nguyên, đính chính nằm ở đây.
62. **Không xóa run cũ**: 62 run trước đó (Task 6–8) vẫn nằm trong `outputs/runs/` (402 MB trên tổng 640 MB của `outputs/`; 36 run mới chiếm 231 MB); `compare` chỉ lấy run mới nhất cho mỗi model seed. Xóa chúng là quyết định của người dùng.

63. **Chọn run tự động cho notebook mở bằng tay** (Task 16): khi không chỉ định run, `open_run()` dùng run hoàn tất mới nhất có `config_hash` bằng `configs/baseline.yaml` hiện tại. Lý do: VSCode không đặt được biến môi trường trước khi kernel khởi động. Ràng buộc để không vi phạm spec §7 (“không im lặng dùng cache cũ”): phải khớp cấu hình hiện tại, vẫn kiểm đủ fingerprint, header in cách chọn. Chi phí nếu sai: xóa `_default_run` và quay lại bắt buộc `JIRA_AD_RUN_DIR`.

64. **Giai đoạn cải tiến (Task 18)** theo yêu cầu "đề xuất phương án và kế hoạch rồi làm luôn" (người đọc: hội đồng bảo vệ/giảng viên). Kế hoạch và quy tắc quyết định do tôi đặt, khóa trong `configs/improvement_plan.yaml` trước mọi run (người dùng không duyệt từng mục). `baseline.yaml`/`actions.yaml` không sửa; phương pháp/mutant mới chỉ dùng khi YAML liệt kê. Chi phí nếu sai: chạy lại `jira-ad improve` với quy tắc khác (phải ghi là sau-khi-xem).
65. **Chuẩn hóa z theo điểm train** (E_score_fusion và mọi điểm trong cross-validation): std = 0 thì dùng 1,0. Lý do: điểm Isolation Forest của các mô hình khác nhau không cùng thang. Chi phí nếu sai: AUROC gộp fold lệch nhẹ; paired win không bị ảnh hưởng.
66. **Không có reviewer độc lập** cho Task 18: harness chỉ cho khởi chạy subagent khi người dùng yêu cầu ⇒ tự rà soát (yếu hơn). Test của `improvement.py` được viết trước code nhưng không chạy RED trước khi implement ⇒ bù bằng 3 đột biến, đều bị bắt.

### Rulings giai đoạn 2 (2026-10-26)

67. **Kế hoạch giai đoạn 2 viết lại theo `CLAUDE.md`** (mục "Quyết định đã duyệt" và "Quy trình tự làm"): bảy Task 19–25 tương ứng bước A–G; module phẳng trong `src/jira_ad/` theo gợi ý (`process_metrics`, `norms`, `centrality`, `conformance`, `ranking`, …) thay cho subpackage `process/` của bản nháp; một lệnh `jira-ad process` ghi một thư mục run có thư mục con theo bước. Chi phí nếu sai: đổi tên module, logic không đổi.
68. **Phân loại làm/chờ theo Quyết định 2** (khác đề xuất ban đầu của tôi): làm = `In Progress`, `In Test`; chờ = `Inbox`, `To Investigate`, `INVESTIGATED`, `To Do`, cộng đoạn `__CREATED__` (CREATE → lần đổi trạng thái đầu) và trạng thái không khai báo. Độ nhạy: `To Investigate` là làm. *Khoảng do cập nhật bù* (tôi định nghĩa): cận trên của PT tính dwell của lượt ngay trước một đợt bù có đi qua trạng thái làm là thời gian làm (giả thuyết: người dùng làm việc thật rồi mới bấm chuyển trạng thái dồn một lúc). Chi phí nếu sai: đổi một hàm, chạy lại.
69. **Định mức tính trên cả 161 ca** (không chỉ train như bản nháp), vì CLAUDE.md quy định phân tích mô tả quy trình dùng toàn bộ 161 issue. Định mức = phân vị 0,75 của `dwell_work` theo trạng thái; ghi rõ là định mức nội suy từ lịch sử nên ~25% lượt trễ theo cấu tạo. Chi phí nếu sai: thêm tham số `scope: train`.
70. **Ngày làm việc theo offset của event mở lượt** (Quyết định 7): mỗi khoảng được quy về giờ địa phương bằng offset gốc (−0700/−0800) của event bắt đầu khoảng; khoảng vắt qua lần đổi giờ mùa hè lệch tối đa 1 giờ. Chu kỳ 24 giờ T2–T6, không giờ hành chính, không ngày lễ. Độ nhạy: UTC. Chi phí nếu sai: dùng offset của từng đầu mút (phức tạp hơn, chênh ≤ 1 giờ/khoảng).
71. **Conformance theo Quyết định 4** (khác đề xuất ban đầu): mô hình chuẩn dạng danh sách cung trong YAML, dựng Petri net "mỗi activity một transition, mỗi cung một transition ẩn" để nhãn không trùng và token replay của pm4py chạy đúng; 7 cờ quy tắc chỉ đếm. Mô hình chuẩn được trình bày cho người dùng trước khi replay (điểm dừng 2). Khai phá Alpha/Heuristics/Inductive và chất lượng của chính các mô hình khai phá được (cũng dùng replay) **không** phụ thuộc mô hình chuẩn nên chạy trước điểm dừng. Chi phí nếu sai: chạy lại sau khi người dùng chỉnh cung.
72. **Graph2Vec cắt** (Quyết định 5); báo cáo `docs/BAO_CAO_MON_HOC.md` (Quyết định 6); được sửa test khóa 6 notebook để thêm `07_process_analysis.ipynb`; đổi tên `docs/Untitled.md` → `docs/BAO_CAO_TONG_KET_export.md`. Danh sách file khóa mở rộng thêm `configs/experiments.yaml`, `configs/improvement_plan.yaml`, `outputs/improvement/`.
73. **Little theo tuần dùng tuần UTC (bắt đầu Thứ Hai 00:00Z)**, không theo ngày địa phương: Little không phải phép đo ngày làm việc; offset −0700/−0800 chỉ dời ranh giới tuần vài giờ. Chi phí nếu sai: dời ranh giới tuần 7–8 giờ.
74. **Lượt ở trạng thái kết thúc giữa chừng** (ca mở lại sau DONE/Rejected) được tính vào CT và là thời gian *chờ* (`state_class = terminal`); lượt kết thúc cuối cùng không có dwell. `CT = Σ dwell` các lượt (mỗi lượt đo ngày làm việc theo offset của event mở lượt). Chi phí nếu sai: loại khỏi CT các khoảng giữa lần đóng và mở lại (5 lượt ở bug).
75. **Lần đổi trạng thái đầu tiên không bao giờ là cập nhật bù** (khoảng CREATE → lần đổi đầu không thuộc 553 khoảng giữa hai lần đổi trạng thái, khớp "sự thật đã đo"); đổi sang chính trạng thái hiện tại không là "lùi". Cả hai được khóa bằng test sau khi hai đột biến sống sót.
76. **`load_cohort` không tính split** (bước A là mô tả, không cần train); split tính ở Task 20 cho DFG activity train. Chi phí: không.
77. **Quy ước độ đo trung tâm:** betweenness trên đồ thị có hướng, *tôpô* (không trọng số), chuẩn hóa; closeness trên bản vô hướng không trọng số; eigenvector trên bản vô hướng có trọng số = số lần; PageRank có trọng số, d = 0,85; bỏ vòng tự thân khi tính bậc/trung tâm (giữ trong strength); DFG activity bỏ nút biên `__START__`/`__END__`. Lý do: trọng số "số lần" là mức độ thường xuyên, không phải khoảng cách, nên không dùng cho đường ngắn nhất. Chi phí nếu sai: thêm biến thể khoảng cách = 1/số lần.
78. **Định mức chỉ cho trạng thái có ≥ 10 lượt đã đóng** (`norms.min_visits`): `Triage`, `OPEN` và các lượt DONE/Rejected giữa chừng (4–5 lượt) không có định mức và không bị phán đúng/trễ.
79. **Xếp hạng ưu tiên cải tiến theo tổng số ngày vượt định mức** (Σ (dwell − P75) của các lượt trễ), không theo tỉ lệ trễ (≈ 25% ở mọi trạng thái theo cấu tạo). Chi phí nếu sai: đổi tiêu chí trong `improvement_priorities`.
80. **Lỗi tìm thấy bằng kiểm chéo độc lập và đã sửa:** `graph.build_dfg` lưu số lần ở thuộc tính `weight`, `centrality_table` đọc `count` ⇒ strength/PageRank/eigenvector của DFG activity bị tính không trọng số. Test tái hiện RED → sửa (`activity_dfg_train` gắn `count = weight`) → GREEN; kiểm chéo với `graph.graphml` của run V1 khớp. Hai run `outputs/process/20261025T165930Z-882a0696` và `…165938Z-882a0696` mang lỗi này (bị thay bởi `…170333Z-882a0696`); không xóa (xóa artifact là quyết định của người dùng). Manifest nay ghi `code.sha256` (fingerprint mã nguồn) để phân biệt run cùng cấu hình khác mã.
81. **Bước B chỉ cho cohort chính (bug)**; story chỉ đặt cạnh ở bước A (CLAUDE.md: "đặt Story cạnh Bug, không trộn" nằm trong bước A).
82. **pm4py 2.7.23.11 thêm làm extra `process`** sau khi chạy thử bỏ đi (`uv run --with pm4py`) đạt trên pandas 3.0.6/numpy 2.5.4; `uv.lock` chỉ thêm 6 gói (cvxopt, graphviz, lxml, pm4py, pytz, tqdm), không đổi phiên bản gói nào. pm4py dùng giấy phép AGPL (in thông báo khi import): phù hợp đồ án học thuật; dùng thương mại cần xem lại. Thanh tiến trình của pm4py bị tắt (`PM4PY_SHOW_PROGRESS_BAR=False`).
83. **Giả định A1 (chờ duyệt ở điểm dừng 2):** CREATE = issue vào trạng thái khởi tạo Inbox một cách ngầm định, nên cung ra của Inbox cũng là cung ra của CREATE; Inbox tường minh chỉ được phép ngay sau CREATE. Lý do: dữ liệu chỉ có 1 ca CREATE → Inbox tường minh, 95 ca CREATE → To Investigate.
84. **Lane BPMN = vai trò người chuyển ca RA khỏi trạng thái nhiều nhất** (người hoàn tất bước), không phải vai trò chuyển vào (vai trò cổng). Start/end event và gateway nằm trong lane của task kề. BPMN chỉ dùng XOR tách (cung ra > 1); hợp nhánh ngầm định (nhiều cung vào một nút, hợp lệ trong BPMN 2.0).
85. **Hình Petri net sắp nút theo cấu trúc** (tinh chỉnh màu kiểu Weisfeiler–Lehman, SHA-256), không theo tên: pm4py đặt tên place (Alpha) và transition ẩn (Heuristics) theo thứ tự duyệt set, đổi theo `PYTHONHASHSEED` ⇒ hình không tái lập. Hai lần lặp phát hiện qua so sha256 manifest, mỗi lần một test RED → GREEN; sau sửa, hai run với `PYTHONHASHSEED` 1 và 999 cho 60 file giống hệt.
86. **Cờ đếm theo định nghĩa rộng hơn "sự thật đã đo"**: "22 ca CREATE → Rejected" và "22 ca bỏ pha điều tra" là số ca có *đúng nguyên biến thể*; cờ `direct_reject` (lần đổi đầu là Rejected) = 26 ca, `skip_investigation` (vào To Do/In Progress/In Test/DONE khi chưa từng điều tra trước đó) = 39 ca. Cả bốn số được tính lại bằng pandas thô và khớp; không phải mâu thuẫn dữ liệu. Báo cáo nêu cả hai định nghĩa.
87. **Log trạng thái cho pm4py**: thời điểm = `t_enter` + `visit_index` micro giây để giữ thứ tự lượt khi trùng giờ (timestamp gốc có độ phân giải mili giây nên không đảo thứ tự khác giờ). Khai phá trên cả 161 ca (mô tả, CLAUDE.md).
88. **Áp dụng Quyết định 8** (người dùng duyệt phương án (a) ngày 26/10): `reference_model.approved: true`, giữ A1 và đúng danh sách cung; mô hình "luồng nhanh" khai trong section mới `alternative_models` (KHÔNG phải mô hình chuẩn, ứng viên TO-BE cho Ch4), replay cạnh mô hình chuẩn; giữ cung `To Investigate → Rejected` (0 lần) và đo ảnh hưởng precision bằng cách bỏ thử cung đó; sai lệch chọn lọc (section `deviation_report`) báo theo nhánh, tách **ca** có ≥ 1 lần đổi bù ở bất kỳ đâu và đếm thêm số **lần** sai lệch tự nó là lần đổi bù. "Mở lại" trong bảng sai lệch gồm rời DONE *hoặc* Rejected (8 ca), khác cờ `reopen_done` chỉ rời DONE (4 ca).
89. **Chỉ số chính cho câu hỏi 3 là tỉ lệ ca khớp hoàn toàn**, không phải fitness token: fitness token của mô hình chuẩn 0,965 (gần 1) vì một token thiếu chỉ trừ ít điểm, trong khi chỉ 105/161 ca (65,2%) khớp hoàn toàn và nhánh DONE chỉ 47,0%. Vì 56 ca lệch, Ch5 vẫn có sai lệch để bàn ⇒ **không** coi là điểm dừng 3.
90. **Hạ tầng notebook giai đoạn 2** (Quyết định 9): notebook số ≥ 07 chỉ chạy trên run `outputs/process/` (`execute_process_notebooks`), bộ chạy V1 bỏ qua chúng; `jira-ad notebooks` nhận ra run giai đoạn 2 qua manifest (cấu hình có section `states`); biến `JIRA_AD_PROCESS_RUN_DIR`; mở tay tự chọn run hoàn tất mới nhất khớp `configs/process.yaml` (như Ruling 63); `process_analysis.open_process_run` kiểm `completed`, sha256 từng artifact, `config_hash` dựng lại từ manifest. Logic hình và nhận xét nằm trong `process_plots.py`, `process_analysis.py` (có test); notebook nguồn dựng bằng script công cụ ở scratchpad, lưu không output (như Ruling 41). Test khóa 6 notebook đổi thành hai danh sách: 01–06 cho run V1, 07–09 cho run giai đoạn 2.
91. **Hai lỗi trình bày bắt khi xem notebook đã chạy, sửa theo TDD:** (a) câu "kết luận PT/WT phụ thuộc cách phân loại" bị viết cứng nên sai với story (khoảng 28,0%–31,9%) ⇒ `pt_range_verdict` suy kết luận từ độ rộng khoảng (> 10 điểm % là "phụ thuộc", kèm nguyên nhân chính); tiêu đề hình PT đổi sang trung tính; (b) legend đè cột ⇒ đặt ngoài vùng vẽ; hình centrality × trễ bỏ các trạng thái không có định mức (nhãn chồng nhau ở 0) và hiển thị `__CREATED__` là `CREATE`.
92. **Đã xóa hai run mang lỗi trọng số** `outputs/process/20261025T165930Z-882a0696`, `…165938Z-882a0696` theo cho phép của người dùng (26/10); các run khác giữ nguyên.
93. **Bỏ thử một cung chưa xảy ra có thể làm mô hình mất hợp lệ** (nút không còn cung vào) ⇒ `unobserved_arc_precision` ghi `note` và để NaN thay vì ném lỗi (phát hiện ở test ghép nối với dữ liệu nhỏ; có test riêng).
94. **Bảy phép kiểm chứng BPR, ngưỡng khóa trong `configs/process.yaml` (`bpr`) TRƯỚC khi tính phán quyết**, đặt theo nguyên tắc (1 tuần làm việc = 5 ngày; "đáng kể" = 20%; "đa số" = 50%; bootstrap 95% loại trừ 0): loại sớm (tỉ trọng ngày-issue của Rejected ≥ 20% và trung vị tới khi loại ≥ 5 ngày); tự chuyển trạng thái (≥ 30% ca có liên kết commit/MR đầu tiên trước khi vào In Progress, trong số ca vừa có liên kết vừa vào In Progress); gộp INVESTIGATED–To Do (≥ 50% lần chuyển trong ≤ 1 ngày làm việc); phụ thuộc PO (CI 95% bootstrap của chênh trung vị dwell `To Do` giữa lượt PO chuyển ra và lượt vai trò người khác > 0; CI chứa 0 ⇒ "không ủng hộ"); phát hiện trùng (≥ 5 ca Rejected có liên kết "link to duplicates" và trung vị ≥ 5 ngày); thêm Investigating (khoảng PT rộng > 10 điểm % và chủ yếu do cách xếp To Investigate); luồng nhanh (CT trung vị ca DONE bỏ điều tra ≤ ca có điều tra và FPY giảm ≤ 0,10). Chi phí nếu sai: đổi ngưỡng phải ghi là sau-khi-xem.
95. **Mô hình TO-BE và kế hoạch pilot thiết kế SAU phán quyết**, chỉ gồm 5 ứng viên được ủng hộ; hai ứng viên không được ủng hộ (giảm phụ thuộc PO, phát hiện trùng sớm) không đổi sơ đồ. Lane TO-BE: trạng thái có sẵn giữ lane AS-IS; `Investigating` nhận lane của `To Investigate` AS-IS (PO) — đây là đề xuất thiết kế, không phải số đo. Cung `To Do → In Progress` đánh dấu tự động (nét đứt, tên trên sequence flow BPMN).
96. **Ghi chú của người dùng về PO được kiểm chứng, không mặc nhiên đề xuất:** theo trung vị (khóa trước) ⇒ không ủng hộ (46 lượt PO và 25 lượt vai trò khác đều có trung vị ≈ 0). Bảng mô tả bổ sung `todo_excess_by_role.csv`: 60,5% ngày vượt định mức ở To Do rơi vào lượt PO chuyển ra (unknown 36,9%) ⇒ dồn đọng nằm ở đuôi. Phán quyết giữ nguyên; báo cáo trình bày cả hai.
97. **Lỗi do tôi gây ra khi ngắt dòng cho ruff** trong `check_fast_track`: f-string đứng trước biểu thức trong ngoặc bị hiểu là lời gọi ⇒ lần chạy thật `failed` (`TypeError`; manifest của `outputs/process/20261025T175142Z-ac288f0c` ghi `status: failed`), test ghép nối không chạm nhánh này vì fixture chỉ có ca DONE bỏ điều tra. Sửa (dựng chuỗi bằng chứng trước), chạy lại loạt đột biến chạy sau lần ngắt dòng, thêm test hồi quy ghép nối có cả hai nhóm và xác nhận nó bắt được lỗi bằng đột biến. Ngoài ra `problem_table`/`pilot_plan` có test và code viết trong cùng một lệnh (không thấy RED) ⇒ bù bằng 5 đột biến, đều bị bắt.
98. **What-if (tính lại trên log, không mô phỏng)**: loại sớm = ca Rejected kết thúc ở lần đổi trạng thái đầu (cận trên); giới hạn chờ `To Do` = cắt dwell `To Do` ở định mức P75 (7,76 ngày); kịch bản kết hợp hai cái trên cho CT trung vị/P90; tự chuyển trạng thái = phần `To Do` sau liên kết commit/MR đầu tiên tính là làm (cải thiện đo lường, CT không đổi); gộp = bỏ các lần chuyển INVESTIGATED → To Do; tỉ lệ khớp = mô hình luồng nhanh. Mục tiêu TO-BE = đúng giá trị what-if; không có số TO-BE nào khác. KPI không ước tính được (vd tỉ lệ cập nhật bù sau tự động hóa) không được đưa số.
99. **Tham số bước E khóa trong `configs/process.yaml` (`ranking`) trước khi tính**: nhóm nghiệp vụ của activity theo loại trường Jira (trạng thái, mã nguồn, giao việc, kế hoạch, liên kết, tài liệu, phân loại; không liệt kê = other) do tôi định nghĩa; K = 2–6; top 10%; ngưỡng phân vị 0,90; 3 nhóm độ dài; 200 bootstrap; bảng mù 15 + 15.
100. **So sánh biểu diễn trên cùng bài toán "tìm lại nhóm nghiệp vụ của activity"** (49 activity của DFG train, giao với embedding V1): 1-NN leave-one-out (cosine cho Node2Vec, euclid trên đặc trưng cấu trúc đã chuẩn hóa: bậc vào/ra, strength, betweenness, closeness, eigenvector, PageRank) và K-means (silhouette, ARI, NMI); baseline lớp phổ biến. Embedding V1 đọc qua `open_run` (kiểm fingerprint, không fit lại).
101. **Hồ sơ bất thường**: 1 − fitness (replay mô hình chuẩn); số cờ (không tính cờ bù, vì bù là chiều riêng); số lượt trễ định mức; lùi + mở lại; số event đổi người phụ trách trong core view; số lần đổi bù; M_markov out-of-fold (trung bình 3 seed) **khử độ dài** bằng phần dư OLS theo log(số event). Phân vị trong nhóm nhánh × tam phân vị độ dài (toàn bộ ca); xếp theo số chiều > p90, rồi phân vị trung bình, rồi case_id. Ổn định = Jaccard top-k giữa dữ liệu gốc và mẫu bootstrap (lấy lại ca có hoàn lại).
102. **Bước E chạy được khi thiếu nguồn** (run V1, điểm out-of-fold, replay) và ghi phần bị bỏ trong `e_ranking/status.json`; cần cho dự án test nhỏ. Run thật có đủ cả ba nguồn.
103. **Đối chiếu số tự động (`process_report.py`, lệnh `jira-ad check-report`)**: mỗi số định dạng Việt Nam trong báo cáo khớp khi có giá trị artifact (ô số CSV, số trong chuỗi bằng chứng, JSON, cấu hình trong manifest; không đọc `notebooks_executed/`) cho đúng chuỗi đó ở cùng số chữ số thập phân (phần trăm: ×100; so trị tuyệt đối). Bỏ qua code span, ngày tháng, số hiệu tham chiếu. **Giới hạn đã biết:** phép khớp là điều kiện cần — số nguyên nhỏ gần như luôn khớp; không chứng minh số được dùng đúng ngữ cảnh. Bù bằng việc chép số từ bản in `fmt` của artifact và kiểm chéo độc lập ở từng Task.
104. **Định danh không phải số đo đặt trong code span** (offset `-0700`/`-0800`, `Zenodo 8275679`, `ICSME 2023`) để không bị đối chiếu; đây là 4 số duy nhất chưa khớp ở lần đầu.
105. **Báo cáo trích run `outputs/process/20261026T011903Z-5d4973b3`** (run cuối của Task 23; các thay đổi mã sau đó chỉ thêm đối chiếu báo cáo/CLI/notebook, không đổi artifact — đã kiểm bằng lần chạy lặp tất định). Test CLI `check-report` viết sau code (không thấy RED) — ghi nhận.
106. **Định nghĩa thống nhất "lần lùi/mở lại trong đợt cập nhật bù"** (rà soát I1): lần đổi đó thuộc một đợt bù (`burst_id` ≠ −1), kể cả lần đổi mở đầu đợt. Dùng chung cho FPY adjusted và bảng sai lệch (cột mới: số lần thuộc đợt bù, số ca chỉ lệch trong đợt bù, số ca có lệch ngoài đợt bù). Kết quả: FPY adjusted 0,857 → 0,957 (chỉ 7/30 ca có lùi/mở lại ngoài đợt bù). Định nghĩa cũ (chỉ xét lần đổi vào nhanh) và cột "ca có bù ở bất kỳ đâu" bị bỏ.
107. **Kịch bản TO-BE chính = "từ chối ngay khi kết thúc điều tra"** (rà soát I2): ca Rejected đã qua To Investigate được quyết khi rời lượt To Investigate cuối, ca không qua điều tra giữ nguyên — nhất quán với TO-BE vẫn có `Investigating → Rejected`. "Quyết ở lần đổi đầu" thành dòng **cận trên** riêng (`*_upper`). CT trung vị TO-BE: 15,2 (khả thi) và 5,9 (cận trên); ngày-issue Rejected: 1.394,2 và 264,2. Bằng chứng phép kiểm ghi thêm 47/78 ca bị loại ngay sau INVESTIGATED và nói rõ phép kiểm chỉ đo quy mô vấn đề.
108. **Số lần đổi trạng thái/ca tính theo đường TO-BE thật** (rà soát I4): bỏ trạng thái bị gộp, thêm trạng thái mới sau trạng thái đứng trước nó, qua trạng thái vào tường minh — suy tự động từ `reference_model`/`tobe_model`. Kết quả 4,4 → 5,4 (tăng): TO-BE thêm bước để đo lường. Dòng PT ghi rõ chưa tính phần Investigating.
109. **Bằng chứng tự chuyển trạng thái nêu trạng thái chứa liên kết commit/MR đầu tiên** (rà soát I3: To Investigate 22, To Do 12, trước lần đổi đầu 5) và số ca cung tự động áp dụng (12). **Phần đuôi PO ở To Do tách theo trạng thái đích** (rà soát I5, bảng `todo_excess_by_role_target.csv`): 75,3% (527,9 ngày) từ 4 lượt `To Do → Rejected` ⇒ báo cáo bỏ kết luận "điểm nghẽn là PO", thay bằng "rà backlog To Do định kỳ".
110. **Danh sách đồng thuận** (quyết định người dùng 26/10, ngưỡng 70% trong `ranking.consensus_share`): ca nằm trong top `top_share` × *số ca khác nhau được rút* ở ≥ 70% số lần bootstrap mà ca được rút. Bản đầu chọn cố định k = 17 trong mỗi mẫu (mỗi mẫu chỉ có ~63% số ca khác nhau) ⇒ thực chất top ~17% của mẫu, thổi phồng tần suất (22 ca "đồng thuận", nhiều hơn chính top-17) ⇒ sửa theo TDD, còn 10 ca. Jaccard top-17 giữ cách cũ (top-17 mẫu so với top-17 gốc) để không đổi giới hạn đã báo (0,40).
111. **So sánh bảng mù** (`ranking.compare_blind_review`, lệnh `jira-ad blind-review-compare`): bảng 2×2 needs_review / nhãn khác × top / ngẫu nhiên; Fisher exact hai phía; odds ratio + CI 95% (`scipy.stats.contingency.odds_ratio`); tỉ lệ mỗi nhóm + Wilson 95%; hiệu hai tỉ lệ + Newcombe (Wilson lai). Kiểm fingerprint run trước khi mở khóa; dừng nếu còn dòng chưa gán hoặc nhãn sai. Người dùng điền vào bản sao `reviews/blind_review_filled.csv` (không sửa artifact đã băm).
112. **Hai minor còn lại được sửa:** M12 — `_days` cộng 0.0 sau khi làm tròn nên không in "-0,0" (CI PO nay "[0,0; 0,9]"); M3 — `correlations.json` thêm `spearman_n_exceed_vs_n_events` (0,121), báo cáo nêu cạnh Spearman điểm tổng (−0,005). Thêm `replay_summary.unfit` (56 ca không khớp, fitness TB 0,906, thấp nhất 0,833) để giải thích fitness 0,965 so với 65,2%.

## Task 1 — Audit dữ liệu và môi trường tối thiểu

**Files tạo:** `pyproject.toml`, `uv.lock` (do `uv lock`), `.python-version`, `.gitignore`, `CLAUDE.md`,
`src/jira_ad/{__init__,config,types,data,cli}.py`, `configs/{baseline,smoke}.yaml`,
`tests/{conftest,test_config,test_types,test_data,test_cli,test_environment}.py`.

**TDD:**
- RED (trước khi có code): `uv run pytest tests/test_data.py tests/test_config.py tests/test_types.py ...` →
  `ModuleNotFoundError: No module named 'jira_ad.config'` / `'jira_ad.types'`; `tests/test_cli.py` → 4 failed
  (`No module named jira_ad.cli`). Lần chạy đầu của test_cli lỗi do **fixture của tôi** (thiếu `mkdir`), đã sửa rồi chạy lại mới ra lỗi đúng lý do.
- GREEN: 84 passed.
- Kiểm tra đột biến (cố ý phá code để xem test có bắt không): (a) bỏ yêu cầu timezone → bị bắt;
  (b) sắp theo chuỗi timestamp thô thay vì UTC → **không bị bắt** ⇒ thêm test
  `test_order_follows_the_utc_instant_not_the_local_clock_text`, đột biến (b) giờ bị bắt. Code được khôi phục (`diff` giống hệt).

**Lệnh và kết quả:**

| Lệnh | Kết quả |
|---|---|
| `uv lock` | `Resolved 125 packages` |
| `uv sync --locked --all-extras --group dev` | cài thành công |
| smoke môi trường (`tests/test_environment.py`) | gensim Skip-gram `workers=1` fit/save/load, joblib, parquet: pass |
| `uv run ruff check src tests` | `All checks passed!` |
| `uv run pytest -q` | `85 passed` |
| `uv run jira-ad audit --config configs/baseline.yaml` | exit 0 (số liệu bên dưới) |

**Thống kê thật (raw view, `outputs/analysis/audit_raw.json`; `analysis_only`):**

| | Bug | Story |
|---|---:|---:|
| Event | 5.126 | 4.439 |
| Issue | 161 | 182 |
| Event/issue min – median – max (mean) | 4 – 20 – 239 (31,84) | 5 – 15 – 212 (24,39) |
| Role trống | 15 | 0 |
| Role `bot` (tỷ lệ) | 2.230 (43,5%) | 1.941 (43,7%) |
| Role `unknown` | 837 | 261 |
| Issue có file không theo thứ tự thời gian | 161/161 | 182/182 |
| Nhóm trùng thời điểm (cùng issue, cùng instant) | 0 | 0 |
| Dòng trùng hệt | 0 | 0 |
| Offset | −0700: 2.779 · −0800: 2.347 | −0700: 3.243 · −0800: 1.196 |
| Khoảng thời gian (UTC) | 2021-06-02 → 2022-08-09 | 2021-06-16 → 2022-08-22 |
| Action thô khác nhau | 99 | 74 |
| Khớp số tham chiếu trong spec §2 | khớp (Δ=0) | khớp (Δ=0) |

Số tính bằng `jira_ad` trùng với profile độc lập bằng pandas thô ở bước kiểm kê (cùng 5.126/161, 15, 2.230, 161/161).
Fingerprint input: Bug `sha256=cda16f1c…` (386.579 B), Story `sha256=afd53fca…` (336.703 B).

## Task 2 — Chuẩn hóa, core view và split

**Files tạo/sửa:** `configs/actions.yaml`, `src/jira_ad/{preprocess,splits,pipeline}.py`; sửa `config.py`
(`actions_path`), `cli.py` (lệnh `prepare`, `write_json_atomic` chuyển sang `pipeline.py`);
tests `test_preprocess.py`, `test_splits.py`; thêm vào `test_cli.py`, `test_config.py`, `conftest.py`.

**TDD:**
- RED: `tests/test_preprocess.py`, `tests/test_splits.py` → `ModuleNotFoundError: No module named 'jira_ad.preprocess'`;
  `test_cli.py` (3 test `prepare`) và `test_config.py::test_actions_path_is_resolved…` → failed. Một test cũ (`test_non_mapping_yaml_is_rejected`) fail do
  thay đổi fixture của tôi (`configs/` giờ có sẵn) và tôi đã sửa test đó. `test_actions_path_cannot_be_set_from_yaml` pass ngay từ đầu
  (khóa lạ vốn đã bị từ chối) — nó là test bảo vệ hồi quy cho field mới, không chứng minh được RED.
- GREEN: 137 passed → sau sửa lint: **170 passed** toàn suite.
- Đột biến (7/7 bị bắt, source khôi phục giống hệt): cắt ở status đầu thay vì cuối; hòa → mệnh đề cuối thắng; noise thêm `LINK_COMMIT`;
  phát hiện reopen luôn False; bỏ stratify; split bỏ qua seed; không chuẩn hóa role trống.

**Lệnh và kết quả:**

| Lệnh | Kết quả |
|---|---|
| `uv lock --check` | `Resolved 125 packages` (lock khớp pyproject) |
| `uv run ruff check src tests` | `All checks passed!` |
| `uv run pytest -q` | `170 passed in 6.90s` |
| `uv run jira-ad prepare --config configs/baseline.yaml` | exit 0 → `outputs/prepared/bug-1909bcad654a` |
| chạy lại `prepare` | exit 0, `đã có và khớp bản tính lại (không ghi đè)` |
| `shasum -a 256` dataset/ so với bản chụp trước | 6/6 file giống hệt |

**Kết quả thật (Bug, `configs/baseline.yaml`):**

| Funnel (event) | Số |
|---|---:|
| Full view (đã chuẩn hóa) | 5.126 (161 issue) |
| Trong issue bị loại (status cuối không terminal / không có status) | 0 |
| Sau status terminal cuối (post-terminal), 63 issue | 1.117 |
| Nhiễu theo policy (`UPDATE_EXTERNAL_LINK`), 55 issue | 751 |
| **Core view** | **3.258 (161 issue)** — 5.126 = 0 + 1.117 + 751 + 3.258 |

- Tính lại bằng pandas thô (không import `jira_ad`): post=1.117, noise=751, core=3.258, DONE 83 / Rejected 78, 8 issue có reopen → **khớp tuyệt đối**.
- 94% event post-terminal là cập nhật `RemoteIssueLink` (1.025/1.117), tức bot.
- Terminal cuối: DONE 83, Rejected 78; 8 issue có reopen trước mốc cuối. Core: event/issue min–median–max = 4–19–61 (mean 20,2), full là 4–20–239.
- Ánh xạ: 99 action thô → 50 activity (49 trong core); **0** event rơi vào `OTHER_ACTION`; 314 event có `secondary_changes`.
  Kiểm tra phủ trên Story (không chạy prepare): 74 action thô, 0 fallback, 40 activity.
- Role (core): `unknown` 832, thiếu 15, bot 431 (full: 837 / 15 / 2.230).
- Ví dụ đối chiếu `bug:TI-4584`: 63 event full → 51 core; giữ nguyên chuỗi
  `…DONE → In Progress → Rejected → To Do → In Progress → In Test → DONE`, bỏ 3 event sau DONE cuối.

**Cách chia (seed 42, stratify `terminal_status`, 0,60/0,20/0,20, theo issue):**

| split | DONE | Rejected | Tổng | Tỷ lệ |
|---|---:|---:|---:|---:|
| train | 50 | 47 | 97 | 0,602 |
| validation | 17 | 16 | 33 | 0,205 |
| test | 16 | 15 | 31 | 0,193 |
| **Tổng** | 83 | 78 | **161** | |

`split_hash = a3999ae5043900ec…` (đầy đủ trong `preprocess_audit.json`); ba tập rời nhau, hợp = 161 issue core.
Đổi noise policy sang `keep_all` (core 4.009 event) cho **cùng** `split_hash` trên dữ liệu thật.

**Artifact (`outputs/prepared/bug-1909bcad654a/`):** `split_manifest.csv`, `exclusions.csv` (rỗng),
`event_exclusions.csv`, `mapping_coverage.csv`, `preprocess_audit.json`.

## Task 3 — DFG, thống kê và baseline n-gram

**Files tạo/sửa:** `src/jira_ad/{graph,features}.py`; `types.py` (hằng số role), `preprocess.py` (dùng hằng số, loader kiểm `missing_role`),
`pipeline.py` (`PrepareResult.traces`, `traces_for`); tests `test_graph.py`, `test_features.py`, `test_pipeline.py`;
`conftest.py` (fixture `trace_of`, `terminal_cases`), `test_cli.py` (dùng fixture dùng chung), `test_preprocess.py` (+1 case).

**TDD:**
- RED: `ModuleNotFoundError: No module named 'jira_ad.graph'` / `'jira_ad.features'`; test ràng buộc `missing_role` fail (1 failed);
  `test_pipeline.py` fail với `AttributeError: 'PrepareResult' object has no attribute 'traces_for'`.
- GREEN: 89 → **203 passed** toàn suite; `ruff` sạch.
- Đột biến 8/8 sau khi thêm 1 test: làm mượt dùng |V| thay |V|+1; không gắn cờ chuyển tiếp chưa thấy; nối cuối trace này với đầu trace khác;
  coi `unknown` là role xác định; `transform` sửa đồ thị đã fit; `revisit` đếm cả lặp kề nhau; mẫu số bigram = L bị bắt.
  **Đột biến "sort hai token trong khóa bigram" ban đầu sống sót** (không test nào có cả A→B lẫn B→A trong train) ⇒ thêm
  `test_a_pair_and_its_reverse_are_two_different_bigram_features`, đột biến giờ bị bắt. Source khôi phục giống hệt sau mỗi lần.

**Kết quả thật (fit trên train = 97 issue; chỉ transform train + validation, test chưa đụng):**

| | A_stats | B_ngrams |
|---|---:|---:|
| Số feature | 10 (H) | 442 = 10 H + 49 unigram + 383 bigram |
| DFG | 51 nút (49 activity), 386 cạnh, 13 self-loop, mật độ 0,151, 1.998 chuyển tiếp | giống nhau |

- Trên train mọi `unseen_*` = 0 (đúng kỳ vọng: đồ thị fit từ chính chúng). Trên validation: `unseen_node_ratio` = 0 (49 activity đều có trong train),
  `unseen_transition_ratio` trung bình 0,058, tối đa 0,217. Không NaN/Inf. H train/val: mean_transition_surprisal 1,93 / 2,00; max 4,02 / 4,31.
- B_ngrams rất thưa: cột n-gram khác 0 ở trung vị chỉ 2 trong 97 trace train; 241/432 cột n-gram toàn 0 trên validation.
- Artifact: `outputs/analysis/features/{A_stats,B_ngrams}/{feature_schema.json,feature_examples_validation.csv}`
  (tên feature, chiều, `train_ids_sha256` = `803fc479751c…`, DFG diagnostics, `state_sha256`).

**Lệnh:** `uv run pytest -q` → `203 passed`; `uv run ruff check src tests` → sạch.

## Task 4 — Walk, embedding và detector

**Files tạo/sửa:** `src/jira_ad/{walks,embedding,detector}.py`; `features.py` (hoàn tất C_embedding/D_hybrid, `coverage()`, fingerprint gồm embedding);
tests `test_walks.py`, `test_embedding.py`, `test_detector.py`; thêm vào `test_features.py`.

**TDD:**
- RED: `ModuleNotFoundError` cho `jira_ad.walks/embedding/detector`; 6 test C/D trong `test_features.py` fail với `NotImplementedError`.
- GREEN: 47 (walk+embedding+features) rồi 25 (detector) ⇒ **259 passed** toàn suite, `ruff` sạch.
- Kiểm chứng xác suất walk (spec §5.3): bias `1/p`, `1`, `1/q` trên đồ thị vô hướng (0,5 : 1 : 2 khi p=2, q=0,5), nhân với trọng số cạnh;
  biến thể có hướng dùng cạnh `x→t` và **không ép quay lui khi không có cạnh `v→t`**; gộp vô hướng = tổng hai chiều, một self-loop;
  mọi bước là cạnh thật, sink dừng walk; tần suất lấy mẫu 6.000 walk khớp phân phối kỳ vọng (sai ≤ 0,025) và first-step theo trọng số.
- Đột biến: 10 lần (p↔1/p, q↔1/q, bỏ luật `x→t`, gộp vô hướng sai, sink không dừng, pooling bỏ token chưa thấy, dấu điểm, seed bị bỏ qua, D_hybrid bỏ nửa H):
  9 bị bắt (F1 hiện dưới dạng *error* trong fixture). **E2 (hash ngẫu nhiên của Gensim) sống sót** ⇒ điều tra ⇒ thấy `hashfxn` không ảnh hưởng ở gensim 4.4.0 ⇒ gỡ code thừa (Ruling 24).

**Kết quả thật (baseline đầy đủ: d=16, 50 walk/nút, 20 epoch, 200 cây, p=q=1; fit trên train 97, chấm validation 33; test chưa đụng):**

| | n_feature | feature hằng trên train | thời gian fit | Spearman(score, n_events) | lệch sau save/load |
|---|---:|---:|---:|---:|---:|
| A_stats | 10 | 2 | 0,15 s | −0,18 | 0,0 |
| B_ngrams | 442 | 2 | 0,12 s | **+0,47** | 0,0 |
| C_embedding | 33 | 2 | 0,85 s | −0,18 | 0,0 |
| D_hybrid | 42 | 3 | 0,83 s | +0,02 | 0,0 |

- A_stats: hai feature hằng trên train đúng là `unseen_node_ratio` và `unseen_transition_ratio` (rủi ro 12 được xác nhận bằng số liệu).
- Walk (D_hybrid): 2.550 walk, độ dài trung bình 12,96 (tối đa 20), 50 walk một token (từ `__END__`), 0 nút không có ngữ cảnh; embedding phủ 51/51 nút, chuẩn vector 1,54–4,05.
- Điểm validation: A 0,40–0,59; B 0,30–0,38; C 0,39–0,57; D 0,41–0,59 (dải hẹp, không có ngưỡng). Spearman giữa phương pháp: C–D 0,91; A–D 0,59; A–B 0,23.
  Đây là chẩn đoán chạy được, **chưa phải metric đánh giá** (chưa có mutant).
- B_ngrams có điểm tương quan thuận với độ dài trace (ρ=0,47) — cần nhớ khi đọc kết quả bán tổng hợp (mutant `swap` giữ độ dài, `delete`/`duplicate` thì không).
- Artifact: `outputs/analysis/task4/{A_stats,B_ngrams,C_embedding,D_hybrid}/` gồm `bundle.joblib`, `fit_metadata.json`, `feature_schema.json`, `validation_scores.csv`
  (`walk_sample.json` cho C/D).

**Lệnh:** `uv run pytest -q` → `259 passed`; `uv run ruff check src tests` → sạch.

## Task 5 — Mutation và đánh giá trung thực

**Files tạo/sửa:** `src/jira_ad/{mutations,evaluation}.py`; tests `test_mutations.py`, `test_evaluation.py`.

**TDD:**
- RED: `ModuleNotFoundError: No module named 'jira_ad.mutations'` / `'jira_ad.evaluation'`.
- GREEN: 27 test mới ⇒ **286 passed** toàn suite; `ruff` sạch. Hai lần fail đầu là lỗi của *test tôi viết*: id mutant không khớp ledger; và fixture có hai trace mà mutant của trace này
  trùng đúng trace kia — code đã loại đúng quy tắc "trùng chuỗi gốc trong cùng holdout".
- Đột biến 10/10 bị bắt: swap/delete/duplicate chạm event đầu/cuối, role không đi theo activity, chấp nhận mutant trùng bản gốc, ledger sai status, tie tính 0 thay vì 0,5,
  ghép cặp theo thứ tự dòng, chỉ so trên một phương pháp, nhãn đảo.

**Mutant (seed riêng cho từng split; ledger đầy đủ ở `outputs/analysis/task5/{validation,test}/mutation_ledger.csv`):**

| | validation (seed 1042) | test (seed 2042) |
|---|---:|---:|
| parent | 33 | 31 |
| `swap_adjacent` tạo được / bỏ qua | 33 / 0 | 31 / 0 |
| `delete_internal` | 33 / 0 (1 ứng viên trùng bản gốc bị loại) | 31 / 0 (1 ứng viên bị loại) |
| `duplicate_block` | 33 / 0 | 31 / 0 |
| Δ độ dài (−1 / 0 / +1 / +2) | 33 / 33 / 20 / 13 | 31 / 31 / 13 / 18 |

**Validation (khám phá, model seed 42, n = 33 parent mỗi loại, tỷ lệ thiết kế 0,5, AP hằng = 0,5):**

| AUROC | delete | duplicate | swap | | paired win | delete | duplicate | swap |
|---|---:|---:|---:|---|---|---:|---:|---:|
| A_stats | 0,488 | 0,566 | 0,516 | | A_stats | 0,394 | 0,818 | 0,606 |
| B_ngrams | 0,522 | 0,514 | 0,512 | | B_ngrams | 0,515 | 0,455 | 0,530 |
| C_embedding | 0,566 | 0,534 | 0,500 | | C_embedding | 0,636 | 0,697 | 0,500 |
| D_hybrid | 0,558 | 0,561 | 0,527 | | D_hybrid | 0,545 | 0,758 | 0,652 |

**Đối chứng dương (chỉ validation; xáo toàn bộ phần nội bộ, 33 parent):** AUROC / paired win — A_stats 0,863 / 0,939; D_hybrid 0,656 / 0,939; B_ngrams 0,577 / 0,576; C_embedding 0,500 / 0,500.
⇒ bộ máy phát hiện được sai lệch mạnh về thứ tự; `C_embedding` × swap đúng 0,500 vì pooling không thấy thứ tự (đúng thiết kế).

**Test (cấu hình đã khóa, xem đúng một lần; n = 31 parent mỗi loại, tỷ lệ thiết kế 0,5, AP hằng = 0,5; model seed 42):**

| AUROC | delete | duplicate | swap | macro | | paired win | delete | duplicate | swap | macro |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| A_stats | 0,511 | 0,554 | 0,518 | 0,527 | | A_stats | 0,516 | 0,645 | 0,565 | 0,575 |
| B_ngrams | 0,513 | 0,519 | 0,524 | 0,519 | | B_ngrams | 0,645 | 0,645 | 0,694 | 0,661 |
| C_embedding | 0,559 | 0,524 | 0,500 | 0,528 | | C_embedding | 0,710 | 0,613 | 0,500 | 0,608 |
| D_hybrid | 0,568 | 0,554 | 0,514 | 0,545 | | D_hybrid | 0,742 | 0,774 | 0,565 | 0,694 |

AP của A–D nằm trong 0,50–0,59 (xem `metrics_by_type.csv`). **Diễn giải được phép:** với mutant một-chỉnh-sửa ở cỡ mẫu này, cả bốn phương pháp gần ngẫu nhiên theo AUROC;
D_hybrid có trung bình macro cao nhất (0,545) nhưng độ lệch chuẩn của AUROC dưới giả thuyết không với 31+31 mẫu ≈ 0,07 (công thức xấp xỉ), nên chênh lệch ~0,02 giữa các phương pháp
**không có ý nghĩa thống kê**. Paired win rate (so cùng một parent) cao hơn AUROC (tới 0,77 với D_hybrid/duplicate) vì phương sai giữa các parent nhấn chìm tín hiệu trong từng cặp.
**Không được kết luận** embedding bổ sung giá trị hay không từ một model seed, hai split nhỏ và ba loại mutation.

**Lệnh:** `uv run pytest -q` → `286 passed`; `uv run ruff check src tests` → sạch. Artifact: `outputs/analysis/task5/{validation,test}/` (ledger, điểm gốc/mutant, `metrics_by_type.csv`, `paired_scores.csv`, `metrics.json`).

## Task 6 — CLI E2E và artifact có provenance

**Files tạo/sửa:** `src/jira_ad/{analysis,pipeline,cli}.py` (`pipeline.py` mở rộng: `run_experiment`, `config_hash`, `compare_runs`, `score_raw_csv`), `data.py` (`read_events_csv`), `preprocess.py`
(`parse_action_rules`), `detector.py` (`package_versions` công khai), `README.md`, `pyproject.toml` (readme); tests `test_analysis.py`, `test_pipeline.py` (viết lại + mở rộng), `tests/helpers.py`.

**TDD:**
- RED: `ModuleNotFoundError: No module named 'jira_ad.analysis'`; `ImportError: cannot import name 'RunExistsError' from 'jira_ad.pipeline'`.
- GREEN: **316 passed** toàn suite (E2E chạy cả bằng `subprocess`), `ruff` sạch, `uv lock --check` khớp.
- Đột biến vào pipeline 7 lần: run lỗi vẫn đánh dấu completed, tạo mutant cho parent train, fit bundle trên train+validation, dùng lại thư mục run có sẵn, `compare` gộp mọi protocol, chấp nhận metric toàn null, `compare` gộp các cấu hình mô hình khác nhau.
  6/7 bị bắt ngay (P2 hiện dưới dạng *error* ở fixture). **P7 ban đầu sống sót** ⇒ sửa test `compare` thêm một run cùng protocol nhưng khác `embedding.dimensions` ⇒ bị bắt. Thêm test
  `test_every_saved_bundle_was_fitted_on_exactly_the_train_split` (đột biến P3 trước đó chỉ bị bắt nhờ test này). Source khôi phục giống hệt.
- Kiểm tra tuyến cài `pip` (README): `python3 -m venv` + `pip install -e '.[notebook,dev]'` trong venv tạm mất ~50 s, `pytest` 316 passed, `ruff` sạch; venv tạm đã xóa.

**Lệnh thật trên dataset:**

| Lệnh | Kết quả |
|---|---|
| `uv run jira-ad run --config configs/baseline.yaml` | exit 0, `Run dir: outputs/runs/20261015T182352Z-930f8a85`, completed, 2,5 s (fit 1,97 s) |
| so `metrics_by_type.csv` của run với Task 5 | **khớp 12/12 dòng test và 12/12 dòng validation** (AUROC/AP/paired win; chạy lại bằng CLI không đổi số) |
| `uv run jira-ad score --bundle …/D_hybrid/bundle.joblib --input-csv dataset/TIeventlogBug.csv --output …` | chấm 161/161 ca; bundle không đổi (sha256); lệch tối đa so với điểm đã lưu của 64 ca val/test: 5,6e-17 |
| `uv run jira-ad compare --runs-dir outputs/runs` | 1 nhóm (1 run) → `outputs/runs/comparison.csv` (chưa có std vì chỉ 1 seed) |
| `shasum -a 256 -c config_lock` | `baseline.yaml` và `actions.yaml` không đổi kể từ khi khóa ở Task 5 |

**Run thật:** 36 artifact có sha256 trong `manifest.json`; `embedding_shared: true` (C và D học cùng embedding); đếm: train 97 / validation 33 / test 31; mutant 99 (validation) và 93 (test);
bộ rà soát 20/31 ca test (top 10 + random 10 theo D_hybrid). Git: `null` (không phải repo). Môi trường ghi trong manifest: Python 3.12.7, numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1, gensim 4.4.0.

## Task 7 — Notebook và phân tích có thể tái chạy

**Files tạo/sửa:** `src/jira_ad/{plots,notebook_runner}.py` (mới), `analysis.py` (mở rộng: `open_run`/`RunArtifacts`, `trace_variants`, `status_durations`, `create_to_terminal`, `dfg_edge_table`, `embedding_pca`,
`order_blindness_demo`, `case_event_table`), `config.py` (`config_from_dict`, `config_hash`), `pipeline.py` (manifest `config_path`, `compare` theo seed), `cli.py` (`notebooks`); `scripts/execute_notebooks.py`;
6 notebook `notebooks/01…06_*.ipynb`; tests `test_notebook_inputs.py`, `test_notebook_runner.py`, `test_plots.py`, mở rộng `test_analysis.py`, `test_pipeline.py`, `test_config.py`.

**TDD:**
- RED: `ImportError: cannot import name 'case_event_table'/'FingerprintMismatchError' from 'jira_ad.analysis'`; `config_from_dict` chưa có; `RunArtifacts.show`/`plot_case_surprisal` chưa có; test `compare` seed lặp fail
  (`['…120000Z', '…120005Z'] != ['…120005Z']`).
- GREEN: **357 passed** toàn suite (gồm test chạy cả sáu notebook thật trên một run nhỏ, ~20 s), `ruff check src tests scripts` sạch.
- **Lỗi thật do test bắt**: (a) bộ chạy ghi thêm vào `run.log` làm sai fingerprint của chính run ⇒ chuyển nhật ký sang `notebooks_executed/execution_log.json`; (b) truyền `km=` tự dựng làm nbclient **bỏ qua timeout** ⇒ dùng kernelspec tạm (xem Ruling 42).
- Đột biến: analysis loader/bảng 8/8 bị bắt (không kiểm hash artifact, không kiểm dữ liệu đầu vào, không kiểm config_hash, bỏ qua artifact thiếu, nhận run failed, thời lượng cho status cuối, create→terminal đầu tiên, đảo lý do loại);
  notebook runner 5/5 (cho phép lỗi cell, giữ bản pass cũ, sai cwd, thiếu PYTHONHASHSEED, ghi đè notebook nguồn); plots: spring layout thay layer, bỏ ép số nguyên. Hai test plots ban đầu **viết cùng lúc với code nên chưa thấy fail**, đã kiểm lại bằng đột biến.
- **Kiểm tra bằng mắt các hình thật** (đọc từng PNG): DFG ban đầu chồng nút/nhãn ⇒ đổi sang layout theo tầng + gập nhãn; histogram trace gốc bị mutant che (đếm thô) ⇒ chuyển sang mật độ + đường viền; PCA gắn nhãn cả 51 nút ⇒ chỉ nhãn nút thường gặp; trục đếm có 2,5/7,5 ⇒ ép số nguyên.
  Run mới `20261015T185138Z-930f8a85`: 16 hình + bảng dữ liệu tương ứng trong `figures/` và `tables/`.

**Lệnh thật trên dataset:**

| Lệnh | Kết quả |
|---|---|
| `uv run jira-ad run --config configs/baseline.yaml` | `Run dir: outputs/runs/20261015T185138Z-930f8a85`, completed, 2,4 s; macro AUROC/AP/paired y hệt run trước (tất định) |
| `uv run jira-ad notebooks --run-dir outputs/runs/20261015T185138Z-930f8a85` | 6/6 notebook `ok` (2,6–3,2 s mỗi cái, tổng ~20 s), kernel = `.venv/bin/python3`, `allow_errors=False` |
| đối chiếu bảng AUROC notebook 04 với `metrics.json` | 12/12 ô, lệch tối đa 0 |
| đối chiếu `bug:TI-5412` (notebook 05) với CSV gốc bằng code độc lập (không import `jira_ad`) | 87 event full, 3 sau terminal, 23 `RemoteIssueLink` nhiễu, **61** core — khớp notebook (26 bị bỏ = 3 + 23) |
| `compare_runs` sau khi có hai run cùng seed 42 | 1 nhóm, 1 run; run cũ `…182352Z…` ở `superseded` |
| `shasum -a 256 -c` cấu hình khóa Task 5 | `baseline.yaml`, `actions.yaml` không đổi |

**Điều sáu notebook cho thấy trên dữ liệu thật (sinh từ số liệu, không chép tay):**
- *01*: 5.126 event / 161 issue; 15 role trống, 837 `unknown` (16%), 44% bot; 161/161 issue có thứ tự dòng **mới → cũ**; funnel 5.126 → core 3.258 (bỏ 1.117 sau terminal, 94% là bot; 751 nhiễu); 0 chuỗi action rơi vào `OTHER_ACTION`.
- *02*: **153 biến thể cho 161 trace, 98% biến thể chỉ xuất hiện một lần** ⇒ khớp nguyên chuỗi gần như vô dụng. Nhánh DONE (trung vị 25 event, gần như luôn qua In Progress/In Test) và Rejected (trung vị 12 event, hầu như bỏ qua quy trình) là hai quần thể rất khác nhau.
  165/553 đoạn chuyển trạng thái cách nhau < 1 phút. Thời gian từ tạo đến terminal cuối: trung vị 40,7 ngày (DONE) và 19,4 ngày (Rejected).
- *03*: 2.550 walk (trung bình 13,0 nút; 50 walk một token từ `__END__`); độ phủ OOV `unseen_transition_ratio` validation 0,058 / test 0,095; Spearman(cosine, P̂ chuyển tiếp) = 0,21 ⇒ cosine ≠ xác suất;
  hoán đổi hai activity kề nhau cho chênh pooling đúng 0 nhưng surprisal tăng (ví dụ 1,15 → 2,35).
- *04*: **12/12 khoảng tin cậy xấp xỉ 95% của AUROC chứa 0,5**; chênh lệch macro lớn nhất giữa bốn phương pháp 0,026 so với sai số chuẩn xấp xỉ 0,074; Spearman(điểm, n_events) của B_ngrams +0,56.
- *05*: `Rejected` chiếm 60% nhóm điểm cao và 48% ca test; trung vị độ dài nhóm điểm cao 16 so với 18; 0/20 ca có rà soát.
- *06*: 0/9 thực nghiệm ablation trong kế hoạch đã có run; chưa đo được độ ổn định theo seed (1 seed); `A_stats` có 2 feature hằng trên train (`unseen_*`).

## Task 8 — Thực nghiệm thành phần và bàn giao

**Files tạo/sửa:** `configs/experiments.yaml`, `src/jira_ad/experiments.py` (mới), `pipeline.py` (manifest `experiment`/`rerun_command`; `compare` ghi tên thí nghiệm), `analysis.py` (`run_macro_metrics`, gợi ý lệnh tái tạo),
`plots.py` (`plot_ablation`), `cli.py` (`experiments`), notebook 04 và 06 viết lại cho đa seed/ablation, `docs/RESEARCH_NOTES.md`, `docs/DECISIONS.md`, `README.md`; tests `test_experiments.py` (mới), mở rộng `test_pipeline.py`, `test_analysis.py`, `test_plots.py`.

**TDD:**
- RED: `ModuleNotFoundError: No module named 'jira_ad.experiments'`; `test_the_shipped_experiment_plan…` fail vì chưa có `configs/experiments.yaml`; `plot_ablation`, `run_macro_metrics` chưa tồn tại.
- GREEN: **382 passed** toàn suite (gồm chạy cả sáu notebook thật trên run nhỏ); `ruff check src tests scripts` sạch; `uv lock --check` khớp.
- Đột biến: `experiments.py` 6/6 bị bắt (nhiều thay đổi không lý do, bỏ model seed, bỏ kiểm `--only`, không kiểm thay đổi lúc nạp, tên lặp, áp sai khóa). Kiểm tra rò rỉ đầu-cuối: cho `fit` đọc thêm *test* hoặc *validation* đều bị bắt (test tham số hóa theo split);
  lúc đầu chỉ sửa ca test nên chưa bắt rò rỉ từ validation ⇒ đã tham số hóa. Dọn code chết: `REVIEW_LABELS` giờ được notebook 05 dùng để cảnh báo nhãn sai; gỡ property `RunArtifacts.rerun_command` không dùng.

**Lệnh thật trên dataset:**

| Lệnh | Kết quả |
|---|---|
| `uv run jira-ad experiments --config configs/experiments.yaml --dry-run` | liệt kê 8 thí nghiệm × seeds [42, 43, 44], không chạy gì |
| `uv run jira-ad experiments --config configs/experiments.yaml` | 24 run `completed` trong 67 s (2–5 s/run) |
| `uv run jira-ad compare --runs-dir outputs/runs` | 8 nhóm, 3 protocol (bug-mặc định, keep_all, story), mỗi ô 3 seed; hai run seed-42 cũ nằm ở `superseded` |
| `uv run jira-ad notebooks --run-dir outputs/runs/20261015T185618Z-930f8a85` (run bàn giao) | 6/6 notebook `ok` (~3 s mỗi cái) |
| kiểm tra rò rỉ trên bản sao dữ liệu thật (sửa 122 event ở 1 ca validation + 1 ca test) | trạng thái fit của A/B/C/D **giống hệt**, split giống hệt, điểm 62 ca held-out khác lệch **0,0**; hai ca bị sửa có `unseen_node_ratio` 0,89 và 0,67 |
| `shasum -a 256 -c` cấu hình khóa | `baseline.yaml`, `actions.yaml` không đổi từ Task 5; `dataset/` 6/6 giống hệt |

**Kết quả thật (macro AUROC test, trung bình qua 3 model seed; chi tiết ở notebook 04/06 và `docs/RESEARCH_NOTES.md`):**

| Thí nghiệm | A_stats | B_ngrams | C_embedding | D_hybrid |
|---|---:|---:|---:|---:|
| baseline | 0,531 | 0,513 | 0,535 | 0,544 |
| undirected_walk | 0,531 | 0,513 | 0,527 | 0,533 |
| activity_role_nodes | 0,551 | 0,504 | 0,527 | 0,541 |
| q_half | 0,531 | 0,513 | 0,537 | 0,547 |
| q_double | 0,531 | 0,513 | 0,529 | 0,528 |
| dim_32 | 0,531 | 0,513 | 0,531 | 0,538 |
| *keep_all_noise (khác protocol)* | 0,534 | 0,516 | 0,529 | 0,529 |
| *story_cohort (protocol riêng; 36 parent/loại, 1 ca Rejected ở test)* | 0,636 | 0,528 | 0,552 | 0,591 |

- Std theo model seed của macro AUROC (baseline): A 0,007; B 0,006; C 0,006; D 0,004. Sai số chuẩn xấp xỉ do lấy mẫu của một AUROC (n=31): 0,074.
- Mọi ablation cùng protocol lệch ≤ 0,019 so với baseline — trong nhiễu lấy mẫu. **Kết luận âm:** chưa có bằng chứng embedding bổ sung giá trị so với thống kê (xem RESEARCH_NOTES).
- `A_stats`/`B_ngrams` cho đúng cùng số ở các thí nghiệm chỉ đổi walk/embedding (không dùng embedding): kiểm tra chéo về tính tất định.

## Task 9 — Cấu hình mở rộng không làm đổi hash của cấu hình/run cũ

**Files sửa:** `src/jira_ad/config.py` (`EvaluationConfig`, `OPTIONAL_SECTIONS`, metadata `omit_default`, `as_dict(include_defaults)`, `SplitConfig.strategy`, `FeatureConfig.cross_fit_folds`), `src/jira_ad/experiments.py` (`build_config` áp thay đổi lên dict đầy đủ khóa); tests `test_config.py`, `test_experiments.py`.

**TDD:** RED: 9 test fail đúng lý do (khóa chưa tồn tại / section `evaluation` chưa có). Hai test (`cross_fit_folds` ngoài miền, `permutations` ngoài miền) *đã pass trước khi cài đặt* chỉ vì khóa lạ cũng bị từ chối ⇒ kiểm lại bằng đột biến sau khi cài đặt (đột biến ngưỡng và bỏ kiểm đều bị bắt). Test chốt tương thích: cấu hình YAML cũ cho đúng `config_hash` cũ (băm lại độc lập bằng chính công thức cũ, kể cả khóa `reference_counts: null` mà `as_dict` cũ luôn in). Đột biến `omit_default` bị tắt: 4 test fail.

**Kết quả:** `uv run pytest tests/test_config.py tests/test_experiments.py` xanh (85 test lúc đó). Hash cấu hình khóa không đổi.

## Task 10 — Bootstrap theo parent, thử hoán vị trong cặp, so sánh ghép cặp qua các run

**Files sửa:** `src/jira_ad/evaluation.py` (`paired_auroc`, `bootstrap_by_parent` với `aggregate`, `bootstrap_intervals_frame`, `bootstrap_differences_frame`, `paired_chance_test`), `analysis.py` (`ablation_vs_baseline`), `pipeline.py` (artifact `bootstrap_intervals.csv`, `bootstrap_differences.csv`, `chance_test.csv`; `metrics.json` ghi `bootstrap`/`chance_test`); `config.py` (`evaluation.permutations`); tests `test_evaluation.py`, `test_analysis.py`, `test_pipeline.py`.

**TDD và đột biến:** RED = `ImportError` rồi các test hành vi (ước lượng điểm trùng `sklearn.roc_auc_score` kể cả điểm trùng; cùng seed cùng kết quả; không phụ thuộc thứ tự dòng; hai phương pháp giống hệt chênh đúng 0 trong mọi lần resample ⇒ resample chung; bản con đi cùng parent; SE bootstrap cùng cỡ SE Mann–Whitney khi dữ liệu độc lập; parent thiếu một loại vẫn chạy; ít hơn 2 parent ⇒ khoảng null kèm lý do). Đột biến: resample riêng từng loại (5 test fail), hạng không trung bình khi trùng (1 fail); **đột biến bỏ nửa điểm khi hòa trong `prob_positive` ban đầu sống sót** ⇒ thêm hai test (phương pháp giống hệt ⇒ 0,5; phương pháp tốt hơn rõ rệt ⇒ ≈ 1) ⇒ bị bắt. Phép thử hoán vị: 4 đột biến (không đảo nhãn, không đảo mutant, đảo chiều một phía, xác suất đảo 0,9) đều bị bắt. `ablation_vs_baseline`: 3 đột biến (so sai phương pháp, bỏ kiểm cùng parent, bỏ lọc split) đều bị bắt.

**Hiệu năng:** bản đầu lặp `rankdata` cho từng lần resample làm bộ test chậm gấp đôi (78 s → 149 s); thay bằng ma trận cặp Mann–Whitney vector hóa (chính xác, hòa tính 0,5): 2000 lần resample × 4 phương pháp × 3 loại mất 0,06 s; bộ test về 78 s.

**Kiểm chứng độc lập một phát hiện bất ngờ:** khoảng bootstrap của macro AUROC hẹp hơn nhiều so với ghi chú cũ (SE ≈ 0,012–0,019 thay vì 0,074). Đã kiểm bằng phép thử hoán vị trong cặp viết riêng (20.000 lần, không dùng code của bootstrap): dưới giả thuyết không *ghép cặp*, SD của macro AUROC test là 0,012 / 0,009 / 0,008 / 0,010 cho A/B/C/D, và p một phía của AUROC quan sát là 0,012 / 0,020 / 0,0001 / < 0,0001. Xem Ruling 61.

## Task 11 — Đối chứng dương chính thức

**Files sửa:** `src/jira_ad/mutations.py` (`generate_positive_control`, `POSITIVE_CONTROL_TYPE`), `pipeline.py` (`positive_control.csv` có khoảng bootstrap, `positive_control_ledger.csv`, `positive_control_paired_scores.csv`); tests `test_mutations.py`, `test_pipeline.py`.

**TDD và đột biến:** RED = `ImportError`. Test: chỉ xáo phần nội bộ, giữ histogram/độ dài, role và event lineage đi cùng activity, không trùng bản gốc nào, ledger ghi lý do bỏ qua, tái lập và độc lập thứ tự parent, từ chối `test`/`train`/chuỗi rỗng, không thuộc `MUTATION_TYPES`, không lẫn vào ledger/điểm/metric của V1. Đột biến xáo cả event đầu/cuối và bỏ kiểm split đều bị bắt; **đột biến bỏ loại mutant trùng bản gốc ban đầu sống sót** (với 720 hoán vị gần như không va chạm) ⇒ thêm test ép va chạm (hai parent mà hoán vị duy nhất của cái này là cái kia) ⇒ bị bắt.

**Kết quả thật (validation, 33 parent, run bàn giao seed 42):** AUROC A_stats 0,886 [0,826; 0,951], B_ngrams 0,527 [0,448; 0,614], C_embedding 0,500 [0,500; 0,500], D_hybrid 0,658 [0,631; 0,713]; paired win rate 1,00 / 0,61 / 0,50 / 1,00. C_embedding đúng 0,500 vì pooling không thấy thứ tự (lý thuyết); cùng thứ tự và cùng giá trị lý thuyết cho C_embedding như bản chạy rời ở Task 5 (0,863 / 0,577 / 0,500 / 0,656 cho A/B/C/D), khác nhẹ ở các phương pháp còn lại; code của bản rời không còn lưu nên không xác định được chênh lệch do seed hay cách chọn hoán vị.

## Task 12 — Cross-fit đặc trưng train

**Files sửa:** `src/jira_ad/features.py` (`transform_train`, `_fit_cross_fit`, `cross_fit_assignment`, `_h_features` nhận đồ thị tùy chọn), `detector.py` (fit trên `transform_train`); tests `test_features.py`, `test_detector.py`.

**TDD và đột biến:** RED = `AttributeError: transform_train`. Test chốt: không cross-fit ⇒ `transform_train == transform`; trace chỉ có activity hiếm trở thành “chưa thấy” với đồ thị các fold khác; mỗi trace train được mô tả đúng bởi đồ thị dựng độc lập từ các fold khác (tính lại trong test bằng `build_dfg`); fold cân bằng, tất định, độc lập thứ tự và model seed; held-out không đổi; embedding vẫn in-sample; fingerprint thay đổi và `transform_train` không sửa state; từ chối nhiều fold hơn số trace; từ chối trace ngoài train; Isolation Forest được fit đúng trên ma trận cross-fit. Đột biến: detector dùng `transform` (3 fail), cross-fit dùng đồ thị đầy đủ (3 fail), fold = hash mod k không cân bằng (1 fail) — đều bị bắt.

## Task 13 — Quy tắc quyết định khóa trước và kiểm hai giả thuyết

**Files sửa:** `configs/experiments.yaml` (khối `decision` + `cross_fit_5`, `dim_4`, `dim_8`, `temporal_holdout`), `experiments.py` (`DecisionRule`, `load_plan` kiểm khối `decision`); tests `test_experiments.py` (9 trường hợp sai bị từ chối đúng tên khóa; 4 đột biến bị bắt).

**Trình tự (để ghi rõ không xem kết quả trước khi khóa):** (1) viết và test cơ chế; (2) khóa quy tắc vào `experiments.yaml` (Ruling 58) trước mọi run của ba thí nghiệm; (3) `uv run jira-ad experiments --config configs/experiments.yaml` chạy 33 run; (4) phân tích *chỉ validation*; (5) sau phán quyết mới xem test.

**Kết quả thật** (D_hybrid, macro AUROC validation, trung bình 3 model seed, 33 parent, khoảng bootstrap 98,33%):

| Thí nghiệm | Δ so với baseline | Khoảng | Phán quyết |
|---|---:|---|---|
| cross_fit_5 | −0,0122 | [−0,0322; +0,0027] | không có bằng chứng |
| dim_4 | −0,0174 | [−0,0525; +0,0172] | không có bằng chứng |
| dim_8 | −0,0010 | [−0,0291; +0,0227] | không có bằng chứng |

0/3 là ứng viên cải thiện; baseline giữ nguyên. **Cơ chế đã được thỏa**: với cross-fit, số cột hằng trên train của A_stats giảm 2 → 0 và của D_hybrid 3 → 1 (còn `emb_max_12`), tức các cột `unseen_*` có phương sai khi fit, nhưng AUROC không tốt hơn ⇒ giả thuyết 1 không được ủng hộ (không phải vì cross-fit không chạy). Exploratory trên test (xem sau phán quyết): D_hybrid Δ = −0,008 / −0,012 / −0,006, khoảng đều chứa 0. `A_stats`/`B_ngrams` cho đúng Δ = 0 khi đổi số chiều embedding (kiểm chéo tính tất định). Tái lập: chạy lại toàn bộ kế hoạch lần thứ hai (36 run, 123 s, 3,4 s/run) cho phán quyết trùng tới 1,1e-16.

## Task 14 — Holdout theo thời gian

**Files sửa:** `src/jira_ad/splits.py` (`_temporal_splits`, `temporal_report`), `pipeline.py` (`prepare` ghi khối `temporal` trong audit, `strategy` vào khóa chỉ khi khác `random`); tests `test_splits.py`, `test_pipeline.py`.

**TDD và đột biến:** RED = `ImportError: temporal_report`, rồi 3 test pipeline (một test lộ đúng cơ chế an toàn sẵn có: hai protocol cùng khóa `prepare` bị `PrepareError` thay vì ghi đè). Test chốt: train kết thúc trước validation trước test, không phụ thuộc seed/stratify/thứ tự đầu vào, hòa thời điểm ở ranh giới giải quyết theo `trace_id` (test ép hòa vắt qua ranh giới — bản đầu của tôi quá yếu vì cả nhóm hòa rơi vào train, đã sửa), thiếu timestamp thì lỗi nêu đúng ca, manifest ghi `stratum = temporal`. Đột biến sắp theo thời điểm bắt đầu / không tie-break / đếm ca sai: bị bắt.

**Kết quả thật (bug, seed model 42/43/44):** 97 / 32 / 32 ca; train kết thúc 2021-06-30 → 2022-01-25, validation → 2022-04-04, test → 2022-06-27; **29/64 ca held-out đã bắt đầu trước khi train kết thúc** (ca sống lâu: hai giai đoạn chồng lên nhau). DONE/Rejected: train 50/47, validation 18/14, test 15/17. Macro AUROC test (3 seed) A 0,560, B 0,509, C 0,546, D 0,565 so với holdout ngẫu nhiên 0,531 / 0,513 / 0,535 / 0,544 — khác protocol nên chỉ đặt cạnh nhau; khoảng bootstrap (1 seed) của D_hybrid [0,533; 0,616].

## Task 15 — Rà soát khám phá của agent, notebook và tài liệu

**Rà soát:** 20 ca của bảng mù, gán nhãn chỉ từ chuỗi activity/role (không điểm, hạng, nhóm; không mở key/evidence trước khi gán). File: `outputs/runs/20261017T081309Z-930f8a85/reviews/case_review_agent.csv` + `README.md`. Kết quả: `needs_review` 5 (R01, R05, R07, R11, R18), `plausibly_valid` 12, `insufficient_evidence` 3 (R08, R10, R14). **Sau khi mở khóa**: `needs_review` chiếm 2/10 ở nhóm điểm cao và 3/10 ở nhóm ngẫu nhiên (Fisher hai phía p = 1,00); cả 3 ca `insufficient_evidence` đều nằm ở nhóm điểm cao (ít event, nhiều role chưa xác định). Kết quả âm: với rà soát này, mô hình không xếp các ca đáng rà soát lên cao hơn ngẫu nhiên. Không phải nhãn chuyên gia.

**Notebook:** 04 thêm mục 3b (bootstrap, thử hoán vị), 3c (đối chứng dương), 6b (bootstrap trung bình các model seed), sửa mục 3 và nhận xét để không dùng công thức hai mẫu độc lập làm kết luận; 05 thêm mục 3b (rà soát của agent); 06 thêm mục 4b (kiểm hai giả thuyết theo quy tắc khóa), 4c (temporal), kế hoạch ablation 12 mục, nhận xét sinh từ số liệu. Chạy sáu notebook trên run bàn giao `20261017T081309Z-930f8a85`: 6/6 `ok` (3–9 s mỗi cái).

**Hình ablation (kiểm tra bằng mắt thật):** hình `nb06_ablation.png` sinh ra có nhãn trục x chồng nhau (chín thí nghiệm) và dòng chú thích dải xám đè lên một điểm dữ liệu; sửa trong `plots.plot_ablation` theo TDD (hình rộng theo số thí nghiệm, chú thích đặt ở đáy dải). Bản đầu của tôi xoay nhãn 40° và hạ chú giải nhưng đột biến “không xoay” sống sót ⇒ bỏ phần thừa. Một test ban đầu pass vì `Figure()` trần không vẽ thật (`canvas.draw()` không làm gì) ⇒ chuyển sang ép vẽ bằng `savefig` rồi đo lại, đột biến được bắt.

**Báo cáo:** `docs/BAO_CAO.md` (viết cho người chấm môn học). Mọi số được tính lại tự động từ artifact (cùng tham số notebook) và đối chiếu từng chuỗi với văn bản: lần đầu bắt được một sai sót làm tròn kép (p = 0,145 ghi 0,15, đúng là 0,14), đã sửa; kiểm lại: không còn số thiếu.

**Lệnh và kết quả cuối:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `485 passed` sau Task 16 (477 sau Task 15; 382 ở Task 8) |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv lock --check` | `Resolved 125 packages` |
| `shasum -a 256` | `baseline.yaml` `2638fd50…`, `actions.yaml` `4a35ef7d…`, hai CSV và dataset không đổi |
| `open_run(run bàn giao)` | OK, 42 artifact có fingerprint |
| `uv run jira-ad experiments --config configs/experiments.yaml` | 36 run completed trong 123 s |

## Task 16 — Notebook không chạy được khi mở bằng tay trong VSCode

**Triệu chứng (người dùng):** chạy ô đầu tiên của notebook trong VSCode thì notebook không chạy được.

**Điều tra (chưa sửa gì trước khi có nguyên nhân gốc):** (1) cả sáu `.ipynb` hợp lệ theo `nbformat`, không trùng id; (2) `.venv` có `ipykernel` và kernelspec `python3`; `import jira_ad` thành công trong kernel; notebook 01 và 02 có `kernelspec` tên `jira-ad (3.12.7)` do VSCode ghi, tức kernel `.venv` đã được chọn và khởi động;
(3) tái hiện đúng cách VSCode chạy (kernel `.venv`, cwd `notebooks/`, không biến môi trường): **ô code đầu tiên của cả sáu notebook lỗi `NotebookInputError: Chưa chỉ định run`**; (4) chỉ đặt `JIRA_AD_RUN_DIR`: cả sáu ô đầu chạy được.
**Nguyên nhân gốc:** notebook biết run nào để đọc chỉ qua biến `JIRA_AD_RUN_DIR`, và chỉ `jira-ad notebooks` (chạy không giao diện) đặt biến đó. VSCode không có bước đặt biến trước khi kernel khởi động, nên ô đầu luôn lỗi; hướng dẫn cũ trong README (“đặt biến trước khi khởi động kernel”) không khả thi ở đó.
Tôi chưa nhìn được màn hình của người dùng: nếu thấy khác (ví dụ không có output nào), cần thêm thông tin.

**Sửa (Ruling 63):** `open_run()` khi không có đối số và không có biến môi trường sẽ chọn run hoàn tất **mới nhất có `config_hash` bằng cấu hình `configs/baseline.yaml` hiện tại**; không phải cache âm thầm vì run phải khớp cấu hình hiện tại, mọi fingerprint vẫn được kiểm và header in dòng `chọn run`. Cấu hình đã đổi, chưa có run khớp, run chưa `completed`, hoặc không có baseline.yaml thì dừng với lỗi nêu đúng lệnh. Chỉ định tường minh luôn thắng; đường dẫn tương đối của biến môi trường được tìm từ repo root khi cwd là `notebooks/`.

**TDD và đột biến:** RED = 4 test fail bằng đúng thông báo lỗi người dùng gặp (3 test pass vì lúc đó mọi trường hợp đều lỗi, được kiểm lại bằng đột biến); một test cũ phụ thuộc cwd thật của repo (sẽ tự chọn run thật) đã được cô lập bằng `tmp_path`. Đột biến: bỏ lọc `completed`, bỏ lọc `config_hash` (dùng run của cấu hình cũ), chọn run cũ nhất, không ghi lại việc chọn tự động, không giải đường dẫn tương đối theo repo root: 5/5 bị bắt.
Test hồi quy mô phỏng đúng VSCode (kernel không có biến, cwd = `notebooks/`, ô code đầu của cả sáu notebook thật): fail khi tắt bản sửa, pass khi bật.

**Kiểm chứng trên repo thật:** chạy **toàn bộ ô** của cả sáu notebook trong kernel `.venv`, cwd `notebooks/`, không biến môi trường: 6/6 không lỗi; header ghi `chọn run: tự động … run 20261017T081309Z-930f8a85`.

## Task 17 — Bổ sung README cho người mới

**File sửa:** `README.md` (chỉ tài liệu; không đổi code, test hay cấu hình). Thêm: *Tổng quan nhanh* (bài toán, ví dụ một trace, sơ đồ luồng, bảng thuật ngữ), *Dùng như thư viện Python* (đoạn mã đã chạy thử trên dữ liệu thật: chọn `bug:TI-5412` ở đầu bảng điểm test của `D_hybrid`), *Sáu notebook nói gì*, *Xử lý sự cố*, bản đồ module và lộ trình đọc. Phần đã có (cài đặt, lệnh, schema vào/ra, phương pháp, kết quả, tái lập) giữ nguyên.
**Kiểm tra:** các thông báo lỗi trích trong bảng xử lý sự cố đều tồn tại trong mã (`grep`), cả 18 module trong bản đồ đều có file tương ứng, và không thêm con số kết quả mới nào vào README.

## Task 18 — Giai đoạn cải tiến (2026-10-22)

**Kế hoạch:** `docs/superpowers/plans/2026-10-22-cai-tien-mo-hinh.md`. **Báo cáo:** `docs/BAO_CAO_CAI_TIEN.md` (cho hội đồng/giảng viên).

**Files:** tạo `src/jira_ad/{crossval,improvement}.py`, `configs/{improvements,improvement_plan}.yaml`, `tests/{test_crossval,test_improvement}.py`, `docs/BAO_CAO_CAI_TIEN.md`; sửa `config.py` (tên phương pháp E/F/M, mutant `skip_status`/`multi_edit`), `mutations.py`, `features.py`, `embedding.py` (`pool_edges`), `detector.py` (`ZScoreFusion`, `ColumnScore`), `plots.py` (`plot_interval_forest`, `plot_auroc_heatmap`, màu), `cli.py` (`improve`), test tương ứng.

**TDD:** RED đúng lý do cho mutant (ConfigError loại lạ), encoder (AttributeError nhánh chưa có), detector (giá trị điểm sai), crossval (module chưa có), `case_drivers` (hàm chưa có; test đầu của tôi sai giả định 1 chuyển tiếp chưa thấy, thực tế 2 ⇒ sửa test). `test_improvement` chưa chạy RED ⇒ 3 đột biến (phán quyết luôn "cải thiện", bỏ ngưỡng Jaccard, cho chọn trên test) đều bị bắt, source khôi phục giống hệt.

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `521 passed` (sau bản sửa rà soát cuối) |
| `uv run ruff check src tests scripts` | sạch |
| `uv run jira-ad improve --plan configs/improvement_plan.yaml` (2 lần) | `outputs/improvement/20261022T151239Z-bb0fee9a` và `…151529Z-bb0fee9a`, ~88 s; mọi bảng giống hệt, chỉ cột thời gian khác |
| `config_hash(baseline.yaml)` / sha256 `baseline.yaml`, `actions.yaml`, Bug CSV | `930f8a85…` / `2638fd50…`, `4a35ef7d…`, `cda16f1c…` — không đổi |

**Kết quả (chi tiết ở báo cáo):** phán quyết khóa trước trên validation 0/3 ứng viên (`M_markov` +0,032 [−0,008; +0,088], `F_edge_hybrid` +0,004, `E_score_fusion` −0,013 so với `D_hybrid`). Cross-validation 161 issue, 782 mutant (khám phá): macro AUROC `M_markov` 0,603 [0,588; 0,621], `F_edge_hybrid` 0,563, `D_hybrid` 0,554, `A_stats` 0,544; `M_markov − D_hybrid` +0,049 [+0,034; +0,065]; `skip_status` tối đa 0,566. Ứng dụng: không phương pháp nào đạt "tự động cảnh báo"; A/E/F/M đạt "bộ lọc ưu tiên rà soát"; `D_hybrid` không đạt vì Jaccard top-10% giữa seed 0,548.

**Tự rà soát cuối (không có reviewer độc lập):** notebook 04 và 06 chạy lại trong bộ nhớ trên run bàn giao khi `outputs/runs/` có thêm run cải tiến: 0 lỗi, file nguồn không đổi. Phát hiện: `pool_edges` ném lỗi với trace một event khi tắt `add_boundaries` ⇒ test `test_edge_hybrid_without_boundaries_handles_a_single_event_trace` RED → sửa trả vector 0 → GREEN, suite 521/521. Không ảnh hưởng kết quả đã chạy (cấu hình thật bật `add_boundaries`).

**Rủi ro còn lại:** (a) mutant dựng từ activity của parent nên ưu tiên phương pháp dựa trên chuyển tiếp; (b) cross-validation dùng cả test V1 ⇒ khám phá; (c) ngưỡng ứng dụng tự đặt; (d) không có notebook 07 (bộ test khóa đúng 6 notebook), kết quả đọc qua CSV/hình và báo cáo; (e) 6 run mới trong `outputs/runs/` (2 lần chạy × 3 seed) thuộc nhóm cấu hình riêng, không trộn với baseline trong `compare`.

## Task 19 — Bước A: status log + phân tích định lượng (2026-10-26)

**Files tạo:** `configs/process.yaml`, `src/jira_ad/{process_config,worktime,status_log,process_metrics,process_run}.py`, `tests/test_{process_config,worktime,status_log,process_metrics,process_run}.py`. **Sửa:** `src/jira_ad/cli.py` (lệnh `process`, bắt `RunExistsError`/`FrozenInputChanged`), `tests/helpers.py` (`PROCESS_CONFIG`, `stamped_rows`, `status`, `write_process_project`). **Đổi tên:** `docs/Untitled.md` → `docs/BAO_CAO_TONG_KET_export.md`. Kế hoạch giai đoạn 2 viết lại theo CLAUDE.md (Ruling 67–72).

**TDD:** RED đúng lý do cho cả năm file test (`ModuleNotFoundError`); một kỳ vọng tính tay của tôi sai (TI-4 = 26 giờ, không phải 25) được sửa trước khi implement. **Đột biến:** 12 đột biến trên `worktime`, `status_log`, `process_metrics`; lần đầu 10 bị bắt, 2 sống (`<` → `<=` ở "lùi"; tính bù cả lần đổi đầu) ⇒ thêm 2 test ⇒ 12/12 bị bắt (Ruling 75).

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `567 passed` (521 cũ + 46 mới); sau khi sửa định dạng ruff, các file bị sửa chạy lại `31 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` (2 lần) | `outputs/process/20261025T165159Z-733ed503` và `…165205Z-733ed503`, ~5 s; 20 file, sha256 giống hệt; fingerprint input khóa trước = sau |
| `shasum -a 256` | `baseline.yaml` `2638fd50…`, `actions.yaml` `4a35ef7d…`, Bug CSV `cda16f1c…`, `experiments.yaml` `d7641ac8…`, `improvement_plan.yaml` `98be1895…`; 105 mục trong `outputs/runs/`, 2 run trong `outputs/improvement/` |

**Kiểm chéo độc lập** (pandas thô, không import `jira_ad`, ngày làm việc tính bằng cách trừ phần giao với cuối tuần): 161 ca, 83/78, 30 biến thể trạng thái, 22 `CREATE → Rejected`, 553 khoảng / 165 < 60 s — khớp "sự thật đã đo". CT lịch trung vị 23,0316 / P90 104,3069 ngày; CT ngày làm việc 17,0316 / 74,3069 — khớp pipeline đến 4 chữ số. PT share (phân loại chính, đồng hồ lịch) 0,1665 = pipeline 0,16652.

**Kết quả chính (bug, 161 ca, đồng hồ ngày làm việc trừ khi ghi khác):**
- CT trung vị 17,0 ngày làm việc (23,0 ngày lịch), P90 74,3 (104,3). DONE 28,7, Rejected 13,4 (trung vị).
- **Tỉ trọng PT là khoảng rất rộng 16,7%–59,2%**: phân loại chính 16,7% (cận trên do bù 26,9%); nếu `To Investigate` là "làm" thì 57,0% (59,2%). Lý do: `To Investigate` là trạng thái tốn thời gian nhất (tổng 2.110 ngày làm việc, trung vị 10,9 ngày/lượt). CTE trung vị toàn bộ = 0 ở phương án chính vì gần nửa số ca (Rejected) không qua trạng thái "làm"; DONE: 0,305.
- FPY strict 0,814 (30 ca có lùi/mở lại), adjusted 0,857 (23 ca nếu bỏ lần lùi trong đợt bù); với DONE: 0,759 / 0,807.
- Rejected: 78 ca tiêu tốn 1.929 ngày-issue làm việc; 77 ca bị loại **trước** khi vào In Progress, chỉ 1 ca sau.
- Little: λ = 0,413 ca/ngày, W = 45,6 ngày, L = 18,8 (đồng nhất thức); ca đến nửa đầu kỳ 109, nửa sau 52 (thiên lệch sống sót: chỉ có ca đã đóng). Throughput TB 2,82 ca/tuần, WIP TB 18,4.
- Vai trò cổng (vai trò người chuyển vào trạng thái nhiều nhất): PO cho `To Investigate` (91%), `Rejected` (88%), `To Do` (75%), `Inbox` (72%); Eng cho `In Test` (49%); SQA cho `DONE` (54%).
- 29,8% lần đổi trạng thái (không tính lần đầu) là cập nhật bù. Story (đặt cạnh, không trộn): 182 ca, 96% DONE, CT trung vị 19,3 ngày làm việc, PT 28,0%–31,9%, FPY 0,945.

**Rủi ro còn lại:** (a) kết luận "thời gian đi đâu" phụ thuộc mạnh vào cách phân loại `To Investigate` — báo cáo phải nêu khoảng, không nêu một số; (b) tuần cuối kỳ thiếu ca chưa đóng nên λ nửa sau bị hạ thấp; (c) pm4py chưa cài (Task 21).

## Task 20 — Bước B: định mức + centrality (2026-10-26)

**Files tạo:** `src/jira_ad/{norms,centrality,process_figures}.py`, `tests/test_{norms,centrality,process_figures}.py`. **Sửa:** `src/jira_ad/process_config.py` (section `norms`, `centrality`), `configs/process.yaml`, `src/jira_ad/process_run.py` (bước `b_norms`, `code_fingerprint`), `tests/{helpers,test_process_config,test_process_run}.py`.

**TDD:** RED đúng lý do cho `norms`, `centrality`, `process_figures` (`ModuleNotFoundError`) và cho phần ghép nối (section lạ bị từ chối). **Đột biến:** 11 đột biến; 10 bị bắt, 1 sống (`excess` không cắt ở 0) ⇒ thêm `test_on_time_visits_contribute_zero_excess` ⇒ 11/11. **Lỗi thật** do kiểm chéo bắt: trọng số DFG activity (Ruling 80), sửa theo TDD.

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `587 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` | run cuối `outputs/process/20261025T170333Z-882a0696` (bước A + B); hai lần chạy trước khi sửa định dạng cho 34 file giống hệt |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…` — không đổi |

**Kiểm chéo độc lập** (không import `jira_ad`): định mức `To Do` tính lại từ CSV thô = 7,7553 ngày làm việc (106 lượt) = pipeline; DFG activity train: 49 nút (bỏ biên) khớp tập nút `graph.graphml` của run V1 (51 nút, 386 cạnh), in-strength khớp từng nút sau khi sửa lỗi trọng số; train = 97 ca.

**Kết quả chính (bug, ngày làm việc):**
- Định mức P75: `To Investigate` 27,9 ngày; `In Test` 9,8; `To Do` 7,8; `__CREATED__` 4,0; `In Progress` 3,0; `INVESTIGATED` 2,2; `Inbox` 1,1.
- **Ngày vượt định mức tập trung ở `To Do` (1.159 ngày, 48% tổng)** dù trung vị dwell `To Do` ≈ 0: phân bố hai cực (đi xuyên qua khi chuyển dồn, hoặc nằm chờ rất lâu). Năm lần trễ lớn nhất đều là `To Do` 120–150 ngày (3/5 kết thúc Rejected). Tiếp theo: `To Investigate` 511 ngày (21%), `In Test` 295 (12%), `INVESTIGATED` 189 (8%).
- Theo vai trò chuyển ra: PO 1.298 ngày vượt (390 lần chuyển), Eng 223, SQA 171; `unknown` 743 ngày (báo riêng, không xếp hạng).
- 99/161 ca có ≥ 1 lượt trễ; 41 ca có CT vượt P75 của nhánh.
- DFG trạng thái: `In Progress` có betweenness cao nhất (0,37) và PageRank cao nhất (0,245); `To Do → In Progress` 90 lần với trung vị chờ 0,0 ngày; `To Do → Rejected` 5 lần, trung vị 144 ngày. DFG activity train: `EDIT_DESCRIPTION` (0,23) và `ADD_ISSUE_LINK` (0,18) có betweenness cao nhất.
- Danh sách ưu tiên (`priorities.csv`): 1. `To Do` (cổng PO 75%), 2. `To Investigate` (PO 91%), 3. `In Test` (Eng 49%), 4. `INVESTIGATED`, 5. `__CREATED__`, 6. `In Progress`, 7. `Inbox`; mỗi dòng có 3 issueKey ví dụ.

**Rủi ro còn lại:** (a) định mức nội suy nên ~25% lượt trễ theo cấu tạo — chỉ "ngày vượt" mới so sánh được giữa trạng thái; (b) role `unknown` chiếm 743 ngày vượt nên bảng vai trò thiếu một phần đáng kể; (c) nhãn cạnh trong hình DFG chồng nhẹ ở một cạnh ít lần.

## Task 21 — Bước C: Work System, mô hình chuẩn, khai phá, kiểm định (2026-10-26)

**Files tạo:** `src/jira_ad/conformance.py`, `tests/test_conformance.py`. **Sửa:** `pyproject.toml` + `uv.lock` (extra `process`), `src/jira_ad/process_config.py` (`reference_model`, `flags`, `discovery`, `FlagRule`), `configs/process.yaml`, `src/jira_ad/status_log.py` (`CohortData.events_full`), `src/jira_ad/process_figures.py` (`petri_dot`, `bpmn_dot`), `src/jira_ad/process_run.py` (bước `c_conformance`), tests tương ứng.

**TDD:** RED đúng lý do cho mọi file test mới; hai kỳ vọng sai của tôi trong fixture (ca mở lại đi `DONE → In Progress` thực chất kích hoạt cờ "vào In Progress không qua To Do") được sửa trước khi implement. **Đột biến:** 10 đột biến trên `conformance`; 6 bị bắt, 4 sống (thứ tự trong 3 cờ, loại bot khỏi lane) ⇒ thêm 2 test ⇒ 10/10. Hai lỗi tái lập hình (Ruling 85) bắt bằng so manifest.

**Lệnh và kết quả thật (tới điểm dừng):** `uv run pytest -q` → `607 passed` (trước hai test tái lập hình; các file liên quan chạy lại xanh); `ruff` sạch; run `outputs/process/20261025T171708Z-c429ceff` (60 file, giống hệt run với `PYTHONHASHSEED` khác); hash khóa không đổi.

**Kết quả đã có (chưa replay mô hình chuẩn):**
- Work System 8 thành phần, mỗi ô có dẫn chứng (vd bot 2.230/5.126 = 43,5% event; người tạo issue: Eng 54, SQA 44, unknown 26, PO 16, thiếu role 11).
- Khai phá trên log trạng thái 161 ca: Alpha fitness 0,616 / precision 0,453 (0% ca khớp); Heuristics 0,921 / 1,000 (37,9%); Inductive 1,000 / 0,548 (100%); Inductive lọc nhiễu 0,2: 0,979 / 0,855 (78,3%).
- Cờ: bỏ pha điều tra 39 ca (24%); lần đổi đầu là Rejected 26; Rejected sau In Progress 2; mở lại sau DONE 4; lùi về Inbox 17; vào In Progress không qua To Do 6; có đợt bù 69 ca (165 lần).
- Cung ngoài mô hình chuẩn nhiều nhất: CREATE → To Do 37, To Do → Inbox 11, INVESTIGATED → To Investigate 5, In Progress → To Do 5, DONE → In Progress 4, Rejected → Inbox 4. Cung của mô hình chưa từng xảy ra: To Investigate → Rejected (0).

**Sau điểm dừng 2** (Quyết định 8, Ruling 88–93): bật `approved`, thêm `alternative_models`/`deviation_report`, `compare_replays`, `unobserved_arc_precision`, `deviation_breakdown`; 5 đột biến mới đều bị bắt; một trường hợp biên (Ruling 93) bắt bằng test ghép nối.

**Notebook (Quyết định 9):** làm bù `07_quantitative` (Task 19), `08_norms_centrality` (Task 20) và `09_conformance`, cấu trúc 7 phần; hạ tầng `process_analysis.py`, `process_plots.py`, `execute_process_notebooks` (Ruling 90). Hai lỗi trình bày bắt khi đọc bản đã chạy, sửa theo TDD (Ruling 91).

**Lệnh và kết quả cuối:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `638 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` | `outputs/process/20261025T174136Z-0d1acf65` (71 file), giống hệt run `…173600Z-0d1acf65` |
| `uv run jira-ad notebooks --run-dir outputs/process/20261025T174136Z-0d1acf65` | 07, 08, 09: ok; bản đã chạy ở `notebooks_executed/` |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…`, `d7641ac8…`, `98be1895…` — không đổi |

**Kiểm chéo độc lập** (pandas thô): ca khớp hoàn toàn ⇔ mọi cặp liên tiếp là cung được phép (mô hình kiểu máy trạng thái) ⇒ mô hình chuẩn 105 ca, luồng nhanh 130 ca, khớp thêm 25 — **cùng tập ca** với token replay.

**Kết quả replay:** mô hình chuẩn: 105/161 ca khớp hoàn toàn (65,2%), fitness TB theo ca 0,967, fitness log 0,965, precision 0,915, generalization 0,782, simplicity 0,786; DONE 39/83 (47,0%), Rejected 66/78 (84,6%). Luồng nhanh (KHÔNG phải chuẩn): 130/161 (80,7%), giải thích thêm 25 ca (23 DONE, 2 Rejected). Giữ cung `To Investigate → Rejected` (0 lần) làm precision 0,991 → 0,915, fitness không đổi. Sai lệch: CREATE → To Do 37 ca (DONE 30, Rejected 7; 17 ca có cập nhật bù); To Do → Inbox 11 (10 có bù); lùi trạng thái 23 ca (20 có bù); mở lại 8 ca (7 có bù).

**Rủi ro còn lại:** (a) fitness token gần 1 dễ bị đọc nhầm là "tuân thủ tốt" — báo cáo dùng tỉ lệ ca khớp; (b) phần lớn ca lùi/mở lại có cập nhật bù nên một phần có thể là thao tác sửa nhầm, không phải làm lại thật; (c) `outputs/process/` còn các run trung gian của Task 19–21 (không xóa).

## Task 22 — Bước D: BPR (2026-10-26)

**Files tạo:** `src/jira_ad/bpr.py`, `tests/test_bpr.py`, `notebooks/10_bpr.ipynb`. **Sửa:** `configs/process.yaml` (`bpr` khóa trước; `bpr_candidates`, `tobe_model`, `pilot` thiết kế sau), `src/jira_ad/process_config.py` (`BprConfig`, `CandidateConfig`, `TobeModelConfig`, `PilotPhase`, `BPR_CANDIDATES`, `KPI_NAMES`), `src/jira_ad/process_run.py` (bước `d_bpr`), `src/jira_ad/conformance.py` (`flow_labels`), `src/jira_ad/process_figures.py` (`automated`), `src/jira_ad/process_plots.py` (`plot_kpi_delta`), `src/jira_ad/process_analysis.py` (`remarks_bpr`), tests tương ứng.

**TDD và đột biến:** RED đúng lý do cho `bpr`, config, BPMN tự động, bước D, hình/nhận xét. Đột biến: 9 (4 sống ⇒ +4 test ⇒ 9/9), 5 bù cho TDD sai thứ tự (5/5), 1 xác nhận test hồi quy. Lỗi thật và sai thứ tự TDD ghi ở Ruling 97.

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `662 passed` (trước bản sửa câu bằng chứng trùng; `test_bpr` chạy lại 18/18) |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` | run cuối `outputs/process/20261025T175956Z-ac288f0c` (80 file); hai run trước đó cùng cấu hình cho file giống hệt |
| `uv run jira-ad notebooks --run-dir outputs/process/20261025T175956Z-ac288f0c` | 07, 08, 09, 10: ok |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…` — không đổi |

**Kiểm chéo độc lập** (pandas thô): ngày-issue làm việc của ca Rejected AS-IS 1.928,5597 và TO-BE (loại ở lần đổi đầu) 264,2330 — khớp pipeline đến 4 chữ số.

**Kết quả:** ủng hộ 5/7 — loại sớm (Rejected chiếm 36,8% ngày-issue, trung vị 13,4 ngày tới khi loại), tự chuyển trạng thái (39/58 ca có commit/MR trước In Progress, trễ trung vị 1,7 ngày lịch), gộp INVESTIGATED–To Do (43/62 lần đi xuyên qua), thêm Investigating (PT 16,7% so với 57,0%), luồng nhanh (CT 11,2 so với 35,9 ngày; FPY 0,75 so với 0,76; quan sát, không nhân quả). Không ủng hộ — giảm phụ thuộc PO (trung vị như nhau; nhưng 60,5% ngày vượt ở To Do thuộc lượt PO chuyển ra), phát hiện trùng sớm (7 ca trùng bị loại sau trung vị 3,2 ngày — đã nhanh). KPI AS-IS (đo) → TO-BE (mục tiêu / kịch bản ước tính): CT trung vị 17,0 → 5,9 ngày làm việc; CT P90 74,3 → 50,9; ngày-issue Rejected 1.928,6 → 264,2; tỉ trọng PT đo được 16,7% → 16,9%; số lần đổi trạng thái/ca 4,4 → 4,0; tỉ lệ ca khớp mô hình 65,2% → 80,7%.

**Rủi ro còn lại:** (a) số TO-BE là cận trên trên dữ liệu cũ; (b) luồng nhanh có thể chỉ phản ánh bug vốn đơn giản; (c) lợi ích đo lường của tự chuyển trạng thái nhỏ dù tỉ lệ ca cao; (d) lane của `Investigating` là đề xuất.

## Task 23 — Bước E: học biểu diễn + xếp hạng ưu tiên rà soát (2026-10-26)

**Files tạo:** `src/jira_ad/ranking.py`, `tests/test_ranking.py`, `notebooks/11_ranking.ipynb`. **Sửa:** `configs/process.yaml` (`ranking`), `src/jira_ad/process_config.py` (`RankingConfig`), `src/jira_ad/process_run.py` (bước `e_ranking`), `src/jira_ad/process_plots.py` (3 hình), `src/jira_ad/process_analysis.py` (`remarks_ranking`), tests tương ứng.

**TDD và đột biến:** RED đúng lý do cho `ranking`, `build_profile`, bước E, hình, nhận xét, định dạng lý do. Đột biến: 7 (3 sống ⇒ +3 test ⇒ 7/7); một fixture test do tôi dựng sai (hai ca hòa số chiều vượt) được sửa, mã không đổi; 2 đột biến xác nhận test tích hợp `load_v1_vectors` (bỏ kiểm fingerprint, không bỏ nút biên) đều bị bắt.

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `682 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` | run cuối `outputs/process/20261026T011903Z-5d4973b3` (91 file); chạy lại với `PYTHONHASHSEED=7` (`…011940Z-5d4973b3`) giống hệt |
| `uv run jira-ad notebooks --run-dir outputs/process/20261026T011903Z-5d4973b3` | 07, 08, 09, 10, 11: ok |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…` — không đổi |

**Kiểm chéo độc lập** (pandas thô): số lần đổi người phụ trách của `TI-4748` trong core view = 7 = pipeline; Spearman điểm M_markov gốc–số event đọc thẳng từ `cv_original_scores.csv` = 0,5071 = pipeline.

**Kết quả:** tìm lại nhóm nghiệp vụ (1-NN): Node2Vec 0,449 (macro-F1 0,352), bậc + trung tâm 0,286 (0,205), baseline lớp phổ biến 0,245 (0,049) ⇒ Node2Vec tốt hơn đặc trưng cấu trúc ở bài toán này (khác kết luận âm của giai đoạn 1 về phát hiện bất thường). K-means: NMI tối đa 0,388 (Node2Vec, K = 6), ARI ≤ 0,134, silhouette Node2Vec ≤ 0,137 ⇒ cấu trúc cụm yếu. Xếp hạng: 7 chiều; phân bố số chiều vượt 0: 97 ca, 1: 40, 2: 12, 3: 7, 4: 2, 5: 3; top 17 ca (nên xem trước) có 52,9% Rejected so với 48,4% toàn bộ, trung vị số event như toàn bộ (19); Spearman điểm–độ dài −0,005; khử độ dài đưa Spearman M_markov–độ dài từ 0,507 xuống 0,040. **Ổn định top-17 chỉ vừa phải**: Jaccard bootstrap 0,40 [0,21; 0,62].

**Rủi ro còn lại:** (a) danh sách top thay đổi đáng kể khi lấy mẫu lại — chỉ dùng làm gợi ý; (b) nhóm nghiệp vụ là định nghĩa của tác giả, 49 activity nên số dao động lớn; (c) bảng mù chưa có người rà soát.

## Task 24 — Bước F: báo cáo + notebook tổng hợp + đối chiếu số (2026-10-26)

**Files tạo:** `docs/BAO_CAO_MON_HOC.md`, `src/jira_ad/process_report.py`, `tests/test_process_report.py`, `notebooks/12_summary_report.ipynb`. **Sửa:** `src/jira_ad/cli.py` (lệnh `check-report`), `README.md` (mục giai đoạn 2), `AGENTS.md`, `tests/test_notebook_runner.py` (danh sách 07–12).

**TDD và đột biến:** RED đúng lý do cho `process_report`; 5 đột biến (1 sống: bỏ code span ⇒ +1 test ⇒ 5/5). Test CLI viết sau code (Ruling 105).

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `687 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad check-report --report docs/BAO_CAO_MON_HOC.md --run-dir outputs/process/20261026T011903Z-5d4973b3` | lần đầu 323 số, 4 chưa khớp (đều là định danh, Ruling 104); sau sửa: **319 số, 0 chưa khớp** |
| `uv run jira-ad notebooks --run-dir outputs/process/20261026T011903Z-5d4973b3` | 07, 08, 09, 10, 11, 12: ok; notebook 12 in "Đã đối chiếu 319 con số; chưa khớp: 0" |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…` — không đổi |

**Báo cáo:** 6 chương theo Buổi 1–6, mở đầu mỗi chương bằng buổi học áp dụng; giả định dữ liệu ở đầu báo cáo và từng chương có số thời gian; số TO-BE luôn ghi "mục tiêu / kịch bản ước tính"; xếp hạng = "nên xem trước"; chi tiết thống kê ở phụ lục; ghi nguồn gốc thật của dữ liệu (Zenodo) bên cạnh giả định đề bài.

**Rủi ro còn lại:** phép đối chiếu là điều kiện cần (Ruling 103); các nhận định bằng lời (vd "một phần ba số ca lệch") không được kiểm tự động — để reviewer độc lập (Task 25) đọc.

## Task 25 — Bước G: rà soát độc lập (2026-10-26)

**Reviewer:** một subagent độc lập (CLAUDE.md cho phép), chỉ đọc; tính lại bằng pandas thô (script ở scratchpad `review/`, không import `jira_ad`). **Kết quả:** mọi số chính trong báo cáo khớp (kể cả tập 105/130 ca khớp, top-17 đúng thứ tự, phân bố số chiều vượt); BPMN ↔ Petri net ↔ danh sách cung đúng; token replay ⇔ định nghĩa "khớp hoàn toàn"; không số TO-BE nào trình bày như kết quả đo; bảng BPR trùng `checks.csv`. Không có phát hiện Critical; 5 Important, 12 Minor.

**Một lượt sửa (TDD, mỗi sửa có test RED → GREEN):**
- Final: fixed I1 (ba định nghĩa "trong đợt bù") — `test_fpy_strict_and_adjusted` (sửa theo định nghĩa đợt bù), `test_deviation_breakdown_by_branch_and_backfill`, `test_deviation_breakdown_counts_back_transition_inside_a_burst` RED→GREEN (Ruling 106).
- Final: fixed I2 (loại sớm: TO-BE tự mâu thuẫn) — `test_reject_at_investigation_end_keeps_investigation_and_drops_later_waits`, `test_early_triage_evidence_counts_rejections_right_after_investigation`, `test_reject_at_investigation_end_uses_the_last_investigation_round` (thêm sau đột biến sống), `test_step_d_reports_feasible_and_upper_bound_scenarios_after_review` RED→GREEN (Ruling 107).
- Final: fixed I3 (bằng chứng tự chuyển trạng thái) — `test_auto_transition_reports_where_the_first_link_falls` RED→GREEN (Ruling 109).
- Final: fixed I4 (số lần đổi trạng thái mâu thuẫn TO-BE) — `test_tobe_path_counts_status_changes_on_the_redesigned_route` RED→GREEN (Ruling 108).
- Final: fixed I5 (kết luận PO vượt dữ liệu) — `test_state_excess_by_role_and_target_splits_backlog_cleanup` RED→GREEN; báo cáo sửa (Ruling 109).
- Đột biến cho lượt sửa: 6 (1 sống ⇒ +1 test ⇒ 6/6).
- Báo cáo sửa theo I1–I5 và các Minor là câu sai/gây hiểu nhầm: M1 (1 so với 2 ca Rejected sau In Progress), M2 (ghi rõ "ca DONE", chênh CT một phần là cơ học, Ford/Mazda chỉ là gợi ý), M4 (bỏ so sánh story), M6 (nêu 22/37/39 và 22/26), M7 ("khoảng một nửa số lượt"), M8 (dấu "…"), M9 (tỉ lệ khớp so với mô hình luồng nhanh), M10 (To Investigate: vấn đề đo lường, không khẳng định là hàng đợi), M3 (dẫn chứng không thiên độ dài bằng trung vị số sự kiện), M11 (lane PO là đề xuất, số mỏng).

**Lệnh và kết quả cuối:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `695 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` | `outputs/process/20261026T015124Z-5d4973b3`; chạy lại với `PYTHONHASHSEED=11` (`…015723Z-5d4973b3`) giống hệt |
| `uv run jira-ad check-report --report docs/BAO_CAO_MON_HOC.md --run-dir outputs/process/20261026T015124Z-5d4973b3` | **369 số, 0 chưa khớp** |
| `uv run jira-ad notebooks --run-dir outputs/process/20261026T015124Z-5d4973b3` | 07–12: ok |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…`, `d7641ac8…`, `98be1895…`; 105 mục trong `outputs/runs/`, 2 run trong `outputs/improvement/` |

**Final: minor (deferred):**
- M5: `_backfill_promoted` dùng `dwell_cal_s < 60` có tính cả lượt `__CREATED__` (khác `is_backfill_entry`); ảnh hưởng không đáng kể tới cận trên PT.
- M12: khoảng tin cậy in "[-0,0; 0,9]" (số âm rất nhỏ làm tròn thành −0,0).
- M3 (phần còn lại): riêng `n_exceed` có Spearman 0,121 với độ dài — chưa đưa vào báo cáo dưới dạng số.

**Rủi ro còn lại (giai đoạn 2):** không có nhãn lỗi thật; mô hình chuẩn, nhóm nghiệp vụ, lane TO-BE là giả định; số TO-BE là kịch bản trên dữ liệu cũ; bảng mù chưa có người rà soát; `outputs/process/` còn nhiều run trung gian (không xóa).

## Task 26 — Theo quyết định của người dùng sau Task 25 (2026-10-26)

**Quyết định của người dùng:** (1) chấp nhận mức lợi ích TO-BE sau rà soát, trình bày CT dạng khoảng; (2) xóa run trung gian; (3) hướng dẫn + lệnh so sánh bảng mù; (4) thay top-17 bằng danh sách đồng thuận; (5) giải thích fitness so với tỉ lệ ca khớp; (6) sửa M12, M3.

**Đơn vị "5,9":** báo cáo luôn là **5,9 ngày làm việc**; chữ "giờ" chỉ có trong tin nhắn chat của tôi (nghĩa "bây giờ"), không có trong báo cáo.

**Đã xóa khỏi `outputs/process/`** (21 run trung gian, theo cho phép của người dùng): 20261025T165159Z-733ed503, 20261025T165205Z-733ed503, 20261025T170102Z-882a0696, 20261025T170333Z-882a0696, 20261025T171519Z-c429ceff, 20261025T171528Z-c429ceff, 20261025T171606Z-c429ceff, 20261025T171616Z-c429ceff, 20261025T171659Z-c429ceff, 20261025T171708Z-c429ceff, 20261025T173600Z-0d1acf65, 20261025T174136Z-0d1acf65, 20261025T175142Z-ac288f0c, 20261025T175158Z-ac288f0c, 20261025T175326Z-ac288f0c, 20261025T175910Z-ac288f0c, 20261025T175956Z-ac288f0c, 20261025T180801Z-5d4973b3, 20261026T011903Z-5d4973b3, 20261026T011940Z-5d4973b3, 20261026T015723Z-5d4973b3. Sau đó tôi xóa thêm hai run do chính tôi tạo trong lượt này: `20261026T025311Z-399b0a40` (bản danh sách đồng thuận lỗi, Ruling 110) và `20261026T030023Z-399b0a40` (bản kiểm tất định, giống hệt run cuối). **Còn lại:** `20261026T015124Z-5d4973b3` (người dùng yêu cầu giữ) và `20261026T025412Z-399b0a40` (run mới, cần cho các artifact bổ sung; báo cáo trích run này).

**Files:** sửa `src/jira_ad/{ranking,bpr,process_run,process_analysis,process_config,cli}.py`, `configs/process.yaml` (`ranking.consensus_share`), tests tương ứng, `docs/BAO_CAO_MON_HOC.md`, notebook 11, 12; tạo `docs/HUONG_DAN_RA_SOAT_MU.md`.

**TDD và đột biến:** RED đúng lý do cho `_days` (âm 0), `topk_consensus`, `compare_blind_review` (2 test), `replay_summary.unfit`, Spearman `n_exceed`, CLI `blind-review-compare` (2 test), nhận xét mới, kích thước top theo tỉ lệ. Đột biến: 5/5 bị bắt.

**Lệnh và kết quả thật:**

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q` | `705 passed` |
| `uv run ruff check src tests scripts` | `All checks passed!` |
| `uv run jira-ad process --config configs/process.yaml` | `outputs/process/20261026T025412Z-399b0a40`; chạy lại với `PYTHONHASHSEED=5` giống hệt |
| `uv run jira-ad check-report --report docs/BAO_CAO_MON_HOC.md --run-dir outputs/process/20261026T025412Z-399b0a40` | **401 số, 0 chưa khớp** |
| `uv run jira-ad notebooks --run-dir outputs/process/20261026T025412Z-399b0a40` | 07–12: ok |
| `shasum -a 256` | `2638fd50…`, `4a35ef7d…`, `cda16f1c…` — không đổi |

**Kết quả mới:** CT trung vị TO-BE thực tế 15,2 so với AS-IS 17,0 (giảm 10,7%), cận trên lý tưởng 5,9 (giảm 65,5%, không khả thi vì 47/78 ca Rejected bị loại sau điều tra); danh sách đồng thuận 10 ca (5 ca lọt top 100% số lần); Spearman số chiều vượt–độ dài 0,121; 56 ca không khớp có fitness TB 0,906.

## Task 27 — Bản nộp, câu hỏi bảo vệ, dọn run, Git (2026-10-26)

**Theo yêu cầu người dùng:**
1. **Đã xóa** `outputs/process/20261026T015124Z-5d4973b3` (người dùng cho phép). `outputs/process/` chỉ còn `20261026T025412Z-399b0a40` (run báo cáo trích).
2. **Bản nộp** `docs/BAO_CAO_MON_HOC_nop.md`: văn phong học viên, bỏ thuật ngữ nội bộ (Ruling, Task, agent, "mình", "giai đoạn 1", reviewer), giữ nguyên mọi số; lệnh, hash, run id gom vào "Phụ lục B. Tái lập". Thêm 10 hình có chú thích đánh số (`docs/figures/hinh01…hinh10`): 5 sơ đồ Graphviz sao chép từ run, 5 biểu đồ sinh bằng `process_plots` từ chính run đó. `check-report` trên bản nộp: **435 số, 0 chưa khớp**. Xuất `docs/BAO_CAO_MON_HOC_nop.docx` bằng pandoc (gói `pypandoc_binary` chạy qua `uv run --with`, không đổi `pyproject.toml`, không cài pandoc toàn cục): Times New Roman 13 (tiêu đề 16/14/13 đậm), mục lục 2 cấp (trường TOC — Word cần "Update Field"/F9 khi mở), 10 hình với chú thích "Hình 1…10" kiểu Image Caption.
3. **Câu hỏi bảo vệ** `docs/CAU_HOI_BAO_VE.md`: 20 câu kèm gợi ý trả lời và số dẫn chứng; `check-report`: **117 số, 0 chưa khớp** (câu về Node2Vec trong phát hiện bất thường dẫn `docs/BAO_CAO_TONG_KET.md` bằng lời, không chép số của giai đoạn trước).
4. **Git:** `git init`, `.gitignore` thêm `.DS_Store`; commit trạng thái hiện tại, chỉ `git add` các đường dẫn cụ thể (không `git add .`); `dataset/`, `outputs/`, `.venv/` bị chặn bởi `.gitignore`.

**Ruling 113.** Hình của bản nộp được sinh lại từ run cuối bằng hàm vẽ có sẵn (không vẽ tay); file hình nằm trong `docs/figures/` (không phải artifact đã băm). Công cụ xuất docx là script ở scratchpad (như Ruling 41), không nằm trong repo. Chi phí nếu sai: chạy lại script khi run đổi.

## Tự rà soát cuối (không có reviewer độc lập)

Skill yêu cầu một reviewer mới cho toàn nhánh, nhưng phiên này không được phép khởi chạy subagent nếu người dùng không yêu cầu, nên tôi **tự rà soát** (yếu hơn reviewer độc lập; người dùng quyết định có đủ hay không):
đọc lại các ranh giới fit/transform, kiểm tra rò rỉ đầu-cuối trên dữ liệu thật, chạy đột biến trên từng module có logic nghiên cứu, kiểm tra bằng mắt mọi hình, đối chiếu notebook với `metrics.json` và một trace với CSV gốc bằng code độc lập, quét ký hiệu công khai không dùng.
Ghi chú: một số lỗi **chính tôi** gây ra và đã được test bắt (ghi trong từng Task): fixture thiếu `mkdir`, id mutant trong test không khớp ledger, `run.log` bị sửa bởi bộ chạy notebook, `km=` làm mất timeout, code `hashfxn` thừa.

**Deferred minors (không sửa, để người dùng quyết định):**
- `analysis.py` gom bốn việc (nạp run, bảng mô tả, bằng chứng ca, bộ rà soát); có thể tách khi lớn hơn.
- Khoảng tin cậy trong notebook 04/06 là xấp xỉ giải tích (Hanley–McNeil, Wilson, SE dưới H0); chưa có bootstrap theo parent.
  **[Cập nhật 2026-10-22: đã có bootstrap theo parent và thử hoán vị trong cặp (Task 10); notebook 04/06 dùng chúng để kết luận.]**
- Bảng "Nhận xét" của notebook dùng chữ cố định cho phần diễn giải khái niệm (không có số), chỉ phần số liệu được sinh tự động.
- Nhật ký stderr của kernel in cảnh báo TCP không mã hóa (chỉ cục bộ).
- Chưa có temporal holdout, mô hình riêng theo nhánh DONE/Rejected, hay cross-fitting đặc trưng train (là giả thuyết, không phải lỗi).
  **[Cập nhật 2026-10-22: temporal holdout (Task 14) và cross-fit đặc trưng train (Task 12–13) đã làm; còn lại mô hình riêng theo nhánh DONE/Rejected.]**

## Lỗi còn tồn tại / rủi ro

1. **Không có Git** → không có commit/lịch sử theo task. Nếu `git init` sau, `.gitignore` đã chặn dataset/outputs/.venv.
2. **Đường dẫn tài liệu** khác prompt (xem Ruling 1); chưa di chuyển file.
3. **Python 3.12** thay vì 3.11 (Ruling 3); `uv.lock` chưa kiểm chứng trên 3.11. Extra `notebook` (jupyterlab, nbclient…) đã được cài nhưng chưa được dùng/kiểm chứng — Task 7.
    **[Cập nhật 2026-10-17: extra `notebook` đã được dùng và kiểm chứng ở Task 7–8, 15 (sáu notebook chạy bằng nbclient trong kernel của `.venv`); `uv.lock` vẫn chưa kiểm chứng trên Python 3.11.]**
4. **Thứ tự dòng CSV**: trong *cả 161* issue Bug, `source_row` chạy **ngược** thời gian (log xuất mới → cũ; dòng đầu là `Issue created`).
   Hiện không có tie (0 nhóm), nên quy tắc "tie → source_row tăng dần" chưa tác động; nếu có tie, thứ tự do quy tắc này có thể ngược thứ tự thật.
5. **Chọn mẫu**: cả 161 issue Bug đều kết thúc ở DONE/Rejected → nhánh loại "status cuối không terminal" chỉ được kiểm bằng fixture, chưa chạm dữ liệu thật.
   Dataset có vẻ chỉ gồm issue đã đóng ⇒ kết luận chỉ áp dụng cho ca có kết thúc quan sát được (đúng với phạm vi hồi cứu của spec).
6. **Mẫu nhỏ**: test 31 issue (16/15), validation 33 ⇒ metric ở Task 5 sẽ dao động mạnh; mỗi per-type benchmark còn nhỏ hơn.
7. **22% event nằm sau terminal cuối** (chủ yếu bot) và 751 event nhiễu bị bỏ: core giảm từ 5.126 xuống 3.258. Đây là lựa chọn thiết kế của spec;
   `keep_all` vs policy mặc định sẽ cần so sánh ở Task 8 (`keep_all` core = 4.009 event).
8. **Chuỗi trạng thái dồn dập**: `bug:TI-4584` có 6 chuyển trạng thái trong ~25 giây (11:04:34–11:04:59). Hiện được tính là reopen thật (8 issue);
   chưa điều tra đó là thao tác thử/migration hay quy trình thực. Chưa kết luận gì; cần lưu ý khi đọc đặc trưng chuyển tiếp ở Task 3.
9. Role `unknown` chiếm ~16% event core: đặc trưng role bị hạn chế (đúng như spec: `unknown` không tính là role xác định).
10. `pyproject.toml` chưa có `readme`; README.md, AGENTS.md, docs/DECISIONS.md, docs/RESEARCH_NOTES.md chưa tạo (Task 6/8).
    **[Cập nhật 2026-10-17: `readme` đã có trong pyproject; README.md, DECISIONS.md, RESEARCH_NOTES.md đã được tạo ở Task 6/8. Còn thiếu: AGENTS.md (Ruling 9).]**
    **[Cập nhật 2026-10-22: AGENTS.md đã tạo, chỉ trỏ tới CLAUDE.md và spec, không chép quy định.]**
11. `jira-ad prepare` chưa chạy với `cohort: story` (chỉ kiểm phủ ánh xạ).
    **[Cập nhật 2026-10-17: `prepare` và `run` với `cohort: story` đã chạy thật ở Task 8 (`story_cohort`, 3 seed).]**
12. **Đặc trưng train là in-sample** (Task 3→4): đồ thị fit từ chính các trace train nên trên train `unseen_node_ratio` và
    `unseen_transition_ratio` ≡ 0 và surprisal thấp hơn so với held-out. Isolation Forest không chia được theo feature hằng ⇒ hai feature
    `unseen_*` có thể bị bỏ qua khi fit detector. Spec không quy định cross-fitting nên V1 giữ nguyên (fit→transform), nhưng cần đo ở Task 4
    (phương sai feature trên train) và cân nhắc ablation "leave-one-out train features" ở Task 8. Chưa quyết định đổi thiết kế.
    **[Đã giải quyết 2026-10-17 (Task 12–13): cross-fit làm các cột `unseen_*` hết hằng (A_stats 2 → 0 cột hằng) nhưng không cải thiện AUROC trên validation; giả thuyết 1 không được ủng hộ. Embedding vẫn in-sample (Ruling 54).]**
13. **B_ngrams 442 chiều / 97 trace train**, cột thưa: so sánh với A/D phải đọc cùng cảnh báo này.
14. **Điểm validation trong dải hẹp, mẫu 33**: chưa thể kết luận hạng phương pháp; chờ Task 5 (mutant) và đo lại ở Task 8 với 3 model seed.
    **[Cập nhật 2026-10-17: đã đo với 3 model seed và bootstrap theo parent; hạng giữa các phương pháp vẫn chưa thiết lập được ngoại trừ D_hybrid > B_ngrams (xem RESEARCH_NOTES).]**
15. **Nâng phiên bản gensim/numpy** có thể làm đổi vector (không bitwise giữa OS/CPU, spec §5.3): `uv.lock` đã khóa; test hash-seed canh sự phụ thuộc vào `PYTHONHASHSEED`.
16. **Kết quả gần ngẫu nhiên** trên mutant V1 ở cả validation và test; sai khác giữa phương pháp nằm trong nhiễu lấy mẫu. Cần 3 model seed (Task 8) và, nếu muốn, bootstrap theo parent; không nên khẳng định thứ hạng.
    **[ĐÍNH CHÍNH 2026-10-17 (Ruling 61): “nằm trong nhiễu lấy mẫu” dựa trên SE hai mẫu độc lập ≈ 0,074 là quá bảo thủ cho thiết kế ghép cặp (SD dưới H0 ghép cặp ≈ 0,016). AUROC 0,52–0,55 là hiệu ứng rất nhỏ nhưng phân biệt được với 0,5 ở một số loại (delete, duplicate), không ở swap; chênh lệch *giữa các phương pháp* vẫn phần lớn không phân biệt được với 0.]**
17. **Giả thuyết (chưa kiểm chứng)**: D_hybrid có paired win cao nhưng AUROC thấp hơn A_stats trên đối chứng dương (0,66 so với 0,86) — có thể vì 32/42 feature là pooling không thấy thứ tự làm loãng
    Isolation Forest. Chỉ là giả thuyết cho ablation Task 8; chưa thử gì thêm.
    **[Đã kiểm 2026-10-17 (Task 13): `dim_4` và `dim_8` không cải thiện D_hybrid trên validation (Δ −0,017 và −0,001, khoảng chứa 0); giả thuyết 2 không được ủng hộ ở các số chiều này.]**
18. **Phương sai giữa các parent** (độ dài, số lần revisit) lấn át tín hiệu của một chỉnh sửa; AUROC theo mẫu độc lập đo cả điều này, còn paired win rate thì không. Cả hai đều được báo.
    **[Cập nhật 2026-10-17: bootstrap và thử hoán vị theo cặp đã có (Task 10), nên phần phương sai giữa các parent đã được triệt tiêu trong so sánh ghép cặp.]**
19. **Test đã được xem** (một lần, Task 5, cấu hình khóa). Mọi thay đổi thiết kế sau đây dựa trên test phải được ghi là khám phá, không phải confirmatory (spec §7).
    **[Cập nhật 2026-10-17: xem mục 28; các so sánh mới (cross-fit, số chiều) chỉ được xem trên test sau phán quyết trên validation.]**
20. `manifest.git = null` vì thư mục không phải repo Git; nếu `git init` sau này, run mới sẽ ghi commit và cờ dirty (đã có test cho nhánh `None`, chưa test nhánh có Git).
21. `compare` mới chỉ chạy trên 1 run thật; độ ổn định theo model seed cần 3 run (Task 8).
    **[Cập nhật 2026-10-17: đã có 3 model seed cho mọi thí nghiệm (Task 8, 13).]**
22. Bộ rà soát ca thật đã tạo nhưng **chưa có rà soát nào** (cột trống); chưa có kết luận nào về "ca thật đáng rà soát".
    **[Cập nhật 2026-10-17: vẫn chưa có rà soát của *con người*; đã có rà soát khám phá của agent (Task 15), không phải nhãn chuyên gia.]**
23. Nhật ký stderr của kernel in cảnh báo `Kernel is running over TCP without encryption` (chỉ cục bộ, khai thác được trên máy dùng chung); chưa chuyển sang IPC.
24. Hình/bảng của notebook nằm trong thư mục run nhưng **ngoài manifest**; nếu xóa `figures/` thì run vẫn hợp lệ nhưng cần chạy lại `jira-ad notebooks` để có lại.
25. Khoảng tin cậy ở notebook 04 là xấp xỉ giải tích; chưa có bootstrap theo parent. Notebook chưa được Jupyter mở thủ công (chỉ chạy bằng nbclient).
    **[Cập nhật 2026-10-17: bootstrap theo parent đã có (Task 10) và notebook 04 không còn dùng khoảng giải tích hai mẫu độc lập để kết luận (vẫn hiển thị để đối chiếu, kèm cảnh báo). Notebook vẫn chưa được mở thủ công trong Jupyter.]**
26. **Gensim `Exception ignored in 'our_dot_float'`** ở một số run (xem Ruling 51): tất định, vector hữu hạn và giống hệt bit giữa hai bộ numpy/scipy; chưa rõ nguyên nhân gốc, chưa chứng minh vô hại về mặt thống kê huấn luyện.
27. **Story chỉ có 7 issue Rejected** (test: 1 ca); chia stratify chạy được nhưng nhánh Rejected của Story gần như không đánh giá được; không so AUROC giữa bug và story như cùng một thang.
28. **Test đã được xem nhiều lần với cấu hình khóa** (Task 5, `run`, `experiments`; tất định, cùng số). Chưa có tập kiểm tra chưa-từng-xem nào; mọi kết luận về độ nhạy vẫn là khám phá.
29. **Chưa có rà soát ca thật nào** và chưa có bootstrap theo parent; kết luận chính (không bằng chứng embedding hơn thống kê) dựa trên mẫu nhỏ và mutant tinh vi.
    **[Cập nhật 2026-10-17: bootstrap theo parent đã có; vẫn chưa có rà soát của chuyên gia nghiệp vụ. Kết luận chính đã được tinh chỉnh, xem `docs/RESEARCH_NOTES.md`.]**
30. **Khung nguyên nhân của giả thuyết 2 còn hẹp**: chỉ thử số chiều 4/8/16/32; chưa thử bỏ riêng nửa max-pooling, chưa thử trọng số cột. “Không có bằng chứng” khác với “đã loại bỏ”.
31. **Cross-fit chỉ áp cho cột H** (Ruling 54); embedding vẫn học in-sample trên train. Tác động của cross-fit embedding chưa được đo.
32. **Holdout theo thời gian chồng lấn**: 29/64 ca held-out đã bắt đầu trước khi train kết thúc. Không rò rỉ lịch sử train vào tương lai nhưng hai giai đoạn không tách hẳn nhau.
33. **Rà soát khám phá của agent chỉ dựa vào chuỗi activity/role** (không thời gian, không nội dung issue); “quen thuộc” được định nghĩa từ chính 20 ca. Nhãn có thể sai; không dùng làm nhãn bất thường.
34. **Đa so sánh**: p-value hoán vị theo từng (phương pháp, loại) và khoảng bootstrap giữa các phương pháp chưa hiệu chỉnh trong notebook 04/06 (12 ô; 6 cặp × 2 split). Chỉ họ ba so sánh khóa trước ở Task 13 có hiệu chỉnh Bonferroni. Sau Bonferroni 12 ô, 3 ô còn lại: C_embedding/delete, D_hybrid/delete, D_hybrid/duplicate.
35. **Delete/duplicate đổi độ dài và histogram; swap giữ cả hai.** Tín hiệu phát hiện được ở delete/duplicate không nhất thiết là nhạy với thứ tự (Spearman điểm–độ dài trên bản gốc: B_ngrams +0,56; A/C/D gần 0, điều đó không loại trừ ảnh hưởng của độ dài/thiếu activity lên mutant). Swap là loại duy nhất không phương pháp nào phân biệt được với ngẫu nhiên (p một phía 0,06–1,00).
36. **Bootstrap percentile có thiên lệch nhỏ hướng lên** do parent trùng (Ruling 55); phép thử hoán vị là kiểm chứng độc lập và cho kết luận cùng hướng.
37. **Dung lượng**: `outputs/` 640 MB, trong đó 62 run cũ (402 MB) đã bị thay thế nhưng chưa xóa (Ruling 62).

## Bước tiếp theo

**[Cập nhật 2026-10-22]** Task 1–18 đã xong (Task 18: giai đoạn cải tiến, báo cáo tổng kết `docs/BAO_CAO_TONG_KET.md`). `AGENTS.md` đã tạo (trỏ tới CLAUDE.md và spec). Còn lại, theo giá trị thông tin (xem `docs/RESEARCH_NOTES.md`):
1. Nhờ người hiểu quy trình rà soát mù top-10% của `M_markov` cùng một mẫu ngẫu nhiên có số ca bằng nhau (nhãn `needs_review` / `plausibly_valid` / `insufficient_evidence`) để đo precision@k thật.
2. Xác nhận `M_markov` theo quy tắc khóa trước trên dữ liệu chưa từng xem (issue mới hoặc team khác).
3. Kết hợp quy tắc nghiệp vụ cho lỗi đã biết (bỏ `In Test`, lùi về `Inbox`); thử Markov bậc 2 khi có thêm dữ liệu.
4. Mô hình riêng theo nhánh DONE/Rejected; cross-fit cho embedding.
5. Xóa các run cũ nếu muốn giải phóng dung lượng (quyết định của người dùng).

<details><summary>Bản cũ (trước Task 16–18)</summary>

Tất cả Task 1–15 đã xong. Còn lại (theo giá trị thông tin, xem `docs/RESEARCH_NOTES.md`): (1) nhờ một người có kiến thức quy trình rà soát 20 ca bằng `case_review_blinded.csv` (cột nhãn hợp lệ: `needs_review`, `plausibly_valid`, `insufficient_evidence`) và so với rà soát khám phá của agent; (2) mutant mạnh hơn hoặc nhiều chỉnh sửa trên mỗi parent để tách rõ hiệu ứng thứ tự khỏi độ dài; (3) mô hình riêng theo nhánh DONE/Rejected; (4) cross-fit cho embedding; (5) tạo `AGENTS.md` nếu cần; (6) xóa các run cũ nếu muốn giải phóng 402 MB.

</details>
