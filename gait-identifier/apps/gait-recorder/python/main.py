"""Gait identifier - step 2 - the recorder.

The sketch sends an IMU reading 100 times a second:  imu(n, ax, ay, az, gx, gy, gz)  (n = counter, a in g, gyro in degrees/second).
This app turns that stream into labelled CSV files. Open the web page (port 7000) on a phone or laptop on the same network:

    1. type who is wearing it, tap an activity (still / walk / run / bike), choose a duration
    2. press START: a 5 second countdown (get into position, start walking), then it records
    3. the LED matrix on the board shows the state: dots counting down, a bar filling up while recording, a tick when saved
    4. files appear in the list on the page; download them one by one or all at once as a zip

Files go to  assets/data/  (the web page serves that folder, so every file has a link):
    <person>__<activity>__<date>-<time>.csv     columns: n, ax, ay, az, gx, gy, gz   (n counts samples, so a lost sample shows as a jump)
    manifest.csv                                one row per recording: who, what, when, how many samples, how many were lost

A recording with more than 2% of its samples lost is flagged on the page: delete it and record it again.
Training should ignore about the first and last second of every file (starting and stopping are not the activity).
"""

import collections
import csv
import datetime
import math
import os
import re
import threading
import time
import zipfile
from pathlib import Path

from arduino.app_utils import *
from arduino.app_bricks.web_ui import WebUI

LABELS = ("still", "walk", "run", "bike")
RATE_HZ = 100                   # samples per second the sketch sends
COUNTDOWN_S = 5                 # seconds between pressing START and the first recorded sample
MIN_SAVE_S = 2.0                # stopping a recording earlier than this throws it away
MAX_LOST_PCT = 2.0              # more lost samples than this and the file is flagged
DEFAULT_DURATION_S = 60
MANIFEST_FIELDS = ["file", "subject", "label", "note", "start", "seconds", "samples", "dropped", "lost_pct"]
DATA_DIR = Path(os.environ.get("GAIT_DATA_DIR") or Path(__file__).resolve().parent.parent / "assets" / "data")


def clean(text, allowed, limit):
    return re.sub(allowed, "", str(text or "")).strip()[:limit]


class Recorder:
    """All the recording logic, with no web page and no board in it, so it can be tested on its own."""

    def __init__(self, data_dir, clock=time.monotonic, wall=datetime.datetime.now):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clock, self.wall = clock, wall
        self.lock = threading.RLock()
        self.mode = "idle"                       # idle -> countdown -> recording -> idle
        self.subject = self.label = self.note = ""
        self.duration = DEFAULT_DURATION_S
        self.t_mode = 0.0
        self.t_start_wall = None
        self.rec = []                            # (n, ax, ay, az, gx, gy, gz) of the recording in progress
        self.recent = collections.deque(maxlen=300)        # (|a|, |gyro|) of the last 3 seconds, for the live plot
        self.arrivals = collections.deque()      # arrival times of the last second, to measure the rate
        self.last_saved = None
        self.rows = self._load_manifest()

    # ---- the stream ----------------------------------------------------------------------------------------------
    def add_sample(self, n, ax, ay, az, gx, gy, gz):
        now = self.clock()
        with self.lock:
            self.arrivals.append(now)
            while self.arrivals and now - self.arrivals[0] > 1.0:
                self.arrivals.popleft()
            self.recent.append((math.sqrt(ax * ax + ay * ay + az * az), math.sqrt(gx * gx + gy * gy + gz * gz)))
            if self.mode == "recording":
                self.rec.append((n, ax, ay, az, gx, gy, gz))

    def imu_rate(self):
        with self.lock:
            now = self.clock()
            while self.arrivals and now - self.arrivals[0] > 1.0:
                self.arrivals.popleft()
            return len(self.arrivals)

    # ---- commands from the page ----------------------------------------------------------------------------------
    def start(self, subject, label, note="", duration=DEFAULT_DURATION_S):
        with self.lock:
            if self.mode != "idle":
                raise ValueError("A recording is already running: stop it first.")
            subject = clean(subject, r"[^A-Za-z0-9_-]", 20)
            if not subject:
                raise ValueError("Type who is wearing it (letters and digits).")
            if label not in LABELS:
                raise ValueError("Pick an activity: " + ", ".join(LABELS) + ".")
            try:
                duration = int(float(duration))
            except (TypeError, ValueError):
                raise ValueError("The duration must be a number of seconds.")
            duration = max(5, min(600, duration))
            if self.imu_rate() < 50:
                raise ValueError("No IMU data is arriving (about %d a second). Check the sensor before recording." % self.imu_rate())
            self.subject, self.label, self.duration = subject, label, duration
            self.note = clean(note, r"[^A-Za-z0-9 _.-]", 40)
            self.mode, self.t_mode = "countdown", self.clock()
            self.rec = []

    def stop(self):
        """Stop now. Returns what happened: a saved-file dict, {'discarded': reason}, or None if nothing was running."""
        with self.lock:
            if self.mode == "countdown":
                self.mode = "idle"
                return {"discarded": "cancelled during the countdown"}
            if self.mode == "recording":
                if self.clock() - self.t_mode < MIN_SAVE_S:
                    self.mode, self.rec = "idle", []
                    return {"discarded": "stopped within %g seconds" % MIN_SAVE_S}
                return self._finish()
            return None

    def tick(self):
        """Call about 10 times a second. Moves countdown -> recording -> saved. Returns a result dict when a recording ends."""
        with self.lock:
            now = self.clock()
            if self.mode == "countdown" and now - self.t_mode >= COUNTDOWN_S:
                self.mode, self.t_mode, self.rec = "recording", now, []
                self.t_start_wall = self.wall()
            elif self.mode == "recording" and now - self.t_mode >= self.duration:
                return self._finish()
            return None

    # ---- saving --------------------------------------------------------------------------------------------------
    def _finish(self):
        rec, self.rec, self.mode = self.rec, [], "idle"
        if not rec:
            return {"discarded": "no samples arrived during the recording"}
        stamp = (self.t_start_wall or self.wall()).strftime("%Y%m%d-%H%M%S")
        name = "%s__%s__%s.csv" % (self.subject, self.label, stamp)
        k = 2
        while (self.dir / name).exists():
            name = "%s__%s__%s-%d.csv" % (self.subject, self.label, stamp, k)
            k += 1
        with open(self.dir / name, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["n", "ax", "ay", "az", "gx", "gy", "gz"])
            for n, ax, ay, az, gx, gy, gz in rec:
                w.writerow([n, "%.4f" % ax, "%.4f" % ay, "%.4f" % az, "%.3f" % gx, "%.3f" % gy, "%.3f" % gz])
        expected = rec[-1][0] - rec[0][0] + 1                       # the counter says how many samples there should be
        dropped = max(0, expected - len(rec))
        row = {"file": name, "subject": self.subject, "label": self.label, "note": self.note,
               "start": (self.t_start_wall or self.wall()).strftime("%Y-%m-%d %H:%M:%S"),
               "seconds": round(expected / RATE_HZ, 1), "samples": len(rec), "dropped": dropped,
               "lost_pct": round(100.0 * dropped / max(1, expected), 2)}
        self.rows.append(row)
        self._write_manifest()
        self.last_saved = dict(row, flagged=row["lost_pct"] > MAX_LOST_PCT)
        return self.last_saved

    def _load_manifest(self):
        path = self.dir / "manifest.csv"
        rows = []
        if path.exists():
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("file") and (self.dir / r["file"]).exists():
                        for key in ("samples", "dropped"):
                            r[key] = int(float(r.get(key) or 0))
                        for key in ("seconds", "lost_pct"):
                            r[key] = float(r.get(key) or 0)
                        rows.append(r)
        return rows

    def _write_manifest(self):
        with open(self.dir / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            w.writeheader()
            w.writerows(self.rows)

    # ---- files ---------------------------------------------------------------------------------------------------
    def _present(self):
        """The manifest rows whose file is still in the folder (someone may have removed one by hand)."""
        return [r for r in self.rows if (self.dir / r["file"]).exists()]

    def files(self):
        with self.lock:
            return [dict(r, flagged=r["lost_pct"] > MAX_LOST_PCT) for r in reversed(self._present())]

    def delete(self, name):
        with self.lock:
            hit = [r for r in self.rows if r["file"] == name]
            if not hit:
                raise ValueError("No such recording.")
            try:
                (self.dir / name).unlink()
            except FileNotFoundError:
                pass
            self.rows = [r for r in self.rows if r["file"] != name]
            self._write_manifest()

    def make_zip(self):
        with self.lock:
            name = "all_data.zip"
            with zipfile.ZipFile(self.dir / name, "w", zipfile.ZIP_DEFLATED) as z:
                for r in self._present():
                    z.write(self.dir / r["file"], r["file"])
                if (self.dir / "manifest.csv").exists():
                    z.write(self.dir / "manifest.csv", "manifest.csv")
            return name

    def totals(self):
        """Seconds recorded per activity and per person, so you can see if the data set is balanced."""
        with self.lock:
            out = {}
            for r in self._present():
                if r["lost_pct"] <= MAX_LOST_PCT:
                    out.setdefault(r["subject"], {}).setdefault(r["label"], 0.0)
                    out[r["subject"]][r["label"]] = round(out[r["subject"]][r["label"]] + r["seconds"], 1)
            return out

    # ---- what the page shows -------------------------------------------------------------------------------------
    def snapshot(self):
        with self.lock:
            now = self.clock()
            rate = self.imu_rate()
            snap = {"mode": self.mode, "label": self.label, "subject": self.subject, "duration": self.duration,
                    "imu_rate": rate, "imu_ok": rate >= 80, "samples": len(self.rec), "countdown_left": 0, "remaining": 0, "progress": 0}
            if self.mode == "countdown":
                snap["countdown_left"] = max(0, int(math.ceil(COUNTDOWN_S - (now - self.t_mode))))
            elif self.mode == "recording":
                elapsed = now - self.t_mode
                snap["remaining"] = max(0, int(math.ceil(self.duration - elapsed)))
                snap["progress"] = min(1.0, elapsed / self.duration)
            recent = list(self.recent)[::3]
            snap["recent_a"] = [round(a, 2) for a, _ in recent]
            snap["recent_g"] = [round(g) for _, g in recent]
            return snap


# ---- the glue: the page, the sketch --------------------------------------------------------------------------------
recorder = Recorder(DATA_DIR)
print("recordings are saved in", DATA_DIR, flush=True)


def on_imu(n, ax, ay, az, gx, gy, gz):
    """Called by the sketch for every reading, on the Bridge's own thread: keep it light."""
    recorder.add_sample(n, ax, ay, az, gx, gy, gz)


Bridge.provide("imu", on_imu)
ui = WebUI()


led_state = {"sent": None, "saved_at": -99.0}      # what the LED matrix shows now, and when a file was last saved (for the tick)
ticks = {"n": 0}


def notice(level, text):
    ui.send_message("notice", {"level": level, "text": text})


def push_files():
    ui.send_message("files", {"files": recorder.files(), "totals": recorder.totals(), "zip": None})


def report(result):
    """Tell the page how a recording ended."""
    if not result:
        return
    if "discarded" in result:
        notice("warn", "Not saved: " + result["discarded"] + ".")
    elif result["flagged"]:
        notice("warn", "Saved %s, but %.1f%% of the samples were lost on the way: delete it and record it again." % (result["file"], result["lost_pct"]))
    else:
        notice("ok", "Saved %s (%.0f s, %d samples, %.1f%% lost)." % (result["file"], result["seconds"], result["samples"], result["lost_pct"]))
    if "discarded" not in result:
        led_state["saved_at"] = time.monotonic()
    push_files()


def on_cmd(sid, data):
    try:
        action = (data or {}).get("action")
        if action == "start":
            recorder.start(data.get("subject"), data.get("label"), data.get("note", ""), data.get("duration", DEFAULT_DURATION_S))
            notice("info", "Get ready: recording starts in %d seconds." % COUNTDOWN_S)
        elif action in ("stop", "cancel"):
            report(recorder.stop())
        elif action == "delete":
            recorder.delete(str(data.get("file", "")))
            push_files()
        elif action == "zip":
            ui.send_message("files", {"files": recorder.files(), "totals": recorder.totals(), "zip": recorder.make_zip()})
        elif action == "refresh":
            push_files()
        else:
            notice("warn", "Unknown command.")
    except ValueError as e:
        notice("warn", str(e))
    except Exception as e:                       # never let a bad command kill the app
        notice("warn", "Something went wrong: " + str(e)[:120])


ui.on_message("cmd", on_cmd)
ui.on_connect(lambda sid: push_files())

def led_for(snap):
    """(mode, cols) for the LED matrix: 0 idle, 1 countdown dots, 2 recording bar, 3 saved tick."""
    if snap["mode"] == "countdown":
        return 1, snap["countdown_left"]
    if snap["mode"] == "recording":
        return 2, int(round(13 * snap["progress"]))
    if time.monotonic() - led_state["saved_at"] < 2.0:
        return 3, 0
    return 0, 0


def loop():
    time.sleep(0.1)
    report(recorder.tick())
    snap = recorder.snapshot()
    ticks["n"] += 1
    if ticks["n"] % 2 == 0:                                          # 5 times a second is plenty for a page
        ui.send_message("state", snap)
    want = led_for(snap)
    if want != led_state["sent"]:
        try:
            Bridge.call("led", want[0], want[1], timeout=2)
            led_state["sent"] = want
        except Exception as e:
            if ticks["n"] % 100 == 0:
                print("(LED matrix not answering: " + str(e)[:60] + ")", flush=True)


App.run(user_loop=loop)
