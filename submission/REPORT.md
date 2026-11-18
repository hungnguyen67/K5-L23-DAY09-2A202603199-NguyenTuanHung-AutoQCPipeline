# Báo cáo Day 09 — Nguyễn Tuấn Hưng,

## 1. Kết luận trước

Pipeline kết luận **Hold**. Intake nhận 202/224 ảnh và loại 22 ảnh (2 hỏng, 3 quá nhỏ, 8 trùng byte, 5 rò rỉ test/val, 4 trùng gần); manifest của bản nháp có 202 ảnh. Sau mô phỏng duyệt 80 ảnh, còn cảnh báo trên 62/202 ảnh = 30,7%, vượt ngưỡng Hold 10%; không còn lỗi bắt buộc ở lần chạy thường.

## 2. Lỗi và phân việc

Lấy từ `02_error_list_v1` (gom theo mã lỗi). Cột "ai sửa": **máy** (autofix) hay **người** (hàng đợi); chỉ ghi những mã có mặt trong lô của bạn.

| Mã lỗi                 |           Số ảnh/dòng | Ai sửa (máy/người) | Vì sao                                         |
| ---------------------- | --------------------: | ------------------ | ---------------------------------------------- |
| `BAD_CLASS_ID`         |                6 dòng | Máy                | ID lớp ngoài danh sách; xoá dòng.              |
| `BAD_CLASS_NAME`       |       1 ảnh (2 issue) | Máy                | Chuẩn hoá tên lớp trong `data.yaml`.           |
| `BAD_FORMAT`           |                3 dòng | Máy                | Sai định dạng YOLO; xoá dòng.                  |
| `BAD_SIZE`             |                 3 ảnh | Máy                | Ảnh dưới kích thước intake cho phép; loại ảnh. |
| `BOX_HUGE`             |                 3 ảnh | Người              | Xác minh box lớn có bao đúng vật thể không.    |
| `BOX_OUT_OF_IMAGE`     |                8 dòng | Máy                | Box tràn ảnh; clip vào biên.                   |
| `BOX_TINY`             |         4 ảnh (6 box) | Người              | Phân biệt vật thể nhỏ thật với nhãn lỗi.       |
| `BOX_ZERO`             |                4 dòng | Máy                | Box có chiều rộng/cao bằng 0; xoá dòng.        |
| `CLASS_RARE`           |            4 cảnh báo | Người              | Đánh giá lớp hiếm theo phân bố dữ liệu.        |
| `CORRUPT_IMAGE`        |                 2 ảnh | Máy                | Ảnh hỏng; loại ảnh.                            |
| `DUP_BOX`              |                7 dòng | Máy                | Box cùng lớp bị lặp; xoá dòng sau.             |
| `DUP_IMAGE_EXACT`      |                 8 ảnh | Máy                | Trùng byte; loại ảnh trùng.                    |
| `DUP_IMAGE_NEAR`       |                 4 ảnh | Máy                | Trùng gần theo pHash; loại ảnh trùng.          |
| `EMPTY_LABEL`          |                12 ảnh | Người              | Xác minh là ảnh nền hay bị thiếu nhãn.         |
| `LEAK_TEST`            |                 5 ảnh | Máy                | Trùng kho test/val; loại khỏi intake.          |
| `MISSING_LABEL_FILE`   |                 6 ảnh | Người              | Cần gán nhãn; máy không được bịa nhãn.         |
| `POSSIBLE_FALSE_POS`   |       27 ảnh (29 box) | Người              | Xác minh box nhãn có vật thể thật không.       |
| `POSSIBLE_LOOSE_BOX`   |  45 ảnh (58 cảnh báo) | Người              | Xem box có bị lỏng/lệch không.                 |
| `POSSIBLE_MISSING`     | 97 ảnh (267 cảnh báo) | Người              | Tìm vật thể chưa được gán nhãn.                |
| `POSSIBLE_WRONG_CLASS` |  21 ảnh (22 cảnh báo) | Người              | Xác minh lớp theo ngữ nghĩa ảnh.               |

`05_review_queue.csv` cộng trọng số cảnh báo theo ảnh (cảnh báo có confidence cao và các loại như thiếu nhãn/nhầm lớp được ưu tiên), rồi sắp xếp priority giảm dần. Ví dụ `img_0160` đứng đầu với 109.727 do `POSSIBLE_MISSING;POSSIBLE_WRONG_CLASS`. Ngân sách mô phỏng xem 80/147 ảnh; 74/80 ảnh đầu có ít nhất một cờ ngữ nghĩa. Các cờ theo ảnh chồng lấn: MISSING 64, LOOSE 25, WRONG_CLASS 20, FALSE_POS 13.

## 3. Calibration (2 ngưỡng)

| Tham số                 | Khởi đầu | Đã chọn | Precision / Recall (trước → sau)                                                                                               | Lý do (đánh đổi)                                                                                                                                                                    |
| ----------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `duplicates.phash_dist` | 2        | 12      | EXACT 1.00/1.00 → 1.00/1.00; NEAR 1.00/0.50 → 1.00/0.67                                                                        | Chọn 12: tăng recall near-duplicate trên calib nhưng giữ ngưỡng thấp hơn vùng raw bắt đầu tăng nhiều cặp đáng ngờ. Đây là check tự loại ảnh nên ưu tiên precision.                  |
| `second_opinion.conf`   | 0.25     | 0.1     | WRONG_CLASS 0.56/0.83 → 0.56/0.83; MISSING 0.50/1.00 → 0.40/1.00; LOOSE 0.29/0.40 → 0.38/0.60; FALSE_POS 0.31/1.00 → 0.31/1.00 | Chọn 0.1 để giữ recall cảnh báo cao nhất; chấp nhận precision MISSING thấp hơn vì cảnh báo sẽ do người xem, không tự sửa nhãn. Không tăng ngưỡng chỉ để làm hàng đợi vừa ngân sách. |

Điểm có thể đánh lừa: trên calib, `phash_dist=16` tăng recall DUP_IMAGE_NEAR lên 0.83 (từ 0.67 ở 12), nhưng raw cho 17 cờ ở ngưỡng 12 và 26 ở 16. Đã mở xem ba cặp mới ở khoảng cách 16: `img_0011`–`img_0008` (quần vợt và trượt tuyết) và `img_0177`–`img_0113` (lướt sóng và chân dung) là ảnh khác hẳn; `img_0084`–`img_0074` trông là cùng cảnh/ảnh gần trùng. Hai báo động giả trong ba cặp cho thấy ngưỡng 16 quá dễ gộp ảnh khác, nên giữ 12 dù sẽ bỏ sót một số cặp khoảng cách cao. Ở ngưỡng 12, intake loại 22/224 ảnh: 8 trùng byte, 5 rò rỉ test/val, 4 trùng gần, 2 hỏng và 3 quá nhỏ. Với `conf=0.1`, hàng đợi là 147 ảnh, vượt ngân sách duyệt 80; không nâng conf chỉ để ép hàng đợi nhỏ lại vì sẽ bỏ sót cảnh báo.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

Gate proof: chạy `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb` cho kết luận **Rework**, mã thoát 20; `work/rep_nb/07_error_list_v3.csv` còn 6 `MISSING_LABEL_FILE` (`img_0031`, `img_0053`, `img_0126`, `img_0135`, `img_0170`, `img_0219`), `06_review_log.csv` rỗng và `work/exp_nb` không tồn tại. Không có người gán nhãn thì autofix không thể tự tạo nhãn.

Điểm mù có bằng chứng: (1) pHash có thể gộp nhầm ảnh khác cảnh: cặp raw `img_0011`–`img_0008` cách 16 trông lần lượt là quần vợt và trượt tuyết; cặp `img_0177`–`img_0113` là lướt sóng và chân dung. Vì vậy tăng ngưỡng để bắt thêm ảnh trùng có thể tự loại ảnh tốt. (2) Ý kiến model không xác nhận được ngữ nghĩa trong cảnh đông: `img_0160` là bãi xe dày đặc, được xếp đầu hàng đợi (priority 109.727, `POSSIBLE_MISSING;POSSIBLE_WRONG_CLASS`); `img_0084` là đám đông người với nhiều box chồng lấn (`POSSIBLE_MISSING`). Các cảnh này cần người phân biệt vật thể/box lân cận; cảnh báo model không phải đáp án đúng-sai.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)

**Chưa chạy**; phần train Colab là tùy chọn và chưa có kết quả trong `submission/results/`, nên chưa thể so sánh mAP raw/clean hoặc kết luận về độ lệch giữa các seed.

## 6. Quyết định và ghi chú AI

**Quyết định: Hold.** Mình chưa phát hành bộ clean vì còn 62/202 ảnh có cảnh báo. Cần kiểm tra, xử lý thêm để số ảnh còn cảnh báo không quá 20 (dưới 10%), rồi chạy pipeline lại. Không nên hạ ngưỡng chỉ để lấy kết quả Release.

**Ghi chú AI**

- Cách dùng: mình dùng AI để hỗ trợ đọc yêu cầu, docstring và test, giải thích hướng xử lý và hoàn thiện các module; các thay đổi được đối chiếu với yêu cầu của bài trước khi giữ lại.
- Kiểm tra: đối chiếu với 79 test; chạy pipeline thường và `--budget 0`; kiểm tra báo cáo, ngưỡng calibration và mở xem ảnh/cặp ảnh. Kết luận Hold dựa trên số liệu pipeline.
- Một lần AI sai: ban đầu chỉ cài lại Pillow; import Pillow đã hết lỗi nhưng pytest vẫn lỗi vì NumPy trong Python 3.15 còn binary cho 3.12. Sau đó xác minh interpreter và kiểm thử bằng Python 3.12.

_(Thưởng +2, tùy chọn)_ CVAT: lọc `width < 20`, ảnh/số box khớp, đối chiếu `BOX_TINY` (xem docs/CVAT_FILTER.md), 1 câu về `can_review`.
