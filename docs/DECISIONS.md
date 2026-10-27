# DECISIONS — thay đổi so với phương án và lý do

Tài liệu này gom các quyết định *khác với hoặc không được xác định bởi* [spec](superpowers/2026-10-16-jira-ad.md) mà người triển khai (Claude) đã tự đưa ra, theo nhóm.
Mỗi mục: **quyết định — lý do — chi phí nếu sai**. Số thứ tự trùng với mục *Rulings* trong [PROGRESS.md](PROGRESS.md), nơi có thêm bằng chứng kiểm tra.
Không có quyết định nào làm đổi mục tiêu, hợp đồng dữ liệu, ranh giới fit/transform hay protocol đánh giá của spec.

## Quy trình và môi trường

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 1 | Giữ tài liệu spec ở `docs/superpowers/2026-10-16-jira-ad.md`, không chuyển vào `plans/` | File thật nằm ở đó; không tự di chuyển file của người dùng | `mv` một lệnh + sửa 1 dòng CLAUDE.md |
| 2 | Không Git: `docs/PROGRESS.md` làm ledger, không commit; thêm `.gitignore` | Thư mục chưa là repo; chặn dataset/outputs nếu `git init` sau | Không có lịch sử commit theo task |
| 3 | Python 3.12.7 (`requires-python >=3.11,<3.13`), không tải 3.11 | Máy chỉ có 3.12; tránh tải runtime | `uv python install 3.11` + `uv lock` lại |
| 4 | Phiên bản do resolver chọn (numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, gensim 4.4.0…) | Spec: không sao chép pin cũ; đã kiểm gensim fit/save/load | Pin thấp hơn nếu gensim lỗi (xem rủi ro `our_dot_float`) |
| 8, 40 | Thêm `tests/helpers.py`, `conftest.py`, `test_types/cli/environment.py`, lớp `ProjectConfig/RunSettings/NotebookConfig`, `readme` trong pyproject | Cần cho fixture và đủ các section YAML mẫu | Xóa file/lớp |
| 9 | Chỉ tạo `CLAUDE.md`, chưa tạo `AGENTS.md` | Người dùng chỉ yêu cầu CLAUDE.md | Tạo `AGENTS.md` ngắn |
| 47 | `ruff line-length` 110 | Chú thích tiếng Việt làm dòng dài | Đổi lại 100 và ngắt dòng |

## Dữ liệu, tiền xử lý, split

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 5 | Khóa tùy chọn `data.reference_counts` | Audit báo "sai khác" theo spec §2 mà không hardcode trong code | Xóa khóa |
| 6 | `source_row` = chỉ số 1-based của dòng dữ liệu (không tính header) | "vị trí dữ liệu trong CSV" (§4.1) | Đổi offset |
| 7 | Schema CSV nghiêm ngặt; timestamp thiếu timezone, `issueKey` trống bị từ chối | Không đoán múi giờ/khóa | Nới lỏng loader |
| 11 | Activity = động từ + tên field, không lưu giá trị; status giữ nguyên giá trị | Spec chỉ cho thứ tự ưu tiên + fallback; mức mịn nằm trong `configs/actions.yaml` | Sửa YAML (đổi `action_rules_hash`) |
| 12 | Activity chính của dòng nhiều mệnh đề theo thứ tự ưu tiên trong YAML; phần còn lại ở `secondary_changes` | Giữ một event/dòng (§4.1) | Đổi quy tắc chọn |
| 13 | Split bằng SHA-256 của `seed:case_id`; stratum < 3 ca → lỗi | Ổn định qua NumPy/OS/thứ tự; YAML mẫu không có fallback | Đổi hàm gán |
| 14 | Cắt core theo vị trí; event terminal cuối luôn giữ khi lọc nhiễu | Tập ca không phụ thuộc noise policy | Đổi quy tắc cắt |

## Đặc trưng, walk, embedding, detector

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 17 | \|V\| trong làm mượt = activity train + `__END__`; +1 cho UNK | Spec chỉ ghi "\|V\| vocabulary train" | Đổi hằng `n_targets` |
| 18 | DFG luôn có hướng; `graph.directed` chỉ điều khiển walk | Surprisal cần đếm có hướng | — |
| 19 | Định nghĩa 10 đặc trưng H (revisit, role xác định, surprisal gồm biên…) | Spec chỉ đặt tên | Sửa `_h_features` |
| 20, 21, 22 | Token role thiếu là hằng số giao thức; khóa bigram JSON; `PrepareResult.traces_for` | Encoder không phụ thuộc YAML; không nhập nhằng | — |
| 23–25 | Walk bắt đầu từ mọi nút; gỡ `hashfxn` tùy biến (gensim 4.4.0 không phụ thuộc `PYTHONHASHSEED`); vector OOV = zero | Đã đo bằng thực nghiệm; test canh khi nâng gensim | Thêm `hashfxn` nếu gensim đổi |
| 26–28 | C = pooling + `unseen_node_ratio`; D = pooling + H; `fit_detector(..., seed=None)`; bundle tự chứa (kể cả nội dung `actions.yaml`) | Spec §5.4, §9 | — |

## Mutation, đánh giá, pipeline

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 29 | Event đầu/cuối được bảo vệ; ứng viên trùng chuỗi gốc bị loại; RNG riêng theo (seed, parent, loại); thêm cột ledger | Spec §6.1 | — |
| 30, 31 | Ghép cặp theo parent, giao tập giữa các phương pháp, `macro_by_method`; đối chứng dương chỉ trên validation | Spec §6.2; kiểm tra bộ máy | Đổi cách tổng hợp |
| 32 | Test được xem một lần ở Task 5 với cấu hình đã khóa (checksum), model seed 42 | Quy trình "khóa rồi mới xem test" | — (đã ghi trong RESEARCH_NOTES) |
| 33–35 | `run_id` = UTC + hash cấu hình; một run = một model seed; validation cũng được đánh giá | Spec §9, §6.2 | — |
| 36 | Bộ rà soát xếp hạng theo `D_hybrid`, `review_id` không mã hóa hạng | Phương pháp đề xuất; chặn lộ hạng | Đổi phương pháp xếp hạng |
| 37, 46 | `compare` nhóm theo protocol × cấu hình mô hình; mỗi model seed chỉ giữ run mới nhất | Tránh trộn không tương thích và std giả | — |
| 38, 39 | `score` lấy cohort/quy tắc/chính sách từ bundle; run lỗi ghi `failed` (cả Ctrl-C) | Spec §8, §9 | — |

## Notebook và thực nghiệm thành phần

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 41–45 | Nhận xét notebook sinh từ số liệu; chạy bằng kernelspec tạm (tránh `km=` vì nbclient bỏ timeout); không sửa tập artifact đã băm; `open_run` kiểm fingerprint đủ bốn lớp | Spec §7, §10; hai lỗi thật do test bắt (xem PROGRESS) | — |
| 48 | `configs/experiments.yaml` + `jira-ad experiments`: mỗi thí nghiệm đổi một yếu tố, ba model seed, nhiều thay đổi phải có `allow_multiple_changes` kèm lý do; manifest ghi `experiment` và `rerun_command` | Spec §11 Task 8 ("từng yếu tố một", không tích Descartes) | — |
| 49 | Các thí nghiệm Task 8 báo trên test như **độ nhạy khám phá**; không chọn cấu hình theo chúng; baseline vẫn là cấu hình ghi nhận | Spec §5, §7: không chọn theo test rồi công bố như holdout | — |
| 50 | `keep_all_noise` và `story_cohort` nằm ở protocol khác và không được so trực tiếp với baseline | Khác nội dung core/mutant hoặc khác cohort | — |
| 51 | Không chặn thông báo `Exception ignored in 'our_dot_float'` của gensim; ghi vào rủi ro | Đã đo: tất định, vector giống hệt bit giữa hai bộ numpy/scipy; chưa rõ nguyên nhân gốc | Bọc/lọc stderr hoặc nâng gensim |
| 52 | Thêm kiểm tra rò rỉ đầu-cuối (sửa ca held-out ⇒ trạng thái fit trên train không đổi) và bất biến thứ tự dòng | Bằng chứng trực tiếp cho tiêu chí nghiệm thu "không fit nào đọc test" | — |

## Mở rộng sau Task 8 (Task 9–15, 2026-10-17)

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 53 | Khóa cấu hình mới (`cross_fit_folds`, `split.strategy`, section `evaluation`) chỉ hiện khi khác mặc định; `baseline.yaml` không bị sửa | Giữ `config_hash` của 26 run cũ để `open_run`/`compare` còn đúng; user yêu cầu bám baseline đã đề ra | Thêm khóa vào baseline.yaml (sẽ đổi hash và protocol) |
| 54 | Cross-fit chỉ áp cho cột H phụ thuộc đồ thị; embedding vẫn in-sample trên train | Embedding học trên từng fold thuộc các không gian không so sánh được | Cross-fit cả embedding bằng căn chỉnh không gian (chưa làm) |
| 55–56 | Bootstrap theo parent (percentile, 2000 lần) và thử hoán vị trong cặp (2000 lần) thay cho công thức Hanley–McNeil | Dữ liệu ghép cặp; công thức hai mẫu độc lập quá rộng (SE 0,074 so với SD null 0,016) | Đổi phương pháp khoảng (BCa) hoặc tăng số lần |
| 57 | Đối chứng dương chính thức `shuffle_internal`, chỉ validation, hàm từ chối split khác | Kiểm tra bộ máy; không được dùng để chọn cấu hình (Ruling 31) | Chạy thêm trên test (không nên) |
| 58 | Quy tắc quyết định khóa trước trong `experiments.yaml` (`decision`): D_hybrid, validation, Bonferroni 3 so sánh | Tránh chọn sau khi thấy kết quả; ba giả thuyết nêu từ trước | Đổi họ so sánh (phải ghi là sau-khi-xem) |
| 59 | Holdout theo thời gian sắp theo thời điểm event terminal cuối, hòa theo `trace_id`, báo số ca chồng lấn | Spec §5.1 mở rộng; đo mức tách thời gian thật thay vì tuyên bố | Dùng thời điểm tạo, hoặc loại ca chồng lấn |
| 60 | Rà soát khám phá của agent từ bảng mù, lưu ở `reviews/` ngoài manifest, sha256 bảng mù được ghi lại | Spec §6.3 cho phép agent là reviewer khám phá; giữ nguyên artifact đã băm | Bỏ file; nhờ chuyên gia gán nhãn lại |
| 61 | Đính chính: bỏ kết luận “mọi AUROC chứa 0,5” dựa trên SE hai mẫu độc lập | Đã kiểm độc lập bằng hoán vị trong cặp | — (đã sửa trong RESEARCH_NOTES/notebook) |
| 62 | Không xóa 62 run cũ | Xóa artifact là quyết định của người dùng | Xóa thủ công để giải phóng 402 MB |
| 63 | `open_run()` tự chọn run hoàn tất mới nhất khớp `configs/baseline.yaml` hiện tại khi không chỉ định run | Notebook mở tay trong VSCode không có biến `JIRA_AD_RUN_DIR`; vẫn kiểm fingerprint và in cách chọn để không thành cache âm thầm | Bắt buộc `JIRA_AD_RUN_DIR` như cũ |

## Giai đoạn cải tiến (Task 18, 2026-10-22)

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 64 | Ba phương pháp mới E/F/M và hai mutant `skip_status`/`multi_edit`; quy tắc chọn trên validation khóa trong `configs/improvement_plan.yaml` trước khi chạy | Mỗi phương pháp nhắm một điểm yếu đã đo; tránh chọn sau khi xem | Chạy lại với quy tắc khác, ghi là sau-khi-xem |
| 64 | Giao thức cross-validation 5 fold trên cả 161 issue, ghi là **khám phá** | Tăng từ 31 lên 161 parent; nhưng dùng cả test V1 đã xem | Chỉ dùng làm giả thuyết, cần dữ liệu mới để xác nhận |
| 64 | Ngưỡng ba mức ứng dụng (cảnh báo / bộ lọc / chưa đủ) do tôi đặt, khóa trước | Có tiêu chí cụ thể thay vì đánh giá cảm tính | Đổi ngưỡng trong YAML |
| 65 | Chuẩn hóa z theo điểm train cho E_score_fusion và cho điểm gộp fold | Điểm IF của các mô hình khác nhau không cùng thang | AUROC gộp fold lệch nhẹ |
| 64 | Không tạo notebook 07; kết quả đọc qua CSV/hình và `docs/BAO_CAO_CAI_TIEN.md` | Bộ test hiện khóa đúng 6 notebook | Thêm notebook và sửa test |

## Giai đoạn 2 — đồ án môn học (Task 19+, 2026-10-26)

Nguồn: `CLAUDE.md` mục "Quyết định đã duyệt" (người dùng trả lời 6 câu hỏi; câu 2 và 4 khác đề xuất của tôi).

| # | Quyết định | Lý do | Chi phí nếu sai |
|---|---|---|---|
| 67 | Kế hoạch viết lại theo bước A–G, module phẳng, một lệnh `jira-ad process` | Khớp CLAUDE.md | Đổi tên module |
| 68 | Làm = In Progress, In Test; chờ = Inbox, To Investigate, INVESTIGATED, To Do (+ `__CREATED__`); độ nhạy To Investigate là làm; cận trên PT do cập nhật bù | Quyết định 2; "To …" là hàng đợi trong Jira | Đổi phân loại trong YAML |
| 69 | Định mức = P75 dwell ngày làm việc theo trạng thái, trên cả 161 ca | Quyết định 3; phân tích mô tả dùng toàn bộ issue | Thêm `scope: train` |
| 70 | Ngày làm việc theo offset gốc của event mở khoảng; UTC là độ nhạy | Quyết định 7; không đoán múi giờ | Chênh ≤ 1 giờ/khoảng qua đổi giờ |
| 71 | Mô hình chuẩn dạng cung → Petri net transition ẩn mỗi cung; 7 cờ chỉ đếm; khai phá chạy trước điểm dừng replay | Quyết định 4 | Chạy lại replay |
| 72 | Graph2Vec cắt; báo cáo `BAO_CAO_MON_HOC.md`; notebook 07; đổi tên `Untitled.md` | Quyết định 5, 6; CLAUDE.md | — |
| 73 | Little theo tuần UTC | Little không đo theo ngày làm việc | Dời ranh giới tuần 7–8 giờ |
| 74 | Lượt ở trạng thái kết thúc giữa chừng tính vào CT là chờ; CT = Σ dwell các lượt | Ca mở lại vẫn đang nằm trong quy trình | Bỏ 5 lượt khỏi CT |
| 75 | Lần đổi trạng thái đầu không là bù; đổi sang chính trạng thái không là lùi | Khớp định nghĩa 553 khoảng | — |
| 76 | `load_cohort` không tính split | Bước A là mô tả | — |
| 77 | Betweenness có hướng tôpô; closeness, eigenvector trên bản vô hướng; PageRank trọng số d = 0,85; bỏ vòng tự thân, nút biên | "Số lần" là tần suất, không phải khoảng cách | Thêm biến thể khoảng cách = 1/số lần |
| 78 | Định mức chỉ cho trạng thái ≥ 10 lượt | Phân vị của 1–5 lượt vô nghĩa | Đổi `norms.min_visits` |
| 79 | Ưu tiên theo tổng ngày vượt định mức | Tỉ lệ trễ ≈ 25% theo cấu tạo | Đổi tiêu chí |
| 80 | Sửa lỗi trọng số DFG activity (`weight` → `count`); manifest có `code.sha256` | Kiểm chéo với V1 phát hiện | — |
| 81 | Bước B chỉ cho bug | Story chỉ đặt cạnh ở bước A | Chạy thêm cho story |
| 82 | pm4py extra `process` (AGPL, học thuật), lock chỉ thêm 6 gói | Quyết định 1; chạy thử đạt | Venv riêng nếu xung đột |
| 83 | Giả định A1: CREATE = vào Inbox ngầm định (chờ duyệt) | 95 ca CREATE → To Investigate, 1 ca Inbox tường minh | Sửa cung trong YAML |
| 84 | Lane = vai trò chuyển ra nhiều nhất; chỉ XOR tách | Người hoàn tất bước | Đổi sang vai trò cổng |
| 85 | Hình Petri net sắp theo cấu trúc (WL + SHA-256) | Tên nút pm4py đổi theo PYTHONHASHSEED | — |
| 86 | Cờ dùng định nghĩa rộng (26/39) bên cạnh số nguyên biến thể (22/22) | Đều tính lại bằng pandas thô | Thu hẹp định nghĩa |
| 87 | Log pm4py: `t_enter` + `visit_index` µs | Giữ thứ tự khi trùng giờ | — |
| 88 | Quyết định 8: approved; `alternative_models` (luồng nhanh, không phải chuẩn); giữ cung 0 lần; sai lệch theo nhánh + cập nhật bù | Người dùng duyệt (a) | — |
| 89 | Chỉ số chính câu 3 = tỉ lệ ca khớp hoàn toàn; không coi fitness token 0,965 là điểm dừng 3 | 56 ca vẫn lệch | Dừng hỏi nếu người dùng muốn |
| 90 | Notebook 07+ chỉ chạy trên run `process`; loader có kiểm fingerprint, tự chọn run | Quyết định 9 | — |
| 91 | Nhận xét PT suy từ độ rộng khoảng (> 10 điểm %); sửa bố cục hình | Lỗi viết cứng sai cho story | Đổi ngưỡng |
| 92 | Xóa hai run lỗi trọng số | Người dùng cho phép | — |
| 93 | Bỏ thử cung làm mô hình mất hợp lệ ⇒ ghi chú, không ném lỗi | Trường hợp biên | — |
| 94 | Bảy phép kiểm chứng BPR, ngưỡng khóa trước theo nguyên tắc | Tránh chọn sau khi xem | Đổi ngưỡng phải ghi sau-khi-xem |
| 95 | TO-BE + pilot thiết kế sau phán quyết, chỉ ứng viên được ủng hộ; lane Investigating = lane To Investigate AS-IS | Thiết kế dựa trên bằng chứng | Sửa YAML `tobe_model` |
| 96 | Giả thuyết PO: phán quyết theo trung vị (không ủng hộ) + bảng đuôi mô tả | Kiểm chứng ghi chú người dùng | — |
| 97 | Sửa lỗi f-string tự gây; test hồi quy; bù TDD sai thứ tự bằng đột biến | Lần chạy thật thất bại | — |
| 98 | What-if = tính lại trên log; mục tiêu TO-BE = giá trị what-if | Không bịa số TO-BE | — |
| 99 | Tham số + nhóm nghiệp vụ activity khóa trước | Tránh chọn sau khi xem | Đổi định nghĩa nhóm |
| 100 | So biểu diễn bằng 1-NN LOO + K-means trên bài toán nhóm nghiệp vụ, có baseline | Cùng bài toán cho cả hai biểu diễn | — |
| 101 | Hồ sơ 7 chiều, phân vị trong nhóm nhánh × độ dài, M_markov khử độ dài | Tránh ca dài tự lên đầu | Đổi chiều/nhóm |
| 102 | Bước E chạy được khi thiếu nguồn, ghi `status.json` | Dự án test nhỏ | — |
| 103 | Đối chiếu số tự động là điều kiện cần (khớp chuỗi ở cùng độ chính xác) | Bắt chép sai số | Bổ sung kiểm ngữ cảnh |
| 104 | Định danh (offset, mã Zenodo, năm) trong code span | Không phải số đo | — |
| 105 | Báo cáo trích run `20261026T011903Z-5d4973b3` | Run cuối có đủ bước A–E | Chạy lại nếu đổi mã tính toán |
| 106 | Một định nghĩa "trong đợt bù" (lần đổi thuộc đợt bù) cho FPY và bảng sai lệch | Rà soát I1 | — |
| 107 | TO-BE chính = từ chối khi kết thúc điều tra; cận trên tách dòng | Rà soát I2: nhất quán với TO-BE | — |
| 108 | Số lần đổi trạng thái theo đường TO-BE thật | Rà soát I4 | — |
| 109 | Bằng chứng auto-transition theo trạng thái; phần đuôi PO tách theo trạng thái đích | Rà soát I3, I5 | — |
| 110 | Danh sách đồng thuận: top theo tỉ lệ số ca được rút, ngưỡng 70% | Quyết định người dùng; tránh thổi phồng | — |
| 111 | Bảng mù: Fisher + Wilson + Newcombe + OR, kiểm fingerprint trước khi mở khóa | Quyết định người dùng | — |
| 112 | Sửa M12 (−0,0), M3 (Spearman 0,121), thêm fitness ca không khớp | Rà soát + người dùng | — |
| 113 | Hình bản nộp sinh lại từ run cuối bằng hàm vẽ có sẵn; script xuất docx ở scratchpad | Không vẽ tay, không thêm phụ thuộc | Chạy lại script khi run đổi |
