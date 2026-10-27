# Câu hỏi hội đồng có thể đặt ra và gợi ý trả lời

Mỗi câu gồm gợi ý trả lời ngắn và con số dẫn chứng. Số liệu lấy từ báo cáo nộp (`docs/BAO_CAO_MON_HOC_nop.md`). Riêng câu 12 dẫn số của phần phát hiện bất thường trước đó (`docs/BAO_CAO_TONG_KET.md`).

## A. Dữ liệu và giả định

**1. Dữ liệu có đáng tin để rút kết luận cho doanh nghiệp không?**
Dữ liệu là log thật của một team: 161 bug đã đóng, 5.126 sự kiện. Đây là nghiên cứu hồi cứu trên một team, nên kết luận chỉ áp dụng cho team đó. Hai điểm cần dè dặt:
- 43,5% sự kiện do bot tạo, và khoảng 30% lần đổi trạng thái là cập nhật dồn.
- Dữ liệu chỉ có ca đã đóng. Vì vậy số ca đến nửa sau kỳ (52) thấp hơn hẳn nửa đầu (109), một dấu hiệu thiên lệch sống sót.

**2. PT và WT được định nghĩa thế nào, vì sao báo cáo thành khoảng?**
Jira chỉ ghi thời điểm đổi trạng thái, không ghi lúc bắt đầu hay kết thúc từng việc.
- PT = thời gian nằm ở các trạng thái được xếp là "làm" (In Progress, In Test). WT = CT − PT.
- Kết quả phụ thuộc vào việc To Investigate là chờ hay làm: PT chiếm 16,7% CT nếu To Investigate là chờ, 57,0% nếu là làm.
- Thêm biến thể cận trên do cập nhật dồn thì khoảng là 16,7%–59,2%.
- Báo khoảng là cách trung thực; một con số duy nhất sẽ che giả định.

**3. Giả định "tạo issue = vào Inbox" (giả định A1) có hợp lý không?**
Jira không ghi trạng thái khởi tạo như một sự kiện riêng. Nếu bắt buộc phải có sự kiện Inbox tường minh thì gần như mọi ca lệch ngay từ bước đầu, và kiểm định mất ý nghĩa. Giả định này được trình bày và chốt trước khi chạy kiểm định tuân thủ.

**4. Vì sao dùng ngày làm việc, và vì sao theo giờ địa phương?**
Thời gian chờ qua cuối tuần không phản ánh hiệu năng của team. CT trung vị là 17,0 ngày làm việc so với 23,0 ngày lịch. Ngày làm việc được xác định theo múi giờ ghi trong chính dữ liệu, không đoán múi giờ, nên không bị lệch ranh giới ngày.

**5. Cập nhật dồn là gì, ảnh hưởng tới kết quả ra sao?**
Cập nhật dồn là các lần đổi trạng thái cách nhau dưới 60 giây, tức người dùng ghi nhận muộn rồi bấm chuyển liền nhiều bước.
- Chiếm 29,8% số lần đổi trạng thái.
- FPY nghiêm ngặt là 0,814, nhưng nếu bỏ các lần lùi nằm trong đợt cập nhật dồn thì FPY là 0,957: chỉ 7/30 ca có lần lùi thật.
- 17/23 ca lùi trạng thái chỉ lùi trong các đợt này, nhiều khả năng là sửa thao tác.

## B. Định lượng và định mức

**6. Định luật Little cho kết quả gì?**
λ = 0,413 ca/ngày, W = 45,6 ngày, L = 18,8 ca. Với log chỉ gồm ca đã đóng, L = λ·W đúng theo định nghĩa (đồng nhất thức), nên không dùng để "kiểm chứng" Little. Thông tin có ích nằm ở sự thay đổi theo thời gian: số ca đến giảm từ 109 xuống 52 giữa hai nửa kỳ.

**7. Vì sao định mức là phân vị 75, và vì sao không xếp hạng theo tỉ lệ trễ?**
Công ty không có SLA, nên phân vị 0,75 của lịch sử là mốc nội suy hợp lý và thay được bằng SLA thật trong cấu hình. Theo cách xây dựng, khoảng 25% lượt của mọi trạng thái đều "trễ", nên tỉ lệ trễ không phân biệt được các trạng thái. Báo cáo xếp hạng theo số ngày vượt định mức: To Do 1.159,3 ngày (48%), To Investigate 510,6 ngày (21%).

**8. Vai trò nào là điểm nghẽn?**
Dữ liệu không xác định được.
- Giả thuyết "chờ ở To Do gắn với PO" không được ủng hộ: khoảng tin cậy 95% của chênh lệch trung vị chứa 0.
- 60,5% số ngày vượt định mức ở To Do thuộc các lượt PO chuyển ra, nhưng 75,3% phần này (527,9 ngày) đến từ đúng 4 ca backlog cũ bị từ chối.
- Vai trò chuyển ca ra chỉ là người ghi nhận, không phải nguyên nhân.

## C. Khai phá quy trình và kiểm định tuân thủ

**9. Fitness 0,965 mà chỉ 65,2% ca khớp hoàn toàn, có mâu thuẫn không?**
Không mâu thuẫn, vì hai chỉ số đo hai thứ khác nhau.
- Fitness đo tỉ lệ token đúng trên toàn log. Một ca sai một cung chỉ thiếu một token và thừa một token trên khoảng mười mấy token.
- 56 ca không khớp vẫn có fitness trung bình 0,906 (thấp nhất 0,833).
- Câu hỏi "bao nhiêu ca lệch" phải trả lời bằng tỉ lệ ca khớp hoàn toàn: 105/161; ở nhánh DONE chỉ 39/83.

**10. Vì sao Alpha Miner cho kết quả kém, và nên tin mô hình khai phá nào?**
Alpha không xử lý được vòng lặp và nhiễu: fitness 0,616, không ca nào khớp. Inductive khớp mọi ca (fitness 1,000) nhưng precision chỉ 0,548, tức cho phép quá nhiều đường. Bản Inductive lọc nhiễu 0,2 cân bằng nhất: fitness 0,979, precision 0,855.

**11. Vì sao giữ cung To Investigate → Rejected dù chưa từng xảy ra?**
Đây là đường đi hợp lệ về nghiệp vụ: điều tra xong có thể từ chối ngay. Giữ cung này làm precision giảm từ 0,991 xuống 0,915, còn fitness không đổi. Chấp nhận precision thấp hơn để mô hình chuẩn đúng nghiệp vụ hơn.

## D. Học biểu diễn

**12. Vì sao Node2Vec không hơn thống kê chuyển tiếp trong phát hiện bất thường?**
- Trong phần phát hiện bất thường (`docs/BAO_CAO_TONG_KET.md`), mô hình xác suất chuyển tiếp đơn giản đạt macro AUROC cao hơn mô hình Node2Vec + Isolation Forest khi kiểm định chéo.
- Lý do: Node2Vec học vector từ chính đồ thị chuyển tiếp nên không có thêm thông tin, còn việc lấy trung bình vector làm mất thứ tự các bước.
- Đồ án này dùng Node2Vec vào một bài toán khác và cho kết quả dương: tìm lại nhóm nghiệp vụ của hoạt động, accuracy 0,449 so với 0,286 của đặc trưng cấu trúc và 0,245 của baseline.

**13. Jaccard 0,40 có làm danh sách xếp hạng vô dụng không?**
Danh sách 17 ca đứng đầu thay đổi đáng kể khi lấy mẫu lại (Jaccard 0,40 [0,21; 0,62]). Vì vậy báo cáo chỉ dùng **danh sách đồng thuận**: 10 ca lọt nhóm đầu ở ít nhất 70% số lần bootstrap, trong đó 5 ca lọt ở 100% số lần. Danh sách là gợi ý rà soát, không phải thước đo, và đang được kiểm chứng bằng bảng mù.

**14. Xếp hạng có thiên vị ca dài hay ca bị từ chối không?**
Không đáng kể.
- Trung vị số sự kiện của nhóm đầu bằng của toàn bộ (19).
- Điểm tổng gần như không tương quan với độ dài (Spearman −0,005); riêng thành phần số chiều vượt có tương quan nhẹ (0,121).
- Tỉ lệ Rejected ở nhóm đầu là 52,9% so với 48,4% trên toàn bộ.

## E. Tái thiết kế

**15. Vì sao TO-BE chỉ giảm CT 10,7%?**
- 47/78 ca Rejected chỉ bị loại sau khi đã điều tra, nên phần lớn thời gian của chúng là cần thiết.
- Kịch bản thực tế (từ chối ngay khi điều tra xong, chờ To Do không quá định mức) chỉ giảm CT trung vị từ 17,0 xuống 15,2 ngày. Cận trên lý tưởng 5,9 ngày đòi hỏi quyết định từ chối ngay từ đầu, điều không khả thi.
- Giá trị chính của TO-BE nằm ở đo lường (thêm Investigating), phân loại sớm và rà backlog, không nằm ở rút ngắn CT.

**16. TO-BE làm tăng số lần đổi trạng thái (4,4 → 5,4), vậy có phải là tệ hơn không?**
Không. Các bước thêm (Investigating, Inbox tường minh) có mục đích làm việc điều tra và phân loại đo được. Hiện nay không phân biệt được chờ điều tra với đang điều tra. Một bước thêm giúp quản lý biết thời gian đi đâu là có ích.

**17. Luồng nhanh (bỏ điều tra) có chứng minh được là tốt hơn không?**
Chưa chứng minh được. Ca DONE bỏ điều tra có CT 11,2 ngày so với 35,9 ngày, FPY tương đương (0,75 so với 0,76). Nhưng đây là quan sát, không phải quan hệ nhân quả: bug được sửa thẳng có thể vốn đơn giản hơn, và chênh lệch một phần do bỏ luôn thời gian ở To Investigate. Vì vậy đề xuất được đưa vào kế hoạch thí điểm thay vì áp dụng ngay.

**18. Tự động chuyển trạng thái theo commit có đáng làm không?**
- 39/58 ca có commit hoặc merge request trước khi chuyển In Progress, tức trạng thái Jira cập nhật muộn so với công việc thật.
- Tuy vậy, quy tắc To Do → In Progress chỉ áp dụng cho 12 ca. Phần lớn liên kết đầu tiên rơi vào To Investigate (22 ca), nên lợi ích đo lường nhỏ (tỉ trọng PT 16,7% → 16,9%).
- Phát hiện này lại củng cố đề xuất thêm trạng thái Investigating.

## F. Phương pháp

**19. Làm sao bảo đảm các con số trong báo cáo đúng?**
- Mọi con số sinh từ mã chạy lại được, kết quả tất định.
- Một công cụ tự động đối chiếu từng con số trong báo cáo với tệp kết quả, và không có số nào chưa khớp.
- Mỗi bước phân tích có ít nhất một số được tính lại độc lập từ dữ liệu thô. Toàn bộ số chính đã được kiểm tra lại độc lập một lần.
- Ngưỡng kết luận được cố định trước khi xem kết quả.

**20. Hạn chế lớn nhất của đồ án là gì, và bước tiếp theo?**
- Hạn chế: không có nhãn lỗi thật, chỉ một team, và mô hình chuẩn là giả định của tác giả.
- Bước tiếp theo có giá trị nhất:
  1. hoàn tất rà soát bảng mù (15 ca đứng đầu so với 15 ca ngẫu nhiên, kiểm định Fisher);
  2. thí điểm TO-BE trong 10 tuần, đo lại bằng cùng định nghĩa;
  3. thêm trạng thái Investigating để đo được công sức điều tra.
