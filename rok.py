"""Thin ADB/LDPlayer helpers for driving Rise of Kingdoms in the emulator."""
import os
import random
import subprocess
import time

import cv2
import numpy as np

LD = "/mnt/d/LDPlayer/LDPlayer9"
# one LDPlayer instance per game account; instance N listens on adb port 5554 + 2N
INDEX = int(os.environ.get("ROK_INDEX", 0))
DEV = f"emulator-{5554 + 2 * INDEX}"


_busy = _stop = False


def adb(*args):
    global _busy
    _busy = True
    try:
        out = subprocess.run([f"{LD}/adb.exe", "-s", DEV, *args], capture_output=True, check=True).stdout
    finally:
        _busy = False
    if _stop:
        raise SystemExit(0)
    return out


def stop_when_safe(*_):
    """SIGTERM handler: exit now, or right after the adb command that is running.

    A drag cut off half-way leaves the game holding a finger down: after that the emulator's
    zoom only taps the map and taps do nothing, until the game is restarted. Seen twice,
    both times right after a farm was killed.
    """
    global _stop
    _stop = True
    if not _busy:
        raise SystemExit(0)


def shot():
    """Current screen as a BGR image (1280x720)."""
    return cv2.imdecode(np.frombuffer(adb("exec-out", "screencap", "-p"), np.uint8), cv2.IMREAD_COLOR)


# Nobody hits the same pixel after the same pause twice. Every button here is far wider than
# the jitter, and every step is followed by a check of the screen, so this costs nothing.
def tap(x, y, wait=1.0):
    adb("shell", "input", "tap", str(x + random.randint(-2, 2)), str(y + random.randint(-2, 2)))
    time.sleep(wait * random.uniform(1, 1.25))


def swipe(x1, y1, x2, y2, ms=600, wait=1.0):
    x1, y1, x2, y2 = (v + random.randint(-8, 8) for v in (x1, y1, x2, y2))
    adb("shell", "input", "swipe", *map(str, (x1, y1, x2, y2, int(ms * random.uniform(0.9, 1.15)))))
    time.sleep(wait * random.uniform(1, 1.25))


def zoom(direction, steps=1, wait=0.8):
    """direction: 'In' or 'Out' (LDPlayer's own zoom gesture)."""
    for _ in range(steps):
        subprocess.run([f"{LD}/ldconsole.exe", f"zoom{direction}", "--index", str(INDEX)], check=True)
        time.sleep(wait)


def search_box_open(im=None):
    """True when the coordinate search box is showing (its blue 'go' button is visible)."""
    b, g, r = (shot() if im is None else im)[125:160, 865:905].reshape(-1, 3).mean(0)
    return b > 200 and r < 60


def _wait(check, what, tries=6):
    for _ in range(tries):
        im = shot()
        if check(im):
            return im
        time.sleep(0.4)
    raise RuntimeError(f"{what} - stopping before any further tap")


def goto(x, y, wait=2.5):
    """Jump the map camera to kingdom coordinates via the in-game search box.

    Every tap is preceded by a check that the expected UI is on screen: a tap that
    lands on the map instead opens the teleport/march popup (or zooms the far view in).
    """
    im = shot()
    if im[655:685, 100:1000].mean() > 240:  # text-entry bar left open by an interrupted run
        tap(1198, 668, 0.5)
        im = shot()
    if not search_box_open(im):
        # magnifier next to the coordinate readout; the far (icon) view has a cyan
        # button top-left instead of the avatar, which shifts the readout left
        b, g, r = im[14:26, 27:39].reshape(-1, 3).mean(0)
        tap(249 if b > 200 and r < 60 else 441, 20, 0.5)
    for field_x, value in ((640, x), (795, y)):
        _wait(search_box_open, "coordinate search box is not open")
        tap(field_x, 143, 0.3)
        # Android text-entry bar: a white strip along the bottom with OK at the right
        _wait(lambda im: im[655:685, 100:1000].mean() > 240, "text entry bar did not appear")
        adb("shell", "input", "text", str(value))
        tap(1198, 668, 0.3)  # OK
    _wait(search_box_open, "coordinate search box closed unexpectedly")
    tap(885, 143, wait)  # go


def set_scan_zoom():
    """Widest normal map zoom: fully in, then three LDPlayer zoom-out steps (a fourth enters strategic view)."""
    zoom("In", 5)
    zoom("Out", 3)
    time.sleep(1.5)


# 10x23 grey glyphs cut from the readout itself, 0..9 side by side; four rows = the four
# widths the game draws them at for a 4-digit kingdom with 5, 6, 7 and 8 coordinate digits
DIGITS = cv2.imread(os.path.join(os.path.dirname(__file__), "digits.png"), cv2.IMREAD_GRAYSCALE)


def _readout_digits(grey):
    """Grey 10x23 glyphs (left-aligned) of the X digits and of the Y digits in the readout strip."""
    edges = np.flatnonzero(np.diff(np.r_[0, (grey > 170).any(0), 0]))
    runs = list(zip(edges[::2].tolist(), edges[1::2].tolist()))
    colons = [i for i, (a, b) in enumerate(runs) if b - a <= 3]
    if len(colons) != 2:
        return None

    def glyph(a, b):
        g = np.zeros((23, 10), np.uint8)
        g[:, :min(10, b - a)] = cv2.subtract(grey[:, a:a + min(10, b - a)], 120)  # drop the terrain behind
        return g

    # '#3306 X:' digits 'Y:' digits -> between the colons minus the 'Y', and after the second
    return [[glyph(*r) for r in part] for part in (runs[colons[0] + 1:colons[1] - 1], runs[colons[1] + 1:])]


def camera_coords(im=None):
    """Kingdom coordinates of the map centre, read from the readout at the top.

    The game fits the text to the bar by drawing it narrower the longer it is, so the row of
    DIGITS that fits is not known up front: every row is tried and the reading whose worst
    digit matches best wins. A longer kingdom name (#S11476) is narrower than any sampled
    row, so the strip is also tried stretched sideways.
    ponytail: template digits for this one font at 1280x720. Anything that does not look
    like the readout (glare, a pop-up over the bar) raises instead of guessing.
    """
    im = shot() if im is None else im
    b, g, red = im[14:26, 27:39].reshape(-1, 3).mean(0)
    left = 78 if b > 200 and red < 60 else 265  # the far view has no avatar: the readout sits further left
    grey = im[9:32, left:left + 163].min(2)  # white text: every channel is high
    best = (0, None)
    for stretch in np.arange(1.0, 1.51, 0.05):
        parts = _readout_digits(cv2.resize(grey, None, fx=stretch, fy=1, interpolation=cv2.INTER_CUBIC))
        if not parts or not all(parts):
            continue
        for row in range(0, len(DIGITS), 23):
            worst, text = 1.0, []
            for part in parts:
                digits = ""
                for glyph in part:
                    # text sits at sub-pixel offsets, so the same digit never renders twice alike:
                    # slide each template +-2 px over the glyph and keep its best correlation
                    area = cv2.copyMakeBorder(glyph, 2, 2, 2, 2, cv2.BORDER_CONSTANT)
                    score = [cv2.matchTemplate(area, DIGITS[row:row + 23, k * 10:k * 10 + 10],
                                               cv2.TM_CCOEFF_NORMED).max() for k in range(10)]
                    worst, digits = min(worst, max(score)), digits + str(int(np.argmax(score)))
                text.append(digits)
            best = max(best, (worst, text))
        if best[0] > 0.9:  # the unstretched strip already fits: the usual case
            break
    if best[0] < 0.85:
        raise RuntimeError(f"could not read the map coordinates (best fit {best[0]:.2f})")
    numbers = [int(t) for t in best[1]]
    if max(numbers) > 1199:
        raise RuntimeError(f"could not read the map coordinates (got {numbers})")
    return tuple(numbers)
