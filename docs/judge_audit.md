# Judge audit

Chạy (trong `src/`): `python -m lab9.judge --csv <file> --audit 5`. Backend replay: verdict của judge lưu sẵn trong CSV, không gọi API. Lớp dương là **FAIL** (việc của judge là tìm lỗi).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, nhưng chỉ làm metric không chặn (non-blocking) cho văn phong |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt**: κ và R dưới sàn (exit 1) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn (FAIL = dương):

| | tp | fp | fn | tn | Specificity | Tỉ lệ FAIL quan sát → hiệu chỉnh Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.943 | 0.28 → **0.30** |
| helpful | 9 | 0 | 21 | 70 | 1.000 | 0.09 → **0.30** |

Đọc kết quả: judge helpful **không bao giờ báo nhầm** (P = 1.0) nhưng **bỏ sót 21/30 lỗi thật** (R = 0.3). Nếu đếm thẳng theo judge, tỉ lệ reply không hữu ích chỉ là 9%; sau hiệu chỉnh Rogan-Gladen con số thật là khoảng 30%, gấp hơn 3 lần.

## ≥5 case audit thủ công

### tone_ok: đủ cả 10 bất đồng

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Judge coi suồng sã là "thân thiện". Rubric thêm: *xưng "LogiX", gọi khách "anh/chị"; "em/bạn/nha/nhé" ⇒ FAIL*, kèm ví dụ few-shot FAIL. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ … rồi nha." | PASS | FAIL | **Người** | Cùng gốc với #1 (xưng hô). Quy tắc xưng hô ở #1 xử lý được case này. |
| 3 | H-029 "Dạ, vui lòng chờ. … không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ bắt từ khóa lịch sự ("Dạ, vui lòng"). Rubric thêm: *câu mệnh lệnh / chặn khách liên hệ ⇒ FAIL dù có kính ngữ.* |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric bỏ yêu cầu bắt buộc xin lỗi: *ngắn, đủ ý, có kính ngữ ⇒ PASS.* |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ …" | FAIL | PASS | **Người** | Thuật ngữ "refund" nằm trong danh sách được phép của CS LogiX. Rubric thêm *danh sách thuật ngữ tiếng Anh được phép* (refund, ship, voucher). |
| 6 | H-063 "… đã hoàn 20.000đ và sẽ hoàn thêm …" | PASS | FAIL | **Người** | Hứa ngoài kết quả hệ thống là lỗi **nội dung**, không phải giọng văn. Không giao cho judge: chuyển sang grader code `reply_ledger_match` (FM-08). Rubric tone ghi rõ: *không chấm cam kết tiền.* |
| 7 | H-070 "… cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Rubric thêm: *emoji trong ngữ cảnh khiếu nại / hoàn tiền ⇒ FAIL.* |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Người gán nhãn đọc nhầm ticket. **Sửa nhãn người → FAIL** ở phiên bản CSV kế tiếp (không sửa file public đang dùng làm tham chiếu). Sau khi sửa: tp=25, fp=3, P=0.893, R=0.806, κ=0.784. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ …" | FAIL | PASS | **Người** | Lặp từ do lỗi gõ không làm sai giọng văn. Rubric thêm: *lỗi gõ nhỏ không đổi nghĩa ⇒ không FAIL tone*, kèm ví dụ PASS. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341 …" | PASS | FAIL | **Người** | Mất dấu tiếng Việt (văn bản máy dịch). Rubric thêm: *tiếng Việt không dấu ⇒ FAIL.* |

### helpful: 21 bất đồng, gom theo nguyên nhân

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 11 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge **không thấy ledger**, nên không thể biết số tiền sai. Đây chính là FM-08. Có **18/21** bất đồng thuộc dạng này (HL-015, 016, 020, 028, 035, 041, 043, 053, 058, 062, 070, 072, 074, 087, 090, 096, 098, 100). Chuyển việc này cho grader code `reply_ledger_match`, không sửa rubric judge. |
| 12 | HL-016 / HL-028 / HL-090: hai câu xin lỗi dài bọc quanh một số tiền sai | PASS | FAIL | **Người** | **Verbosity bias**: lời xin lỗi dài kéo judge về PASS. Rubric: *chấm "có trả lời đúng câu hỏi không" trước, giọng văn không cộng điểm*. Thêm ví dụ few-shot FAIL dạng "xin lỗi dài + số sai". |
| 13 | HL-047 / HL-091 / HL-097 "Ok bạn, đơn O-xxx xử lý rồi nhé." | PASS | FAIL | **Người** | Không nói kết quả (hoàn hay từ chối, bao nhiêu tiền). Rubric thêm: *reply phải nêu trạng thái và số tiền (nếu có), thiếu ⇒ FAIL.* |

## Kết luận

- **helpful bị loại khỏi gate.** Theo ma trận nhầm lẫn, judge bắt được 9/30 lỗi (R = 0.30) và κ = 0.375. Nếu dùng nó làm gate, 70% reply không hữu ích sẽ được merge. Precision 1.0 không cứu được: một judge "ít khi nói FAIL" luôn có precision cao. Nguyên nhân chính (18/21 case) là reply nói số tiền khác ledger, mà judge chỉ đọc chữ, không đọc ledger. Theo quy tắc "tiền luôn chấm bằng code", lỗi này thuộc metric code `reply_ledger_match` (FM-08, M3).
- **tone_ok dùng được, chỉ làm metric không chặn.** Judge đạt cả ba sàn. Sau khi sửa nhãn H-081, κ = 0.784. Các bất đồng còn lại có pattern rõ (xưng hô, emoji, mất dấu, mệnh lệnh), xử lý được bằng rubric và few-shot ở trên. Tỉ lệ FAIL báo cáo phải là số đã hiệu chỉnh Rogan-Gladen (0.30), không phải số quan sát (0.28).
- **Rủi ro còn lại:**
  - Judge chỉ được kiểm trên 100 dòng replay đã công khai, do cùng nhóm người gán nhãn. Cần một bộ nhãn người mới (held-out) để chắc κ không bị overfit theo rubric vừa sửa.
  - Khoảng tin cậy của κ với n = 100 còn rộng.
  - Judge replay không đo được độ trôi khi đổi model hoặc prompt: mỗi lần đổi phải chạy calibrate lại.
