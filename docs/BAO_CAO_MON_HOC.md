# Phân tích, kiểm định và tái thiết kế quy trình xử lý lỗi phần mềm dựa trên event log Jira

Đồ án môn **Hoạch định nguồn lực doanh nghiệp nâng cao**. Người đọc: giảng viên và hội đồng môn học.

> **Nguồn số liệu.** Mọi con số trong báo cáo sinh từ run `outputs/process/20261026T025412Z-399b0a40` (lệnh `uv run jira-ad process --config configs/process.yaml`, tất định, có manifest + sha256 từng artifact). Sau khi viết, mọi số đã được đối chiếu tự động với artifact bằng `uv run jira-ad check-report` (Phụ lục C). Notebook minh họa từng chương: `notebooks/07_quantitative.ipynb` đến `notebooks/12_summary_report.ipynb`.

---

## Tóm tắt cho người quản lý

**Bối cảnh.** Team xử lý lỗi phần mềm của công ty dùng Jira. Log gồm 161 bug đã đóng (83 DONE, 78 Rejected), 5.126 sự kiện, giai đoạn 2021-06 → 2022-08. Chúng tôi trả lời bốn câu hỏi quản trị:

| Câu hỏi | Trả lời ngắn | Chương |
|---|---|---|
| 1. Quy trình thực tế chạy thế nào? | Phần lớn ca đi theo đúng trình tự Jira, nhưng có nhiều đường tắt và quay lui. 105/161 ca (65,2%) khớp hoàn toàn mô hình chuẩn; ở nhánh DONE chỉ 39/83 ca (47,0%). | 1, 5 |
| 2. Thời gian đi đâu, vai trò nào là điểm nghẽn? | CT trung vị 17,0 ngày làm việc. Thời gian dồn vào `To Investigate` (trung vị 10,9 ngày/lượt; không tách được chờ và điều tra) và `To Do` (48% số ngày vượt định mức, phần lớn từ vài ca nằm chờ rất lâu rồi bị từ chối). Dữ liệu **không** cho thấy một vai trò cụ thể gây chờ. Tỉ trọng thời gian "làm" chỉ đo được thành khoảng 16,7%–59,2%, vì Jira không có trạng thái "đang điều tra". | 2, 3 |
| 3. Bao nhiêu ca lệch chuẩn, lệch ở đâu? | Lệch nhiều nhất là bỏ pha điều tra (`CREATE → To Do`, 37 ca, đa số là quyết định thật, không phải thao tác dồn), lùi trạng thái (23 ca) và lùi về Inbox (`To Do → Inbox`, 11 ca). 17/23 ca lùi trạng thái chỉ lùi trong đợt cập nhật bù, tức nhiều khả năng là sửa thao tác. Danh sách đồng thuận gồm 10 ca "nên xem trước" (ổn định qua bootstrap), mỗi ca có lý do bằng chữ. | 5, 6 |
| 4. Tái thiết kế ra sao, đo bằng KPI gì? | 5/7 ứng viên được dữ liệu ủng hộ. Lợi ích chính là **đo được công sức điều tra** (thêm trạng thái Investigating), **phân loại sớm** ở Inbox và **rà backlog To Do định kỳ**. Mức rút ngắn CT là vừa phải: kịch bản thực tế 17,0 → 15,2 ngày làm việc (giảm 10,7%); cận trên lý tưởng 5,9 ngày (giảm 65,5%) không khả thi vì 47/78 ca Rejected chỉ bị loại sau khi đã điều tra (mục tiêu / kịch bản ước tính). | 4 |

**Giả định dữ liệu (áp dụng cho mọi chương có số đo thời gian).**
- Jira chỉ ghi **thời điểm đổi trạng thái**, không ghi bắt đầu/kết thúc từng việc. Vì vậy thời gian làm (PT) và chờ (WT) là **xấp xỉ** theo cách phân loại trạng thái.
- **Không có số nhân sự/giờ công.** Năng lực đo qua thông lượng; phân tích nguồn lực dừng ở **vai trò** (PO, Eng, SQA…), không đánh giá cá nhân.
- 43,5% sự kiện do `bot`. 30% lần đổi trạng thái là **cập nhật bù** (đổi trong vòng 60 giây sau lần đổi trạng thái trước; lần đổi đầu sau khi tạo không tính). Một **đợt bù** là chuỗi các lần đổi như vậy, kể cả lần đổi mở đầu chuỗi; một lần lùi/mở lại "trong đợt bù" là lần đổi thuộc một đợt bù — định nghĩa này dùng thống nhất cho FPY và bảng sai lệch.
- **Ngày làm việc** = T2–T6 theo giờ địa phương từ offset gốc của timestamp (`-0700`/`-0800`), chu kỳ 24 giờ, không tính ngày lễ.
- **Chỉ có ca đã đóng**, nên không dùng cho phát hiện sớm. Dữ liệu được coi là của công ty theo kịch bản đồ án; nguồn gốc thật là bộ dữ liệu công khai `Zenodo 8275679` (Team "Newt", bài `ICSME 2023`).

---

## Chương 1 — Work System và BPMN chuẩn của quy trình xử lý bug

*Áp dụng Buổi 1: khung Work System (8 thành phần) để mô tả hệ thống làm việc, và BPMN 2.0 (pool, lane, gateway) để mô hình hóa quy trình chuẩn.*

### 1.1 Work System

| Thành phần | Nội dung | Dẫn chứng từ dữ liệu |
|---|---|---|
| Khách hàng | Người dùng gặp lỗi (giả định đề bài) và các vai trò nội bộ báo lỗi | Vai trò tạo issue (5 nhóm lớn nhất): Eng 54, SQA 44, unknown 26, PO 16, thiếu role 11, … |
| Sản phẩm/dịch vụ | Lỗi được sửa (DONE) hoặc quyết định không sửa (Rejected); thay đổi mã liên kết commit/MR | DONE 83, Rejected 78; 342 sự kiện liên kết commit, 95 liên kết merge request |
| Quy trình và hoạt động | Chuỗi trạng thái Jira, xen sửa trường, giao việc, liên kết | 10 trạng thái, 30 biến thể trạng thái, 49 loại hoạt động |
| Người tham gia | Các vai trò con người | PO 1.296, Eng 489, SQA 168, RTE 43 sự kiện…; không xác định: unknown 837, thiếu role 15 |
| Thông tin | Mô tả lỗi, liên kết issue, phân loại backlog, phiên bản sửa, epic | ADD_ISSUE_LINK 384, EDIT_DESCRIPTION 357, UPDATE_BACKLOG_CLASSIFICATION 134 |
| Công nghệ | Jira tích hợp hệ thống quản lý mã nguồn qua bot | bot 2.230/5.126 sự kiện (43,5%) |
| Môi trường | Một team trong công ty phần mềm lớn, có áp lực phát hành | 47 lần cập nhật trường "chặn phát hành" |
| Hạ tầng | Máy chủ Jira, Git/merge request (giả định đề bài; log không mô tả trực tiếp) | Dấu vết tích hợp: 342 + 95 sự kiện liên kết |

### 1.2 Mô hình chuẩn (BPMN)

Mô hình chuẩn là **giả định của tác giả**, được duyệt trước khi kiểm định. Trình tự chính là `Inbox → To Investigate → INVESTIGATED → To Do → In Progress → In Test → DONE`. Từ các trạng thái trước `In Progress` có nhánh XOR rẽ sang `Rejected`, và có vòng `In Test → In Progress` khi kiểm thử không đạt. Giả định A1: tạo issue tương đương với vào `Inbox` ngầm định.

- Lane theo vai trò hoàn tất bước, tức vai trò chuyển ca ra khỏi trạng thái nhiều nhất: **PO** cho Inbox, To Investigate, INVESTIGATED, To Do; **Eng** cho In Progress; **SQA** cho In Test.
- File BPMN 2.0: `c_conformance/reference_model.bpmn` (mở được bằng bpmn.io). Hình và Petri net tương ứng có trong notebook 09.

---

## Chương 2 — Phân tích định lượng: thời gian đi đâu?

*Áp dụng Buổi 2: CT = PT + WT, hiệu suất chu trình CTE = PT/CT, định luật Little, năng lực đo qua thông lượng, FPY.*

**Giả định của chương:** PT/WT là xấp xỉ, nên được báo thành **khoảng** giữa bốn biến thể. Hai cách phân loại "làm": (a) chính là `In Progress`, `In Test`; (b) độ nhạy, xếp thêm `To Investigate` là làm. Mỗi cách có hai phiên bản: nguyên trạng, và cận trên khi tính là "làm" lượt ngay trước một đợt cập nhật bù có đi qua trạng thái làm (người dùng làm việc thật rồi mới bấm chuyển dồn). Mọi số dùng ngày làm việc, trừ khi ghi khác.

### 2.1 Bảng KPI AS-IS (đo được)

| KPI | Bug | Story (đặt cạnh, không trộn) |
|---|---|---|
| Số ca | 161 | 182 |
| CT trung vị (ngày làm việc / ngày lịch) | 17,0 / 23,0 | 19,3 / 27,3 |
| CT P90 (ngày làm việc) | 74,3 | 54,8 |
| Tỉ trọng PT (khoảng giữa bốn biến thể) | 16,7%–59,2% | 28,0%–31,9% |
| FPY strict / adjusted | 0,814 / 0,957 | 0,945 / 0,967 |
| Thông lượng trung bình (ca/tuần) | 2,8 | 3,3 |
| WIP trung bình (ca) | 18,4 | 17,0 |
| Tỉ lệ lần đổi trạng thái là cập nhật bù | 29,8% | 14,1% |

### 2.2 Phát hiện

- **Kết luận "làm bao nhiêu" phụ thuộc gần như hoàn toàn vào cách hiểu `To Investigate`.** Theo phân loại chính, PT chiếm 16,7% CT; nếu `To Investigate` là "làm" thì 57,0%. `To Investigate` là trạng thái tốn thời gian nhất: trung vị 10,9 ngày mỗi lượt, tổng 2.109,6 ngày làm việc. Đây là vấn đề **đo lường**: Jira không ghi lại phần điều tra thực sự diễn ra trong `To Investigate`. (Story không có trạng thái `To Investigate`, nên khoảng hẹp của story không so sánh được với bug.)
- **Nhánh Rejected tốn nhiều thời gian trước khi bị loại.** 78 ca Rejected tiêu tốn 1.928,6 ngày-issue làm việc, trung vị 13,4 ngày. Chỉ 1 ca kết thúc Rejected sau khi đã vào `In Progress`; công sức chủ yếu mất ở giai đoạn chờ và điều tra. (Cờ ở Chương 5 đếm 2 ca vì tính cả `TI-4584`: bị Rejected giữa chừng rồi mở lại và kết thúc DONE.)
- **Định luật Little:** λ = 0,413 ca/ngày, W = 45,6 ngày, L = 18,8 ca. Với log chỉ gồm ca đã đóng, L = λ·W là đồng nhất thức. Thông tin nằm ở chỗ khác: số ca đến nửa đầu kỳ là 109, nửa sau là 52. Đây là dấu hiệu thiên lệch sống sót (ca mở cuối kỳ chưa có trong log) hoặc lượng việc giảm, nên không dùng để dự báo.
- **Vai trò cổng** (ai chuyển ca vào trạng thái): PO cho `To Investigate` (91%), `Rejected` (88%), `To Do` (75%); Eng cho `In Test`; SQA cho `DONE` (54%).
- **FPY:** 30 ca có lùi trạng thái hoặc mở lại. Chỉ 7 ca có lần lùi/mở lại nằm **ngoài** đợt cập nhật bù; phần còn lại nhiều khả năng là sửa thao tác. Vì vậy FPY adjusted là 0,957 so với FPY strict 0,814.

---

## Chương 3 — Định mức đúng/trễ và độ đo trung tâm

*Áp dụng Buổi 3: event log, định mức đúng/trễ theo trạng thái, vai trò và ca; DFG và các độ đo trung tâm (degree, betweenness, closeness, eigenvector, PageRank).*

**Giả định của chương:** công ty **không có SLA chính thức**. Định mức là **phân vị 0,75 của thời gian nằm ở trạng thái** trong lịch sử, tính bằng ngày làm việc, và chỉ đặt cho trạng thái có từ 10 lượt trở lên. Theo cấu tạo, khoảng 25% lượt của mỗi trạng thái "trễ", nên so sánh dựa vào **số ngày vượt định mức**, không dựa vào tỉ lệ trễ. Ngưỡng có thể thay bằng SLA thật trong `configs/process.yaml`.

### 3.1 Định mức và ngày vượt định mức

| Trạng thái | Định mức P75 (ngày) | Ngày vượt định mức | Tỉ trọng | Vai trò cổng |
|---|---|---|---|---|
| To Do | 7,8 | 1.159,3 | 48% | PO |
| To Investigate | 27,9 | 510,6 | 21% | PO |
| In Test | 9,8 | 295,3 | 12% | Eng |
| INVESTIGATED | 2,2 | 188,6 | 8% | PO |
| Từ lúc tạo tới lần đổi đầu | 4,0 | 177,6 | 7% | — |
| In Progress | 3,0 | 95,6 | 4% | PO |

- **`To Do` là ưu tiên số 1.** Trung vị thời gian ở `To Do` gần 0 (khoảng một nửa số lượt chỉ kéo dài vài giây khi chuyển dồn), nhưng một số ca nằm chờ rất lâu. Ví dụ lớn nhất là ca `TI-5200`: 149,9 ngày ở `To Do`, rồi bị từ chối.
- **Theo vai trò chuyển ra** (mức vai trò): PO gắn với 1.298,1 ngày vượt định mức qua 390 lần chuyển, Eng 222,7, SQA 171,3. Phần không gán được vai trò người (unknown) là 742,9 ngày, nên bảng vai trò chưa đầy đủ. Vai trò chuyển ca ra là người ghi nhận bước kết thúc, **không** phải nguyên nhân của thời gian chờ.
- 99 ca có ít nhất một lượt trễ; 41 ca có CT vượt P75 của nhánh.

### 3.2 Độ đo trung tâm

- Trên DFG trạng thái, **`In Progress`** có betweenness cao nhất (0,367) và PageRank cao nhất (0,245): mọi luồng sửa lỗi đều đi qua đây.
- Các trạng thái có nhiều ngày vượt định mức nhất (`To Do`, `To Investigate`) **không** phải nút trung gian nhất. Độ trễ nằm ở hàng đợi trước điểm làm việc chính, không nằm ở chính điểm đó.
- Trên DFG hoạt động (tập train), `EDIT_DESCRIPTION` (betweenness 0,231) và `ADD_ISSUE_LINK` (0,180) là các hoạt động nối nhiều nhất, phù hợp với vai trò của mô tả lỗi và liên kết trong điều tra.

---

## Chương 4 — Tái thiết kế quy trình (BPR): AS-IS → TO-BE

*Áp dụng Buổi 4: BPR với AS-IS/TO-BE, bài học Ford/Mazda và bảng KPI; cùng các BPR heuristics của Buổi 2.*

**Giả định của chương:** mỗi ứng viên được **kiểm chứng trên dữ liệu** bằng một câu hỏi đo được và ngưỡng **khóa trước** (1 tuần làm việc = 5 ngày; "đáng kể" = 20%; "đa số" = 50%; khoảng tin cậy 95% loại trừ 0). Số TO-BE là **tính lại trên chính log** (what-if), không phải mô phỏng hay kết quả đã triển khai, và thường là **cận trên**.

### 4.1 Vấn đề → bằng chứng → thủ pháp → kiểm chứng

| Vấn đề | Bằng chứng | Thủ pháp BPR | Kiểm chứng |
|---|---|---|---|
| Ca bị từ chối vẫn nằm lâu trước khi bị loại | 78 ca Rejected chiếm 36,8% ngày-issue; trung vị 13,4 ngày tới khi bị loại; nhưng 47/78 ca bị loại ngay sau INVESTIGATED, tức cần điều tra trước khi quyết | Triage / knock-out sớm (ở Inbox với ca rõ ràng, ngay khi kết thúc điều tra với ca còn lại) | **ủng hộ** (quy mô vấn đề; phép kiểm không đo được bao nhiêu ca có thể quyết sớm hơn) |
| Trạng thái Jira cập nhật muộn so với việc thật | 39/58 ca (67,2%) có commit/MR trước khi chuyển In Progress; liên kết đầu rơi vào To Investigate 22 ca, To Do 12 ca, trước lần đổi đầu 5 ca | Task automation: tự chuyển In Progress theo commit/MR | **ủng hộ**, nhưng cung tự động `To Do → In Progress` chỉ áp dụng cho 12 ca |
| INVESTIGATED chỉ là bước đi xuyên qua | 43/62 lần (69,4%) chuyển sang To Do trong ≤ 1 ngày | Task composition: gộp INVESTIGATED vào To Do | **ủng hộ** |
| PO là cổng của phần lớn trạng thái chờ | Trung vị chờ ở To Do như nhau giữa lượt PO và vai trò khác (khoảng tin cậy 95% chứa 0) | Empower / phân quyền | **không ủng hộ** |
| Bug trùng bị phát hiện muộn | 7 ca trùng bị loại sau trung vị 3,2 ngày, tức đã nhanh | Kiểm tra trùng ngay khi tạo | **không ủng hộ** |
| Công sức điều tra không hiện trong Jira | PT 16,7% so với 57,0% tùy cách hiểu To Investigate | Thêm trạng thái Investigating | **ủng hộ** |
| Mọi bug đều phải qua điều tra | Ca DONE bỏ điều tra (32 ca): CT 11,2 ngày, FPY 0,75; ca DONE có điều tra (51 ca): CT 35,9 ngày, FPY 0,76 | Triage: luồng nhanh cho bug rõ ràng | **ủng hộ** (quan sát, không nhân quả: chênh CT một phần là cơ học vì bỏ luôn thời gian ở To Investigate, và bug sửa thẳng có thể vốn đơn giản hơn) |

**Ghi chú về PO.** Giả thuyết "chờ ở To Do gắn với PO" không được ủng hộ theo phép kiểm khóa trước (trung vị). Phân tích mô tả sau đó cho thấy 60,5% số ngày vượt định mức ở To Do rơi vào lượt do PO chuyển ra, nhưng 75,3% phần này (527,9 ngày) đến từ đúng 4 lượt PO chuyển `To Do → Rejected`. Đây giống việc **dọn backlog cũ** hơn là PO làm chậm việc sửa. Đề xuất phù hợp là rà backlog To Do định kỳ, không phải phân quyền lại.

**Bài học Ford/Mazda.** Ford không làm nhanh hơn bước đối chiếu hóa đơn mà bỏ hẳn bước đó. Tương tự, thay vì nhắc người dùng cập nhật trạng thái, để commit/MR tự chuyển `In Progress`. Mazda cho thấy giá trị của việc so một quy trình với cách làm khác của chính mình. Tương tự, luồng "bỏ điều tra" và luồng có điều tra của chính team chênh nhau rất xa về CT; đây là **gợi ý** để thử phân luồng ở Inbox trong pilot, chưa phải bằng chứng rằng phân luồng sẽ rút ngắn CT.

### 4.2 Mô hình TO-BE

`CREATE → Inbox (triage) → { Rejected | To Do (luồng nhanh) | To Investigate → Investigating → { To Do | Rejected } } → In Progress (tự động khi có commit/MR) → In Test → { In Progress | DONE }`.

TO-BE chỉ gồm ứng viên được ủng hộ. File `d_bpr/tobe_model.bpmn`, hình có trong notebook 10. Lane của `To Investigate`/`Investigating` (PO) dựa trên số liệu mỏng và là đề xuất.

### 4.3 KPI AS-IS (đo) và TO-BE (mục tiêu / kịch bản ước tính)

| KPI | AS-IS (đo) | TO-BE (mục tiêu / kịch bản ước tính) | Kịch bản và giả định |
|---|---|---|---|
| CT trung vị (ngày làm việc) — **kịch bản thực tế** | 17,0 | 15,2 (giảm 10,7%) | Ca Rejected đã qua điều tra được quyết ngay khi kết thúc điều tra (bỏ chờ ở INVESTIGATED và sau đó) + chờ To Do không quá định mức |
| CT P90 (ngày làm việc) — kịch bản thực tế | 74,3 | 57,9 (giảm 22,1%) | Như trên |
| CT trung vị (ngày làm việc) — **cận trên lý tưởng** | 17,0 | 5,9 (giảm 65,5%) | Mọi ca Rejected được quyết ở lần đổi trạng thái đầu. **Không khả thi:** 47/78 ca Rejected chỉ bị loại sau khi đã điều tra, và TO-BE vẫn giữ `Investigating → Rejected` |
| Ngày-issue của ca Rejected — kịch bản thực tế | 1.928,6 | 1.394,2 (giảm 27,7%) | Quyết ngay khi kết thúc điều tra |
| Ngày-issue của ca Rejected — cận trên lý tưởng | 1.928,6 | 264,2 (giảm 86,3%) | Thông tin để từ chối đã có từ lần đổi trạng thái đầu (không khả thi, như trên) |
| Tỉ trọng PT đo được | 16,7% | 16,9% | Phần To Do sau commit/MR đầu tiên là làm (cải thiện đo lường, CT không đổi); chưa tính phần Investigating vì chưa đo được |
| Số lần đổi trạng thái/ca | 4,4 | 5,4 | Đường AS-IS chuyển sang đường TO-BE: bỏ INVESTIGATED, thêm Investigating, qua Inbox tường minh |
| Tỉ lệ ca khớp mô hình | 65,2% | 80,7% | So với mô hình luồng nhanh (chuẩn + `CREATE → To Do`): đổi chuẩn so sánh, hành vi không đổi |

**Thông điệp của chương.** Tái thiết kế không hứa rút ngắn CT nhiều: kịch bản thực tế chỉ giảm CT trung vị khoảng một phần mười (17,0 → 15,2 ngày làm việc). Giá trị chính nằm ở ba điểm:
1. **Đo được công sức điều tra.** Tách `To Investigate` thành hàng đợi và `Investigating` thành việc, để biết thời gian thật sự đi đâu. Hiện tỉ trọng PT chỉ đo được trong khoảng 16,7%–59,2%.
2. **Phân loại sớm ở Inbox.** Bug rõ ràng đi luồng nhanh; bug cần điều tra được quyết từ chối ngay khi điều tra xong, không để chờ thêm ở INVESTIGATED/To Do.
3. **Rà backlog To Do định kỳ.** Phần lớn số ngày vượt định mức ở To Do đến từ vài ca nằm chờ hàng trăm ngày rồi mới bị từ chối.

Cận trên 5,9 ngày chỉ để biết giới hạn lý thuyết, không phải mục tiêu.

- **TO-BE thêm bước, không bớt bước:** số lần đổi trạng thái/ca tăng, vì mục tiêu của Investigating và Inbox tường minh là **đo được** việc điều tra và phân loại.
- **Tự chuyển trạng thái** có lợi ích đo lường nhỏ (16,7% → 16,9%), vì lần liên kết commit/MR đầu tiên hiếm khi rơi vào `To Do` (12/39 ca); phần lớn rơi vào `To Investigate` (22 ca). Điều này là thêm một dấu hiệu rằng việc thật đang diễn ra trong `To Investigate`, ủng hộ đề xuất thêm Investigating.

### 4.4 Kế hoạch pilot

| Giai đoạn | Tuần | Việc | KPI theo dõi (mốc AS-IS) |
|---|---|---|---|
| Chuẩn bị | 1–2 | Cấu hình Jira: thêm Investigating, bỏ INVESTIGATED, tự chuyển In Progress; họp triage hằng ngày ở Inbox | Số lần đổi trạng thái/ca (4,4; đường TO-BE dự kiến 5,4), tỉ trọng PT (16,7%) |
| Chạy thử | 3–8 | Chạy quy trình TO-BE với một team | CT trung vị (17,0), ngày-issue Rejected (1.928,6), tỉ lệ ca khớp mô hình TO-BE (mốc AS-IS so với mô hình luồng nhanh: 65,2%) |
| Đánh giá | 9–10 | So KPI pilot với mốc AS-IS bằng cùng lệnh, cùng định nghĩa; tiếp tục nếu KPI chính đi đúng hướng và khoảng tin cậy không chứa 0 | CT trung vị, CT P90 (74,3), ngày-issue Rejected, tỉ lệ ca khớp |

---

## Chương 5 — Khai phá quy trình AS-IS và kiểm định tuân thủ

*Áp dụng Buổi 5: khai phá bằng Alpha, Heuristics và Inductive Miner; Petri net; kiểm định tuân thủ bằng token replay (fitness, precision, generalization, simplicity).*

### 5.1 Khai phá AS-IS (log mức trạng thái, 161 ca)

| Mô hình | Fitness | Precision | Generalization | Simplicity | % ca khớp |
|---|---|---|---|---|---|
| Alpha | 0,616 | 0,453 | 0,725 | 0,433 | 0% |
| Heuristics | 0,921 | 1,000 | 0,567 | 0,639 | 37,9% |
| Inductive | 1,000 | 0,548 | 0,781 | 0,667 | 100% |
| Inductive (lọc nhiễu 0,2) | 0,979 | 0,855 | 0,669 | 0,733 | 78,3% |

Không mô hình khai phá nào vừa khớp hết vừa chặt. Alpha không xử lý được vòng lặp và nhiễu; Inductive khớp mọi ca nhưng cho phép quá nhiều đường. Bản Inductive lọc nhiễu là mô tả AS-IS cân bằng nhất.

### 5.2 Token replay trên mô hình chuẩn

| | Tất cả | DONE | Rejected |
|---|---|---|---|
| Ca khớp hoàn toàn | 105/161 (65,2%) | 39/83 (47,0%) | 66/78 (84,6%) |
| Fitness trung bình theo ca | 0,967 | 0,952 | 0,984 |

**Vì sao fitness 0,965 nhưng chỉ 65,2% ca khớp hoàn toàn.**
- Hai chỉ số đo hai thứ khác nhau. Fitness theo token đo **tỉ lệ token được tiêu thụ/sinh ra đúng** trên toàn log. Tỉ lệ ca khớp hoàn toàn đếm **số ca không sai bước nào**.
- Một ca chỉ đi sai một cung (ví dụ `CREATE → To Do` thay vì qua điều tra) thiếu một token và thừa một token, trên tổng khoảng mười mấy token của cả chuỗi. Fitness của ca đó vẫn cao, nhưng ca không còn "khớp hoàn toàn".
- Thực tế, 56 ca không khớp vẫn có fitness trung bình 0,906 (thấp nhất 0,833).
- Vì vậy fitness gần 1 không có nghĩa quy trình được tuân thủ tốt. Câu hỏi 3 được trả lời bằng **tỉ lệ ca khớp hoàn toàn**, còn fitness dùng để so sánh mức lệch giữa các mô hình. Precision của mô hình chuẩn là 0,915. Nếu bỏ cung `To Investigate → Rejected` (chưa từng xảy ra, nhưng được giữ theo quyết định của tác giả) thì precision là 0,991, fitness không đổi.

**Mô hình phụ "luồng nhanh"** (chuẩn + `CREATE → To Do`; **không phải mô hình chuẩn**, là ứng viên TO-BE): 130 ca khớp (80,7%), giải thích thêm 25 ca, chủ yếu ở nhánh DONE.

### 5.3 Lệch ở đâu

| Sai lệch | Số ca | DONE | Rejected | Số lần / trong đợt bù | Ca chỉ lệch trong đợt bù |
|---|---|---|---|---|---|
| `CREATE → To Do` (bỏ điều tra) | 37 | 30 | 7 | 37 / 9 | 9 |
| `To Do → Inbox` | 11 | 6 | 5 | 11 / 10 | 10 |
| Lùi trạng thái | 23 | 16 | 7 | 26 / 20 | 17 |
| Mở lại (rời DONE hoặc Rejected) | 8 | 5 | 3 | 9 / 8 | 7 |

- **Cờ quy tắc** (đếm, không kết luận lỗi): đổi trạng thái trong đợt cập nhật bù 69 ca (42,9%); bỏ pha điều tra 39 ca; lần đổi đầu là Rejected 26 ca; lùi về Inbox 17 ca; vào In Progress không qua To Do 6 ca; mở lại sau DONE 4 ca; Rejected sau khi đã In Progress 2 ca. Không cờ nào bằng 0.
- **Hai cách đếm "bỏ điều tra" và "tạo rồi từ chối":** 22 ca có đúng nguyên biến thể `To Do → In Progress → In Test → DONE`; 37 ca có cung `CREATE → To Do`; cờ đếm 39 ca vì tính mọi ca vào To Do/In Progress/In Test/DONE khi chưa từng điều tra (gồm cả `CREATE → In Progress` và ca đi qua OPEN/Triage). Tương tự, 22 ca chỉ có `CREATE → Rejected`, còn cờ đếm 26 ca có lần đổi đầu là Rejected (4 ca sau đó mở lại).
- Ví dụ issueKey: bỏ điều tra `TI-4751`, `TI-4759`; lùi về Inbox `TI-4748`, `TI-5118`; mở lại `TI-4584`, `TI-5362`.
- 17/23 ca lùi trạng thái và 7/8 ca mở lại **chỉ** lệch trong đợt cập nhật bù, nên nhiều khả năng là sửa thao tác. Ngược lại, `CREATE → To Do` phần lớn nằm ngoài đợt bù (28 ca): đây là quyết định bỏ điều tra thật.

---

## Chương 6 — Học biểu diễn đồ thị và danh sách ca nên xem trước

*Áp dụng Buổi 6: Node2Vec (tái sử dụng embedding của giai đoạn 1, không fit lại). Graph2Vec chỉ được nêu như hướng mở rộng.*

### 6.1 Node2Vec có học được ý nghĩa nghiệp vụ của hoạt động không?

Bài toán: tìm lại nhóm nghiệp vụ của 49 hoạt động (trạng thái, mã nguồn, giao việc, kế hoạch, liên kết, tài liệu, phân loại) từ biểu diễn của chúng.

| Biểu diễn | Accuracy (1-NN, leave-one-out) | Macro-F1 |
|---|---|---|
| Node2Vec (giai đoạn 1) | 0,449 | 0,352 |
| Bậc + độ đo trung tâm | 0,286 | 0,205 |
| Baseline lớp phổ biến | 0,245 | 0,049 |

Node2Vec đặt các hoạt động cùng nhóm nghiệp vụ gần nhau tốt hơn đặc trưng cấu trúc. Tuy vậy, cấu trúc cụm yếu: silhouette tối đa 0,137, NMI tối đa 0,388 với K = 6. Kết quả dương này bổ sung cho kết luận âm của giai đoạn 1: Node2Vec không giúp phát hiện bất thường tốt hơn thống kê chuyển tiếp.

### 6.2 Danh sách ca nên xem trước

Mỗi ca có hồ sơ 7 chiều:
- lệch mô hình chuẩn;
- số cờ quy tắc;
- số lượt trễ định mức;
- lùi/mở lại;
- đổi người phụ trách;
- lần đổi trạng thái bù;
- độ bất ngờ M_markov (đã khử độ dài).

Mỗi chiều được so **trong nhóm cùng nhánh (DONE/Rejected) và cùng độ dài**, rồi xếp hạng theo số chiều vượt phân vị 90.

- **Danh sách đồng thuận: 10 ca nên xem trước** (không phải vi phạm). Đây là các ca nằm trong top 10% ở ít nhất 70% số lần bootstrap mà ca đó được rút, mỗi ca có lý do bằng chữ (notebook 11):
  - lọt top ở 100% số lần: `TI-4584`, `TI-4671`, `TI-4748`, `TI-5260`, `TI-5564`;
  - lọt top ở 87,6%–97,8% số lần: `TI-4872`, `TI-5770`, `TI-6208`, `TI-5261`, `TI-6163`.
- **Giới hạn:** danh sách top 17 đơn lẻ không ổn định. Jaccard giữa top 17 của dữ liệu gốc và của các mẫu bootstrap chỉ là 0,40 [0,21; 0,62]. Ví dụ ca hạng 4 (`TI-5598`) chỉ lọt top ở 65,9% số lần nên không vào danh sách đồng thuận. Vì vậy báo cáo chỉ dùng danh sách đồng thuận làm gợi ý rà soát, không làm thước đo.
- Danh sách không thiên về ca dài: trung vị số sự kiện của top 17 bằng của toàn bộ (19); riêng thành phần "số chiều vượt" có tương quan nhẹ với độ dài (Spearman 0,121), còn điểm tổng gần như không (−0,005). Danh sách không thiên nhiều về Rejected (52,9% so với 48,4% toàn bộ). Việc khử độ dài đưa tương quan của M_markov với độ dài từ 0,507 xuống 0,040.
- Bảng mù gồm 15 ca top và 15 ca ngẫu nhiên đã được chuẩn bị để người hiểu quy trình tự gán nhãn (`e_ranking/blind_review.csv`, khóa để riêng). Hướng dẫn: `docs/HUONG_DAN_RA_SOAT_MU.md`. Lệnh mở khóa và so sánh: `uv run jira-ad blind-review-compare` (Fisher exact, khoảng tin cậy Wilson/Newcombe).

**Hướng mở rộng — Graph2Vec:** biểu diễn cả một ca thành một vector để gom cụm các kiểu xử lý. Chưa làm vì 161 đồ thị nhỏ cho giá trị thấp so với chi phí; hợp lý khi có dữ liệu nhiều team.

---

## Kết luận

1. **Quy trình thực tế** phần lớn theo trình tự Jira, nhưng một phần ba số ca lệch khỏi mô hình chuẩn; ở nhánh DONE, chưa đến một nửa số ca khớp hoàn toàn. Lệch phổ biến nhất là đi thẳng vào To Do mà không điều tra, và lùi trạng thái.
2. **Thời gian** dồn vào `To Investigate` (không tách được chờ và điều tra) và `To Do`, không phải vào lúc sửa (`In Progress`). Dữ liệu không xác định được vai trò nào gây chờ: phép kiểm về PO không được ủng hộ, và phần đuôi ở To Do chủ yếu là các ca backlog cũ bị từ chối.
3. **Đo lường là vấn đề trước tiên.** Jira không tách "chờ điều tra" khỏi "đang điều tra", nên tỉ trọng thời gian làm chỉ đo được thành khoảng rất rộng.
4. **Tái thiết kế đề xuất:** thêm Investigating để đo được công sức điều tra; phân loại sớm ở Inbox (luồng nhanh cho bug rõ ràng, từ chối ngay khi điều tra xong); rà backlog To Do định kỳ; gộp INVESTIGATED; tự chuyển trạng thái theo commit/MR. Mức rút ngắn CT là vừa phải: 17,0 → 15,2 ngày làm việc (giảm 10,7%) theo kịch bản thực tế; cận trên lý tưởng 5,9 ngày không khả thi. Hiệu quả chỉ được khẳng định sau pilot đo bằng cùng định nghĩa.

**Giới hạn.** Một team, 161 bug đã đóng; không có nhãn lỗi thật. Mô hình chuẩn và nhóm nghiệp vụ là giả định của tác giả. PT/WT là xấp xỉ. Số TO-BE là kịch bản ước tính trên dữ liệu cũ. So sánh luồng nhanh với luồng có điều tra là quan sát, không phải quan hệ nhân quả.

---

## Phụ lục A — Phương pháp thống kê và kiểm soát

- Ngưỡng của các phép kiểm chứng BPR và tham số xếp hạng được **khóa trong cấu hình trước khi tính** (Ruling 94, 99). Mô hình TO-BE thiết kế sau phán quyết (Ruling 95).
- Khoảng tin cậy dùng bootstrap: 2000 lần cho chênh trung vị (PO), 200 lần cho độ ổn định top-k.
- Kiểm thử: TDD cho mọi module; kiểm đột biến cho logic tính số (thời gian, định mức, replay, xếp hạng); mỗi bước có ít nhất một con số được tính lại bằng pandas thô không dùng mã của dự án (`docs/PROGRESS.md`, Task 19–23).
- Tất định: chạy lại cùng cấu hình (kể cả với seed băm khác) cho cùng nội dung từng file.

## Phụ lục B — Tái lập

```bash
uv sync --locked --all-extras --group dev
uv run jira-ad process --config configs/process.yaml        # ghi outputs/process/<run>
uv run jira-ad notebooks --run-dir outputs/process/<run>    # notebook 07–12
uv run jira-ad check-report --report docs/BAO_CAO_MON_HOC.md --run-dir outputs/process/<run>
```

## Phụ lục C — Đối chiếu số liệu và rà soát độc lập

Kết quả chạy `check-report` trên báo cáo này được ghi trong notebook `12_summary_report.ipynb` và `docs/PROGRESS.md` (Task 24, Task 25). Một reviewer độc lập đã tính lại các số chính bằng pandas thô (không khớp: không có) và chỉ ra 5 chỗ kết luận mạnh hơn bằng chứng; các chỗ đó đã được sửa trong bản này (định nghĩa đợt bù thống nhất, kịch bản TO-BE khả thi tách khỏi cận trên, số lần đổi trạng thái theo đường TO-BE, bằng chứng tự chuyển trạng thái, diễn giải về PO).
