"""Send armies to gem deposits found by gems.py.

Every tap is preceded by a check that the expected button is on screen, and the
march is only pressed on the new-army screen, so a misplaced tap cannot reach
the teleport button or attack anything.
"""
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np

import rok

HERE = Path(__file__).parent
BTN_GATHER = cv2.imread(str(HERE / "btn_gather.png"))
BTN_NEW_ARMY = cv2.imread(str(HERE / "btn_new_army.png"))
NUMPAD = {**{str(d): (905 + 72 * ((d - 1) % 3), 261 + 62 * ((d - 1) // 3)) for d in range(1, 10)}, "0": (941, 449)}


def find_button(im, template, min_score=0.8):
    res = cv2.matchTemplate(im, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(res)
    if score < min_score:
        return None
    return x + template.shape[1] // 2, y + template.shape[0] // 2


def gem_near_centre(im):
    """Pixel centre of the crimson gem deposit closest to the screen centre (close view), or None."""
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    raw = cv2.inRange(hsv, (168, 120, 55), (179, 255, 255)) | cv2.inRange(hsv, (0, 120, 55), (3, 255, 255))
    raw[:135] = 0  # top bar and event icons
    raw[620:] = 0
    raw[135:440, :270] = 0  # quest panel
    closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, labels, stats, centres = cv2.connectedComponentsWithStats(closed)
    blobs = [centres[i] for i in range(1, n) if np.count_nonzero(raw[labels == i]) >= 800]
    if not blobs:
        return None
    x, y = min(blobs, key=lambda c: abs(c[0] - 640) + abs(c[1] - 360))
    return int(x), int(y)


BTN_SLOTS = cv2.imread(str(HERE / "btn_slots.png"))  # unlit faces of buttons 1..5, side by side


def slot_button_y(im):
    """y of saved-army button 1 in the numbered column right of the troop list (54 px apart).

    Accounts differ in how many icon buttons sit above the numbers, so the column is found
    by looking for any unlit number rather than assumed.
    """
    column = im[:, 1080:1130]
    for k in range(5):
        found = find_button(column, BTN_SLOTS[:, k * 20:k * 20 + 20], 0.85)
        if found:
            return found[1] - 54 * k
    raise RuntimeError("no saved army slots on the new-army screen")


def slot_loaded(im, slot, y1):
    """True when saved-army button `slot` is lit; y1 is slot_button_y()."""
    y = y1 + 54 * (slot - 1)
    return im[y - 9:y + 9, 1094:1114].min(2).mean() > 90  # lit ~145, dark ~20


def send_new_army(x, y, slots):
    """March a new army, loaded from the first of the saved-army `slots` the game accepts,
    to the deposit near tile x,y.

    Returns 'marched', 'blocked' (game refused: no path), 'no_gem', or 'full' (no free queue).
    """
    rok.goto(x, y)
    gem = gem_near_centre(rok.shot())
    if gem is None:
        return "no_gem"
    rok.tap(*gem, 1.5)
    gather = find_button(rok.shot(), BTN_GATHER)
    if gather is None:  # occupied node, someone else's, or we tapped something else
        rok.tap(1240, 400, 1.0)  # empty ground at the right edge closes any popup
        return "no_gem"
    rok.tap(*gather, 1.5)
    new_army = find_button(rok.shot(), BTN_NEW_ARMY)
    if new_army is None:  # every march queue is in use, whatever the queue panel seemed to show
        rok.tap(560, 640, 1.0)  # empty ground closes the picker; left open, it blocks the zoom
        return "full"
    rok.tap(*new_army, 2.0)

    def march_button(im):  # orange button, only present on the new-army screen
        b, g, r = im[610:625, 820:1040].reshape(-1, 3).mean(0)
        return r > 200 and b < 80

    rok._wait(march_button, "new-army screen did not open")
    y1 = slot_button_y(rok.shot())
    for slot in slots:
        rok.tap(1104, y1 + 54 * (slot - 1), 1.5)  # numbered button = load that saved army
        im = rok.shot()
        if slot_loaded(im, slot, y1) and march_button(im):
            break
    else:
        rok.tap(1115, 44, 1.5)  # X: leave without marching
        raise RuntimeError("none of the saved army slots could be loaded")
    rok.tap(930, 633, 3.0)  # march
    # When the path is blocked the game shows a notice and moves the camera to the
    # blocking pass, so the deposit is no longer where we tapped it.
    after = gem_near_centre(rok.shot())
    if after is None or abs(after[0] - gem[0]) + abs(after[1] - gem[1]) > 40:
        return "blocked"
    return "marched"


# ---- continuous farming -------------------------------------------------------

SLOT_Y = [193, 268, 345, 421, 497]  # army portraits in the queue panel (x = 1223), top to bottom
PICK_ROW_Y = [104, 224, 341, 459, 576]  # the same armies in the gather dialog's column (x = 1211)
ICONS = {name: cv2.imread(str(HERE / f"icon_{name}.png")) for name in ("gathering", "marching")}
BTN_MARCH_SMALL = cv2.imread(str(HERE / "btn_march_small.png"))
CITY = (370, 965)  # replaced at start-up
# ponytail: a fixed square around the city, clipped to the 1200x1200 map. One sweep of it takes
# ~10 min; widen it (or grow it when a sweep finds nothing) if deposits run out.
SCAN_RADIUS = 60
BOOT = {name: cv2.imread(str(HERE / f"btn_{name}.png")) for name in ("tap_start", "map", "city", "popup_close", "reconnect")}
MIN_GATHER_S = 11 * 60  # a level-1 deposit (10 gems) took ~14 min with 18k siege; never redirect sooner


def boot_step(im):
    """What to do on a start-up screen: 'ready' (on the map), a point to tap, or None (wait)."""
    if is_far(im) or find_button(im, BOOT["city"]):
        return "ready"
    if find_button(im, BOOT["tap_start"]):  # "Nhấn để bắt đầu" title screen
        return 640, 400
    if find_button(im, BOOT["reconnect"]):  # "Đã ngắt kết nối mạng" after idling: its XÁC NHẬN
        return 640, 474
    # "Tải xuống nội dung thêm" offer on entering the city: its X, never the download button.
    # Otherwise we are inside the city: the map button, bottom-left.
    return find_button(im, BOOT["popup_close"]) or find_button(im, BOOT["map"])


def open_game():
    """Start the game if it is not running and bring it to the kingdom map."""
    rok.adb("shell", "monkey", "-p", "com.rok.gp.vn", "-c", "android.intent.category.LAUNCHER", "1")
    for _ in range(60):  # a cold start took ~2 min
        step = boot_step(rok.shot())
        if step == "ready":
            return
        if step:
            rok.tap(*step, 3)
        else:
            time.sleep(4)
    raise RuntimeError("game did not reach the map (login screen or a pop-up?)")


def city_coords():
    """Map coordinates of our own city: going into the city and back centres the map on it."""
    to_near()
    city = find_button(rok.shot(), BOOT["city"])
    if city is None:
        raise RuntimeError("no city button on the map")
    rok.tap(*city, 3)
    for _ in range(10):  # really inside the city? Read too early and "our city" is wherever the camera was
        if find_button(rok.shot(), BOOT["map"]):
            break
        time.sleep(1)
    else:
        raise RuntimeError("could not enter the city")
    open_game()  # taps the map button
    time.sleep(2)
    im = rok.shot()
    try:
        coords = rok.camera_coords(im)
    except RuntimeError:
        cv2.imwrite(str(HERE / f"fail_coords{rok.INDEX}.png"), im)  # to see what the readout looked like
        raise
    if coords != rok.camera_coords():  # the camera was still moving
        raise RuntimeError("map coordinates not stable")
    return coords


def is_far(im):
    """Far (icon) map view: a cyan button replaces the avatar top-left."""
    b, g, r = im[14:26, 27:39].reshape(-1, 3).mean(0)
    return bool(b > 200 and r < 60)


QUEUE_COUNT = cv2.imread(str(HERE / "queue_count.png"), cv2.IMREAD_GRAYSCALE)  # digits 1..5 of the "N/5" counter


def queue_count(im, shift):
    """Armies out according to the queue panel's "N/5" counter, or None if it cannot be read."""
    digit = cv2.subtract(im[131 + shift:163 + shift, 1210:1226].min(2), 120)
    cells = [QUEUE_COUNT[:, k * 10:k * 10 + 10] for k in range(5)]
    # a blank cell (a digit not sampled yet) correlates perfectly with anything: skip it
    score = [cv2.matchTemplate(digit, c, cv2.TM_CCOEFF_NORMED).max() if c.any() else 0 for c in cells]
    return int(np.argmax(score)) + 1 if max(score) >= 0.8 else None


def army_states(im):
    """State of each occupied queue slot: 'gathering', 'marching' or 'returning'."""
    shift = 21 if is_far(im) else 0  # the queue panel sits lower in the far view
    # The panel only exists while armies are out: its cyan expand button heads it. Without
    # this check sunlit grass where the badges would be once read as five returning armies.
    b, g, r = im[137 + shift:157 + shift, 1170:1190].reshape(-1, 3).mean(0)
    if not (b > 180 and r < 80):
        return []
    count = queue_count(im, shift)
    states = []
    for y in (v + shift for v in SLOT_Y[:count]):
        badge = im[y + 5 : y + 45, 1225:1265]  # status badge at the portrait's lower right
        hsv = cv2.cvtColor(badge, cv2.COLOR_BGR2HSV)
        green = np.count_nonzero(cv2.inRange(hsv, (40, 120, 100), (85, 255, 255)))
        orange = np.count_nonzero(cv2.inRange(hsv, (8, 120, 120), (25, 255, 255)))  # return-arrow badge
        scores = {n: cv2.matchTemplate(badge, t, cv2.TM_CCOEFF_NORMED).max() for n, t in ICONS.items()}
        best = max(scores, key=scores.get)
        if scores[best] >= 0.6:
            states.append(best)
        # Only when neither green icon is there: the orange return-arrow badge. (Colour
        # alone is not enough - golden hair in a portrait once passed for it, and terrain
        # fills the whole box where a badge covers a third of it.)
        elif 120 < orange < 900 and orange > green:
            states.append("returning")
        elif count:  # the counter says an army is here; an unknown badge is left alone
            states.append("gathering")
        else:  # counter unreadable and no badge -> no army in this slot
            break
    return states


def open_gather_dialog(x, y):
    """goto the deposit and open its army picker. Returns the gem's pixel position or None."""
    rok.goto(x, y)
    gem = gem_near_centre(rok.shot())
    if gem is None:
        return None
    rok.tap(*gem, 1.5)
    gather = find_button(rok.shot(), BTN_GATHER)
    if gather is None:
        rok.tap(1240, 400, 1.0)
        return None
    rok.tap(*gather, 1.5)
    return gem


def redirect_army(slot, x, y):
    """Send the already-deployed army in queue slot `slot` to the deposit near x,y.

    Only valid with all 5 queues in use (otherwise the picker has an extra 'new army' row).
    Returns 'marched', 'blocked' or 'no_gem'.
    """
    gem = open_gather_dialog(x, y)
    if gem is None:
        return "no_gem"
    rok.tap(1211, PICK_ROW_Y[slot], 1.5)
    march = find_button(rok.shot(), BTN_MARCH_SMALL, 0.75)
    if march is None:
        rok.tap(560, 640, 1.0)  # empty ground closes the picker
        raise RuntimeError("no march button after picking the army")
    rok.tap(*march, 3.0)
    after = gem_near_centre(rok.shot())
    if after is None or abs(after[0] - gem[0]) + abs(after[1] - gem[1]) > 40:
        return "blocked"
    return "marched"


BTN_FILTER = cv2.imread(str(HERE / "btn_filter.png"))


def is_strategic(im):
    """Zoomed out past the icon view: the strategic map with its filter panel, where gem deposits are not drawn."""
    return find_button(im, BTN_FILTER) is not None


def to_far():
    """Zoom out to the far (icon) view used for scanning.

    ponytail: stops at the first icon level (zoom ~1.4-1.8 of the reference). One level further
    out still shows gem icons and would cover more per frame, but LDPlayer's zoom steps are
    uneven: aiming for it overshot onto the strategic map (no gem icons there) or, stepping
    back, into the close view. Needs a finer zoom than `ldconsole zoomOut` to be worth it.
    """
    for _ in range(10):  # this took 1 to 4+ steps
        im = rok.shot()
        if is_strategic(im):
            rok.zoom("In", 1, wait=2.5)
        elif is_far(im):
            return
        else:
            rok.zoom("Out", 1, wait=2.5)
    raise RuntimeError("could not reach the far map view")


def to_near():
    """Back to the close view used for sending armies (tapping the far view zooms in)."""
    for _ in range(4):  # a tap only zooms in from the icon view, not from the strategic map
        if not is_strategic(rok.shot()):
            break
        rok.zoom("In", 1, wait=2.5)
    if is_far(rok.shot()):
        rok.tap(640, 330, 2.5)
        if is_far(rok.shot()):
            raise RuntimeError("could not leave the far map view")
        rok.tap(1240, 400, 1.0)  # in case the tap also selected something


def sweep(x0, y0, x1, y1, moved):
    """Endless zig-zag over the rectangle in the far view; yields (camera x, camera y, frame).

    The map is dragged like a player would and the position read back from the readout:
    ~2 s a frame, where typing coordinates into the search box took ~8 s. Set moved[0] after
    taking the camera elsewhere and the sweep jumps back to where it was.
    """
    pos, heading, stuck = (x0, y0), 1, 0
    moved[0] = True
    while True:
        if moved[0]:
            rok.goto(*pos)
            moved[0] = False
        im = rok.shot()
        try:
            seen = rok.camera_coords(im)
        except RuntimeError:  # glare behind the readout: go where we meant to be instead
            rok.goto(*pos)
            seen, im = pos, rok.shot()
        stuck = stuck + 1 if seen == pos and stuck else int(seen == pos)
        pos = x, y = seen
        yield x, y, im
        if moved[0]:  # the caller went off to give orders: come back before dragging on
            continue
        row_done = x >= x1 if heading > 0 else x <= x0
        if stuck > 1 or (row_done and y >= y1):  # the map edge stopped us, or the last row is done
            pos, heading, stuck, moved[0] = (x0, y0), 1, 0, True
        elif row_done:
            rok.swipe(640, 180, 640, 540, 1000, 0.6)  # finger down: the camera goes up the map (+y)
            heading = -heading
        elif heading > 0:
            rok.swipe(1000, 400, 250, 400, 1000, 0.6)  # ~12 tiles; a frame shows ~20, and some drags run long
        else:
            rok.swipe(250, 400, 1000, 400, 1000, 0.6)


def farm(x0, y0, x1, y1, slots):
    """Keep every march queue gathering gems inside the given map rectangle, forever.

    While armies gather, the map is swept for more deposits; every frame of the sweep
    (one per ~8 s) also reads the queue panel. As soon as an army has emptied its deposit
    it is sent to the nearest known one instead of walking home, and whenever a queue is
    free (an army came home full) a fresh army goes out.
    """
    import gems

    def log(*a):
        print(time.strftime("%H:%M:%S"), *a, flush=True)

    def near(a, b, r=3):
        return abs(a[0] - b[0]) <= r and abs(a[1] - b[1]) <= r

    todo = []  # known deposits nobody was sent to yet
    # Where marches got through and where the game refused them (a pass in the way). A pass
    # shuts off a whole side of the map: in one 20-minute run 6 of 10 deposits lay behind the
    # same one and each cost ~40 s to find out.
    # ponytail: nearest-neighbour guess, relearned every run; a deposit just in front of a
    # pass can be skipped wrongly until a march nearer to it succeeds.
    reached, blocked = [CITY], []

    def behind_a_pass(tile):
        def nearest_d2(points):
            return min((p[0] - tile[0]) ** 2 + (p[1] - tile[1]) ** 2 for p in points)

        return bool(blocked) and nearest_d2(blocked) < nearest_d2(reached)
    # deposit -> time we sent an army there (or found it unreachable); kept on disk so a
    # restart does not send a second army to a deposit one of ours is already emptying
    used_file = HERE / f"used{rok.INDEX}.json"
    used = {tuple(m): t for m, t in json.loads(used_file.read_text())} if used_file.exists() else {}
    at = {}  # queue slot -> tile the army in that slot was last sent to
    gathering_since = {}  # queue slot -> when we watched it arrive and start gathering
    was_marching = set()  # slots seen marching, so their next 'gathering' is a real start
    returning_reads = {}  # queue slot -> consecutive frames read as 'returning'
    moved = [True]  # the camera left the sweep's position (orders were given)
    frames = sweep(x0, y0, x1, y1, moved)

    def read_states(im):
        """Queue states with a slot reported 'returning' only when that is certain:
        read twice in a row, and - if we watched the army start - not before a deposit
        could possibly be empty. Until then it counts as still gathering."""
        states = army_states(im)
        now = time.time()
        if len(states) != len(at):
            # ponytail: an army went home and the panel re-packed, so slot -> army is
            # lost; forget the clocks and fall back to "nearest to the city".
            at.clear()
            at.update({s: CITY for s in range(len(states))})
            gathering_since.clear()
            was_marching.clear()
            returning_reads.clear()
        for slot, state in enumerate(states):
            if state == "marching":
                was_marching.add(slot)
                gathering_since.pop(slot, None)
            elif state == "gathering" and slot in was_marching:
                was_marching.discard(slot)
                gathering_since[slot] = now
            if state != "returning":
                returning_reads.pop(slot, None)
                continue
            returning_reads[slot] = returning_reads.get(slot, 0) + 1
            too_early = now - gathering_since.get(slot, 0) < MIN_GATHER_S
            if returning_reads[slot] < 2 or too_early:
                states[slot] = "gathering"
        return states

    def nearest(origin):
        return min(todo, key=lambda m: (m[0] - origin[0]) ** 2 + (m[1] - origin[1]) ** 2)

    # The queue panel was read as "a queue is free" on an account whose five queues were all
    # out; the game then offers no new army. Believe the game and stop asking for a while.
    full_until = 0

    def needs_orders(states):
        return (len(states) < 5 and time.time() > full_until) or "returning" in states

    failures = 0
    while True:
        try:
            # --- sweep for deposits until an army needs orders -------------------------
            to_far()
            for cx, cy in ((x0, y0), ((x0 + x1) // 2, (y0 + y1) // 2), (x1, y1)):
                try:  # featureless or animated terrain (water) can defeat one calibration spot
                    zoom = gems.measure_zoom(cx, cy)
                    break
                except RuntimeError as e:
                    log(e)
            else:
                raise RuntimeError("zoom calibration failed at every spot")
            moved[0] = True
            for x, y, im in frames:
                for px, py in gems.gems_in_frame(im):
                    tile = tuple(round(float(v)) for v in gems.to_tile(x, y, px, py, zoom))
                    # ponytail: a deposit we used is forgotten after 45 min so a respawn at
                    # the same spot is picked up again
                    recent = [m for m, t in used.items() if time.time() - t < 2700]
                    if not any(near(tile, m) for m in todo + recent) and not behind_a_pass(tile):
                        todo.append(tile)
                        log("found deposit", tile, f"({len(todo)} waiting)")
                states = read_states(im)
                # Every queue busy and deposits in hand: more sweeping finds nothing we can
                # use, and hours of non-stop dragging is what no player does. Sit still and
                # glance at the queue until an army needs orders.
                while len(todo) >= 3 and not needs_orders(states) and (len(states) == 5 or time.time() < full_until):
                    time.sleep(random.uniform(20, 30))
                    states = read_states(rok.shot())
                if todo and needs_orders(states):
                    break
            # --- give orders ---------------------------------------------------------
            to_near()
            while todo:
                states = read_states(rok.shot())
                if len(states) < 5 and time.time() > full_until:
                    target = nearest(CITY)
                    result = send_new_army(*target, slots)
                    log("new army ->", target, result)
                    if result == "full":
                        full_until = time.time() + 300
                        continue  # the deposit stays on the list for an army that finishes
                    if result == "marched":
                        # The queue panel lists the newest army first (seen with the first five
                        # sent), so every tracked slot moves down one and the new army is slot 0.
                        for d in (at, gathering_since, returning_reads):
                            shifted = {k + 1: v for k, v in d.items()}
                            d.clear()
                            d.update(shifted)
                        shifted_marching = {k + 1 for k in was_marching}
                        was_marching.clear()
                        was_marching.update(shifted_marching)
                        at[0] = target
                elif "returning" in states:
                    slot = states.index("returning")
                    target = nearest(at[slot])
                    result = redirect_army(slot, *target)
                    log(f"slot {slot} finished at {at[slot]} ->", target, result)
                    if result == "marched":
                        at[slot] = target
                        gathering_since.pop(slot, None)
                        returning_reads.pop(slot, None)
                else:
                    break
                todo.remove(target)
                if result in ("marched", "blocked"):
                    (reached if result == "marched" else blocked).append(target)
                used[target] = time.time()
                used_file.write_text(json.dumps([[m, t] for m, t in used.items() if time.time() - t < 2700]))

            failures = 0
        except RuntimeError as e:
            # A UI check failed (zoom step ignored, popup in the way, ...). Nothing was
            # tapped past the failed check, so start the cycle again with what we know.
            failures += 1
            frames = sweep(x0, y0, x1, y1, moved)  # a generator that raised is finished
            cv2.imwrite(str(HERE / f"fail{rok.INDEX}_{failures}.png"), rok.shot())  # what the screen looked like
            log("recovering from:", e)
            if failures >= 5:
                raise
            if failures == 3:
                # Seen: the client got into a state where the emulator's zoom gesture only
                # tapped the map. Nothing on screen showed it; restarting the game cured it.
                log("restarting the game")
                rok.adb("shell", "am", "force-stop", "com.rok.gp.vn")
                time.sleep(2)
                open_game()
            time.sleep(5)
            # Event pop-ups ("Kỳ Sơ Khảo sắp bắt đầu...") are a yes/no dialog: red KHÔNG
            # left, cyan CÓ right. KHÔNG only ever declines, so it is the safe way out.
            im = rok.shot()
            no, yes = (im[490:530, x:x + 200].reshape(-1, 3).mean(0) for x in (380, 710))
            if no[2] > 170 and no[0] < 90 and yes[0] > 200 and yes[2] < 60:
                log("closing a yes/no pop-up with KHÔNG")
                rok.tap(477, 511, 1.5)

if __name__ == "__main__":
    import signal
    import sys

    signal.signal(signal.SIGTERM, rok.stop_when_safe)  # /stop must not cut a drag in half

    # usage: farm.py SLOTS                           scan around our own city
    #        farm.py X0 Y0 X1 Y1 SLOTS [CITY_X CITY_Y]
    # SLOTS = the saved armies to use, as digits: 12345 (ponytail: slots 1-9 only; the
    # new-army screen shows five buttons without scrolling anyway)
    # (ROK_INDEX picks the emulator)
    args = list(map(int, sys.argv[1:]))
    open_game()
    if len(args) == 1:
        CITY = city_coords()
        args = [max(0, CITY[0] - SCAN_RADIUS), max(0, CITY[1] - SCAN_RADIUS),
                min(1199, CITY[0] + SCAN_RADIUS), min(1199, CITY[1] + SCAN_RADIUS), args[0]]
        print(time.strftime("%H:%M:%S"), "city at", CITY, "scanning", args[:4], flush=True)
    elif len(args) > 5:
        CITY = tuple(args[5:7])
    farm(*args[:4], [int(d) for d in str(args[4])])
