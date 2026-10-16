"""Live view of the emulator screens over HTTP (for a Cloudflare quick tunnel).

usage: view.py [port]   -> page at http://127.0.0.1:port/VIEW/ for every account in accounts.json,
VIEW being that account's "view" secret.
Screenshots are always served. Input (tap, swipe, text, three keys) is only passed on for the
LDPlayer indexes listed in control.json, which bot.py keeps: on after /login so the player can
sign in to their own game account, off while the farm is running.
"""
import json
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

from rok import LD

HERE = Path(__file__).parent
KEYS = {"back": "4", "enter": "66", "del": "67"}
PAGE = """<!doctype html><meta name=viewport content="width=device-width">
<title>RoK live</title><body style="margin:0;background:#111;color:#eee;font:16px sans-serif">
<img id=s draggable=false style="width:100%;max-width:1280px;display:block;margin:auto;touch-action:none" alt="Màn hình game">
<form id=f style="display:flex;gap:8px;max-width:1280px;margin:8px auto;padding:0 8px">
<label for=t style="align-self:center">Gõ chữ</label>
<input id=t autocomplete=off autocapitalize=off style="flex:1;font:inherit;padding:8px">
<button style="font:inherit;padding:8px">Gửi</button>
<button type=button data-k=del style="font:inherit;padding:8px">Xoá</button>
<button type=button data-k=enter style="font:inherit;padding:8px">Enter</button>
<button type=button data-k=back style="font:inherit;padding:8px">Quay lại</button></form>
<p id=m role=status style="max-width:1280px;margin:8px auto;padding:0 8px"></p>
<script>
const s=document.getElementById('s'),m=document.getElementById('m'),t=document.getElementById('t');
function next(){const i=new Image();i.onload=()=>{s.src=i.src;setTimeout(next,1500)};
i.onerror=()=>setTimeout(next,3000);i.src='shot.jpg?'+Date.now()}
next();
async function send(path,body){const r=await fetch(path,{method:'POST',body});
m.textContent=r.ok?'':'Điều khiển đang tắt (đang treo hoặc chưa đăng nhập bot).'}
function at(e){const r=s.getBoundingClientRect();
return [Math.round((e.clientX-r.left)/r.width*1280),Math.round((e.clientY-r.top)/r.height*720)]}
let down;
s.onpointerdown=e=>{down=at(e);e.preventDefault()};
s.onpointerup=e=>{if(!down)return;const u=at(e);send(`tap?x=${down[0]}&y=${down[1]}&x2=${u[0]}&y2=${u[1]}`);down=null};
document.getElementById('f').onsubmit=e=>{e.preventDefault();if(t.value)send('text',t.value);t.value=''};
document.querySelectorAll('[data-k]').forEach(b=>b.onclick=()=>send('key?k='+b.dataset.k));
</script>""".encode()

lock = threading.Lock()
cache = {}  # LDPlayer index -> (time, jpeg)


def adb(index, *args):
    return subprocess.run([f"{LD}/adb.exe", "-s", f"emulator-{5554 + 2 * index}", *args],
                          capture_output=True, check=True).stdout


def account_index(secret):
    """LDPlayer index for a view secret, or None. Read per request, so a new account needs no restart."""
    for acc in json.loads((HERE / "accounts.json").read_text()).values():
        if secret and acc.get("view") == secret:
            return acc["index"]


def frame(index):
    """Latest screen as JPEG, re-captured at most every 1.5 s however many viewers there are."""
    with lock:
        if time.time() - cache.get(index, (0,))[0] > 1.5:
            png = adb(index, "exec-out", "screencap", "-p")
            ok, jpg = cv2.imencode(".jpg", cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR),
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
            cache[index] = time.time(), jpg.tobytes()
        return cache[index][1]


class Handler(BaseHTTPRequestHandler):
    def reply(self, body=b"", ctype="text/plain"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def target(self):
        """(LDPlayer index, rest of the path, query) - index None unless the path starts with a view secret."""
        url = urlsplit(self.path)
        secret, slash, rest = url.path[1:].partition("/")
        return (account_index(secret) if slash else None), rest, parse_qs(url.query)

    def do_GET(self):
        index, rest, _ = self.target()
        if index is None or rest not in ("", "shot.jpg"):
            self.send_error(404)  # anything without a view secret gets nothing
        elif rest:
            self.reply(frame(index), "image/jpeg")
        else:
            self.reply(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        index, rest, query = self.target()
        control = HERE / "control.json"
        if index is None:
            return self.send_error(404)
        if not control.exists() or index not in json.loads(control.read_text()):
            return self.send_error(403)
        try:
            if rest == "tap":
                x, y, x2, y2 = (min(max(int(query[k][0]), 0), limit) for k, limit in
                                (("x", 1279), ("y", 719), ("x2", 1279), ("y2", 719)))
                if abs(x2 - x) + abs(y2 - y) > 20:
                    adb(index, "shell", "input", "swipe", str(x), str(y), str(x2), str(y2), "300")
                else:
                    adb(index, "shell", "input", "tap", str(x), str(y))
            elif rest == "key":
                adb(index, "shell", "input", "keyevent", KEYS[query["k"][0]])
            elif rest == "text":
                text = self.rfile.read(min(int(self.headers["Content-Length"]), 200)).decode()
                # ponytail: `input text` only types printable ASCII, and reads "%s" as a space
                if not text or not text.isascii() or not text.isprintable():
                    return self.send_error(400)
                # the device runs this through its shell: quote it, or the text is a command
                adb(index, "shell", "input", "text", shlex.quote(text.replace(" ", "%s")))
            else:
                return self.send_error(404)
        except (KeyError, ValueError, TypeError):
            return self.send_error(400)
        self.reply()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
