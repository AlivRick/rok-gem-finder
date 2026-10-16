"""Find gem deposits on the Rise of Kingdoms map by sweeping the far (icon) view.

usage: gems.py X0 Y0 X1 Y1     (kingdom tile coordinates, inclusive corners)

Before running, zoom the world map out by hand until resource nodes turn into
white icons (minimap visible top-right). The script only moves the camera
through the coordinate search box and reads the screen; it never taps the map.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

import rok

HERE = Path(__file__).parent
# reference shapes: the far icon view, and the closer icon view (icons carry level badges)
GEMS = [cv2.imread(str(HERE / f), cv2.IMREAD_GRAYSCALE).astype(np.float32) for f in ("gem_icon.png", "gem_icon_close.png")]
MIN_SCORE = 0.82  # gem icons score 0.93-0.96 against GEM, the closest other icon (gold) 0.71

# Pixel <-> tile model, measured at the reference zoom (camera target = screen centre).
# The view is tilted, so rows further up the screen are compressed.
REF_PX_PER_TILE = 46  # horizontal, at the centre row
ROW_PY = [108, 294, 365, 432, 470]  # screen y ...
ROW_DY = [9, 2, 0, -2, -3]  # ... of a tile dy rows above the camera target
STEP_X, STEP_Y = 20, 12  # tiles per jump; a screen shows ~27 x 18, so frames overlap


def icons(im):
    """White map icons in a frame: (centre_x, centre_y, shape normalised to 24x24)."""
    white = cv2.inRange(cv2.cvtColor(im, cv2.COLOR_BGR2HSV), (0, 0, 185), (179, 70, 255))
    # HUD: chat row, coordinate readout, minimap, age-rating badge
    white[620:] = 0
    white[:60, :360] = 0
    white[:145, 1060:] = 0
    white[100:150, 90:225] = 0
    white[150:530, 1160:] = 0  # army queue panel
    # dilate so multi-part icons (gem facets, stone + pebble) become one blob
    n, _, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(white, np.ones((5, 5), np.uint8)))
    out = []
    for x, y, w, h, _ in stats[1:]:
        if 12 <= w <= 44 and 12 <= h <= 56:
            if h > 1.25 * w:  # closer zooms hang a level badge under the icon; drop it
                h = int(h * 0.72)
            shape = cv2.resize(white[y : y + h, x : x + w], (24, 24), interpolation=cv2.INTER_AREA)
            out.append((x + w // 2, y + h // 2, shape.astype(np.float32)))
    return out


def gem_score(shape):
    def corr(ref):
        a, b = shape - shape.mean(), ref - ref.mean()
        return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9))

    return max(corr(ref) for ref in GEMS)


def gems_in_frame(im):
    """Pixel centres of gem icons in one 1280x720 far-view frame."""
    return [(x, y) for x, y, shape in icons(im) if gem_score(shape) >= MIN_SCORE]


def to_tile(cam_x, cam_y, px, py, zoom=1.0):
    """Map a screen pixel to kingdom tile coordinates. zoom = current / reference scale."""
    # ponytail: piecewise-linear fit through 5 measured rows, accurate to about +-1 tile;
    # fit a proper homography if exact tiles are ever needed.
    py = 360 + (py - 360) / zoom
    dy = np.interp(py, ROW_PY, ROW_DY)
    if py < ROW_PY[0]:
        dy = ROW_DY[0] + (ROW_PY[0] - py) * (ROW_DY[0] - ROW_DY[1]) / (ROW_PY[1] - ROW_PY[0])
    if py > ROW_PY[-1]:
        dy = ROW_DY[-1] - (py - ROW_PY[-1]) * (ROW_DY[-2] - ROW_DY[-1]) / (ROW_PY[-1] - ROW_PY[-2])
    px_per_tile = (35 + 0.03 * py) * zoom  # 46 at the centre row, ~38 near the top
    return cam_x + (px - 640) / px_per_tile, cam_y + dy


def measure_zoom(x, y):
    """Current zoom relative to the reference, from how far the terrain slides for a 5-tile jump."""
    rok.goto(x, y)
    a = rok.shot()
    rok.goto(x + 5, y)
    # The terrain can only have slid left by 5 tiles at 0.5x-2x the reference scale, on the
    # same row; searching just that band keeps look-alike terrain elsewhere from matching.
    lo, hi = int(5 * REF_PX_PER_TILE * 0.5), int(5 * REF_PX_PER_TILE * 2)
    band = rok.shot()[245:475, 490 - hi : 790 - lo]
    res = cv2.matchTemplate(band, a[260:460, 490:790], cv2.TM_CCOEFF_NORMED)
    _, conf, _, loc = cv2.minMaxLoc(res)
    zoom = (hi - loc[0]) / (5 * REF_PX_PER_TILE)
    if conf < 0.3:
        raise RuntimeError(f"zoom calibration failed (conf {conf:.2f}) - is the map in the far icon view?")
    return zoom


def scan(x0, y0, x1, y1):
    zoom = measure_zoom(x0, y0)
    print(f"zoom x{zoom:.2f} of reference", file=sys.stderr)
    step_x, step_y = max(1, int(STEP_X / zoom)), max(1, int(STEP_Y / zoom))
    found = []
    for row, y in enumerate(range(y0, y1 + step_y, step_y)):
        xs = list(range(x0, x1 + step_x, step_x))
        for x in xs[:: 1 if row % 2 == 0 else -1]:  # zig-zag keeps jumps short
            rok.goto(x, y)
            for px, py in gems_in_frame(rok.shot()):
                tx, ty = to_tile(x, y, px, py, zoom)
                # the same deposit shows up in overlapping frames
                if all(abs(tx - gx) > 3 or abs(ty - gy) > 3 for gx, gy in found):
                    found.append((tx, ty))
                    print(f"gem deposit near X:{tx:.0f} Y:{ty:.0f}", flush=True)
    return found


if __name__ == "__main__":
    scan(*map(int, sys.argv[1:5]))
