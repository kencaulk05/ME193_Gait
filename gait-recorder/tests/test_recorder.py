"""Tests for python/main.py: the Recorder logic and the glue to the page and the board. No board needed."""
import csv, datetime, importlib.util, io, os, sys, tempfile, threading, time, types, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = HERE.parent / "python" / "main.py"
problems = 0

def expect(label, cond, detail=""):
    global problems
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"   [{detail}]" if detail else ""))
    problems += (not cond)

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s

def load_main(clock, data_dir):
    """Import main.py with stand-ins for arduino.app_utils / arduino.app_bricks.web_ui and a fake clock."""
    log = {"messages": [], "handlers": {}, "led": [], "provided": {}, "led_fails": False}
    class Bridge:
        @staticmethod
        def provide(name, fn): log["provided"][name] = fn
        @staticmethod
        def call(name, *args, timeout=10):
            if name == "led":
                if log["led_fails"]: raise TimeoutError("no answer")
                log["led"].append(args)
                return args[0]
    class App:
        @staticmethod
        def run(user_loop=None): log["loop"] = user_loop
    class WebUI:
        def on_message(self, kind, fn): log["handlers"][kind] = fn
        def on_connect(self, fn): log["handlers"]["connect"] = fn
        def send_message(self, kind, msg, room=None): log["messages"].append((kind, msg))
    u = types.ModuleType("arduino.app_utils"); u.Bridge, u.App = Bridge, App
    w = types.ModuleType("arduino.app_bricks.web_ui"); w.WebUI = WebUI
    pkg = types.ModuleType("arduino"); bricks = types.ModuleType("arduino.app_bricks")
    sys.modules.update({"arduino": pkg, "arduino.app_utils": u, "arduino.app_bricks": bricks, "arduino.app_bricks.web_ui": w})
    os.environ["GAIT_DATA_DIR"] = str(data_dir)
    real = (time.monotonic, time.sleep)
    time.monotonic, time.sleep = clock, clock.sleep
    try:
        spec = importlib.util.spec_from_file_location("gait_recorder_main", MAIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        pass                                        # keep the fake clock installed while the tests run
    return mod, log, real

clock = Clock()
tmp = Path(tempfile.mkdtemp())
mod, log, real_time = load_main(clock, tmp / "glue")
Recorder = mod.Recorder
wall0 = datetime.datetime(2026, 10, 27, 14, 0, 0)

def wall(): return wall0 + datetime.timedelta(seconds=clock.t - 1000.0)

def feed(rec, seconds, hz=100, counter=[0], drop_every=0, shape=None):
    """Advance the fake clock and feed samples at hz; counter keeps running across calls."""
    for _ in range(int(seconds * hz)):
        counter[0] += 1
        clock.t += 1.0 / hz
        if drop_every and counter[0] % drop_every == 0: continue
        v = shape(counter[0]) if shape else (0.0, 0.0, 1.0, 1.0, 2.0, 3.0)
        rec.add_sample(counter[0], *v)

def fresh():
    d = Path(tempfile.mkdtemp(dir=tmp)); return Recorder(d, clock=clock, wall=wall), d

print("1. a whole recording: countdown, record, save")
rec, d = fresh()
feed(rec, 2)
rec.start("kendrick", "walk", "air bike!", 10)
s = rec.snapshot()
expect("mode is countdown and it shows 5 s left", s["mode"] == "countdown" and s["countdown_left"] == 5, str((s["mode"], s["countdown_left"])))
feed(rec, 2.05); rec.tick(); s = rec.snapshot()
expect("2 s later: still countdown, 3 s left", s["mode"] == "countdown" and s["countdown_left"] == 3, str(s["countdown_left"]))
rec.tick(); feed(rec, 3.2); rec.tick()
s = rec.snapshot()
expect("after 5 s it is recording", s["mode"] == "recording", s["mode"])
n_countdown = len(rec.rec)
feed(rec, 4.0); rec.tick(); s = rec.snapshot()
expect("4 s into a 10 s recording: about 6 s remaining, progress about 0.4, samples about 400", s["remaining"] in (6, 7) and 0.35 < s["progress"] < 0.45 and 380 <= s["samples"] <= 420, str((s["remaining"], round(s["progress"], 2), s["samples"])))
result = None
for _ in range(80):
    feed(rec, 0.1); result = rec.tick() or result
expect("it saved by itself at the end", result is not None and "file" in result, str(result and result.get("file")))
expect("file name is person__activity__date-time.csv", result["file"] == "kendrick__walk__20261027-140007.csv", result["file"])
rows = list(csv.reader(open(d / result["file"])))
expect("header is n,ax,ay,az,gx,gy,gz", rows[0] == ["n", "ax", "ay", "az", "gx", "gy", "gz"], str(rows[0]))
expect("about 1000 samples were saved, none from the countdown", 990 <= len(rows) - 1 <= 1010, str(len(rows) - 1))
expect("values are written with fixed decimals", rows[1][1:4] == ["0.0000", "0.0000", "1.0000"] and rows[1][4:] == ["1.000", "2.000", "3.000"], str(rows[1]))
expect("the counter in the file is consecutive", all(int(rows[i + 1][0]) == int(rows[i][0]) + 1 for i in range(1, len(rows) - 1)))
man = list(csv.DictReader(open(d / "manifest.csv")))
expect("manifest has one row with person, activity, note and the sample count", len(man) == 1 and man[0]["subject"] == "kendrick" and man[0]["label"] == "walk" and man[0]["note"] == "air bike" and int(man[0]["samples"]) == len(rows) - 1, str(man[0]))
expect("0% lost and not flagged", result["lost_pct"] == 0 and result["flagged"] is False)
expect("back to idle", rec.snapshot()["mode"] == "idle")

print("2. lost samples are measured from the counter and flagged")
rec, d = fresh()
feed(rec, 1); rec.start("ann", "run", "", 10); feed(rec, 5.2); rec.tick()
feed(rec, 10.2, drop_every=20)                       # 5% of the samples never arrive
r = rec.tick() or rec.stop()
expect("about 5% lost, flagged", r and 4.0 <= r["lost_pct"] <= 6.0 and r["flagged"], str(r and (r["lost_pct"], r["flagged"])))
expect("flagged recordings do not count in the totals", rec.totals() == {}, str(rec.totals()))

print("3. stop early, cancel, throw away short ones")
rec, d = fresh()
feed(rec, 1); rec.start("bo", "still", "", 60); feed(rec, 5.1); rec.tick(); feed(rec, 20); r = rec.stop()
expect("stopping after 20 s saves about 20 s", r and "file" in r and 19 <= r["seconds"] <= 21, str(r and r.get("seconds")))
rec.start("bo", "still", "", 60); feed(rec, 5.1); rec.tick(); feed(rec, 1.0); r = rec.stop()
expect("stopping within 2 s throws it away", r and "discarded" in r and len(rec.files()) == 1, str(r))
rec.start("bo", "still", "", 60); feed(rec, 2); r = rec.stop()
expect("cancelling in the countdown records nothing", r and "discarded" in r and rec.snapshot()["mode"] == "idle", str(r))
expect("stop when idle does nothing", rec.stop() is None)

print("4. the checks on what you type")
rec, d = fresh(); feed(rec, 1)
def bad(*a, **k):
    try: rec.start(*a, **k); rec.mode = "idle"; return None
    except ValueError as e: return str(e)
expect("no person", bad("", "walk") and "who" in bad("", "walk").lower())
expect("only symbols as a person", bad("!!!", "walk") is not None)
expect("unknown activity", bad("a", "swim") and "activity" in bad("a", "swim").lower())
expect("duration that is not a number", bad("a", "walk", "", "abc") is not None)
rec.start("Ken Dr!ck", "walk", "a<b>c; d", 3); rec.mode = "idle"
expect("person and note are cleaned, duration is raised to 5", rec.subject == "KenDrck" and rec.note == "abc d" and rec.duration == 5, str((rec.subject, rec.note, rec.duration)))
rec.start("a", "walk", "", 99999); rec.mode = "idle"
expect("duration is capped at 600", rec.duration == 600)
rec.start("a", "walk", "", 60)
expect("a second start while running is refused", bad("a", "walk") and "already" in bad("a", "walk"))
rec.mode = "idle"; clock.t += 5
expect("no IMU stream: refused with a clear message", bad("a", "walk") and "No IMU data" in bad("a", "walk"))

print("5. files survive a restart; deleting; the zip")
rec, d = fresh()
feed(rec, 1)
for who, lab in (("a", "walk"), ("a", "run"), ("b", "walk")):
    rec.start(who, lab, "", 5); feed(rec, 5.1); rec.tick(); feed(rec, 5.2); rec.tick(); feed(rec, 1)
expect("three recordings listed, newest first", [f["label"] for f in rec.files()] == ["walk", "run", "walk"] and rec.files()[0]["subject"] == "b", str([(f["subject"], f["label"]) for f in rec.files()]))
tot = rec.totals()
expect("totals per person and activity", set(tot) == {"a", "b"} and tot["a"]["walk"] >= 4.9 and tot["b"]["walk"] >= 4.9 and "run" in tot["a"], str(tot))
rec2 = Recorder(d, clock=clock, wall=wall)
expect("a new Recorder (a restart) finds them again", len(rec2.files()) == 3)
(d / rec.files()[1]["file"]).unlink()
expect("a file removed by hand disappears from the list", len(Recorder(d, clock=clock, wall=wall).files()) == 2)
expect("...also in the running app, which does not crash on it", len(rec.files()) == 2 and len(rec.totals()) >= 1)
zname = rec.make_zip()
names = set(zipfile.ZipFile(d / zname).namelist())
expect("the zip holds the two remaining files and the manifest, and skips the missing one", "manifest.csv" in names and len([n for n in names if n.endswith(".csv")]) == 3, str(sorted(names)))
victim = rec.files()[0]["file"]; rec.delete(victim)
expect("delete removes the file and its row", not (d / victim).exists() and all(f["file"] != victim for f in rec.files()))
outside = tmp / "precious.txt"; outside.write_text("keep me")
try: rec.delete("../precious.txt"); err = None
except ValueError as e: err = str(e)
expect("a path trick cannot delete outside the folder", outside.exists() and err == "No such recording.", str(err))

print("6. two recordings in the same second get different names")
rec, d = fresh(); feed(rec, 1); names = []
for _ in range(2):
    rec.start("a", "walk", "", 5); rec.mode, rec.t_mode, rec.rec, rec.t_start_wall = "recording", clock.t, [], wall0
    rec.rec = [(i, 0, 0, 1, 0, 0, 0) for i in range(100)]; names.append(rec._finish()["file"])
expect("second file has a -2 suffix", names[0] != names[1] and names[1].endswith("-2.csv"), str(names))

print("7. samples arriving from another thread while the app ticks")
rec, d = fresh(); feed(rec, 1); rec.start("a", "walk", "", 5)
errors = []
def pump():
    try:
        for i in range(3000): rec.add_sample(i, 0, 0, 1, 0, 0, 0)
    except Exception as e: errors.append(e)
t = threading.Thread(target=pump); t.start()
for _ in range(300): rec.tick(); rec.snapshot()
t.join()
expect("no errors", not errors and len(rec.snapshot()["recent_a"]) <= 100, str(errors[:1]))

print("8. the glue: commands from the page, messages back, the LED matrix")
log["messages"].clear(); log["led"].clear()
glue, on_cmd, loop = mod.recorder, log["handlers"]["cmd"], log["loop"]
def kinds(kind): return [m for k, m in log["messages"] if k == kind]
feed_glue = lambda secs, **k: feed(glue, secs, counter=[10**6], **k)
log["handlers"]["connect"]("sid")
expect("connecting pushes the (empty) file list", kinds("files") and kinds("files")[-1]["files"] == [])
on_cmd("sid", {"action": "start", "subject": "kendrick", "label": "walk"})
expect("start with no IMU data is answered with a warning, not a crash", kinds("notice")[-1]["level"] == "warn" and "No IMU data" in kinds("notice")[-1]["text"], kinds("notice")[-1]["text"][:60])
for _ in range(200): clock.t += 0.01; mod.on_imu(1, 0, 0, 1, 0, 0, 0)               # IMU alive (100/s)
on_cmd("sid", {"action": "start", "subject": "kendrick", "label": "walk", "note": "", "duration": 5})
expect("start is accepted: 'Get ready' notice", kinds("notice")[-1]["level"] == "info" and "5 seconds" in kinds("notice")[-1]["text"])
n = [0]
for i in range(130):                                                                  # 13 s of the 100 Hz stream in 0.1 s ticks
    for _ in range(10): n[0] += 1; clock.t += 0.01; mod.on_imu(n[0], 0, 0, 1, 0, 0, 0)
    loop_clock = clock.t; log["loop"]()
saved = [m for m in kinds("notice") if m["level"] == "ok"]
expect("the recording finished and the page was told", saved and "Saved kendrick__walk__" in saved[0]["text"], saved[0]["text"][:70] if saved else "")
expect("state messages went out about every other tick", 50 < len(kinds("state")) < 90, str(len(kinds("state"))))
expect("the file list was pushed with the new file", kinds("files")[-1]["files"] and kinds("files")[-1]["files"][0]["label"] == "walk")
modes = [a[0] for a in log["led"]]
expect("the LED showed countdown, then recording, then the tick, then idle", modes[:1] == [1] and 2 in modes and 3 in modes and modes[-1] == 0 and modes.index(1) < modes.index(2) < modes.index(3), str(modes))
cd = [a[1] for a in log["led"] if a[0] == 1]
expect("the countdown dots decrease 5, 4, 3, 2, 1", cd == [5, 4, 3, 2, 1], str(cd))
bar = [a[1] for a in log["led"] if a[0] == 2]
expect("the progress bar only grows, up to 13", bar == sorted(bar) and bar[-1] == 13, str(bar))
on_cmd("sid", {"action": "zip"})
expect("the zip command answers with the zip name", kinds("files")[-1]["zip"] == "all_data.zip")
on_cmd("sid", {"action": "delete", "file": kinds("files")[-1]["files"][0]["file"]})
expect("delete from the page works", kinds("files")[-1]["files"] == [])
on_cmd("sid", {"action": "nonsense"}); expect("an unknown command is answered, not fatal", kinds("notice")[-1]["text"] == "Unknown command.")
on_cmd("sid", None); expect("an empty command is not fatal either", kinds("notice")[-1]["text"] == "Unknown command.")
log["led_fails"] = True; n0 = len(log["led"])
on_cmd("sid", {"action": "start", "subject": "a", "label": "run", "duration": 5})
for _ in range(5): log["loop"]()
expect("if the LED matrix does not answer, the app keeps running", kinds("state") and glue.mode == "countdown")

time.monotonic, time.sleep = real_time
print(f"\n{'ALL PASSED' if problems == 0 else 'SOME FAILED'} ({problems} problem{'s' if problems != 1 else ''})")
sys.exit(1 if problems else 0)
