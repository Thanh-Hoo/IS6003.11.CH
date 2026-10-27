# Phát hiện các ca xử lý Jira khác thường bằng biểu diễn đồ thị Node2Vec và Isolation Forest

Đồ án môn học — chủ đề: học biểu diễn đồ thị (Node2Vec là phương pháp biểu diễn, Isolation Forest là bộ xếp hạng khác thường).

> Mọi số trong báo cáo lấy từ run bàn giao `outputs/runs/20261017T081309Z-930f8a85` và 35 run còn lại của kế hoạch `configs/experiments.yaml` (xem Phụ lục B), qua sáu notebook trong `notebooks/`.
> Báo cáo không có nhãn bất thường thật, nên không có phát biểu nào về độ chính xác phát hiện lỗi thực tế.

## 1. Tóm tắt

Chúng tôi xếp hạng các **issue Jira đã kết thúc** theo mức khác thường của diễn tiến xử lý. Mỗi issue là một chuỗi hoạt động (activity) và vai trò (role) theo thứ tự. Đồ thị directly-follows (DFG) chỉ dựng từ tập train;
Node2Vec (random walk có thiên lệch + Skip-gram) học vector cho từng activity; vector của một issue là mean/max pooling các vector của nó; Isolation Forest cho điểm khác thường.
Vì **không có nhãn bất thường thật**, đánh giá là *bán tổng hợp*: so các issue gốc với các “mutant” cấu trúc do chúng tôi chèn (hoán đổi hai activity kề nhau, xóa một activity, lặp một khối 1–2 activity).

Kết quả chính (dữ liệu bug, 161 issue; holdout 97/33/31 issue; ba model seed):

1. Pipeline chạy từ event log thật đến đặc trưng, mô hình, bảng kết quả và phân tích ca; kết quả tái lập (chạy lại toàn bộ kế hoạch lần hai cho phán quyết trên validation trùng tới 1e-16) và không rò rỉ giữa train và held-out (đã đo trực tiếp: sửa nội dung ca held-out không đổi bit nào của trạng thái đã fit).
2. Với mutant một chỉnh sửa, cả bốn phương pháp chỉ đạt macro AUROC **0,51–0,54**: hiệu ứng rất nhỏ. Hiệu ứng này khác 0,5 ở `delete_internal` và `duplicate_block` nhưng **không** ở `swap_adjacent` (không phương pháp nào).
3. Biểu diễn đồ thị (`D_hybrid`) **cao hơn n-gram** (`B_ngrams`) ở cả validation (+0,047) và test (+0,031) với khoảng bootstrap không chứa 0, nhưng **chưa chứng minh** được là hơn thống kê quy trình (`A_stats`): +0,023 và +0,012 với khoảng chứa 0.
4. Hai giả thuyết nêu từ trước (cross-fit đặc trưng train; pooling làm loãng `D_hybrid`) được kiểm theo quy tắc quyết định khóa trước: **không được ủng hộ**.
5. Một bài học phương pháp: công thức sai số chuẩn cho hai mẫu độc lập (≈ 0,074) quá rộng cho dữ liệu ghép cặp; bản đầu của đồ án kết luận sai “mọi AUROC chứa 0,5”. Đã đính chính bằng bootstrap theo parent và thử hoán vị trong cặp.

## 2. Bài toán và câu hỏi nghiên cứu

**Đầu vào:** lịch sử một issue đã quan sát (activity và role theo thứ tự). **Đầu ra:** điểm khác thường liên tục, thứ hạng và bằng chứng hành vi để rà soát.
Điểm cao **không** đồng nghĩa vi phạm quy trình; hiếm ≠ sai; `Rejected` ≠ bất thường.

- **Câu hỏi chính:** biểu diễn đồ thị có bổ sung giá trị so với thống kê quy trình (A) và unigram/bigram (B) không?
- **Câu hỏi phụ:** chiều embedding, ngữ cảnh vai trò, tham số walk, đặc trưng chuyển tiếp ảnh hưởng thế nào? Mean/max pooling đánh mất sai lệch thứ tự nào?

Phạm vi V1: tập bug, CPU, hồi cứu trên ca có kết thúc quan sát được, chỉ mô hình hóa cấu trúc/thứ tự (thời gian chỉ dùng khám phá dữ liệu). Không tuyên bố phát hiện sớm hay vận hành online.

## 3. Dữ liệu

Nguồn: bộ dữ liệu *Process Mining from Jira Issues at a Large Company* (ICSME 2023), https://zenodo.org/records/8275679 — event log của Team Newt, hai CSV (bug, story) cùng bốn cột `issueKey, timestamp, role, action`. Dữ liệu gốc chỉ đọc; mọi file được ghi SHA-256 (bug: `cda16f1c…`).

| | Bug | Story |
|---|---:|---:|
| Event | 5.126 | 4.439 |
| Issue | 161 | 182 |
| Event/issue: min – trung vị – max | 4 – 20 – 239 | 5 – 15 – 212 |
| Role `bot` | 43,5% | 43,7% |

Chất lượng và chuẩn hóa (bug): 15 role trống, 837 role `unknown` (16%); cả 161 issue có thứ tự dòng CSV mới → cũ nên phải sắp lại theo thời điểm UTC; không có dòng trùng hay trùng thời điểm.
99 hành động thô được ánh xạ thành 50 activity (động từ + tên field, không lưu giá trị; trạng thái giữ nguyên giá trị), không event nào rơi vào `OTHER_ACTION`.

**Core view** (dùng cho mô hình): giữ đến cập nhật trạng thái terminal *cuối* (DONE hoặc Rejected), giữ mọi vòng mở lại, bỏ cập nhật `RemoteIssueLink` chung chung của bot.
5.126 event → **3.258 event core** (1.117 event nằm sau terminal cuối, 94% là bot; 751 event nhiễu). Cả 161 issue đều kết thúc ở DONE (83) hoặc Rejected (78), nên kết luận chỉ áp dụng cho ca đã đóng.

Quan sát về quy trình (khám phá, `analysis_only`): 153 biến thể cho 161 trace, 98% biến thể chỉ xuất hiện một lần, nên so khớp nguyên chuỗi gần như vô dụng. Nhánh DONE (trung vị 25 event, gần như luôn qua In Progress/In Test) và Rejected (trung vị 12 event, hầu như bỏ qua quy trình) là hai quần thể rất khác nhau.

**Chia dữ liệu:** theo issue (không theo event), seed 42, tỷ lệ 0,60/0,20/0,20, phân tầng theo trạng thái kết thúc: train 97 (50 DONE, 47 Rejected), validation 33 (17, 16), test 31 (16, 15). Mọi thứ học được (đồ thị, embedding, từ vựng, mô hình) chỉ fit trên train.

## 4. Phương pháp

**Đồ thị.** DFG có hướng từ train; nút là activity (thêm `__START__`, `__END__`); trọng số là số lần directly-follows, đếm theo từng trace. Train có 51 nút (49 activity), 386 cạnh, 1.998 chuyển tiếp.
Xác suất chuyển tiếp làm mượt Laplace (α = 1) với một nhóm UNK; surprisal = −log P.

**Node2Vec.** Sampler random walk tự viết (đã kiểm chứng xác suất bias 1/p, 1, 1/q trên đồ thị nhỏ), rồi Skip-gram của Gensim. Cấu hình baseline: d = 16, độ dài walk 20, 50 walk mỗi nút, window 3, p = q = 1, 20 epoch, negative 5, một worker.
Node chưa thấy ở validation/test nhận vector 0 và được báo qua tỷ lệ `unseen_node_ratio`; không retrain.

**Bốn cấu hình đối chứng** (cùng Isolation Forest 200 cây; điểm = −`score_samples`, lớn hơn = khác thường hơn):

| ID | Đặc trưng | Số chiều |
|---|---|---:|
| A_stats | 10 thống kê quy trình H (độ dài, tỷ lệ activity khác nhau, lặp kề nhau, quay lại activity, đổi role xác định, độ phủ role, surprisal trung bình/lớn nhất, hai tỷ lệ chưa thấy) | 10 |
| B_ngrams | H + unigram + bigram **có thứ tự** (tần suất tương đối) | 442 |
| C_embedding | mean/max pooling vector Node2Vec + `unseen_node_ratio` | 33 |
| D_hybrid | mean/max pooling + H (phương pháp đề xuất) | 42 |

Mean/max pooling **không thấy thứ tự**: hai chuỗi cùng histogram cho cùng vector pooled. Phần thấy thứ tự của `D_hybrid` đến từ các cột H (surprisal chuyển tiếp).

## 5. Thiết kế đánh giá

**Nhãn bán tổng hợp.** `is_injected` = 0 là trace gốc (chưa xác nhận là bình thường), = 1 là mutant. Ba loại mutant, mỗi parent tối đa một mutant mỗi loại, event đầu và cuối được bảo vệ, role đi cùng activity:
`swap_adjacent` (đổi hai activity kề nhau, giữ độ dài), `delete_internal` (xóa một activity nội bộ), `duplicate_block` (lặp khối 1–2 activity). Mutant chỉ sinh từ parent validation/test (seed 1042 và 2042): 99 mutant ở validation, 93 ở test.
Mỗi loại dùng một bản gốc và một mutant cho mỗi parent, nên tỷ lệ chèn 0,5 là tỷ lệ **thiết kế**, không phải tỷ lệ bất thường thực tế.

**Metric.** AUROC, Average Precision và *paired win rate* (tỷ lệ mutant có điểm cao hơn chính parent của nó, hòa tính 0,5), theo từng loại và macro (trung bình ba loại).

**Suy luận thống kê cho dữ liệu ghép cặp.** Vì mỗi mutant sinh từ chính một bản gốc, hai lớp không độc lập. Dùng (i) **bootstrap theo `parent_case_id`** (resample parent, mang theo bản gốc và mọi bản con; mọi phương pháp dùng chung lần resample nên chênh lệch giữa phương pháp là chênh lệch ghép cặp;
khi gộp ba model seed thì lấy trung bình *trong từng lần resample*) và (ii) **thử hoán vị trong cặp** (giả thuyết không: bản gốc và mutant của cùng parent cùng phân phối).

**Đối chứng dương** (chỉ validation): xáo toàn bộ phần nội bộ của parent. Dùng để kiểm tra bộ máy; không phải loại mutation đánh giá, không dùng chọn cấu hình.

**Quy tắc khóa trước.** Trước khi chạy ba thí nghiệm kiểm hai giả thuyết (`cross_fit_5`, `dim_4`, `dim_8`), quy tắc quyết định được ghi vào `configs/experiments.yaml` (2026-10-17): chỉ số chính là macro AUROC của `D_hybrid` trên **validation**, trung bình ba model seed;
một thí nghiệm chỉ là ứng viên cải thiện nếu khoảng bootstrap của (thí nghiệm − baseline) nằm hoàn toàn trên 0 ở mức tin cậy 1 − 0,05/3. Dù kết quả thế nào, baseline đã khóa vẫn là cấu hình ghi nhận. Test chỉ được xem sau phán quyết, để mô tả.

## 6. Kết quả

### 6.1 Hiệu năng của bốn phương pháp

Macro AUROC, trung bình ba model seed (test: ± độ lệch chuẩn theo seed); khoảng bootstrap theo parent 95% (2000 lần). Paired win rate và AP là macro trên test.

| Phương pháp | Validation (33 parent) | Test (31 parent) | Khoảng bootstrap (test) | Paired win (test) | AP (test) |
|---|---:|---:|---|---:|---:|
| A_stats | 0,524 | 0,531 ± 0,007 | [0,501; 0,567] | 0,593 | 0,534 |
| B_ngrams | 0,500 | 0,513 ± 0,006 | [0,492; 0,536] | 0,563 | 0,529 |
| C_embedding | 0,547 | 0,535 ± 0,006 | [0,515; 0,563] | 0,611 | 0,542 |
| D_hybrid | 0,547 | 0,544 ± 0,004 | [0,523; 0,575] | 0,661 | 0,560 |

Theo loại mutation (AUROC test, trung bình ba seed) và p-value một phía của thử hoán vị trong cặp (run seed 42):

| | delete_internal | duplicate_block | swap_adjacent |
|---|---:|---:|---:|
| A_stats | 0,513 (p = 0,27) | 0,553 (p = 0,03) | 0,528 (p = 0,14) |
| B_ngrams | 0,507 (p = 0,24) | 0,511 (p = 0,11) | 0,520 (p = 0,06) |
| C_embedding | 0,572 (p = 0,001) | 0,533 (p = 0,02) | 0,500 (p = 1,00) |
| D_hybrid | 0,567 (p = 0,001) | 0,553 (p = 0,001) | 0,511 (p = 0,09) |

Phát hiện được ở 5/12 ô (p < 0,05); sau hiệu chỉnh Bonferroni cho 12 ô (p < 0,0042) còn ba ô: `C_embedding`/delete, `D_hybrid`/delete, `D_hybrid`/duplicate. **Không ô `swap_adjacent` nào đạt.**
`C_embedding` × swap cho đúng AUROC 0,500 (p = 1,00): đúng như lý thuyết, vì hoán đổi hai activity kề nhau không đổi mean/max pooling và không đổi `unseen_node_ratio`.
Hình: `figures/nb04_test_auroc.png`, `nb04_test_paired_win.png`, `nb04_paired_deltas.png`.

### 6.2 Câu hỏi chính: biểu diễn đồ thị có hơn không?

Chênh lệch macro AUROC ghép cặp theo parent, trung bình ba model seed, khoảng bootstrap 95% (chưa hiệu chỉnh đa so sánh):

| Cặp (a − b) | Validation | Test |
|---|---|---|
| D_hybrid − A_stats | +0,023 [−0,004; +0,056] | +0,012 [−0,015; +0,040] |
| D_hybrid − B_ngrams | **+0,047 [+0,026; +0,084]** | **+0,031 [+0,005; +0,062]** |
| C_embedding − B_ngrams | **+0,047 [+0,020; +0,085]** | +0,022 [−0,008; +0,053] |
| D_hybrid − C_embedding | 0,000 [−0,015; +0,020] | +0,009 [−0,006; +0,027] |

- **So với n-gram:** `D_hybrid` cao hơn ở cả hai split, khoảng không chứa 0. Nguyên nhân chưa tách được: `B_ngrams` có 442 chiều cho 97 ca train (cột rất thưa) và điểm của nó tương quan với độ dài trace (Spearman +0,56), nên lợi thế có thể đến từ điểm yếu của B chứ không hẳn từ biểu diễn đồ thị.
- **So với thống kê quy trình:** điểm ước lượng của `D_hybrid` cao hơn ở cả hai split nhưng khoảng đều chứa 0: **chưa chứng minh** embedding bổ sung giá trị so với `A_stats`. Điều này không chứng minh embedding vô ích.

### 6.3 Bộ máy phát hiện được sai lệch mạnh (đối chứng dương, validation)

| | A_stats | B_ngrams | C_embedding | D_hybrid |
|---|---:|---:|---:|---:|
| AUROC (seed 42) | 0,886 [0,826; 0,951] | 0,527 [0,448; 0,614] | 0,500 | 0,658 [0,631; 0,713] |
| Paired win rate | 1,00 | 0,61 | 0,50 | 1,00 |

`A_stats` và `D_hybrid` cho điểm mutant cao hơn *mọi* parent của chúng (paired win 1,00); AUROC của `D_hybrid` thấp hơn vì phương sai giữa các parent. `C_embedding` đúng 0,500 như lý thuyết. Bộ máy do đó không hỏng: AUROC thấp ở mutant một chỉnh sửa phản ánh sai lệch tinh vi, không phải lỗi pipeline.

### 6.4 Kiểm hai giả thuyết theo quy tắc khóa trước (validation)

`D_hybrid`, macro AUROC, trung bình ba seed, 33 parent, khoảng bootstrap 98,33%:

| Thí nghiệm | Giả thuyết | Δ so với baseline | Khoảng | Phán quyết |
|---|---|---:|---|---|
| `cross_fit_5` | 1: đặc trưng train in-sample làm các cột `unseen_*` hằng và surprisal thiên thấp | −0,012 | [−0,032; +0,003] | không có bằng chứng |
| `dim_4` | 2: các cột pooling không thấy thứ tự làm loãng Isolation Forest | −0,017 | [−0,053; +0,017] | không có bằng chứng |
| `dim_8` | 2 | −0,001 | [−0,029; +0,023] | không có bằng chứng |

Cơ chế của giả thuyết 1 **đã được thỏa**: với cross-fit, số cột hằng trên train của `A_stats` giảm từ 2 xuống 0 (`D_hybrid` 3 → 1), tức các cột `unseen_*` có phương sai khi fit, nhưng AUROC không tốt hơn.
Trên test (xem sau phán quyết, khám phá) Δ của `D_hybrid` là −0,008, −0,012, −0,006, khoảng chứa 0. Baseline giữ nguyên.

### 6.5 Ablation (độ nhạy khám phá, test)

Δ macro AUROC của `D_hybrid` so với baseline, trung bình ba seed, khoảng bootstrap ghép cặp 95%, **chưa hiệu chỉnh đa so sánh**:
vô hướng −0,010 [−0,025; +0,004]; nút `activity_role` −0,002 [−0,019; +0,018]; q = 0,5 +0,003 [−0,011; +0,018]; q = 2 −0,016 [−0,029; −0,004]; d = 32 −0,006 [−0,019; +0,006].
Chỉ 1/32 ô (thí nghiệm × phương pháp) có khoảng không chứa 0 (q = 2), phù hợp với mức ngẫu nhiên (≈ 1,6 ô ở mức 5%). `A_stats` và `B_ngrams` cho đúng Δ = 0 khi chỉ đổi walk/embedding (không dùng embedding): kiểm chéo tính tất định. Hình: `figures/nb06_ablation.png`.
Khác protocol, không so trực tiếp: `keep_all_noise` 0,534 / 0,516 / 0,529 / 0,529 và tập **Story** (7 issue Rejected; 1 ca Rejected ở test) 0,636 / 0,528 / 0,552 / 0,591 (thứ tự A / B / C / D).

### 6.6 Holdout theo thời gian

Train là 60% ca kết thúc sớm nhất (đến 2022-01-25), validation đến 2022-04-04, test đến 2022-06-27 (97/32/32 ca). **29/64 ca held-out đã bắt đầu trước khi giai đoạn train kết thúc** (ca sống lâu), nên hai giai đoạn chồng lên nhau và đây không phải tách thời gian hoàn toàn.
Macro AUROC test (ba seed): A 0,560, B 0,509, C 0,546, D 0,565, so với 0,531 / 0,513 / 0,535 / 0,544 ở holdout ngẫu nhiên. Khác protocol nên chỉ đặt cạnh nhau; chưa có kiểm định giữa hai cách chia.

### 6.7 Ca thật (rà soát khám phá)

Bộ rà soát gồm 20 ca test (10 điểm cao nhất theo `D_hybrid` + 10 ngẫu nhiên). **Chưa có chuyên gia nghiệp vụ nào rà soát.** Một agent đã gán nhãn khám phá chỉ từ bảng mù (chuỗi activity/role; không điểm, hạng, nhóm):
5 `needs_review` (lùi trạng thái, đổi role bất thường, thay đổi kế hoạch lặp lại...), 12 `plausibly_valid`, 3 `insufficient_evidence`. Sau khi mở khóa nhóm: `needs_review` chiếm 2/10 ở nhóm điểm cao và 3/10 ở nhóm ngẫu nhiên (Fisher p = 1,00);
cả ba ca `insufficient_evidence` đều thuộc nhóm điểm cao (ít event, nhiều role chưa xác định). **Kết quả âm:** không có bằng chứng mô hình xếp các ca đáng rà soát lên cao hơn ngẫu nhiên. Nhãn này không phải nhãn chuyên gia. Ngoài ra `Rejected` chiếm 60% nhóm điểm cao và 48% ca test.

## 7. Thảo luận

- **Hiệu ứng nhỏ nhưng có thật ở một số loại.** Mutant một chỉnh sửa tinh vi so với phương sai tự nhiên giữa các issue; đối chứng dương cho thấy bộ máy bắt được xáo trộn mạnh. Swap một cặp kề nhau hoàn toàn nằm ngoài tầm của cả bốn phương pháp; `C_embedding` mù thứ tự theo thiết kế, và các cột H của A/B/D cũng chưa đủ nhạy với một hoán đổi.
- **Thứ tự phương pháp.** Về điểm ước lượng, {C, D} > A > B ở cả hai split, nhưng chỉ chênh lệch với B là phân biệt được; phân biệt D với A hay C thì chưa. Giả thuyết cần kiểm tiếp: lợi thế so với B có thể do B thưa và nhạy độ dài.
- **Giả thuyết bị bác.** Cả cross-fit lẫn giảm số chiều đều không giúp, dù cơ chế của cross-fit đã chạy đúng. Chưa thể kết luận rộng hơn: chưa thử bỏ riêng nửa max-pooling hay cross-fit cho embedding.
- **Bài học về suy luận.** Bản đầu của đồ án dùng công thức Hanley–McNeil (SE ≈ 0,074 ở n = 31) và kết luận “mọi AUROC chứa 0,5”. Công thức đó giả định hai mẫu độc lập; dữ liệu ở đây ghép cặp, và dưới giả thuyết không ghép cặp SD của AUROC chỉ ≈ 0,016.
  Kết luận được sửa sau khi kiểm bằng một phép thử hoán vị viết riêng, độc lập với code bootstrap: SD của macro AUROC test dưới giả thuyết không là 0,008–0,012 và p một phía của AUROC quan sát từ < 0,0001 đến 0,02 (với macro phép thử này giả định các loại độc lập nên chỉ dùng để kiểm độ lớn; kết luận chính dựa trên p theo từng loại ở mục 6.1). Cả hai phương pháp mới cho cùng hướng.
- **Về độ tin cậy của các con số.** Bootstrap percentile có thiên lệch nhỏ hướng lên (parent trùng làm tăng trọng số cặp của chính nó, cỡ 0,005 ở n = 31); phép thử hoán vị là kiểm chứng độc lập. Các p-value theo ô và các khoảng chênh lệch giữa phương pháp chưa hiệu chỉnh đa so sánh, trừ ba so sánh khóa trước ở mục 6.4.

## 8. Giới hạn

- Một team, ~160 issue bug đã đóng, một khoảng thời gian; không có nhãn bất thường; chỉ ca có kết thúc quan sát được. Không áp dụng cho phát hiện sớm hay vận hành online, hay cho doanh nghiệp khác.
- Cỡ mẫu holdout nhỏ (31 ca test, 33 ca validation); ba loại mutant dùng chung các parent nên macro không giảm nhiễu nhiều. Chỉ ba loại mutant một chỉnh sửa; chưa thử seed mutation khác hay mutant mạnh hơn.
- Test đã được xem nhiều lần với cấu hình khóa (tất định, cùng số); mọi phân tích độ nhạy trên test là khám phá. Câu hỏi chính (D so với A và B) có trong spec ngay từ đầu nhưng không có quy tắc quyết định khóa riêng.
- Rà soát ca thật chỉ ở dạng khám phá của agent, chỉ dựa vào chuỗi activity/role (không thời gian, không nội dung issue).
- Holdout theo thời gian có chồng lấn (29/64 ca). Cross-fit chỉ áp cho cột H, embedding vẫn học trên toàn train.
- Phiên bản thư viện rất mới (numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, gensim 4.4.0); Gensim in `Exception ignored in 'our_dot_float'` ở một số run (tất định, vector hữu hạn và giống hệt bit giữa hai bộ numpy/scipy, nhưng nguyên nhân gốc chưa rõ).

## 9. Kết luận và hướng phát triển

Đồ án xây được pipeline hồi cứu hoàn chỉnh (đồ thị chỉ từ train → Node2Vec → Isolation Forest → đánh giá bán tổng hợp có suy luận ghép cặp) với kiểm tra không rò rỉ và tái lập. Trên mutant một chỉnh sửa, biểu diễn đồ thị cho hiệu ứng rất nhỏ nhưng thật ở delete/duplicate,
hơn n-gram ở cả hai split, và **chưa chứng minh** hơn thống kê quy trình; hai giả thuyết cải tiến nêu từ trước không được ủng hộ. Kết luận hẹp nhưng được phân biệt rõ giữa điều đã đo, điều chưa đo và điều không được suy ra.

Hướng tiếp theo, theo giá trị thông tin: (1) nhờ người hiểu quy trình rà soát 20 ca bằng `case_review_blinded.csv` và so với rà soát khám phá; (2) mutant mạnh hơn hoặc nhiều chỉnh sửa, và seed mutation khác, để tách hiệu ứng thứ tự khỏi hiệu ứng độ dài;
(3) tách nguyên nhân lợi thế so với `B_ngrams` (thu gọn từ vựng, chuẩn hóa độ dài); (4) mô hình riêng theo nhánh DONE/Rejected; (5) cross-fit cho embedding.

## Phụ lục A — Tái lập

```bash
uv sync --locked --all-extras --group dev
uv run jira-ad audit --config configs/baseline.yaml
uv run jira-ad run --config configs/baseline.yaml                       # một run (model seed 42)
uv run jira-ad experiments --config configs/experiments.yaml            # 12 thí nghiệm × 3 seed = 36 run (~2 phút)
uv run jira-ad compare --runs-dir outputs/runs
uv run jira-ad notebooks --run-dir outputs/runs/<run_id>               # sáu notebook
uv run pytest -q && uv run ruff check src tests scripts                 # 521 test (sau giai đoạn cải tiến, xem BAO_CAO_CAI_TIEN.md)
```

Run bàn giao: `20261017T081309Z-930f8a85` (config_hash `930f8a85…`, split_hash `a3999ae5…`, quy tắc action `4a35ef7d…`; Python 3.12.7, macOS arm64). Các tùy chọn mới (`features.cross_fit_folds`, `split.strategy`, section `evaluation`) vắng trong YAML thì giữ hành vi V1.

## Phụ lục B — Nguồn số liệu

| Nội dung | Nơi xem |
|---|---|
| Audit và chuẩn hóa | notebook 01, `preprocess_audit.json` |
| Biến thể trace, DFG | notebook 02 |
| Walk, embedding, OOV, pooling | notebook 03 |
| Bảng 6.1–6.3 | notebook 04 (mục 2, 3b, 3c, 6b); `metrics_by_type.csv`, `chance_test.csv`, `positive_control.csv`, `bootstrap_*.csv` |
| Rà soát ca thật | notebook 05; `case_review_blinded.csv`, `reviews/case_review_agent.csv` |
| Ablation, giả thuyết, holdout thời gian | notebook 06 (mục 3, 4b, 4c); `configs/experiments.yaml` |
| Tiến độ, quyết định, rủi ro | `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/RESEARCH_NOTES.md` |

## Tài liệu tham khảo

- Bộ dữ liệu và bài gốc: https://zenodo.org/records/8275679 ; *Process Mining from Jira Issues at a Large Company*, ICSME 2023.
- A. Grover, J. Leskovec. *node2vec: Scalable Feature Learning for Networks.* KDD 2016.
- T. Mikolov và cộng sự. *Efficient Estimation of Word Representations in Vector Space.* 2013 (Skip-gram).
- F. T. Liu, K. M. Ting, Z.-H. Zhou. *Isolation Forest.* ICDM 2008.
