"""Self-check for the detector (no emulator needed): python check.py"""
import cv2

from gems import gems_in_frame, to_tile

# frame with camera at 385,966; both deposits were confirmed in game at 383,964 and 392,975
found = gems_in_frame(cv2.imread("fixtures/far_two_gems.png"))
tiles = sorted((round(float(x)), round(float(y))) for x, y in (to_tile(385, 966, *p) for p in found))
assert tiles == [(383, 964), (392, 975)], tiles
# one gem among stone, gold, wood and corn icons
assert len(gems_in_frame(cv2.imread("fixtures/far_gem.png"))) == 1
print("ok")

from farm import army_states

assert army_states(cv2.imread("fixtures/queue_marching.png")) == ["marching"] * 5
assert army_states(cv2.imread("fixtures/queue_empty.png")) == []
assert army_states(cv2.imread("fixtures/queue_two_marching.png")) == ["marching"] * 2  # 2/5 on green terrain
assert army_states(cv2.imread("fixtures/far_badges_gem.png")) == ["gathering"] * 3  # far view, 3/5
assert army_states(cv2.imread("fixtures/queue_far_mixed.png")) == ["marching", "gathering", "gathering", "marching", "gathering"]
assert army_states(cv2.imread("fixtures/queue_one_marching.png")) == ["marching"]
assert army_states(cv2.imread("fixtures/queue_none_sunny.png")) == []  # sunlit grass, no queue panel
assert army_states(cv2.imread("fixtures/far_gem.png")) == []  # far view, no queue panel
from farm import queue_count

assert army_states(cv2.imread("fixtures/queue_three_gathering.png")) == ["gathering"] * 3
for name, shift, want in (("queue_one_marching", 0, 1), ("queue_two_marching", 0, 2), ("far_badges_gem", 21, 3),
                          ("queue_three_gathering", 0, 3),
                          ("queue_marching", 0, 5), ("queue_far_mixed", 21, 5)):
    assert queue_count(cv2.imread(f"fixtures/{name}.png"), shift) == want, name
print("ok (queue states)")

from farm import boot_step

assert boot_step(cv2.imread("fixtures/boot_tap_start.png")) == (640, 400)
x, y = boot_step(cv2.imread("fixtures/boot_city.png"))  # the map button, bottom-left
assert abs(x - 60) < 5 and abs(y - 655) < 5, (x, y)
x, y = boot_step(cv2.imread("fixtures/boot_popup.png"))  # download offer: its X, top-right
assert abs(x - 1030) < 5 and abs(y - 137) < 5, (x, y)
assert boot_step(cv2.imread("fixtures/boot_disconnected.png")) == (640, 474)  # reconnect
# "logged in on another device" looks alike but must be left to the player: confirming it
# would throw them out of the game on their phone
assert boot_step(cv2.imread("fixtures/boot_other_device.png")) is None
assert boot_step(cv2.imread("fixtures/boot_map.png")) == "ready"
assert boot_step(cv2.imread("fixtures/far_gem.png")) == "ready"
from farm import is_strategic

assert is_strategic(cv2.imread("fixtures/far_strategic.png")) and not is_strategic(cv2.imread("fixtures/far_wide.png"))
assert not is_strategic(cv2.imread("fixtures/far_gem.png"))
print("ok (start-up screens)")

import bot

import json, os, tempfile
bot.HERE = bot.Path(tempfile.mkdtemp())  # accounts.json and control.json of the test, not the live ones
(bot.HERE / "accounts.json").write_text(json.dumps({"tok": {"index": 7, "view": "v"}}))
bot.open_account = lambda chat, acc: None  # no emulator here
assert bot.handle(1, "/start") == "Gõ /login để đăng nhập."  # nothing works before login
bot.handle(1, "/login")
assert "không đúng" in bot.handle(1, "nope") and 1 not in bot.logged_in
assert "thành công" in bot.handle(1, "tok") and bot.logged_in[1]["index"] == 7
started = []
bot.start_farm = lambda chat, acc, slots: started.append(slots) or "started"
assert "khe" in bot.handle(1, "/start") and "không hợp lệ" in bot.handle(1, "1 7")  # only slots 1-5
bot.handle(1, "/start")
assert bot.handle(1, "1, 3 5") == "started" and started == ["135"]
assert bot.handle(1, "2") != "started" and bot.handle(1, "/stop") == "Hiện không treo."
bot.set_control(7, True); bot.set_control(3, True); bot.set_control(7, True); bot.set_control(3, False)
assert json.loads((bot.HERE / "control.json").read_text()) == [7]
quit_calls = []
bot.subprocess.run = lambda cmd, **k: quit_calls.append(cmd[1:])
assert "đăng xuất" in bot.handle(1, "/logout") and quit_calls == [["quit", "--index", "7"]] and 1 not in bot.logged_in
assert bot.handle(1, "/logout") == "Gõ /login để đăng nhập."
for _ in range(bot.MAX_BAD_TOKENS):
    bot.handle(2, "/login")
    bot.handle(2, "guess")
bot.handle(2, "/login")
assert "quá nhiều" in bot.handle(2, "tok") and 2 not in bot.logged_in  # locked out even with the right token
print("ok (bot login flow)")

import rok

for name in ("370_965", "5_1190", "1100_1150", "584_1163"):  # 6, 5, 8 and 7 digits: four font sizes
    want = tuple(map(int, name.split("_")))
    assert rok.camera_coords(cv2.imread(f"fixtures/coords_{name}.png")) == want, name
print("ok (coordinate readout)")

import numpy as np
from farm import slot_button_y, slot_loaded

lit, dark = cv2.imread("fixtures/new_army_slot1.png"), cv2.imread("fixtures/new_army_no_slot.png")
assert slot_button_y(lit) == 233 and slot_button_y(dark) == 233
assert slot_loaded(lit, 1, 233) and not slot_loaded(lit, 2, 233) and not any(slot_loaded(dark, s, 233) for s in (1, 2, 3, 4))
shifted = np.roll(lit, 54, axis=0)  # an account with one more icon button above the numbers
assert slot_button_y(shifted) == 287 and slot_loaded(shifted, 1, 287) and not slot_loaded(shifted, 2, 287)
print("ok (saved army slots)")
