"""Gait identifier - step 3 - the live demo.

The sketch sends an IMU reading 100 times a second:  imu(n, ax, ay, az, gx, gy, gz)  (n = counter, a in g, gyro in degrees/second).
This app keeps the last 2 seconds (200 samples). Every 0.5 seconds (50 new samples) it runs BOTH trained models on that window:

    Model A  looks at one number: the peak of ax (the axis along the shin) in the window
    Model B  looks at 34 numbers made from all six IMU outputs

and shows both answers on the web page (port 7000) and on the LED matrix (Model A's letter on the left, Model B's on the right).
The windows are cut exactly as in training, with the same code (gait_features.py), so the live answers match the offline results.

Test mode: type a name and tap what the person is REALLY doing. Every window is then scored for both models, the page shows a live
accuracy for each, and every window is appended to  assets/data/live_log.csv  (time, person, truth, model A, model B, A's number).
"""

import collections
import csv
import datetime
import math
import os
import re
import threading
import time
from pathlib import Path

from arduino.app_utils import *
from arduino.app_bricks.web_ui import WebUI

import numpy as np                     # after the board libraries, as in the sumo app that already ran on this board
import gait_features as gf
from gait_predict import GaitModels

HERE = Path(__file__).resolve().parent
MODELS_PATH = HERE / "gait_models.json"
DATA_DIR = Path(os.environ.get("GAIT_DATA_DIR") or HERE.parent / "assets" / "data")
LABELS = gf.LABELS
WIN, STEP = gf.WIN, gf.STEP
MAX_SPAN = 1.05          # a window may cover up to 5% more counter steps than samples (a few lost samples are tolerated)
HISTORY = 120            # windows kept for the history strips: 60 seconds
NO_DATA_S = 1.0          # no sample for this long: the stream has stopped
GAUGE = (-1.1, 1.1)      # the range of Model A's number line on the page


def clean_name(text):
    return re.sub(r"[^A-Za-z0-9 _-]", "", str(text or "")).strip()[:20]


def idx(label):
    return LABELS.index(label) if label in LABELS else -1


def path_for_page(path):
    """The questions a tree asked, as the page shows them."""
    out = []
    for name, value, threshold, yes in path:
        text, unit = gf.describe_feature(name)
        out.append({"name": name, "text": text, "unit": unit, "value": round(value, 2), "threshold": round(threshold, 2), "yes": bool(yes)})
    return out


class Live:
    """All the live logic, with no web page and no board in it, so it can be tested on its own."""

    def __init__(self, models, log_path, clock=time.monotonic, wall=datetime.datetime.now):
        self.models, self.log_path, self.clock, self.wall = models, Path(log_path), clock, wall
        self.lock = threading.RLock()
        self.buf = collections.deque(maxlen=WIN)               # (n, ax, ay, az, gx, gy, gz) of the last 2 seconds
        self.since = 0                                         # samples since the last window was cut
        self.pending = collections.deque(maxlen=4)             # windows cut by the Bridge thread, waiting for tick()
        self.arrivals = collections.deque()                    # arrival times of the last second, to measure the rate
        self.last_arrival = None
        self.recent = collections.deque(maxlen=300)            # (ax, |rotation|) of the last 3 seconds, for the plot
        self.hist_a = collections.deque(maxlen=HISTORY)        # raw answers of the last 60 seconds, as label numbers
        self.hist_b = collections.deque(maxlen=HISTORY)
        self.raw = collections.deque(maxlen=3)                 # the last three raw answers, for smoothing
        self.last = None                                       # the most recent analysis
        self.smooth = True
        self.truth, self.person = None, ""
        self.skipped = 0
        self.tally = self._empty_tally()
        self.segments = [{"label": l, "lo": lo, "hi": hi} for l, lo, hi in models.a_segments()]

    # ---- the stream ----------------------------------------------------------------------------------------------
    def add_sample(self, n, ax, ay, az, gx, gy, gz):
        now = self.clock()
        with self.lock:
            if self.last_arrival is not None and now - self.last_arrival > NO_DATA_S:
                self.buf.clear(); self.pending.clear(); self.raw.clear(); self.since = 0; self.last = None      # the stream stopped and came back
            self.last_arrival = now
            self.arrivals.append(now)
            while self.arrivals and now - self.arrivals[0] > 1.0:
                self.arrivals.popleft()
            self.recent.append((ax, math.sqrt(gx * gx + gy * gy + gz * gz)))
            self.buf.append((n, ax, ay, az, gx, gy, gz))
            self.since += 1
            if len(self.buf) == WIN and self.since >= STEP:    # the first window as soon as 2 s are in, then one every 50 samples
                self.since = 0
                self.pending.append(list(self.buf))

    def imu_rate(self):
        with self.lock:
            now = self.clock()
            while self.arrivals and now - self.arrivals[0] > 1.0:
                self.arrivals.popleft()
            return len(self.arrivals)

    def silent(self):
        """True when nothing has arrived for a second (or ever). A partly filled one-second count right after a restart is NOT silence."""
        with self.lock:
            return self.last_arrival is None or self.clock() - self.last_arrival > NO_DATA_S

    # ---- the models ----------------------------------------------------------------------------------------------
    def tick(self):
        """Run both models on every window that is waiting. Returns the list of analyses made."""
        with self.lock:
            windows = list(self.pending)
            self.pending.clear()
        done = []
        for w in windows:
            if w[-1][0] - w[0][0] + 1 > WIN * MAX_SPAN:        # too many samples were lost in this window: do not guess
                with self.lock:
                    self.skipped += 1
                continue
            info = self.models.analyze(np.array([s[1:] for s in w], dtype=float))
            with self.lock:
                self._record(info)
            done.append(info)
        return done

    def _record(self, info):
        self.last = info
        self.hist_a.append(idx(info["a"]))
        self.hist_b.append(idx(info["b"]))
        self.raw.append((info["a"], info["b"]))
        if self.truth:
            t = self.tally
            t["windows"] += 1
            t["a_correct"] += info["a"] == self.truth
            t["b_correct"] += info["b"] == self.truth
            row = t["by_label"][self.truth]
            row["n"] += 1
            row["a"] += info["a"] == self.truth
            row["b"] += info["b"] == self.truth
            if info["a"] != info["b"]:
                t["disagree"]["n"] += 1
                t["disagree"]["a_right"] += info["a"] == self.truth
                t["disagree"]["b_right"] += info["b"] == self.truth
            self._log(info)

    def _log(self, info):
        new = not self.log_path.exists()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "person", "truth", "model_a", "model_b", "a_number"])
            w.writerow([self.wall().strftime("%Y-%m-%d %H:%M:%S"), self.person, self.truth, info["a"], info["b"], "%.4f" % info["a_value"]])

    def _shown(self):
        """The labels the page and the LED show: the latest answers, or the majority of the last three when smoothing is on."""
        if not self.raw:
            return None, None
        out = []
        for k in (0, 1):
            votes = [r[k] for r in self.raw]
            best = max(set(votes), key=lambda v: (votes.count(v), v == votes[-1]))      # ties go to the most recent answer
            out.append(best if self.smooth else votes[-1])
        return out[0], out[1]

    # ---- commands from the page ----------------------------------------------------------------------------------
    @staticmethod
    def _empty_tally():
        return {"windows": 0, "a_correct": 0, "b_correct": 0, "by_label": {l: {"n": 0, "a": 0, "b": 0} for l in LABELS},
                "disagree": {"n": 0, "a_right": 0, "b_right": 0}}

    def set_truth(self, label):
        if label not in (None, *LABELS):
            raise ValueError("Pick one of: " + ", ".join(LABELS) + ".")
        with self.lock:
            self.truth = label

    def set_person(self, text):
        with self.lock:
            self.person = clean_name(text)

    def set_smooth(self, on):
        with self.lock:
            self.smooth = bool(on)

    def reset_tally(self):
        with self.lock:
            self.tally = self._empty_tally()

    # ---- what the page shows -------------------------------------------------------------------------------------
    def snapshot(self):
        with self.lock:
            rate = self.imu_rate()
            mode = "nodata" if self.silent() else ("warming" if self.last is None else "live")
            snap = {"mode": mode, "imu_rate": rate, "warm": round(min(1.0, len(self.buf) / WIN), 2), "skipped": self.skipped,
                    "smooth": self.smooth, "truth": self.truth, "person": self.person, "tally": self.tally,
                    "segments": self.segments, "gauge": list(GAUGE), "labels": LABELS,
                    "a": None, "b": None, "raw_a": None, "raw_b": None, "agree": None, "a_name": None, "a_value": None,
                    "a_path": [], "b_path": []}
            if mode == "live":
                a, b = self._shown()
                snap.update(a=a, b=b, raw_a=self.last["a"], raw_b=self.last["b"], agree=(a == b), a_name=self.last["a_name"],
                            a_value=round(self.last["a_value"], 3), a_path=path_for_page(self.last["a_path"]), b_path=path_for_page(self.last["b_path"]))
            recent = list(self.recent)[::3]
            snap["recent_ax"] = [round(v, 2) for v, _ in recent]
            snap["recent_g"] = [round(g) for _, g in recent]
            snap["hist_a"], snap["hist_b"] = list(self.hist_a), list(self.hist_b)
            return snap


# ---- the glue: the page, the sketch --------------------------------------------------------------------------------
live = Live(GaitModels(MODELS_PATH), DATA_DIR / "live_log.csv")
print("models loaded; test-mode log:", DATA_DIR / "live_log.csv", flush=True)


def on_imu(n, ax, ay, az, gx, gy, gz):
    """Called by the sketch for every reading, on the Bridge's own thread: keep it light."""
    live.add_sample(n, ax, ay, az, gx, gy, gz)


Bridge.provide("imu", on_imu)
ui = WebUI()


def notice(level, text):
    ui.send_message("notice", {"level": level, "text": text})


def on_cmd(sid, data):
    try:
        action = (data or {}).get("action")
        if action == "truth":
            live.set_truth(data.get("label") or None)
        elif action == "person":
            live.set_person(data.get("name", ""))
        elif action == "smooth":
            live.set_smooth(data.get("on", True))
        elif action == "reset":
            live.reset_tally()
            notice("info", "Scores cleared. (The log file keeps everything.)")
        elif action == "refresh":
            pass
        else:
            notice("warn", "Unknown command.")
            return
        ui.send_message("state", live.snapshot())
    except ValueError as e:
        notice("warn", str(e))
    except Exception as e:                       # never let a bad command kill the app
        notice("warn", "Something went wrong: " + str(e)[:120])


ui.on_message("cmd", on_cmd)
ui.on_connect(lambda sid: ui.send_message("state", live.snapshot()))

led_state = {"sent": None}
ticks = {"n": 0}


def loop():
    time.sleep(0.1)
    live.tick()
    snap = live.snapshot()
    ticks["n"] += 1
    if ticks["n"] % 2 == 0:                                          # 5 times a second is plenty for a page
        ui.send_message("state", snap)
    want = (idx(snap["a"]), idx(snap["b"]))                          # (-1, -1) = nothing to show: the LED shows one dot
    if want != led_state["sent"]:
        try:
            Bridge.call("show", want[0], want[1], timeout=2)
            led_state["sent"] = want
        except Exception as e:
            if ticks["n"] % 100 == 0:
                print("(LED matrix not answering: " + str(e)[:60] + ")", flush=True)


App.run(user_loop=loop)
