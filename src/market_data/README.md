# market_data

HOSE put the KRX trading system into operation on 2025-05-05
([Vietstock](https://en.vietstock.vn/2025/05/krx-system-officially-goes-live-36-611671.htm)).

## VN30 futures contract codes

Contracts listed under KRX use a nine-character code
([TCBS](https://help.tcbs.com.vn/ufaq/y-nghia-ma-ky-tu-krx/),
[Pinetree](https://pinetree.vn/post/20250505/thay-doi-krx-tac-dong-giao-dich-phai-sinh/),
[FPTS](https://file.fpts.com.vn/FileStore2/File/2025/04/28/21-04-2025_Tai_lieu_huong_dan_quy_uoc_ma_giao_dich_moi_ckps_final.pdf)):

- `4`: derivative; `1`: futures; `I1`: VN30 index
- expiry year: one character from `0123456789ABCDEFGHJKLMNPQRSTVW` (I, O and U are skipped),
  `0` = 2010 through `W` = 2039, repeating every 30 years
- expiry month: `1` to `9`, then `A`, `B`, `C` for October to December
- `000`: futures identifier

Example: `41I1GB000` expires in November 2026. Contracts listed before 2025-05-05 kept their
earlier codes (such as `VN30F2506`) until expiry.

VN30F1M follows the contract that expires in the current month until its expiry day, and the
next month's contract from the following trading day. The expiry day is the third Thursday of
the month, moved back to the previous trading day when that Thursday is not a trading day
([MBS](https://mbs.com.vn/files/uploads/2025/05/1.-Quy-dinh-giao-dich-hdtl-csvn30.pdf)).

## VN30F1M one-minute bar layout

Vendor one-minute payloads can carry a record at the end minute of a continuous
session (11:30 or 14:30 local time): routinely before 2025-05-05, occasionally after.

The catalog holds 241 bars per full trading day (Asia/Ho_Chi_Minh):
- 09:00 to 11:29 and 13:00 to 14:29, continuous trading, labelled at the minute open
- 14:45, the closing auction

A record at 11:30 or 14:30 is folded into the preceding minute's bar: open from the
preceding bar, the higher high, the lower low, close from the boundary record, and
the summed volume. When the preceding minute has no bar, the record moves to that
minute unchanged. Other minutes outside the grid are dropped.
