# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của nhóm: `seeded_regression C-014@11` (FM-05)

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11` (item E-014, T14), run ID `E-seeded_regression-20261117-6985` trong `reports/eval_seeded_regression.json` |
| Triệu chứng | Grader Lab 8 FAIL `proposal_mismatch`; `refund_amount_correct` FAIL; `reply_ledger_match` FAIL. **Ledger ghi 90.000**, nhãn 120.000. Reply nói *"Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."*, tức khách được báo 120.000đ nhưng chỉ nhận 90.000đ. |
| Bước sai đầu tiên | **Event 5 `proposal`** `{"amount_vnd": 120000}`: agent tự trừ 30.000 đã hoàn trước khi gọi `issue_refund`. |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng contract. Event 2 `investigator` đọc đúng O-515 (`delivered_late`, trễ 5 ngày, `damage_verified=true`). Event 3 `quote` 150.000 (`SHIP-LATE-03` + `DMG-04`, lấy max) khớp `proposal_amount` của nhãn. Event 4 `refund_history` `refunded_vnd: 30000` là một lần **đọc** đúng: `honest_refactor` cũng đọc bước này mà không sai. Sai bắt đầu khi agent **dùng** số đó để hạ đề xuất ở event 5. Host áp trần theo đơn lần nữa (120.000 − 30.000 = 90.000), còn reply ở event 6 báo số agent tự tính. |
| Failure mode | **FM-05** pre_deducted (mode chính). Triệu chứng FM-08 (reply ≠ ledger) là hệ quả của cùng bước 5. |
| Đối chứng | `fixed C-014@11`: không có event `refund_history` / `proposal`. Event 3 `quote` 150.000 được truyền thẳng cho host, host tự trừ phần đã hoàn → ledger 120.000. Event 4 `reply` "120.000đ". Lab 8 PASS. |
| Regression test | `tests/test_lab9_trace_case.py` (marker `student`, chạy trong job `eval-gate`): (1) `test_first_wrong_step_is_event_5_proposal`: assert ở mức step, "`proposal` < `quote` ngay sau `refund_history`" chỉ bắt đúng event 5; (2) `test_graders_catch_the_regression`: `RefundAmountCorrect` và `ReplyLedgerMatch` đều FAIL trên variant lỗi; (3) `test_fixed_shape_passes_same_claim_seed`: cả hai PASS trên `fixed`. Đã chạy: 3/3 pass. Item E-014 đã mang `provenance.from_trace = "seeded_regression C-014@11"`. |
| Chưa chắc chắn | Trace không ghi **lý do** agent trừ trước: có thể do prompt, có thể do đọc sai contract `issue_refund`. Với MockLLM thì đó là công tắc `pre_deducted`, còn với LLM thật cần log prompt để biết. Trace cũng không cho biết khách đã thấy reply hay chưa: chỉ biết reply được tạo ra, không biết đã gửi đi. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
