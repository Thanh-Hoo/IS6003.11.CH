# RESEARCH_NOTES — quan sát, giả thuyết và kết luận

Tách ba loại phát biểu để không lẫn lộn: **quan sát** (đo được, có nguồn), **giả thuyết** (chưa kiểm chứng), **kết luận** (chỉ những gì dữ liệu cho phép).
Mọi số dưới đây lấy từ run bàn giao `outputs/runs/20261017T081309Z-930f8a85` (baseline, model seed 42) và 35 run còn lại của `configs/experiments.yaml`
(12 thí nghiệm × 3 model seed; xem notebook 04, 05, 06 và `outputs/runs/comparison.csv`). Chúng sẽ đổi nếu dữ liệu hoặc cấu hình đổi; hãy chạy lại thay vì chép số.

> **Đính chính (2026-10-17).** Các phiên bản trước của tài liệu này dùng sai số chuẩn Hanley–McNeil/Mann–Whitney (≈ 0,074) và kết luận “mọi khoảng tin cậy của AUROC chứa 0,5, nên bốn phương pháp gần ngẫu nhiên”.
> Công thức đó giả định hai mẫu độc lập, còn ở đây mỗi mutant sinh từ chính một bản gốc (**dữ liệu ghép cặp**). Dưới giả thuyết không ghép cặp, SD của AUROC chỉ ≈ 0,016.
> Bản này dùng bootstrap theo `parent_case_id` và thử hoán vị trong cặp; một số kết luận đổi (đánh dấu **[đổi]**).

## Câu hỏi nghiên cứu

*Biểu diễn đồ thị (Node2Vec) có bổ sung giá trị so với thống kê quy trình và unigram/bigram khi xếp hạng các ca Jira khác thường không?*
Câu hỏi phụ: chiều cạnh, ngữ cảnh vai trò, đặc trưng chuyển tiếp ảnh hưởng thế nào; pooling mean/max đánh mất sai lệch thứ tự nào.

## Quan sát

### Dữ liệu (notebook 01–02; `analysis_only`)
- Bug: 5.126 event, 161 issue (Story: 4.439 event, 182 issue). Chỉ có issue **đã kết thúc**: cả 161 ca Bug đều có status cuối là DONE (83) hoặc Rejected (78). Không có nhãn bất thường.
- Chất lượng: 15 role trống, 837 `unknown` (16%), 44% event do bot; 161/161 issue có thứ tự dòng CSV **mới → cũ**; không có dòng trùng hay trùng thời điểm.
- Funnel: 5.126 → core 3.258 event. 1.117 event (22%) nằm sau status terminal cuối, 94% trong số đó là cập nhật `RemoteIssueLink` của bot; 751 event nhiễu bị bỏ theo policy mặc định.
- **Trace gần như không lặp:** 153 biến thể cho 161 trace, 98% biến thể chỉ xuất hiện một lần.
- **Hai quần thể khác hẳn:** DONE (trung vị 25 event, gần như luôn qua In Progress/In Test) và Rejected (trung vị 12 event, hầu như bỏ qua quy trình). Từ tạo đến terminal cuối: trung vị 40,7 ngày (DONE) và 19,4 ngày (Rejected).
- 165/553 đoạn chuyển trạng thái cách nhau dưới 1 phút (có chuỗi thao tác dồn dập).

### Mô hình (notebook 03–04, 06)
- **Độ phủ OOV:** `unseen_transition_ratio` trung bình 0,058 (validation) và 0,095 (test); mọi activity ở held-out đều có trong train.
- **Cosine ≠ xác suất chuyển tiếp:** Spearman(cosine, P̂ thực nghiệm) = 0,21 trên 2.352 cặp. Hoán đổi hai activity kề nhau cho chênh pooling đúng 0 nhưng làm surprisal tăng (ví dụ 1,15 → 2,35).
- **Hiệu năng trên mutant một chỉnh sửa (test, 31 parent mỗi loại, trung bình 3 model seed):** macro AUROC `A_stats` 0,531, `B_ngrams` 0,513, `C_embedding` 0,535, `D_hybrid` 0,544 (độ lệch chuẩn theo model seed 0,004–0,007).
  Bootstrap theo parent (2000 lần, 95%, trung bình 3 seed): [0,501; 0,567], [0,492; 0,536], [0,515; 0,563], [0,523; 0,575]. Validation (33 parent): 0,524 / 0,500 / 0,547 / 0,547.
- **[đổi] Khác ngẫu nhiên không?** Thử hoán vị trong cặp (test, seed 42): p một phía < 0,05 ở 5/12 ô (phương pháp × loại), gồm 2 ô `delete_internal` và 3 ô `duplicate_block`, **không có ô `swap_adjacent` nào** (p = 0,06–1,00). Sau Bonferroni 12 ô còn 3 ô:
  `C_embedding`/delete, `D_hybrid`/delete, `D_hybrid`/duplicate. Tức là có hiệu ứng **rất nhỏ** (macro AUROC 0,51–0,54) ở một số loại sai lệch, không ở mọi loại. `C_embedding` × swap cho đúng p = 1,0 vì pooling không thấy thứ tự.
- **[đổi] So sánh giữa các phương pháp (bootstrap ghép cặp theo parent, trung bình 3 model seed, macro AUROC; chưa hiệu chỉnh đa so sánh):**
  `D_hybrid − B_ngrams` = +0,047 [+0,026; +0,084] (validation) và +0,031 [+0,005; +0,062] (test), khoảng **không** chứa 0 ở cả hai split;
  `C_embedding − B_ngrams` = +0,047 [+0,020; +0,085] (validation) và +0,022 [−0,008; +0,053] (test);
  `D_hybrid − A_stats` = +0,023 [−0,004; +0,056] (validation) và +0,012 [−0,015; +0,040] (test), khoảng chứa 0 ở cả hai split;
  `D_hybrid − C_embedding` chứa 0 ở cả hai split. Về điểm ước lượng, {C, D} > A > B ở cả hai split; C và D ngang nhau ở validation (0,547 và 0,547), D nhỉnh hơn C ở test (0,544 và 0,535).
- **Độ ổn định theo seed nhỏ hơn độ bất định do chọn ca ở cấp macro:** std theo model seed 0,004–0,007; SE bootstrap theo parent của macro AUROC xấp xỉ 0,01–0,02.
- **Bộ máy hoạt động (đối chứng dương, validation, seed 42):** xáo toàn bộ phần nội bộ cho AUROC `A_stats` 0,886 [0,826; 0,951], `B_ngrams` 0,527 [0,448; 0,614], `C_embedding` 0,500, `D_hybrid` 0,658 [0,631; 0,713]; paired win rate 1,00 / 0,61 / 0,50 / 1,00.
  `D_hybrid` thắng mọi cặp nhưng AUROC không ghép chỉ 0,66 vì phương sai giữa parent; `C_embedding` đúng 0,500 theo lý thuyết.
- **Ablation cùng protocol** (đổi một yếu tố, 3 seed; bootstrap ghép cặp 95% trên test, chưa hiệu chỉnh đa so sánh): |Δ macro AUROC| lớn nhất 0,019; 1/32 ô (thí nghiệm × phương pháp) có khoảng không chứa 0 (`q_double`/`D_hybrid` −0,016 [−0,029; −0,004]);
  ở mức 5% và 32 ô thì khoảng 1,6 ô như vậy là điều đã kỳ vọng do ngẫu nhiên. `A_stats` và `B_ngrams` cho đúng Δ = 0 ở các thí nghiệm chỉ đổi walk/embedding (không dùng embedding) — kiểm chéo tính tất định.
- **Khác protocol (không so trực tiếp với baseline):** `keep_all_noise` 0,534 / 0,516 / 0,529 / 0,529; **Story** (182 issue, chỉ 7 Rejected; 36 parent mỗi loại ở test, 1 ca Rejected) 0,636 / 0,528 / 0,552 / 0,591;
  **holdout theo thời gian** 0,560 / 0,509 / 0,546 / 0,565 (xem dưới). Mỗi dãy theo thứ tự A / B / C / D.
- **Độ dài:** điểm của `B_ngrams` tương quan thuận với số event của trace (Spearman +0,56 trên test); `A_stats`, `C_embedding`, `D_hybrid` gần như không (|ρ| ≤ 0,16).
- **Đặc trưng hằng trên train:** `unseen_node_ratio` và `unseen_transition_ratio` luôn 0 trên train ở baseline (đồ thị fit từ chính các trace train).
- **Không rò rỉ (đo trực tiếp):** sửa 122 event trong hai ca held-out (1 validation, 1 test) không làm đổi bit nào trạng thái đã fit của A/B/C/D, và điểm của 62 ca held-out còn lại lệch đúng 0,0.

### Kiểm hai giả thuyết bằng quy tắc quyết định khóa trước (ngày 2026-10-17, trước khi chạy)
Chỉ số chính: macro AUROC của `D_hybrid` trên **validation**, trung bình 3 model seed, khoảng bootstrap 98,33% (Bonferroni 3 so sánh).

| Thí nghiệm | Giả thuyết | Δ so với baseline | Khoảng | Phán quyết |
|---|---|---:|---|---|
| `cross_fit_5` | 1: đặc trưng train in-sample | −0,0122 | [−0,0322; +0,0027] | không có bằng chứng |
| `dim_4` | 2: pooling làm loãng | −0,0174 | [−0,0525; +0,0172] | không có bằng chứng |
| `dim_8` | 2: pooling làm loãng | −0,0010 | [−0,0291; +0,0227] | không có bằng chứng |

Cơ chế của giả thuyết 1 đã được thỏa: với cross-fit, số cột hằng trên train của `A_stats` giảm từ 2 xuống 0 (`D_hybrid` 3 → 1), nhưng AUROC không tốt hơn. Trên test (xem sau phán quyết, khám phá) Δ của `D_hybrid` là −0,008 / −0,012 / −0,006, khoảng chứa 0.

### Holdout theo thời gian (protocol riêng)
97 / 32 / 32 ca (train kết thúc đến 2022-01-25). **29/64 ca held-out đã bắt đầu trước khi giai đoạn train kết thúc**: ca sống lâu nên hai giai đoạn chồng lên nhau, và cách chia này không phải tách thời gian hoàn toàn.
Macro AUROC test (3 seed): `A_stats` 0,560, `B_ngrams` 0,509, `C_embedding` 0,546, `D_hybrid` 0,565, so với 0,531 / 0,513 / 0,535 / 0,544 ở holdout ngẫu nhiên (khác protocol). Thứ hạng D > A > C > B khác với holdout ngẫu nhiên (D > C > A > B); chưa có kiểm định giữa hai protocol.

### Ca thật
- Bộ rà soát 20/31 ca test (theo `D_hybrid`) có **chưa có rà soát của con người**. Một agent đã rà soát khám phá từ bảng mù (chỉ chuỗi activity/role): 5 `needs_review`, 12 `plausibly_valid`, 3 `insufficient_evidence`.
  Sau khi mở khóa, `needs_review` chiếm 2/10 ở nhóm điểm cao và 3/10 ở nhóm ngẫu nhiên (Fisher p = 1,00); cả 3 ca `insufficient_evidence` đều thuộc nhóm điểm cao (ít event, nhiều role chưa xác định).
  **Kết quả âm:** với rà soát này, không có bằng chứng mô hình xếp các ca đáng rà soát lên cao hơn ngẫu nhiên. Không phải nhãn chuyên gia.
- `Rejected` chiếm 60% nhóm điểm cao và 48% ca test.

### Giai đoạn cải tiến (2026-10-22; `outputs/improvement/20261022T151529Z-bb0fee9a`)
Ba phương pháp mới: `E_score_fusion` (hai Isolation Forest riêng cho H và pooling, gộp điểm z theo train), `F_edge_hybrid` (vector cạnh `v_a ⊙ v_b` + H), `M_markov` (surprisal chuyển tiếp trung bình trên DFG train, không Isolation Forest). Hai mutant mới chỉ dùng ở cross-validation: `skip_status` (bỏ một bước trạng thái), `multi_edit` (ba chỉnh sửa).

- **Quy tắc khóa trước** (validation, 33 parent, 3 seed, khoảng 98,33%): so với `D_hybrid`, `E_score_fusion` −0,013 [−0,037; +0,011], `F_edge_hybrid` +0,004 [−0,026; +0,033], `M_markov` +0,032 [−0,008; +0,088] (P(Δ>0) = 0,97) ⇒ **0/3 ứng viên cải thiện**; `D_hybrid` vẫn là cấu hình ghi nhận. Test (khám phá): Δ −0,005 / −0,007 / +0,022, khoảng đều chứa 0.
- **Trên split V1** (3 seed): macro AUROC test `M_markov` 0,566 (validation 0,579), cao nhất; A–D tái lập đúng số V1.
- **Đối chứng dương** (seed 42): `M_markov` 0,979 [0,949; 0,996], `F_edge_hybrid` 0,843, `E_score_fusion` 0,786 (A–D như cũ).
- **Phép thử hoán vị trong cặp** (test, seed 42): `M_markov` swap p = 0,0005, duplicate p = 0,0005, delete p = 0,14 — phương pháp đầu tiên phân biệt được `swap_adjacent` với ngẫu nhiên.
- **Cross-validation 5 fold, 161 issue, 782 mutant (khám phá, dùng cả test đã xem):** macro AUROC `M_markov` 0,603 [0,588; 0,621], `F_edge_hybrid` 0,563, `D_hybrid` 0,554, `E_score_fusion` 0,554, `C_embedding` 0,549, `A_stats` 0,544, `B_ngrams` 0,512.
  `M_markov − D_hybrid` +0,049 [+0,034; +0,065]; `F_edge_hybrid − D_hybrid` +0,009 [+0,001; +0,017]; `E_score_fusion − D_hybrid` −0,000 [−0,008; +0,008]; `D_hybrid − A_stats` +0,010 [−0,004; +0,025].
  Theo loại, `M_markov`: swap 0,669, multi_edit 0,696; mọi phương pháp ở `skip_status` chỉ 0,52–0,57.
- **Inference out-of-fold:** Jaccard top-10% (17 ca) giữa 3 seed: `M_markov` 1,000, `A_stats` 0,889, `E`/`F` 0,646, `C`/`D` 0,548; chấm < 0,25 ms/ca mọi phương pháp. Ca top của `M_markov` có trung bình 6,3 chuyển tiếp chưa thấy (D 4,2; A 2,7), ít Rejected hơn (29% so với 48% toàn tập), điểm tương quan với độ dài (Spearman +0,51) và với số chuyển tiếp chưa thấy (+0,75).
- **Dữ liệu:** 87/161 ca có ≥ 1 chuyển tiếp chưa thấy so với đồ thị các fold khác (DONE trung bình 2,41, Rejected 0,81; tương quan với độ dài +0,55).

## Giả thuyết (chưa kiểm chứng; không được trình bày như kết quả)

1. ~~Cross-fitting~~ **Đã kiểm, không được ủng hộ** (xem trên). Còn lại: cross-fit cho cả embedding chưa được đo.
2. ~~Loãng pooling~~ **Đã kiểm ở số chiều 4/8 (và 32 trước đó), không được ủng hộ.** Kiểm thêm bằng gộp điểm hai rừng riêng (`E_score_fusion`, 2026-10-22): bằng `D_hybrid` ⇒ vẫn không được ủng hộ.
3. **Mutant quá tinh vi.** Swap một cặp kề nhau không được phương pháp nào phân biệt với ngẫu nhiên; delete/duplicate được phát hiện rất yếu. Mutant mạnh hơn hoặc nhiều chỉnh sửa có thể phát hiện được (đối chứng dương ủng hộ).
4. **Hai quần thể.** DONE và Rejected khác nhau mạnh nên một mô hình chung có thể kém; mô hình riêng theo nhánh có thể tốt hơn (cỡ mẫu mỗi nhánh còn nhỏ hơn). Chưa thử.
5. **Chuỗi trạng thái dồn dập** (chuyển trạng thái trong vài giây) có thể là thao tác thử/migration, không phải quy trình thật; chưa điều tra.
6. **Mới:** lợi thế của `C_embedding`/`D_hybrid` so với `B_ngrams` có thể do `B_ngrams` thưa (442 chiều / 97 ca train) và nhạy độ dài (ρ = +0,56), chứ không hẳn do biểu diễn đồ thị. Chưa tách được hai nguyên nhân.
7. **Mới (2026-10-22):** mô hình xác suất chuyển tiếp (`M_markov`) tốt hơn `D_hybrid` — được cross-validation ủng hộ mạnh nhưng chưa xác nhận theo quy tắc khóa trước. Một phần lợi thế có thể do mutant được dựng từ activity của parent nên sinh chuyển tiếp hiếm (đúng thứ `M_markov` đo); ở `skip_status` nó không tốt hơn (0,540 so với 0,566).

## Kết luận được phép

- Pipeline Python + Jupyter chạy được từ event log thật đến đặc trưng, mô hình, bảng kết quả và phân tích ca; kết quả tái lập được (cùng cấu hình, môi trường; chạy lại toàn bộ kế hoạch lần hai cho phán quyết trùng tới 1e-16) và không rò rỉ train/held-out (đã đo).
- **[đổi]** Với mutant một chỉnh sửa, các phương pháp phát hiện được hiệu ứng **rất nhỏ** nhưng khác 0,5 ở loại `delete_internal` và `duplicate_block` (macro AUROC 0,51–0,54); không phương pháp nào phân biệt được `swap_adjacent` với ngẫu nhiên. Đây không phải “độ chính xác phát hiện lỗi thực tế”.
- **[đổi] Về câu hỏi chính:** (a) so với n-gram `B_ngrams`, `D_hybrid` cao hơn ở cả validation và test với khoảng bootstrap không chứa 0 (chưa hiệu chỉnh đa so sánh; xem giả thuyết 6 về nguyên nhân);
  (b) so với thống kê quy trình `A_stats`, `D_hybrid` có điểm ước lượng cao hơn ở cả hai split (+0,023 và +0,012) nhưng khoảng đều chứa 0, nên **chưa chứng minh** embedding bổ sung giá trị so với thống kê quy trình. Điều này **không** chứng minh embedding vô ích.
- Cross-fit đặc trưng train và giảm số chiều embedding **không** cải thiện `D_hybrid` trên validation theo quy tắc khóa trước.
- Bộ máy phát hiện được sai lệch thứ tự mạnh (đối chứng dương: `A_stats` 0,886, `D_hybrid` 0,658 và thắng 100% cặp), và pooling mean/max đúng như lý thuyết không phân biệt được hai chuỗi cùng histogram (`C_embedding` đúng 0,500).

- **[mới 2026-10-22]** Theo quy tắc khóa trước, không phương pháp mới nào được xác nhận tốt hơn `D_hybrid`. Trong đánh giá khám phá (cross-validation 161 issue), `M_markov` cao hơn mọi phương pháp khác với khoảng không chứa 0, và Node2Vec (C, D, E, F) không vượt được thống kê chuyển tiếp trực tiếp trên DFG.
- **[mới 2026-10-22]** Không phương pháp nào đạt tiêu chí "tự động cảnh báo" khóa trước; `M_markov`, `F_edge_hybrid`, `E_score_fusion`, `A_stats` đạt tiêu chí "bộ lọc ưu tiên rà soát"; `D_hybrid` không đạt vì danh sách top-10% không ổn định giữa seed.

## Không được kết luận

Embedding thắng hay thua thống kê quy trình; điểm cao là vi phạm quy trình; `Rejected` là bất thường; thứ hạng phương pháp ổn định; kết quả áp dụng cho phát hiện sớm, vận hành online hoặc cho doanh nghiệp khác;
độ chính xác phát hiện lỗi thực tế (nhãn `is_injected` là mutant do ta chèn, tỷ lệ 0,5 là tỷ lệ thiết kế); bất kỳ ca nào ‘thật sự đáng rà soát’ (chưa có người rà soát; rà soát khám phá của agent không phải nhãn chuyên gia);
rằng mô hình xếp các ca đáng rà soát lên cao (rà soát khám phá cho kết quả ngược: 2/10 so với 3/10);
rằng `M_markov` đã được xác nhận tốt hơn `D_hybrid` (chỉ cross-validation khám phá ủng hộ); rằng các phương pháp phát hiện được lỗi "bỏ qua bước" trong thực tế.

## Giới hạn dữ liệu và thiết kế

- Một team, ~160 issue bug đã đóng, một khoảng thời gian; không có nhãn doanh nghiệp. Holdout ngẫu nhiên theo ca không chứng minh khả năng triển khai theo thời gian; holdout theo thời gian có làm nhưng chồng lấn (29/64 ca held-out đã bắt đầu trước khi train kết thúc).
- Cỡ mẫu holdout nhỏ (31 ca test, 33 ca validation; Story chỉ 1 ca Rejected ở test). Ba loại mutant dùng chung các parent nên macro không giảm nhiễu nhiều.
- **Lịch sử xem test:** test được xem lần đầu ở Task 5 với cấu hình đã khóa, rồi lặp lại bằng `run`/`experiments` (tất định, cùng số). Các thí nghiệm Task 8 chạy trên test là **độ nhạy khám phá**; không có cấu hình nào được chọn theo chúng.
  Ba thí nghiệm của Task 13 có quy tắc khóa trước trên validation; test chỉ được xem sau phán quyết. Các so sánh giữa phương pháp (D−A, D−B...) là câu hỏi chính của spec §1 nhưng không có quy tắc quyết định khóa riêng và chưa hiệu chỉnh đa so sánh.
- Mô hình chỉ dùng cấu trúc/thứ tự; thời gian chỉ dùng cho EDA. Mutation chỉ gồm ba loại một chỉnh sửa; chưa có seed mutation khác.
- Bootstrap percentile có thiên lệch nhỏ hướng lên (parent trùng); phép thử hoán vị trong cặp là kiểm chứng độc lập cho cùng kết luận.
- Phiên bản thư viện rất mới (numpy 2.5, pandas 3.0, scipy 1.18). Gensim 4.4.0 in `Exception ignored in 'our_dot_float'` ở một số run; tất định theo dữ liệu/seed, vector giống hệt bit giữa numpy 2.5/scipy 1.18 và numpy 2.4/scipy 1.17, nhưng chưa rõ nguyên nhân gốc.

## Bước tiếp theo đề xuất (theo giá trị thông tin; cập nhật 2026-10-22)

1. Rà soát mù của người hiểu quy trình: top-10% của `M_markov` trộn với một mẫu ngẫu nhiên có số ca bằng nhau, đo precision@k thật.
2. Xác nhận `M_markov` theo quy tắc khóa trước trên dữ liệu chưa từng xem (issue mới, team khác).
3. Kết hợp quy tắc nghiệp vụ cho lỗi đã biết; thử Markov bậc 2 khi có thêm dữ liệu.
4. Mô hình riêng theo nhánh DONE/Rejected; cross-fit cho embedding (ưu tiên thấp hơn vì embedding chưa cho thêm giá trị).
