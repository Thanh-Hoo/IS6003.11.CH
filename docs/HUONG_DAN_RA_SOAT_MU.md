# Hướng dẫn rà soát bảng mù (Chương 6)

Mục đích: kiểm tra xem các ca được xếp "nên xem trước" có thật sự đáng xem hơn các ca chọn ngẫu nhiên hay không. Đây là phép đo duy nhất về giá trị thực của bảng xếp hạng, vì dữ liệu không có nhãn lỗi.

## 1. Chuẩn bị (không sửa file trong `outputs/`)

```bash
mkdir -p reviews
cp outputs/process/20261026T025412Z-399b0a40/e_ranking/blind_review.csv reviews/blind_review_filled.csv
```

Chỉ điền vào bản sao `reviews/blind_review_filled.csv`. File gốc trong run có sha256 trong manifest; nếu sửa, run sẽ không còn qua kiểm fingerprint.

**Để giữ tính "mù", trước khi gán xong nhãn KHÔNG mở các file sau:**
- `blind_review_key.csv`: chứa nhóm top/ngẫu nhiên và hạng của từng dòng;
- `ranking.csv`, `top.csv`, `consensus.csv`, `profile.csv`;
- notebook 11 và 12, mục Chương 6 trong báo cáo.

## 2. Các cột

| Cột | Ý nghĩa | Bạn làm gì |
|---|---|---|
| `review_id` | Mã dòng `R01`…`R30` (đã xáo trộn, không mang thông tin hạng) | Giữ nguyên |
| `case_id` | Mã issue, ví dụ `bug:TI-4671` | Giữ nguyên; có thể mở issue trong Jira để xem thêm |
| `sequence` | `Trạng thái: CREATE > …` và `Hoạt động: …` theo thứ tự thời gian | Đọc để đánh giá |
| `label` | Nhãn | **Điền** một trong ba nhãn bên dưới, viết đúng chính tả |
| `note` | Lý do ngắn | **Điền** 1 câu (khuyến khích) |

## 3. Ba nhãn

| Nhãn | Khi nào dùng | Ví dụ minh họa (không lấy từ bảng) |
|---|---|---|
| `needs_review` | Với hiểu biết về quy trình của team, bạn **muốn xem lại** ca này: có bước bất thường, quay lui khó giải thích, đổi người phụ trách nhiều lần, bỏ qua bước mà loại bug này lẽ ra phải qua, hoặc từ chối sau khi đã tốn nhiều công. | `CREATE > To Do > In Progress > To Do > In Progress > In Test > Inbox > Rejected`: đã sửa và kiểm thử rồi mới đưa về Inbox và từ chối. |
| `plausibly_valid` | Diễn tiến **có lý** với cách team làm việc, dù có thể dài hoặc lạ về hình thức. | `CREATE > To Investigate > INVESTIGATED > Rejected`: điều tra xong rồi từ chối là đường bình thường. |
| `insufficient_evidence` | Chuỗi sự kiện **không đủ** để kết luận (quá ngắn, chủ yếu thao tác của bot, cần nội dung issue mới đánh giá được). | `CREATE > Rejected` với vài lần cập nhật liên kết. |

Một số nguyên tắc:
- **Đánh giá diễn tiến xử lý, không đánh giá người.** Vai trò (PO, Eng, SQA) chỉ là bối cảnh.
- **`Rejected` không tự động là `needs_review`.** Nhiều bug bị từ chối là đúng quy trình.
- Chuyển trạng thái dồn dập trong vài giây (cập nhật bù) thường là thao tác ghi nhận muộn. Chỉ gắn `needs_review` nếu thứ tự sau khi "gộp" lại vẫn đáng ngờ.
- Khi phân vân giữa `needs_review` và `plausibly_valid`, hãy tự hỏi: "Nếu đây là buổi retrospective, tôi có muốn đưa ca này ra bàn không?"

## 4. Sau khi điền xong: mở khóa và so sánh

```bash
uv run jira-ad blind-review-compare \
  --run-dir outputs/process/20261026T025412Z-399b0a40 \
  --labels reviews/blind_review_filled.csv
```

Lệnh trên làm các việc sau:
- kiểm fingerprint của run, rồi đọc khóa `blind_review_key.csv`;
- đếm nhãn trong từng nhóm (top và ngẫu nhiên);
- in tỉ lệ `needs_review` của mỗi nhóm kèm **khoảng tin cậy Wilson 95%**;
- in **hiệu hai tỉ lệ** kèm khoảng Newcombe 95%;
- in **odds ratio** kèm khoảng 95% và **p-value Fisher exact hai phía** cho bảng 2×2 (`needs_review` hay nhãn khác, theo nhóm top hay ngẫu nhiên).

Nếu còn dòng chưa gán nhãn hoặc nhãn viết sai, lệnh dừng và liệt kê các `review_id` cần sửa.

**Cách đọc kết quả:**
- Có 15 ca mỗi nhóm, nên khoảng tin cậy sẽ rộng.
- Bảng xếp hạng có giá trị nếu tỉ lệ `needs_review` ở nhóm top cao hơn nhóm ngẫu nhiên, và khoảng tin cậy của hiệu hai tỉ lệ không chứa 0.
- Nếu khoảng chứa 0, kết luận đúng là "chưa đủ bằng chứng rằng xếp hạng giúp chọn ca đáng xem", và báo cáo nên ghi như vậy.
- Một người rà soát duy nhất là giới hạn; nếu có thể, nhờ thêm một người gán độc lập.
