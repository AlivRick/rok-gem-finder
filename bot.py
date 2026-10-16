"""Telegram bot for players: /login (asks for the account token), /start and /stop the gem farm, /logout.

usage: bot.py       run the bot (bot token in .bot_token; must NOT be the CEO bot's token, two pollers
                    kick each other out)
       bot.py add   create a fresh LDPlayer instance with the game installed and print its login token
accounts.json: {"<login token>": {"index": 0, "view": "<secret>"}}
  index = LDPlayer instance of that game account,
  view = path of the account's live view. Between /login and /start that page also passes
  taps and typing on to the emulator, so the player can sign in to their own game account.
One view.py behind one Cloudflare quick tunnel serves every account at <tunnel url>/<view>/.
Logging in boots the account's LDPlayer instance and sends that link. /start asks which saved
armies (the numbered slots of the game's new-army screen) to farm with.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from rok import LD

HERE = Path(__file__).parent
MAX_BAD_TOKENS = 5

ACCOUNTS = {}  # login token -> account, loaded in main()
awaiting = set()  # chats that were asked for their token
awaiting_slots = set()  # chats that were asked which saved armies to use
logged_in = {}  # chat -> account
bad_tokens = {}  # chat -> wrong tokens sent. ponytail: forgotten on restart; tokens are 128-bit random anyway
VIEW_PORT = 8900
monitor = []  # view.py process, cloudflared process, public url - filled by start_monitor()
farms = {}  # LDPlayer index -> farm.py process
# ponytail: one lock, so logins are served one at a time (a cold LDPlayer boot takes minutes);
# make it per index if several players log in at once.
opening = threading.Lock()


def api(method, **params):
    token = (HERE / ".bot_token").read_text().strip()
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data, timeout=70) as r:
        return json.load(r)["result"]


def set_control(index, on):
    """Let (or stop letting) the live view pass the player's taps and typing on to that emulator."""
    path = HERE / "control.json"
    allowed = set(json.loads(path.read_text())) - {index} if path.exists() else set()
    path.write_text(json.dumps(sorted(allowed | {index} if on else allowed)))


def env_for(index):
    return {**os.environ, "ROK_INDEX": str(index)}


def start_monitor():
    """One live-view server for all accounts, published through a quick tunnel (new url on every start)."""
    view = subprocess.Popen([sys.executable, "view.py", str(VIEW_PORT)], cwd=HERE)
    tunnel = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{VIEW_PORT}"],
                              stderr=subprocess.PIPE, text=True)
    monitor[:] = view, tunnel
    for line in tunnel.stderr:
        url = re.search(r"https://[-\w]+\.trycloudflare\.com", line)
        if url:
            break
    else:
        raise RuntimeError("cloudflared exited without a url")
    threading.Thread(target=tunnel.stderr.read, daemon=True).start()  # keep its pipe from filling
    monitor.append(url[0])


def open_account(chat, acc):
    """Boot the account's LDPlayer instance and send the link to its live view."""
    i = acc["index"]
    try:
        with opening:
            subprocess.run([f"{LD}/ldconsole.exe", "launch", "--index", str(i)], check=True)
            for _ in range(60):
                booted = subprocess.run([f"{LD}/adb.exe", "-s", f"emulator-{5554 + 2 * i}", "shell", "getprop",
                                         "sys.boot_completed"], capture_output=True).stdout
                if booted.strip() == b"1":
                    break
                time.sleep(3)
            else:
                raise RuntimeError("LDPlayer did not boot")
        set_control(i, True)
        api("sendMessage", chat_id=chat, text=f"LDPlayer đã mở. Màn hình trực tiếp: {monitor[2]}/{acc['view']}/\n"
                                              "Trên trang đó bạn bấm và gõ được để đăng nhập tài khoản game của mình "
                                              "(điều khiển tắt trong lúc treo). Đừng chia sẻ link này.\n"
                                              "/start bắt đầu treo, /stop dừng treo, /logout đăng xuất.")
    except Exception as e:  # the player must hear about it either way
        print("open_account", i, repr(e), flush=True)
        api("sendMessage", chat_id=chat, text="Không mở được LDPlayer, hãy báo quản trị viên.")


def watch(chat, i, proc):
    """Tell the player when the farm dies on its own (after /stop it is no longer in `farms`)."""
    proc.wait()
    if farms.get(i) is proc:
        del farms[i]
        set_control(i, True)
        api("sendMessage", chat_id=chat, text="Treo đã dừng do lỗi. Gõ /start để chạy lại.")


def start_farm(chat, acc, slots):
    i = acc["index"]
    if i in farms:
        return "Đang treo rồi."
    set_control(i, False)  # the player's taps would fight the farm's
    log = open(HERE / f"farm{i}.log", "a")
    farms[i] = subprocess.Popen([sys.executable, "farm.py", slots], cwd=HERE, env=env_for(i), stdout=log, stderr=log)
    threading.Thread(target=watch, args=(chat, i, farms[i]), daemon=True).start()
    return f"Đã bắt đầu treo với khe {' '.join(slots)}."


def stop_farm(chat, acc):
    proc = farms.pop(acc["index"], None)
    if proc is None:
        return "Hiện không treo."
    proc.terminate()
    set_control(acc["index"], True)
    return "Đã dừng treo."


def logout(chat):
    """Stop the farm, close the account's LDPlayer instance and forget the chat."""
    acc = logged_in.pop(chat)
    stop_farm(chat, acc)
    set_control(acc["index"], False)
    subprocess.run([f"{LD}/ldconsole.exe", "quit", "--index", str(acc["index"])])
    return "Đã đăng xuất: dừng treo và đóng LDPlayer. Gõ /login để vào lại."


def handle(chat, text):
    """Reply to one private message."""
    text = text.strip()
    cmd = text.split("@")[0]
    asked, asked_slots = chat in awaiting, chat in awaiting_slots
    awaiting.discard(chat)
    awaiting_slots.discard(chat)
    if cmd == "/login":
        awaiting.add(chat)
        return "Gửi token của bạn."
    if (asked or chat not in logged_in) and not text.startswith("/"):  # /login first is optional
        if bad_tokens.get(chat, 0) >= MAX_BAD_TOKENS:
            return "Bạn đã nhập sai token quá nhiều lần."
        ACCOUNTS.update(json.loads((HERE / "accounts.json").read_text()))  # `bot.py add` needs no restart
        if text not in ACCOUNTS:
            bad_tokens[chat] = bad_tokens.get(chat, 0) + 1
            return "Token không đúng. Gõ /login để thử lại."
        logged_in[chat] = ACCOUNTS[text]
        threading.Thread(target=open_account, args=(chat, ACCOUNTS[text]), daemon=True).start()
        return "Đăng nhập thành công. Đang mở LDPlayer, chờ một chút..."
    if chat not in logged_in:
        return "Gõ /login để đăng nhập."
    if cmd == "/start":
        if logged_in[chat]["index"] in farms:
            return "Đang treo rồi."
        awaiting_slots.add(chat)
        return "Dùng những khe đạo quân đã lưu nào? Gửi số khe, ví dụ: 1 2 3 4 5"
    if asked_slots:
        slots = text.replace(" ", "").replace(",", "")
        if not slots or set(slots) - set("12345") or len(set(slots)) != len(slots):
            return "Số khe không hợp lệ (chỉ 1 đến 5, không lặp). Gõ /start để thử lại."
        return start_farm(chat, logged_in[chat], slots)
    if cmd == "/logout":
        return logout(chat)
    if cmd == "/stop":
        return stop_farm(chat, logged_in[chat])
    return "/start bắt đầu treo, /stop dừng treo, /logout đăng xuất."


def add_account():
    """A new, empty LDPlayer instance with the game installed, and a login token for it.

    Never a copy of an existing instance: that would hand out its Google and game logins.
    Only the game's APK files are taken from instance 0.
    """
    def ld(*args):
        # no check=True: ldconsole exits 1 even when `add` worked; the steps after it fail loudly instead
        return subprocess.run([f"{LD}/ldconsole.exe", *args], capture_output=True, text=True).stdout

    def adb(index, *args):
        return subprocess.run([f"{LD}/adb.exe", "-s", f"emulator-{5554 + 2 * index}", *args],
                              capture_output=True, text=True, check=True).stdout

    def boot(index):
        ld("launch", "--index", str(index))
        for _ in range(100):
            done = subprocess.run([f"{LD}/adb.exe", "-s", f"emulator-{5554 + 2 * index}", "shell", "getprop",
                                   "sys.boot_completed"], capture_output=True, text=True).stdout
            if done.strip() == "1":
                return
            time.sleep(3)
        raise RuntimeError(f"LDPlayer {index} did not boot (is ADB debugging on for it?)")

    apks = HERE / "apk"
    if not apks.exists():  # once: the game's install files, which hold no account data
        boot(0)
        apks.mkdir()
        for path in adb(0, "shell", "pm", "path", "com.rok.gp.vn").split():
            adb(0, "pull", path.removeprefix("package:"), f"apk/{path.rsplit('/', 1)[1]}")
    before = {line.split(",")[0] for line in ld("list2").split()}
    ld("add", "--name", f"rok-{secrets.token_hex(2)}")
    index = int(({line.split(",")[0] for line in ld("list2").split()} - before).pop())
    # ponytail: 4 cores / 4 GB each; the host's RAM is what limits how many can farm at once
    ld("modify", "--index", str(index), "--resolution", "1280,720,240", "--cpu", "4", "--memory", "4096")
    config = Path(LD) / "vms" / "config" / f"leidian{index}.config"
    config.write_text(json.dumps({**json.loads(config.read_text()), "basicSettings.adbDebug": 1}, indent=4))
    boot(index)
    adb(index, "install-multiple", *(f"apk/{p.name}" for p in sorted(apks.iterdir())))
    ld("quit", "--index", str(index))
    token = secrets.token_hex(12)  # hex: no l/I or O/0 to mix up when someone types it
    accounts = json.loads((HERE / "accounts.json").read_text())
    accounts[token] = {"index": index, "view": secrets.token_urlsafe(16)}
    (HERE / "accounts.json").write_text(json.dumps(accounts, indent=1))
    print(f"LDPlayer {index} ready. Login token: {token}")


def main():
    (HERE / "control.json").write_text("[]")  # nobody is logged in after a restart
    start_monitor()
    print("monitor at", monitor[2], flush=True)
    offset = 0
    while True:
        try:
            for u in api("getUpdates", offset=offset, timeout=50, allowed_updates='["message"]'):
                offset = u["update_id"] + 1
                msg = u.get("message", {})
                if msg.get("chat", {}).get("type") != "private" or "text" not in msg:
                    continue
                chat, text = msg["chat"]["id"], msg["text"]
                is_token = chat not in logged_in and not text.startswith("/")
                api("sendMessage", chat_id=chat, text=handle(chat, text))
                if is_token:  # do not leave the token sitting in the chat history
                    api("deleteMessage", chat_id=chat, message_id=msg["message_id"])
        except OSError as e:  # network hiccup or a Telegram error: the offset already moved on
            print("telegram:", e, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    if sys.argv[1:] == ["add"]:
        os.chdir(HERE)  # adb.exe is a Windows program: give it relative paths
        sys.exit(add_account())
    try:
        main()
    finally:
        for proc in [*farms.values(), *monitor[:2]]:
            proc.terminate()
