# Báo cáo tổng kết phát hiện ca Jira khác thường

Oct 22, 2026 · @Hehe

Phương án tốt nhất tìm được là M\_markov, một mô hình xác suất chuyển tiếp trên đồ thị directly-follows; nó vượt phương án Node2Vec ban đầu ở mọi giao thức đánh giá nhưng chưa được xác nhận theo quy tắc khóa trước.

## Tóm tắt

M\_markov chấm mỗi issue bằng độ "bất ngờ" trung bình (−log xác suất) của các bước chuyển trong lịch sử xử lý, theo đồ thị directly-follows (DFG) học từ dữ liệu train. Người đọc: hội đồng bảo vệ, giảng viên; mục Ứng dụng viết thêm cho doanh nghiệp. Dữ liệu không có nhãn bất thường thật, nên mọi metric là đánh giá bán tổng hợp (phân biệt ca gốc với sai lệch do chúng tôi chèn), không phải độ chính xác phát hiện lỗi thực tế.

| Chỉ số | M\_markov | D\_hybrid (đề xuất ban đầu) |
| --- | --- | --- |
| Macro AUROC, cross-validation 161 issue | **0,603** \[0,588; 0,621\] | 0,554 \[0,546; 0,567\] |
| Chênh lệch ghép cặp | +0,049 \[+0,034; +0,065\] | — |
| Đối chứng dương (xáo trộn thứ tự) | **0,979** | 0,658 |
| Phát hiện đảo thứ tự hai bước (swap, CV) | **0,669** | 0,510 |
| Quy tắc khóa trước trên validation (33 ca) | +0,032 \[−0,008; +0,088\], **chưa xác nhận** | cấu hình ghi nhận |
| Thời gian học / chấm | 0,01 s / 0,08 ms mỗi issue | 0,79 s / 0,17 ms |

- **Câu hỏi nghiên cứu:** trên dữ liệu này, Node2Vec không bổ sung giá trị so với dùng trực tiếp thống kê chuyển tiếp của DFG.
- **Mức chắc chắn:** ứng viên tốt nhất, cần xác nhận trên dữ liệu mới; cross-validation là khám phá vì dùng cả dữ liệu test đã xem.
- **Ứng dụng:** phù hợp làm danh sách gợi ý rà soát hồi cứu (top 10% issue vừa đóng kèm chuyển tiếp bất thường), con người quyết định; chưa đủ để cảnh báo tự động (bỏ một bước trạng thái chỉ đạt AUROC 0,540).

## Bài toán

Xếp hạng các issue Jira đã đóng theo mức khác thường của diễn tiến xử lý, để người có chuyên môn xem trước các ca đáng xem.

- **Đầu vào:** chuỗi activity và role của một issue.
- **Đầu ra:** điểm liên tục, thứ hạng và bằng chứng (các chuyển tiếp bất thường).
- **Không suy ra:** hiếm ≠ sai; Rejected ≠ bất thường; điểm cao ≠ vi phạm quy trình.
- **Câu hỏi nghiên cứu:** biểu diễn đồ thị (Node2Vec) có bổ sung giá trị so với thống kê quy trình và n-gram không?

## Phân tích dữ liệu và hệ quả cho thiết kế

Lịch sử xử lý bug gần như không bao giờ lặp nguyên chuỗi, nên thông tin hữu ích nằm ở bước chuyển "A rồi đến B" — điều này dẫn thẳng tới cấu trúc DFG. Nguồn: [Process Mining from Jira Issues at a Large Company (ICSME 2023)](https://zenodo.org/records/8275679), event log bug của một team, 4 cột issueKey, timestamp, role, action.

| Phát hiện | Số liệu | Hệ quả cho thiết kế |
| --- | --- | --- |
| Quy mô nhỏ | 5.126 event, 161 issue; 4–20–239 event/issue (nhỏ nhất–trung vị–lớn nhất) | Chia theo issue; suy luận thống kê cẩn thận |
| Thứ tự dòng CSV ngược thời gian | 161/161 issue | Luôn sắp lại theo UTC |
| Bot và role thiếu | 43,5% event do bot; 837 role unknown (16%); 15 role trống | Mô hình chính dựa vào activity |
| Hoạt động sau khi đóng | 1.117 event, 94% là bot cập nhật link | Core view cắt tại trạng thái kết thúc cuối |
| Nhiễu cập nhật link chung | 751 event | Bỏ theo chính sách nhiễu, giữ link commit/MR |
| Action dạng văn bản tự do | 99 chuỗi thô → 50 activity, 0 event không phân loại được | Chuẩn hóa bằng quy tắc YAML (động từ + tên field) |
| Chỉ có ca đã đóng | 83 DONE, 78 Rejected; 8 ca mở lại | Đánh giá hồi cứu, không phát hiện sớm |
| **Chuỗi gần như không lặp** | **153 biến thể cho 161 ca** | Mô hình hóa ở mức bước chuyển |
| Hai quần thể khác nhau | DONE: 27,3 event, 17,7 activity, 6,1 lần đổi trạng thái; Rejected: 12,7 / 9,6 / 2,7 | Không coi Rejected là lỗi |
| Chuyển tiếp chưa từng thấy phổ biến | 87/161 ca có ≥ 1 so với đồ thị của các fold khác (DONE 2,41, Rejected 0,81 trung bình) | Làm mượt xác suất, không cho xác suất 0 |
| Chuyển trạng thái dồn dập | 165/553 lần cách nhau dưới 1 phút | Ghi nhận rủi ro; chưa dùng thời gian |

Sau tiền xử lý còn 3.258 event; một issue trung bình 20,2 event và đi qua 13,8 trong 49 activity của quy trình. Chia theo issue, seed 42, phân tầng theo trạng thái kết thúc: train 97, validation 33, test 31; mọi thứ học được chỉ fit trên train.

## Cấu trúc M\_markov

M\_markov là mô hình Markov bậc 1 trên DFG: "huấn luyện" chỉ là đếm cạnh trên train, không có tham số tối ưu và không có seed ngẫu nhiên, nên hoàn toàn tất định.

**1. Đồ thị directly-follows (DFG).** Nút là activity đã chuẩn hóa cộng hai nút biên START và END. Cạnh A → B có trọng số bằng số lần B xảy ra ngay sau A trong từng issue train (không nối issue này với issue khác, giữ vòng lặp tự thân). DFG học từ 97 issue train có 51 nút, 386 cạnh (13 vòng tự thân), mật độ 0,151 và 1.998 bước chuyển; mỗi activity có trung vị 6 hậu duệ, nhiều nhất 29. DFG là tóm tắt thống kê, không phải BPMN.

| Từ | Đến | Số lần | Tỷ lệ trong bước ra của nguồn |
| --- | --- | --- | --- |
| START | CREATE | 97 | 1,000 |
| LINK\_COMMIT | LINK\_COMMIT | 85 | 0,503 |
| ADD\_ISSUE\_LINK | EDIT\_DESCRIPTION | 75 | 0,350 |
| CREATE | ADD\_ISSUE\_LINK | 73 | 0,753 |
| STATUS\_To Investigate | ADD\_ISSUE\_LINK | 65 | 0,970 |
| STATUS\_DONE | END | 50 | 0,962 |

**2. Xác suất chuyển tiếp có làm mượt Laplace** (|V| = 50 nút đích khả dĩ, cộng một nhóm "chưa biết"; α = 1). Chuyển tiếp chưa thấy vẫn có xác suất nhỏ nhưng dương, nên điểm luôn hữu hạn.

```latex
P(B \mid A) = \frac{\mathrm{count}(A \to B) + \alpha}{\mathrm{out}(A) + \alpha\,(|V| + 1)}, \qquad \mathrm{surprisal}(A \to B) = -\ln P(B \mid A)
```

**3. Điểm của một issue** là trung bình surprisal trên mọi bước chuyển, kể cả START → bước đầu và bước cuối → END. Dùng trung bình chứ không dùng tổng để issue dài không tự động bị điểm cao; đây tương đương log-perplexity của chuỗi.

**4. Ví dụ tính tay trên hai issue test thật.** Issue điểm thấp nhất, bug:TI-5750 (Rejected, 11 event), đạt 1,112 vì mọi bước đều là đường phổ biến, ví dụ CREATE → ADD\_ISSUE\_LINK (P = 0,500). Issue điểm cao nhất, bug:TI-5260 (Rejected, 14 event), đạt 3,251 vì gần như mọi bước đều hiếm:

| Bước của bug:TI-5260 | count | out(A) | P | surprisal |
| --- | --- | --- | --- | --- |
| ADD\_ISSUE\_LINK → UPDATE\_RANK | 1 | 214 | 0,008 | 4,89 |
| REMOVE\_ASSIGNEE → ADD\_ATTACHMENT | 0 | 71 | 0,008 | 4,80 |
| UPDATE\_BLOCKING\_FOR\_RELEASE → UPDATE\_ASSIGNEE | 0 | 31 | 0,012 | 4,41 |
| ADD\_ATTACHMENT → STATUS\_Rejected | 0 | 27 | 0,013 | 4,36 |
| UPDATE\_ASSIGNEE → STATUS\_Inbox | 1 | 50 | 0,020 | 3,92 |

Bảng này chính là bằng chứng gửi người rà soát: issue đổi người phụ trách nhiều lần, quay về Inbox rồi bị từ chối ngay sau khi đính kèm file — đáng hỏi, nhưng không tự động là sai.

**5. Inference trên issue mới:** chuẩn hóa bằng cùng quy tắc actions.yaml (lưu trong bundle) → cắt core view khi issue đóng → tính điểm (có thể chuẩn hóa z theo phân bố điểm train) → xếp hạng, xuất top-k kèm 3 chuyển tiếp hiếm nhất. Không học lại khi chấm.

## Hành trình phát triển: bảy phương pháp

Phương pháp đơn giản nhất (M\_markov) thắng; các cải tiến cho Node2Vec chỉ giúp rất ít.

| ID | Ý tưởng | Vì sao thử | Kết quả chính |
| --- | --- | --- | --- |
| A\_stats | 10 thống kê quy trình + Isolation Forest | Mốc đơn giản | Ổn định, nhưng hay đẩy lên ca ngắn (trung vị 11 event trong top) |
| B\_ngrams | Thống kê + unigram + bigram có thứ tự (442 chiều) | Đối chứng biểu diễn chuỗi | Kém nhất; điểm chủ yếu theo độ dài (Spearman +0,57) |
| C\_embedding | Mean/max pooling vector Node2Vec | Đo embedding đơn lẻ | Mù thứ tự: swap = 0,500 đúng lý thuyết |
| D\_hybrid | Pooling Node2Vec + thống kê (đề xuất ban đầu) | Kết hợp | Hơn n-gram, chưa hơn A\_stats; danh sách top đổi theo seed |
| E\_score\_fusion | Hai Isolation Forest riêng, gộp điểm z | Kiểm "pooling làm loãng" | Bằng D\_hybrid: giả thuyết không được ủng hộ |
| F\_edge\_hybrid | Vector cạnh (nhân từng chiều vector hai nút), pooling + thống kê | Cho embedding thấy thứ tự | Nhỉnh hơn D\_hybrid +0,009; swap 0,51 → 0,55 |
| **M\_markov** | **Surprisal chuyển tiếp trung bình trên DFG** | Đo trực tiếp thứ tự | **Tốt nhất ở mọi giao thức** |

Các biến thể khác của D\_hybrid (đồ thị vô hướng, nút activity–role, q = 0,5 / 2, số chiều 4 / 8 / 32, cross-fit đặc trưng train) đều lệch tối đa 0,019; hai giả thuyết kiểm theo quy tắc khóa trước đều không được ủng hộ.

## Phương pháp đánh giá

Không có nhãn thật, nên chúng tôi chèn sai lệch có kiểm soát vào ca gốc và đo khả năng tách chúng ra; phương án được chọn theo quy tắc khóa trước khi chạy.

| Loại sai lệch | Mô tả | Giao thức |
| --- | --- | --- |
| swap\_adjacent | Đảo hai bước kề nhau (giữ độ dài và tập activity) | 1 và 2 |
| delete\_internal | Bỏ một bước | 1 và 2 |
| duplicate\_block | Lặp một đoạn 1–2 bước | 1 và 2 |
| skip\_status | Bỏ một bước trạng thái (ví dụ bỏ In Test), gần lỗi thực tế nhất | 2 |
| multi\_edit | Ba chỉnh sửa liên tiếp | 2 |
| Đối chứng dương | Xáo toàn bộ phần giữa, chỉ trên validation, để kiểm tra bộ máy | riêng |

- **Metric:** AUROC (xác suất sai lệch có điểm cao hơn ca gốc; 0,5 là ngẫu nhiên), paired win (sai lệch cao điểm hơn chính ca gốc của nó), AP (mốc không kỹ năng 0,5).
- **Suy luận:** khoảng tin cậy bootstrap theo ca gốc (2000 lần, giữ cặp) và phép thử hoán vị trong cặp.
- **Giao thức 1 — chọn phương án (khóa trước):** split 97/33/31, ba model seed; ứng viên chỉ hơn D\_hybrid nếu khoảng 98,33% của chênh lệch macro AUROC trên validation nằm hoàn toàn trên 0; test chỉ xem sau để mô tả.
- **Giao thức 2 — cross-validation 5 fold trên 161 issue (khám phá):** mỗi issue được chấm bởi mô hình chưa thấy nó; 782 sai lệch; điểm mỗi fold chuẩn hóa theo điểm train của chính mô hình fold đó.

## Kết quả và so sánh

M\_markov dẫn đầu ở cả hai giao thức và ở đối chứng dương, nhưng chỉ cross-validation đủ mạnh để tách chênh lệch khỏi 0.

**Giao thức 1 — split 97/33/31, trung bình 3 seed**

| Phương pháp | Macro AUROC validation | Macro AUROC test | Paired win test | AP test |
| --- | --- | --- | --- | --- |
| **M\_markov** | **0,579** | **0,566** | **0,726** | **0,562** |
| D\_hybrid (ban đầu) | 0,547 | 0,544 | 0,661 | 0,560 |
| F\_edge\_hybrid | 0,550 | 0,537 | 0,645 | 0,551 |
| E\_score\_fusion | 0,533 | 0,539 | 0,636 | 0,553 |
| C\_embedding | 0,547 | 0,535 | 0,611 | 0,542 |
| A\_stats | 0,524 | 0,531 | 0,593 | 0,534 |
| B\_ngrams | 0,500 | 0,513 | 0,563 | 0,529 |

Phán quyết khóa trước (validation): M\_markov − D\_hybrid = +0,032 \[−0,008; +0,088\], không đủ bằng chứng; cả 3 ứng viên đều không đạt. Phép thử hoán vị trên test: M\_markov bắt được đảo thứ tự (swap p = 0,0005, duplicate p = 0,0005), D\_hybrid thì không (swap p = 0,088).

**Đối chứng dương (xáo trộn mạnh, validation)**

|  | M\_markov | A\_stats | F\_edge\_hybrid | E\_score\_fusion | D\_hybrid | B\_ngrams | C\_embedding |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AUROC | **0,979** | 0,886 | 0,843 | 0,786 | 0,658 | 0,527 | 0,500 |

**Giao thức 2 — cross-validation, 161 issue (khám phá), AUROC theo loại**

| Phương pháp | delete | duplicate | multi\_edit | skip\_status | swap | Macro \[95%\] |
| --- | --- | --- | --- | --- | --- | --- |
| **M\_markov** | 0,551 | 0,558 | **0,696** | 0,540 | **0,669** | **0,603 \[0,588; 0,621\]** |
| F\_edge\_hybrid | 0,548 | 0,555 | 0,636 | 0,529 | 0,547 | 0,563 \[0,552; 0,577\] |
| D\_hybrid | 0,562 | 0,542 | 0,589 | **0,566** | 0,510 | 0,554 \[0,546; 0,567\] |
| E\_score\_fusion | 0,546 | 0,539 | 0,599 | 0,553 | 0,531 | 0,554 \[0,543; 0,568\] |
| C\_embedding | 0,569 | 0,540 | 0,571 | 0,564 | 0,500 | 0,549 \[0,540; 0,561\] |
| A\_stats | 0,525 | 0,532 | 0,594 | 0,521 | 0,547 | 0,544 \[0,530; 0,559\] |
| B\_ngrams | 0,507 | 0,498 | 0,505 | 0,522 | 0,525 | 0,512 \[0,503; 0,522\] |

Chênh lệch ghép cặp của M\_markov (macro AUROC, khoảng 95%), mọi khoảng đều trên 0: so với D\_hybrid +0,049 \[+0,034; +0,065\]; A\_stats +0,059 \[+0,042; +0,080\]; F\_edge\_hybrid +0,040 \[+0,025; +0,056\]; C\_embedding +0,054 \[+0,039; +0,070\]; B\_ngrams +0,091 \[+0,076; +0,110\].

**Bảng tổng hợp để chọn**

| Tiêu chí | M\_markov | F\_edge\_hybrid | D\_hybrid | A\_stats |
| --- | --- | --- | --- | --- |
| Macro AUROC, cross-validation | **0,603** | 0,563 | 0,554 | 0,544 |
| Đảo thứ tự (swap, CV) | **0,669** | 0,547 | 0,510 | 0,547 |
| Bỏ bước trạng thái (CV) | 0,540 | 0,529 | **0,566** | 0,521 |
| Ổn định top 10% giữa seed (Jaccard) | **1,000** | 0,646 | 0,548 | 0,889 |
| Thời gian học / chấm | **0,01 s / 0,08 ms** | 0,78 s / 0,18 ms | 0,79 s / 0,17 ms | 0,10 s / 0,16 ms |
| Giải thích được | **trực tiếp (chuyển tiếp hiếm)** | khó (vector) | khó (vector) | trung bình |
| Xác nhận theo quy tắc khóa trước | chưa (P = 0,97) | không | cấu hình ghi nhận | — |

## Hành vi khi áp dụng lên toàn bộ issue

Khi mỗi issue được chấm bởi mô hình chưa thấy nó, M\_markov đẩy lên các ca có nhiều bước chuyển hiếm thật, thay vì các ca chỉ đơn giản là ngắn.

- **Chọn ca khác hẳn:** tương quan hạng với D\_hybrid 0,38, với A\_stats −0,08; top-17 trùng 9 ca với D\_hybrid và 5 ca với A\_stats.
- **Bước hiếm thật:** ca điểm cao có trung bình 6,3 chuyển tiếp chưa thấy (D\_hybrid 4,2; A\_stats 2,7), ví dụ STATUS\_In Progress → STATUS\_Inbox (lùi về hộp chờ), REMOVE\_ASSIGNEE → STATUS\_In Test (vào kiểm thử ngay sau khi bỏ người phụ trách).
- **Ít lệch về Rejected:** 29% top-17 so với 48% toàn tập; A\_stats và D\_hybrid hay chọn ca Rejected 4–5 event không có bước nào bất thường.
- **Lệch đã biết:** điểm tăng theo độ dài (Spearman +0,51) vì ca dài có nhiều cơ hội gặp bước hiếm; nên so trong cùng nhóm độ dài hoặc đọc kèm số bước hiếm.

## Thảo luận

Mô hình đơn giản thắng vì nó dùng thẳng thông tin mà phân tích dữ liệu chỉ ra là quan trọng nhất: bước chuyển.

1. **Node2Vec không có thêm thông tin.** Nó học vector cho 51 nút từ các bước đi ngẫu nhiên trên chính DFG đó; pooling làm mất thứ tự; Isolation Forest trên 42 cột pha loãng tín hiệu chuyển tiếp.
2. **Lợi thế có thể bị phóng đại.** Sai lệch được tạo bằng cách sắp xếp lại bước của chính ca gốc, nên sinh chuyển tiếp hiếm — đúng thứ M\_markov đo. Nó vẫn thắng ở swap (giữ nguyên độ dài và tập activity), nhưng ở loại thực tế nhất (skip\_status) nó không tốt hơn (0,540 so với 0,566).
3. **Câu hỏi nghiên cứu:** kết quả âm cho giả thuyết ban đầu — Node2Vec không bổ sung giá trị so với thống kê chuyển tiếp trên DFG trong phạm vi mẫu này.
4. **Mức chắc chắn:** 33 ca validation không đủ mạnh để xác nhận chênh lệch +0,03; cross-validation đủ mạnh nhưng dùng cả test đã xem. Theo cam kết, cấu hình ghi nhận vẫn là D\_hybrid; M\_markov là đề xuất cho bước tiếp theo.

## Ứng dụng trong quy trình phát triển và sửa lỗi phần mềm

M\_markov sẵn sàng cho một thử nghiệm có người kiểm soát (pilot) như công cụ gợi ý rà soát hồi cứu; chưa sẵn sàng cho cảnh báo tự động, chấm điểm nhân viên hay phát hiện sớm (tiêu chí cảnh báo khóa trước là AUROC ≥ 0,80, kể cả với skip\_status, không phương pháp nào đạt).

**Cách tích hợp đề xuất**

1. Xuất changelog các issue đã đóng từ Jira (issueKey, timestamp, role, action).
2. Chuẩn hóa bằng bộ quy tắc actions.yaml của team, cắt core view.
3. Học lại DFG hàng tháng trên các issue đã đóng gần nhất.
4. Chấm các issue đóng trong tuần; xuất top 10% kèm 3 chuyển tiếp hiếm nhất mỗi ca.
5. Trưởng nhóm hoặc QA rà soát trong buổi review/retrospective, ghi nhãn needs\_review / plausibly\_valid / insufficient\_evidence.
6. Dùng nhãn để đo hiệu quả và hiệu chỉnh danh sách.

Song song, chạy quy tắc nghiệp vụ cứng cho lỗi đã biết (ví dụ "DONE phải qua In Test", "không vào In Test khi chưa có assignee"): quy tắc chính xác hơn cho lỗi đã biết, mô hình bổ sung cho mẫu lạ chưa có quy tắc.

**Tình huống phù hợp**

- Rà soát chất lượng quy trình fix bug: bug đóng theo đường lạ (bỏ kiểm thử, lùi trạng thái, đổi người phụ trách nhiều lần).
- Đầu vào cho retrospective: "tuần này 5 bug đi đường hiếm, đây là các bước hiếm".
- Theo dõi khi đổi workflow Jira: chuyển tiếp mới sẽ nổi lên — tín hiệu cần học lại, không phải lỗi.

**Đo hiệu quả pilot (đặt trước khi chạy)**

- Mỗi tuần, người rà soát xem top-k của M\_markov trộn với k ca ngẫu nhiên mà không biết nguồn (thiết kế bảng mù đã có trong đồ án).
- Chỉ số chính: tỷ lệ needs\_review ở top-k so với nhóm ngẫu nhiên (precision@k vượt nền), kèm thời gian rà soát mỗi ca.
- Tiếp tục nếu sau 4–8 tuần precision@k cao hơn nhóm ngẫu nhiên với khoảng tin cậy không chứa 0; nếu không thì dừng.

**Rủi ro và biện pháp**

| Rủi ro | Biện pháp |
| --- | --- |
| Quy trình thay đổi làm mọi ca mới "lạ" | Học lại DFG định kỳ; theo dõi tỷ lệ chuyển tiếp chưa thấy |
| Mỗi team/dự án một quy trình | Mỗi team một DFG và một bộ quy tắc; không gộp team |
| Điểm thiên về ca dài | So trong nhóm độ dài, hiển thị kèm số bước hiếm |
| Dùng sai mục đích (đánh giá cá nhân) | Chỉ dùng ở mức issue/quy trình; role đổi ≠ người sai |
| Ít dữ liệu | Đồ án chạy với 97–129 issue train; dưới mức này chưa kiểm |
| Không có nhãn | Pilot với rà soát mù là bước bắt buộc trước khi tin danh sách |

## Giới hạn

- Không có nhãn bất thường thật: metric đo khả năng phân biệt sai lệch do chúng tôi chèn. Rà soát khám phá của agent trên 20 ca (V1, theo D\_hybrid) không cho thấy ca điểm cao đáng xem hơn ca ngẫu nhiên.
- Một team, 161 bug đã đóng, một giai đoạn; không áp dụng cho phát hiện sớm hay doanh nghiệp khác nếu chưa kiểm.
- Ưu thế của M\_markov chưa được xác nhận theo quy tắc khóa trước; cross-validation là khám phá, có 12 so sánh cặp chưa hiệu chỉnh đa so sánh.
- Tham số chưa tinh chỉnh: α = 1, trung bình thay vì max, Markov bậc 1 — cấu hình mặc định, không phải tối ưu.
- Chỉ dùng cấu trúc và thứ tự; thời gian xử lý chưa được dùng.

## Kết luận và bước tiếp theo

Phương án tốt nhất là M\_markov; nên đưa vào pilot rà soát hồi cứu có đo lường, không dùng để cảnh báo tự động.

1. Thông tin nằm ở bước chuyển: 153 biến thể cho 161 ca, và một nửa số ca có bước chuyển chưa từng thấy.
2. M\_markov tốt nhất ở mọi giao thức (cross-validation 0,603; đối chứng dương 0,979; đảo thứ tự 0,669), đồng thời tất định, nhanh và tự giải thích.
3. Node2Vec + Isolation Forest (D\_hybrid) không bổ sung giá trị; cải tiến cho nó chỉ giúp rất ít (F\_edge\_hybrid +0,009) hoặc không giúp (E\_score\_fusion).
4. Theo quy tắc khóa trước, ưu thế của M\_markov chưa được xác nhận: ứng viên tốt nhất, cần dữ liệu mới.
5. Luôn kết hợp với quy tắc nghiệp vụ cho lỗi đã biết; không dùng để đánh giá con người.

- [ ] Pilot rà soát mù 4–8 tuần để có nhãn thật và đo precision@k
- [ ] Xác nhận M\_markov trên issue mới theo quy tắc khóa trước
- [ ] Thử Markov bậc 2 khi có thêm dữ liệu; tích hợp quy tắc nghiệp vụ

## Phụ lục: tái lập và nguồn số liệu

Mọi số lấy từ artifact đã chạy trong repo đồ án; bản Markdown đầy đủ nằm ở docs/BAO\_CAO\_TONG\_KET.md.

```bash
uv sync --locked --all-extras --group dev
uv run jira-ad run --config configs/baseline.yaml                # V1 (A–D)
uv run jira-ad experiments --config configs/experiments.yaml     # ablation V1, 36 run
uv run jira-ad improve --plan configs/improvement_plan.yaml      # E/F/M, cross-validation, ứng dụng (~90 s)
uv run pytest -q && uv run ruff check src tests scripts          # 521 test
```

| Nội dung | Nguồn trong repo |
| --- | --- |
| Thống kê dữ liệu | outputs/analysis/audit\_raw.json, preprocess\_audit.json, notebook 01–02 |
| DFG train, ví dụ tính tay | outputs/runs/20261022T151529Z-25f2841c (graph.graphml, models/M\_markov) |
| Giao thức 1, đối chứng dương, phép thử hoán vị | outputs/improvement/20261022T151529Z-bb0fee9a và ba run 20261022T1515\* |
| Cross-validation, ứng dụng | outputs/improvement/20261022T151529Z-bb0fee9a (cv\_\*.csv, applicability.csv, top\_cases.csv) |
| Quyết định, tiến độ | docs/PROGRESS.md, docs/DECISIONS.md, docs/RESEARCH\_NOTES.md |

Môi trường: Python 3.12.7, numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1, gensim 4.4.0 (khóa trong uv.lock), macOS arm64.
