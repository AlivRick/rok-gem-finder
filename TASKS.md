# TASKS

Cập nhật: 2026-10-10 14:45 (dựng lại từ farm.log + code, file này trước đó không tồn tại)

## Đang dở
- [ ] Bot người chơi @farm_ROK_bot (`bot.py`): ĐANG CHẠY trong tmux `rokbot` (log `bot.log`, farm ghi `farm<index>.log`). Chạy lại: `tmux new -d -s rokbot "exec .venv/bin/python bot.py >> bot.log 2>&1"`.
  - Mô hình chủ chốt 15:36: mỗi người dùng 1 tab LDPlayer riêng + tài khoản ROK của chính họ. `bot.py add` tạo tab sạch (KHÔNG copy index 0: có Google của chủ), cài ROK từ `apk/`, sinh token vào `accounts.json`.
  - Luồng: /login -> token -> mở tab + link monitor (trang bấm/gõ được: `view.py` POST tap/text/key, chỉ khi index nằm trong `control.json`; bot bật sau /login, tắt khi /start, bật lại khi /stop, tắt khi /logout) -> người dùng tự đăng nhập ROK -> /start -> hỏi khe 1-5 -> `farm.py <khe>` -> /stop, /logout (đóng tab).
  - Đã có: index 0 (tài khoản của chủ, 5 khe test) và index 1 (sạch, token đã gửi chủ 15:50).
  - CHƯA THỬ THẬT: luồng đầy đủ qua Telegram + Internet trên tab mới; lần đầu mở ROK (tải dữ liệu, hướng dẫn tài khoản khách) farm không tự xử lý; farm chỉ khớp giao diện tiếng Việt 1280x720; cả 5 đạo cùng ra.
  - Máy 19 GB RAM: tab mới 4 nhân/4 GB, index 0 6 GB -> khoảng 3 tab cùng lúc.
  - Mỏ phía đông thành index 0 (X > 400) bị đèo cấp 1 của 306C ở (347, 1030) chặn -> "blocked".
- [ ] Người dùng đầu tiên (tab index 1, vương quốc #S11476): 3 lần /start lúc 16:20 chết ở `city_coords` ("unknown digit") vì dòng toạ độ dài hơn -> chữ số hẹp hơn mẫu. 16:35 đã sửa `rok.camera_coords` (4 cỡ chữ + kéo giãn ngang, không bao giờ đoán bừa) và `farm.slot_button_y` (tài khoản này có thêm 1 nút phía trên cột số khe). CHƯA xác nhận trên màn hình thật của họ: nếu lại hỏng, xem `fail_coords1.png` rồi thêm một hàng mẫu vào `digits.png`. Lúc 16:25 giả lập của họ đang bị đá ra vì họ mở game trên điện thoại; tài khoản đang 5/5 đạo ở ngoài.
- [ ] 2026-10-11 sáng: xem log index 1 hôm qua -> farm chết 2 lần vì đếm sai hàng chờ (đọc cỏ nắng thành huy hiệu "đang về") rồi để hộp chọn quân mở. Đã sửa: `army_states` chỉ đọc khi có bảng hàng chờ (nút cyan) và tin bộ đếm "N/5" (`queue_count`, mẫu trong `queue_count.png`; CHƯA có mẫu số 4 -> khi có 4 đạo ở ngoài thì cắt thêm vào ô thứ 4); hết hàng chờ trả về "full" thay vì lỗi; mỗi lần recover lưu `fail<index>_<n>.png`; `boot_step` tự bấm XÁC NHẬN khi "Đã ngắt kết nối mạng" (không bấm hộp "đăng nhập trên thiết bị khác").
- [ ] Quét mỏ: đổi từ gõ toạ độ (8,3 s/khung) sang kéo bản đồ + đọc toạ độ (`farm.sweep`, ~2,3 s/khung). Thử thật index 0: 10 phút xuất 3 đạo (hôm qua 9 phút 1 đạo). Chưa thử trên tài khoản người dùng. Tap/swipe có lệch ngẫu nhiên nhỏ (`rok.tap`, `rok.swipe`). Không tìm thấy bot mã nguồn mở nào dò gem để tham khảo.
- 2026-10-11 08:10: thêm (a) `rok.stop_when_safe`: SIGTERM chờ lệnh adb đang chạy xong - dừng giữa lúc kéo bản đồ làm game kẹt (zoom của giả lập chỉ còn bấm vào bản đồ) cho tới khi restart game; (b) farm tự `am force-stop` + mở lại game ở lần recover thứ 3; (c) đứng yên khi mọi đạo bận và có >= 3 mỏ chờ; (d) bỏ qua mỏ gần chỗ "blocked" hơn chỗ "marched" (`behind_a_pass`); (e) `city_coords` chờ thật sự vào thành. (c)(d) CHƯA chạy thật.
- Zoom: KHÔNG làm được nấc xa thứ 2 ổn định. `ldconsole zoomOut` thất thường (có lúc không đổi, có lúc nhảy sang bản đồ chiến lược `is_strategic`); nấc xa đầu tiên đo được 1,17-1,87. Đo zoom bằng kéo bản đồ và bằng cỡ biểu tượng đều không dùng được. Đừng thử lại trừ khi có cách zoom mịn hơn. Phóng to hết cỡ ngay trên thành sẽ chui vào thành.
- Chạy 20 phút index 0 (07:29-07:49): 10 mỏ, 3 marched, 6 blocked (đèo phía đông), 1 no_gem, 0 recover.
- [ ] Game lag (vòng xoay tải) làm các kiểm tra UI thất bại; 15:25 farm tự hồi phục, 13:16 thì chết sau 5 lần. Chưa xử lý riêng (ví dụ chờ lâu hơn khi thấy vòng xoay).

## Xong
- boot_step / open_game (tự vào game từ màn hình khởi động), check.py qua cả 3 nhóm.

- Tự tìm toạ độ thành (15:10): `rok.camera_coords()` đọc thanh "X: Y:" bằng mẫu chữ số trong `digits.png` (4 cỡ chữ, 5-8 chữ số), `farm.city_coords()` vào thành rồi ra bản đồ để lấy toạ độ; `farm.py TROOPS` quét ô vuông bán kính 60 quanh thành. Đã thử thật: ra đúng (370, 965). Pop-up "Tải xuống nội dung thêm" khi vào thành được đóng bằng X.

- Khe lưu đạo quân (15:30): trên màn hình "Quân mới", cột nút số bên phải (1104, 233 + 54*(n-1)) = NẠP khe n; nút sáng lên khi nạp được, tướng bận thì game từ chối. Mũi tên xanh = bảng LƯU (bấm ô trống là lưu, bấm ô có sẵn là ghi đè), bánh răng = xoá. `farm.send_new_army` thử lần lượt các khe.

## Ghi chú
- Khi chạy farm, ghi lại lệnh đầy đủ vào đây.
