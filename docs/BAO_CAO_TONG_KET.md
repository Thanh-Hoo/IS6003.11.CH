# Báo cáo tổng kết: phát hiện ca xử lý Jira khác thường — từ dữ liệu đến phương án tốt nhất và khả năng ứng dụng

Đồ án môn học (chủ đề học biểu diễn đồ thị). Người đọc: hội đồng bảo vệ, giảng viên; phần 9 viết thêm cho người muốn áp dụng trong doanh nghiệp.

> **Phạm vi số liệu.** Mọi số trong báo cáo lấy từ artifact đã chạy:
> - V1: run bàn giao `outputs/runs/20261017T081309Z-930f8a85` và 36 run của `configs/experiments.yaml`;
> - giai đoạn cải tiến: `outputs/improvement/20261022T151529Z-bb0fee9a` và ba run `outputs/runs/20261022T1515{29,34,40}Z-*`.
>
> Dữ liệu **không có nhãn bất thường thật**, nên mọi metric là đánh giá **bán tổng hợp**: phân biệt ca gốc với sai lệch do chúng tôi chèn vào. Đây không phải độ chính xác phát hiện lỗi thực tế. Báo cáo chi tiết từng giai đoạn: [BAO_CAO.md](BAO_CAO.md) (V1), [BAO_CAO_CAI_TIEN.md](BAO_CAO_CAI_TIEN.md) (cải tiến).

---

## 0. Tóm tắt

- **Phương án tốt nhất tìm được là `M_markov`.** Nó là một mô hình xác suất chuyển tiếp trên đồ thị directly-follows (DFG) học từ dữ liệu train. Điểm khác thường của một issue là độ "bất ngờ" trung bình (−log xác suất) của các bước chuyển trong lịch sử xử lý của nó.
- **Vì sao chọn nó: tốt nhất ở mọi giao thức đánh giá.**
  - Cross-validation trên 161 issue: macro AUROC **0,603** [0,588; 0,621], cao hơn phương án đề xuất ban đầu `D_hybrid` (Node2Vec + Isolation Forest) **+0,049** [+0,034; +0,065].
  - Đối chứng dương (xáo trộn mạnh thứ tự): AUROC **0,979**, so với 0,658 của `D_hybrid` và 0,886 của `A_stats`.
  - Là phương pháp duy nhất phát hiện tốt việc **đảo thứ tự hai bước kề nhau** (AUROC 0,62–0,67; các phương pháp khác ≤ 0,55).
- **Ưu điểm vận hành.** Huấn luyện chỉ là đếm (0,01 giây), chấm 0,08 ms/issue, tất định (chạy lại cho cùng danh sách), và giải thích được bằng chính các chuyển tiếp hiếm.
- **Mức độ chắc chắn.**
  - Theo quy tắc quyết định khóa trước trên validation (33 ca), `M_markov` **chưa được xác nhận** tốt hơn `D_hybrid`: +0,032 [−0,008; +0,088], xác suất tốt hơn 0,97.
  - Kết quả cross-validation mạnh hơn nhưng là khám phá, vì dùng cả dữ liệu test đã xem.
  - Kết luận đúng mức: *ứng viên tốt nhất, cần xác nhận trên dữ liệu mới*.
- **Câu hỏi nghiên cứu.** Trên dữ liệu này, biểu diễn Node2Vec **không** bổ sung giá trị so với việc dùng trực tiếp thống kê chuyển tiếp của DFG.
- **Ứng dụng.**
  - Phù hợp làm **danh sách gợi ý rà soát hồi cứu** (ví dụ hàng tuần, top 10% issue vừa đóng, kèm chuyển tiếp bất thường), với con người quyết định.
  - **Chưa đủ** để cảnh báo tự động: lỗi "bỏ qua một bước trạng thái" chỉ được phát hiện ở AUROC 0,54.

---

## 1. Bài toán

Mỗi issue Jira để lại một chuỗi sự kiện: tạo, đổi trạng thái, gán người, gắn commit… Đồ án xếp hạng các issue **đã đóng** theo mức khác thường của diễn tiến xử lý, để người có chuyên môn xem trước các ca đáng xem.

- **Đầu vào:** chuỗi activity và role của một issue.
- **Đầu ra:** điểm liên tục, thứ hạng, và bằng chứng (các chuyển tiếp bất thường).
- **Những gì không được suy ra:** hiếm ≠ sai; `Rejected` ≠ bất thường; điểm cao ≠ vi phạm quy trình.

**Câu hỏi nghiên cứu:** biểu diễn đồ thị (Node2Vec) có bổ sung giá trị so với thống kê quy trình và n-gram không?

---

## 2. Phân tích dữ liệu và những gì nó quyết định cho thiết kế

**Nguồn:** *Process Mining from Jira Issues at a Large Company* (ICSME 2023), https://zenodo.org/records/8275679. Event log bug của một team (Team Newt), 4 cột `issueKey, timestamp, role, action`. Dữ liệu gốc chỉ đọc; SHA-256 được kiểm trước và sau mọi lần chạy.

| Phát hiện (đã đo) | Số liệu | Hệ quả cho thiết kế |
|---|---|---|
| Quy mô nhỏ | 5.126 event, 161 issue; 4–20–239 event/issue (nhỏ nhất – trung vị – lớn nhất) | Chia theo issue; cần suy luận thống kê cẩn thận |
| Thứ tự dòng CSV ngược thời gian | 161/161 issue | Luôn sắp lại theo thời điểm UTC |
| Bot và role thiếu | 43,5% event do bot; 837 role `unknown` (16%); 15 role trống | Đặc trưng role yếu; mô hình chính dựa vào activity |
| Nhiều hoạt động sau khi đóng | 1.117 event sau trạng thái kết thúc cuối, 94% là bot cập nhật link | **Core view**: cắt tại trạng thái kết thúc cuối |
| Nhiễu cập nhật link chung chung | 751 event `UPDATE_EXTERNAL_LINK` | Bỏ theo chính sách nhiễu (vẫn giữ link commit/MR) |
| Action dạng văn bản tự do | 99 chuỗi action thô → 50 activity, 0 event rơi vào `OTHER_ACTION` | Chuẩn hóa bằng quy tắc YAML (động từ + tên field) |
| Chỉ có ca đã đóng | 83 DONE, 78 Rejected; 8 ca mở lại | Đánh giá hồi cứu; không phát hiện sớm |
| **Chuỗi gần như không lặp** | **153 biến thể cho 161 ca** (98% biến thể chỉ có 1 ca) | So khớp nguyên chuỗi vô dụng ⇒ phải mô hình hóa ở **mức bước chuyển** |
| Hai quần thể khác nhau | DONE: 27,3 event, 17,7 activity khác nhau, 6,1 lần đổi trạng thái; Rejected: 12,7 / 9,6 / 2,7 | Đọc kết quả theo nhánh; không coi Rejected là lỗi |
| Bước chuyển chưa từng thấy rất phổ biến | 87/161 ca có ≥ 1 chuyển tiếp chưa thấy so với đồ thị của các fold khác; trung bình DONE 2,41, Rejected 0,81 | Cần làm mượt xác suất (không cho xác suất 0) |
| Chuyển trạng thái dồn dập | 165/553 lần đổi trạng thái cách nhau < 1 phút | Ghi nhận là rủi ro; không dùng thời gian làm đặc trưng ở V1 |

**Sau tiền xử lý:** core view còn **3.258 event**. Trung bình một issue có 20,2 event và đi qua 13,8 activity khác nhau, trong tổng số 49 activity của cả quy trình.

**Chia dữ liệu:** theo issue, seed 42, phân tầng theo trạng thái kết thúc: train 97, validation 33, test 31. Mọi thứ học được chỉ fit trên train.

**Kết luận của phân tích dữ liệu:**
- Đơn vị thông tin hữu ích nhất không phải cả chuỗi (quá đa dạng), cũng không phải từng activity riêng lẻ (cùng tập activity có thể theo nhiều thứ tự).
- Đó là **bước chuyển "A rồi đến B"**. Điều này dẫn thẳng tới cấu trúc DFG ở phần 3.

---

## 3. Cấu trúc phương án tốt nhất: `M_markov`

### 3.1 Đồ thị directly-follows (DFG)
- **Nút:** mỗi activity đã chuẩn hóa (ví dụ `STATUS_In Test`, `LINK_COMMIT`), cộng hai nút biên `__START__` và `__END__`.
- **Cạnh có hướng A → B, trọng số = số lần B xảy ra ngay sau A**, đếm trong từng issue của tập train. Không bao giờ nối cuối issue này với đầu issue khác. Có giữ vòng lặp tự thân (ví dụ `LINK_COMMIT → LINK_COMMIT`).
- **DFG học từ 97 issue train** có 51 nút, 386 cạnh (13 vòng tự thân), mật độ 0,151, tổng 1.998 bước chuyển. Mỗi activity có trung vị 6 hậu duệ, nhiều nhất 29; 8 activity chỉ có một hậu duệ.

Các cạnh nặng nhất:

| Từ | Đến | Số lần | Tỷ lệ trong các bước ra của nút nguồn |
|---|---|---:|---:|
| `__START__` | `CREATE` | 97 | 1,000 |
| `LINK_COMMIT` | `LINK_COMMIT` | 85 | 0,503 |
| `ADD_ISSUE_LINK` | `EDIT_DESCRIPTION` | 75 | 0,350 |
| `CREATE` | `ADD_ISSUE_LINK` | 73 | 0,753 |
| `STATUS_To Investigate` | `ADD_ISSUE_LINK` | 65 | 0,970 |
| `STATUS_DONE` | `__END__` | 50 | 0,962 |

DFG là tóm tắt thống kê, **không** phải mô hình BPMN/Petri net, và độ trung tâm cao không chứng minh điểm nghẽn vận hành.

### 3.2 Xác suất chuyển tiếp có làm mượt
Với tập nút đích khả dĩ V (49 activity + `__END__`, nên |V| = 50) và một nhóm "chưa biết":

```
P(B | A) = (count(A→B) + α) / (out(A) + α·(|V| + 1)),   α = 1 (làm mượt Laplace)
surprisal(A→B) = −ln P(B | A)
```

- Nút nguồn chưa từng thấy dùng phân phối đều trên |V| + 1.
- Chuyển tiếp chưa thấy vẫn có xác suất nhỏ nhưng dương, nên điểm luôn hữu hạn.

### 3.3 Điểm của một issue

```
score(issue) = trung bình surprisal trên mọi bước chuyển, kể cả __START__→bước đầu và bước cuối→__END__
```

- **Dùng trung bình chứ không dùng tổng**, để issue dài không tự động bị điểm cao. Đây tương đương log-perplexity của chuỗi dưới mô hình Markov bậc 1.
- **"Huấn luyện" chỉ là đếm cạnh trên train.** Không có tham số tối ưu, không có seed ngẫu nhiên, nên kết quả hoàn toàn tất định.
- Trong code: `FeatureEncoder("M_markov")` tính các đặc trưng H trên DFG train, và `ColumnScore` lấy cột `mean_transition_surprisal` ([detector.py](../src/jira_ad/detector.py)).

### 3.4 Ví dụ tính tay trên hai issue test thật (đồ thị học từ 97 issue train)

**Issue có điểm thấp nhất test** — `bug:TI-5750`, Rejected, 11 event: điểm = **1,112**. Mọi bước đều là đường phổ biến:

| Bước | count | out(A) | P | surprisal |
|---|---:|---:|---:|---:|
| `__START__ → CREATE` | 97 | 97 | 0,662 | 0,41 |
| `CREATE → ADD_ISSUE_LINK` | 73 | 97 | 0,500 | 0,69 |
| `STATUS_To Investigate → ADD_ISSUE_LINK` | 65 | 67 | 0,559 | 0,58 |
| `STATUS_INVESTIGATED → STATUS_Rejected` | 20 | 67 | 0,178 | 1,73 |
| … (8 bước khác, surprisal 0,74–1,73) | | | | |

**Issue có điểm cao nhất test** — `bug:TI-5260`, Rejected, 14 event: điểm = **3,251**. Gần như mọi bước đều hiếm:

| Bước | count | out(A) | P | surprisal |
|---|---:|---:|---:|---:|
| `ADD_ISSUE_LINK → UPDATE_RANK` | 1 | 214 | 0,008 | 4,89 |
| `REMOVE_ASSIGNEE → ADD_ATTACHMENT` | **0** | 71 | 0,008 | 4,80 |
| `UPDATE_BLOCKING_FOR_RELEASE → UPDATE_ASSIGNEE` | **0** | 31 | 0,012 | 4,41 |
| `ADD_ATTACHMENT → STATUS_Rejected` | **0** | 27 | 0,013 | 4,36 |
| `UPDATE_ASSIGNEE → STATUS_Inbox` | 1 | 50 | 0,020 | 3,92 |

Bằng chứng gửi người rà soát chính là bảng này. Issue `TI-5260` đổi người phụ trách nhiều lần, quay về `Inbox` rồi bị từ chối ngay sau khi đính kèm file. Đó là diễn tiến *đáng hỏi*, nhưng **không** tự động là sai: chỉ người hiểu quy trình mới kết luận được.

### 3.5 Inference trên issue mới
1. Chuẩn hóa sự kiện bằng cùng quy tắc `actions.yaml` (nội dung quy tắc được lưu trong bundle).
2. Cắt core view khi issue đã đóng.
3. Tính điểm. Có thể chuẩn hóa z theo phân bố điểm của tập train để có thang chung.
4. Xếp hạng, xuất top-k kèm 3 chuyển tiếp có surprisal cao nhất.

Không học lại khi chấm, và chuyển tiếp mới không làm đổi mô hình.

---

## 4. Hành trình phát triển: các phương pháp đã thử

| ID | Ý tưởng | Vì sao thử | Kết quả chính |
|---|---|---|---|
| `A_stats` | 10 thống kê quy trình H (độ dài, lặp, quay lại, đổi role, surprisal TB/max, tỷ lệ chưa thấy) + Isolation Forest | Mốc đơn giản | Ổn định, nhưng hay đẩy lên **ca ngắn** (trung vị 11 event trong top) |
| `B_ngrams` | H + unigram + bigram có thứ tự (442 chiều) + Isolation Forest | Đối chứng biểu diễn chuỗi | Kém nhất; điểm chủ yếu theo độ dài (Spearman +0,57) |
| `C_embedding` | Mean/max pooling vector Node2Vec + tỷ lệ chưa thấy | Đo embedding đơn lẻ | **Mù thứ tự**: swap = 0,500 đúng lý thuyết |
| `D_hybrid` | Pooling Node2Vec + H (**đề xuất ban đầu**) | Kết hợp | Hơn n-gram, chưa hơn `A_stats`; danh sách top đổi theo seed |
| `E_score_fusion` | Hai Isolation Forest riêng (H; pooling), gộp điểm z | Kiểm giả thuyết "pooling làm loãng" | Bằng `D_hybrid` ⇒ giả thuyết không được ủng hộ |
| `F_edge_hybrid` | Vector **cạnh** `v_A ⊙ v_B` (nhân từng chiều), pooling + H | Cho embedding thấy thứ tự | Nhỉnh hơn `D_hybrid` +0,009; swap 0,51 → 0,55 |
| **`M_markov`** | **Surprisal chuyển tiếp trung bình trên DFG** | Đo trực tiếp thứ tự; mốc đơn giản nhất | **Tốt nhất ở mọi giao thức** |

Các thí nghiệm khác với `D_hybrid` đều không làm cải thiện có ý nghĩa: đồ thị vô hướng, nút (activity, role), q = 0,5 / 2, số chiều 4/8/32, cross-fit đặc trưng train. Mọi |Δ| ≤ 0,019; hai giả thuyết kiểm theo quy tắc khóa trước đều không được ủng hộ.

---

## 5. Phương pháp đánh giá

**Sai lệch chèn vào (mutant).** Mỗi ca gốc sinh tối đa một sai lệch mỗi loại. Event đầu và cuối luôn được giữ, và chỉ dùng activity có sẵn của ca.

| Loại | Mô tả | Giao thức |
|---|---|---|
| `swap_adjacent` | Đảo hai bước kề nhau (giữ độ dài, giữ tập activity) | 1 và 2 |
| `delete_internal` | Bỏ một bước | 1 và 2 |
| `duplicate_block` | Lặp một đoạn 1–2 bước | 1 và 2 |
| `skip_status` | **Bỏ một bước trạng thái** (ví dụ bỏ `In Test`) — gần với lỗi quy trình thực tế nhất | 2 |
| `multi_edit` | Ba chỉnh sửa liên tiếp | 2 |
| Đối chứng dương | Xáo trộn toàn bộ phần giữa (chỉ trên validation): kiểm tra bộ máy có hoạt động | riêng |

**Metric.**
- **AUROC**: xác suất một sai lệch có điểm cao hơn một ca gốc; 0,5 là ngẫu nhiên.
- **Paired win**: tỷ lệ sai lệch có điểm cao hơn chính ca gốc của nó.
- **AP**: mốc không kỹ năng là 0,5.
- **Khoảng tin cậy**: bootstrap theo ca gốc (2000 lần), giữ nguyên cặp.
- **Phép thử hoán vị trong cặp**: hỏi AUROC có khác 0,5 không.

**Hai giao thức.**
1. **Chọn phương án (khóa trước).** Dùng split V1, 3 seed. Một phương pháp chỉ được coi là tốt hơn `D_hybrid` nếu khoảng bootstrap 98,33% của chênh lệch macro AUROC trên **validation** nằm hoàn toàn trên 0. Test chỉ xem sau, để mô tả.
2. **Cross-validation 5 fold trên cả 161 issue** (khám phá, mạnh hơn).
   - Mỗi issue được chấm bởi mô hình chưa thấy nó.
   - Có 782 sai lệch.
   - Điểm mỗi fold được chuẩn hóa theo điểm train của chính mô hình fold đó.

---

## 6. Kết quả và so sánh

### 6.1 Giao thức 1 — split V1, trung bình 3 seed

| Phương pháp | Macro AUROC validation | Macro AUROC test | Paired win test | AP test |
|---|---:|---:|---:|---:|
| A_stats | 0,524 | 0,531 | 0,593 | 0,534 |
| B_ngrams | 0,500 | 0,513 | 0,563 | 0,529 |
| C_embedding | 0,547 | 0,535 | 0,611 | 0,542 |
| D_hybrid (đề xuất ban đầu) | 0,547 | 0,544 | 0,661 | 0,560 |
| E_score_fusion | 0,533 | 0,539 | 0,636 | 0,553 |
| F_edge_hybrid | 0,550 | 0,537 | 0,645 | 0,551 |
| **M_markov** | **0,579** | **0,566** | **0,726** | **0,562** |

**Phán quyết khóa trước** (validation): `M_markov − D_hybrid` = +0,032 [−0,008; +0,088] ⇒ *không có bằng chứng đủ mạnh*. Cả 3 ứng viên đều không đạt. Trên test (khám phá): +0,022 [−0,027; +0,078].

**Có khác ngẫu nhiên không?** Theo loại, trên test, phép thử hoán vị (seed 42):
- `M_markov`: swap p = 0,0005; duplicate p = 0,0005; delete p = 0,14.
- `D_hybrid`: swap p = 0,088; duplicate p = 0,001; delete p = 0,001.

Hai phương pháp mạnh ở các loại khác nhau. `M_markov` bắt được việc đảo thứ tự, điều mà các phương pháp dựa trên Isolation Forest không làm được.

### 6.2 Đối chứng dương (xáo trộn mạnh, validation, seed 42)

| | A_stats | B_ngrams | C_embedding | D_hybrid | E_score_fusion | F_edge_hybrid | **M_markov** |
|---|---:|---:|---:|---:|---:|---:|---:|
| AUROC | 0,886 | 0,527 | 0,500 | 0,658 | 0,786 | 0,843 | **0,979** |
| Paired win | 1,00 | 0,61 | 0,50 | 1,00 | 1,00 | 0,91 | **1,00** |

`M_markov` gần như tách hoàn toàn chuỗi bị xáo trộn khỏi chuỗi gốc (khoảng [0,949; 0,996]), nên bộ máy của nó nhạy với thứ tự đúng như thiết kế.

### 6.3 Giao thức 2 — cross-validation, 161 issue (khám phá)

| Phương pháp | delete | duplicate | multi_edit | skip_status | swap | **Macro [95%]** |
|---|---:|---:|---:|---:|---:|---|
| A_stats | 0,525 | 0,532 | 0,594 | 0,521 | 0,547 | 0,544 [0,530; 0,559] |
| B_ngrams | 0,507 | 0,498 | 0,505 | 0,522 | 0,525 | 0,512 [0,503; 0,522] |
| C_embedding | 0,569 | 0,540 | 0,571 | 0,564 | 0,500 | 0,549 [0,540; 0,561] |
| D_hybrid | 0,562 | 0,542 | 0,589 | 0,566 | 0,510 | 0,554 [0,546; 0,567] |
| E_score_fusion | 0,546 | 0,539 | 0,599 | 0,553 | 0,531 | 0,554 [0,543; 0,568] |
| F_edge_hybrid | 0,548 | 0,555 | 0,636 | 0,529 | 0,547 | 0,563 [0,552; 0,577] |
| **M_markov** | 0,551 | 0,558 | **0,696** | 0,540 | **0,669** | **0,603 [0,588; 0,621]** |

**Chênh lệch ghép cặp của `M_markov`** (macro AUROC, khoảng 95%): mọi khoảng đều nằm trên 0.

| So với | Δ | Khoảng |
|---|---:|---|
| D_hybrid | +0,049 | [+0,034; +0,065] |
| A_stats | +0,059 | [+0,042; +0,080] |
| F_edge_hybrid | +0,040 | [+0,025; +0,056] |
| C_embedding | +0,054 | [+0,039; +0,070] |
| B_ngrams | +0,091 | [+0,076; +0,110] |

### 6.4 Bảng tổng hợp để chọn

| Tiêu chí | A_stats | D_hybrid (đề xuất ban đầu) | F_edge_hybrid | **M_markov** |
|---|---|---|---|---|
| Macro AUROC, cross-validation | 0,544 | 0,554 | 0,563 | **0,603** |
| Phát hiện đảo thứ tự (swap, CV) | 0,547 | 0,510 | 0,547 | **0,669** |
| Phát hiện bỏ bước trạng thái (CV) | 0,521 | **0,566** | 0,529 | 0,540 |
| Đối chứng dương | 0,886 | 0,658 | 0,843 | **0,979** |
| Ổn định danh sách top 10% giữa seed (Jaccard) | 0,889 | 0,548 | 0,646 | **1,000** |
| Thời gian fit / chấm | 0,10 s / 0,16 ms | 0,79 s / 0,17 ms | 0,78 s / 0,18 ms | **0,01 s / 0,08 ms** |
| Giải thích được | trung bình | khó (vector) | khó (vector) | **trực tiếp (chuyển tiếp hiếm)** |
| Xác nhận theo quy tắc khóa trước | — | baseline ghi nhận | không | **chưa (P = 0,97)** |

---

## 7. Hành vi khi áp dụng lên toàn bộ issue

Mỗi issue được chấm bởi mô hình chưa thấy nó (out-of-fold):

- **`M_markov` chọn ca khác hẳn các phương pháp khác.** Tương quan hạng với `D_hybrid` là 0,38, với `A_stats` là −0,08. Top-17 trùng 9 ca với `D_hybrid` và 5 ca với `A_stats`.
- **Ca điểm cao có nhiều bước chuyển hiếm thật** (trung bình 6,3 chuyển tiếp chưa thấy, so với 4,2 ở `D_hybrid`, 2,7 ở `A_stats`). Ví dụ có thể diễn giải theo nghiệp vụ:
  - `STATUS_In Progress → STATUS_Inbox`: lùi về hộp chờ;
  - `REMOVE_ASSIGNEE → STATUS_In Test`: vào kiểm thử ngay sau khi bỏ người phụ trách;
  - `ADD_ISSUE_LINK → STATUS_OPEN`.
- **Ít lệch về nhánh Rejected:** 29% top-17, so với 48% toàn tập. `A_stats` và `D_hybrid` hay chọn ca Rejected rất ngắn (4–5 event) không có bước nào bất thường.
- **Lệch đã biết.** Điểm tăng theo độ dài (Spearman +0,51), vì ca dài có nhiều cơ hội gặp bước hiếm. Khi dùng nên so ca trong cùng nhóm độ dài, hoặc đọc kèm số bước hiếm.

---

## 8. Thảo luận

1. **Vì sao mô hình đơn giản thắng mô hình đồ thị học sâu hơn?**
   - Node2Vec học vector cho 51 nút từ các bước đi ngẫu nhiên trên chính DFG đó, nên nó không có thông tin nào mà DFG chưa có.
   - Pooling vector còn làm mất thứ tự. Isolation Forest trên 42 cột pha loãng tín hiệu chuyển tiếp với các cột khác.
   - `M_markov` dùng thẳng thông tin quan trọng nhất mà phân tích dữ liệu chỉ ra: bước chuyển.
2. **Lợi thế có thể bị phóng đại.** Sai lệch được tạo bằng cách sắp xếp lại bước của chính ca gốc, nên tạo ra chuyển tiếp hiếm, đúng thứ `M_markov` đo.
   - Bằng chứng nó không chỉ đo độ dài: nó thắng cả ở `swap_adjacent`, loại giữ nguyên độ dài và tập activity.
   - Nhưng ở loại thực tế nhất (`skip_status`), nó **không** tốt hơn (0,540 so với 0,566 của `D_hybrid`).
3. **Trả lời câu hỏi nghiên cứu.** Trong phạm vi mẫu này, biểu diễn Node2Vec không bổ sung giá trị so với thống kê chuyển tiếp trên DFG. Đây là kết quả âm cho giả thuyết ban đầu, và là kết quả có ích.
4. **Mức chắc chắn.**
   - Quy tắc khóa trước (33 ca validation) không đủ mạnh để xác nhận chênh lệch +0,03.
   - Cross-validation đủ mạnh, nhưng đã dùng dữ liệu test từng xem nên chỉ là khám phá.
   - Theo đúng cam kết, cấu hình ghi nhận của đồ án vẫn là `D_hybrid`; `M_markov` là **đề xuất cho bước tiếp theo**.

---

## 9. Áp dụng vào quy trình phát triển và sửa lỗi phần mềm trong doanh nghiệp

### 9.1 Mức sẵn sàng
- **Sẵn sàng thử nghiệm có người kiểm soát (pilot)** như một công cụ *gợi ý rà soát hồi cứu*.
- **Chưa sẵn sàng** cho cảnh báo tự động, chấm điểm nhân viên hay phát hiện sớm. Tiêu chí "tự động cảnh báo" khóa trước (AUROC ≥ 0,80, kể cả với `skip_status`) không phương pháp nào đạt.

### 9.2 Cách tích hợp đề xuất

```
Jira (changelog các issue đã đóng)
  → xuất event log (issueKey, timestamp, role, action)
  → chuẩn hóa bằng actions.yaml của team → core view
  → M_markov: học lại DFG trên các issue đã đóng gần nhất (hàng tháng)
  → chấm các issue đóng trong tuần → top 10% + 3 chuyển tiếp hiếm nhất mỗi ca
  → trưởng nhóm / QA rà soát trong buổi review hoặc retrospective
  → ghi nhãn: needs_review / plausibly_valid / insufficient_evidence
  → nhãn dùng để đo hiệu quả và hiệu chỉnh danh sách
```

Song song, chạy **quy tắc nghiệp vụ cứng** cho các lỗi đã biết, ví dụ "DONE phải qua In Test" hay "không vào In Test khi chưa có assignee". Quy tắc chính xác hơn mô hình cho lỗi đã biết. Mô hình bổ sung cho các mẫu lạ chưa có quy tắc.

### 9.3 Các tình huống sử dụng phù hợp
- **Rà soát chất lượng quy trình fix bug:** tìm bug đóng theo đường lạ, như bỏ qua kiểm thử, lùi trạng thái hay đổi người phụ trách nhiều lần, để hỏi lại.
- **Đầu vào cho retrospective:** "tuần này có 5 bug đi theo đường hiếm, đây là các bước hiếm".
- **Kiểm tra việc áp dụng workflow mới:** sau khi đổi workflow Jira, các chuyển tiếp mới sẽ hiện ra với surprisal cao. Đây là tín hiệu cần học lại mô hình, không phải lỗi.

### 9.4 Đo hiệu quả trong pilot (đặt trước khi chạy)
- **So sánh mù.** Mỗi tuần, người rà soát xem top-k của `M_markov` trộn với k ca ngẫu nhiên mà không biết ca nào từ đâu. Đây là thiết kế giống bảng mù đã có trong đồ án.
- **Chỉ số chính:** tỷ lệ `needs_review` ở top-k so với nhóm ngẫu nhiên (precision@k vượt nền). Ghi thêm thời gian rà soát mỗi ca.
- **Tiêu chí tiếp tục:** sau khoảng 4–8 tuần, precision@k của top-k cao hơn nhóm ngẫu nhiên với khoảng tin cậy không chứa 0. Nếu không đạt thì dừng; đó cũng là kết quả hợp lệ.

### 9.5 Rủi ro và biện pháp

| Rủi ro | Biện pháp |
|---|---|
| Quy trình thay đổi (drift) làm mọi ca mới "lạ" | Học lại DFG định kỳ; theo dõi tỷ lệ chuyển tiếp chưa thấy |
| Mô hình riêng cho từng team/dự án | Mỗi team một DFG và một bộ quy tắc `actions.yaml`; không gộp team |
| Điểm thiên về ca dài | So trong nhóm độ dài, hoặc hiển thị kèm số bước hiếm |
| Dùng sai mục đích (đánh giá cá nhân) | Chỉ dùng ở mức issue/quy trình; role đổi ≠ người sai |
| Ít dữ liệu | Đồ án chạy với 97–129 issue train; dưới mức này chưa được kiểm |
| Không có nhãn | Pilot với nhãn rà soát mù là bước bắt buộc trước khi tin danh sách |

---

## 10. Giới hạn

- **Không có nhãn bất thường thật.** Mọi metric đo khả năng phân biệt sai lệch do chúng tôi chèn, không phải lỗi quy trình thật. Rà soát khám phá của agent trên 20 ca (V1, theo `D_hybrid`) không cho thấy ca điểm cao đáng xem hơn ca ngẫu nhiên.
- Một team, 161 bug đã đóng, một giai đoạn; không áp dụng cho phát hiện sớm hay doanh nghiệp khác nếu chưa kiểm.
- **Mức chắc chắn của `M_markov`.** Ưu thế của nó chưa được xác nhận theo quy tắc khóa trước. Cross-validation là khám phá, có 12 so sánh cặp chưa hiệu chỉnh đa so sánh.
- **Tham số `M_markov` chưa được tinh chỉnh**: α = 1, trung bình thay vì max, Markov bậc 1. Đây là cấu hình mặc định, không phải tối ưu.
- Mô hình chỉ dùng cấu trúc và thứ tự; thời gian xử lý chưa được dùng.

---

## 11. Kết luận

1. **Phân tích dữ liệu chỉ ra rằng thông tin nằm ở bước chuyển giữa các hoạt động.** Lịch sử xử lý bug gần như không bao giờ lặp nguyên chuỗi (153 biến thể cho 161 ca), và một nửa số ca chứa bước chuyển chưa từng thấy.
2. **Mô hình tốt nhất tìm được là `M_markov`** — xác suất chuyển tiếp làm mượt trên DFG, điểm = surprisal trung bình. Nó tốt nhất trên mọi giao thức đánh giá (cross-validation 0,603, đối chứng dương 0,979, phát hiện đảo thứ tự 0,669), đồng thời tất định, nhanh và tự giải thích.
3. **Phương án Node2Vec + Isolation Forest ban đầu (`D_hybrid`) không bổ sung giá trị** so với thống kê chuyển tiếp trên dữ liệu này. Các cải tiến cho nó chỉ giúp rất ít (`F_edge_hybrid` +0,009) hoặc không giúp (`E_score_fusion`).
4. **Theo quy tắc khóa trước, ưu thế của `M_markov` chưa được xác nhận.** Kết luận đúng mức là "ứng viên tốt nhất, cần xác nhận trên dữ liệu mới".
5. **Về ứng dụng:** dùng được làm danh sách gợi ý rà soát hồi cứu, kèm bằng chứng là các chuyển tiếp hiếm, trong một pilot có đo lường. Không dùng để cảnh báo tự động hay đánh giá con người. Nên luôn kết hợp với quy tắc nghiệp vụ cho các lỗi đã biết.

**Bước tiếp theo, theo thứ tự giá trị:**
- (a) Pilot rà soát mù để có nhãn thật.
- (b) Xác nhận `M_markov` trên issue mới theo quy tắc khóa trước.
- (c) Thử Markov bậc 2 khi có thêm dữ liệu, và kết hợp quy tắc nghiệp vụ.

---

## Phụ lục A — Tái lập

```bash
uv sync --locked --all-extras --group dev
uv run jira-ad audit --config configs/baseline.yaml                 # thống kê dữ liệu
uv run jira-ad run --config configs/baseline.yaml                   # V1 (A–D)
uv run jira-ad experiments --config configs/experiments.yaml        # ablation V1, 36 run
uv run jira-ad improve --plan configs/improvement_plan.yaml         # E/F/M, cross-validation, ứng dụng (~90 s)
uv run pytest -q && uv run ruff check src tests scripts             # 521 test
```

Môi trường: Python 3.12.7, numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1, gensim 4.4.0 (khóa trong `uv.lock`), macOS arm64.

## Phụ lục B — Nguồn số liệu

| Nội dung | Nguồn |
|---|---|
| Thống kê dữ liệu, funnel | `outputs/analysis/audit_raw.json`, `preprocess_audit.json`, notebook 01–02 |
| DFG train, ví dụ tính tay | `outputs/runs/20261022T151529Z-25f2841c/graph.graphml`, `models/M_markov/bundle.joblib` |
| Giao thức 1, đối chứng dương, phép thử hoán vị | `outputs/improvement/…151529Z…/standard_metrics.csv`, `decision_validation.csv`; `outputs/runs/20261022T151529Z-25f2841c/{positive_control,chance_test,metrics_by_type}.csv` |
| Cross-validation, ứng dụng | `outputs/improvement/…151529Z…/cv_*.csv`, `applicability.csv`, `inference_profile.csv`, `top_cases.csv`, `method_agreement.csv` |
| Quyết định, tiến độ | [PROGRESS.md](PROGRESS.md) (Ruling 1–66), [DECISIONS.md](DECISIONS.md), [RESEARCH_NOTES.md](RESEARCH_NOTES.md) |
