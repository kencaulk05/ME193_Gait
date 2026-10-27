"""Tests for python/main.py (the live app). No board needed.   python test_live.py"""
import csv, datetime, importlib.util, os, sys, tempfile, time, types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
APP = HERE.parent
PY = APP / "python"
REPO = APP.parent.parent                      # the repo root when this app sits in apps/gait-live; the data and the originals live there
DATA = REPO / "data"
sys.path.insert(0, str(PY))
import gait_features as gf
from gait_predict import GaitModels

problems = 0
def expect(label, cond, detail=""):
    global problems
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"   [{detail}]" if detail else ""))
    problems += (not cond)

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s
clock = Clock()
tmp = Path(tempfile.mkdtemp())
wall0 = datetime.datetime(2026, 10, 27, 15, 0, 0)
def wall(): return wall0 + datetime.timedelta(seconds=clock.t - 1000.0)

# ---- load main.py with stand-ins for the board libraries ----
log = {"messages": [], "handlers": {}, "show": [], "show_fails": False}
class Bridge:
    @staticmethod
    def provide(name, fn): log.setdefault("provided", {})[name] = fn
    @staticmethod
    def call(name, *args, timeout=10):
        if name == "show":
            if log["show_fails"]: raise TimeoutError("no answer")
            log["show"].append(args); return 0
class App:
    @staticmethod
    def run(user_loop=None): log["loop"] = user_loop
class WebUI:
    def on_message(self, kind, fn): log["handlers"][kind] = fn
    def on_connect(self, fn): log["handlers"]["connect"] = fn
    def send_message(self, kind, msg, room=None): log["messages"].append((kind, msg))
u = types.ModuleType("arduino.app_utils"); u.Bridge, u.App = Bridge, App
w = types.ModuleType("arduino.app_bricks.web_ui"); w.WebUI = WebUI
sys.modules.update({"arduino": types.ModuleType("arduino"), "arduino.app_utils": u, "arduino.app_bricks": types.ModuleType("arduino.app_bricks"), "arduino.app_bricks.web_ui": w})
os.environ["GAIT_DATA_DIR"] = str(tmp / "glue_data")
real = (time.monotonic, time.sleep)
time.monotonic, time.sleep = clock, clock.sleep
spec = importlib.util.spec_from_file_location("gait_live_main", PY / "main.py")
main = importlib.util.module_from_spec(spec); spec.loader.exec_module(main)

models = GaitModels(PY / "gait_models.json")
Live = main.Live

def stream(live, rows, hz=100, tick_every=10, start_n=0, drop=None):
    """Feed rows (n, 6) at hz, advancing the fake clock, calling tick() every tick_every samples. Returns all analyses."""
    out = []
    for i, r in enumerate(rows):
        n = start_n + i
        clock.t += 1.0 / hz
        if drop and drop(n): continue
        live.add_sample(n, *r)
        if (i + 1) % tick_every == 0: out += live.tick()
    out += live.tick()
    return out

def load(name, count=None):
    x = np.loadtxt(DATA / name, delimiter=",", skiprows=1, usecols=range(1, 7))
    return x if count is None else x[:count]

have_data = DATA.exists()

print("1. the models in the app")
expect("the model file loads and Model A is a number line of four labelled stretches in order", [s["label"] for s in main.Live(models, tmp / "a.csv").segments] == ["still", "walk", "run", "bike"], str([s["label"] for s in Live(models, tmp / "a.csv").segments]))
if (REPO / "gait_features.py").exists():
    same = all((PY / n).read_bytes() == (REPO / src).read_bytes() for n, src in (("gait_features.py", "gait_features.py"), ("gait_predict.py", "gait_predict.py"), ("gait_models.json", "models/gait_models.json")))
    expect("the app's copies of the shared code and the models are identical to the repo's originals", same, "if this fails, run: python sync_live_app.py")
else:
    print("  (skipped: this app is not inside the repo, so there are no originals to compare with)")

print("2. live answers equal the offline answers, window by window, on the real recordings")
if have_data:
    files = sorted(DATA.glob("*__*.csv"))
    bad, total = 0, 0
    for f in files:
        x = load(f.name, 2500)
        live = Live(models, tmp / "eq.csv", clock, wall)
        got = stream(live, x, tick_every=7)                     # an awkward tick size on purpose: the windows must not depend on it
        want = [models.analyze(win) for win in gf.windows(x)]
        total += len(want)
        if len(got) != len(want) or any(g["a"] != e["a"] or g["b"] != e["b"] or abs(g["a_value"] - e["a_value"]) > 1e-9 for g, e in zip(got, want)): bad += 1
    expect("all %d windows of %d recordings give the same Model A and Model B answers and the same number for A" % (total, len(files)), bad == 0 and total > 500, "%d recordings differed" % bad)
else:
    print("  (skipped: no data folder next to this app)")

print("3. warming up")
live = Live(models, tmp / "w.csv", clock, wall)
rate_rows = np.tile([0, 0, 1, 0, 0, 0], (400, 1)).astype(float)
for i in range(100): clock.t += 0.01; live.add_sample(i, *rate_rows[i])
s = live.snapshot()
expect("after 1 s: warming up, half the buffer full, nothing to show", s["mode"] == "warming" and abs(s["warm"] - 0.5) < 0.01 and s["a"] is None, str((s["mode"], s["warm"])))
for i in range(100, 199): clock.t += 0.01; live.add_sample(i, *rate_rows[i])
expect("with 199 samples there is still no window", live.tick() == [] and live.snapshot()["mode"] == "warming")
clock.t += 0.01; live.add_sample(199, *rate_rows[199])
r = live.tick()
expect("the 200th sample completes the first window, and it is analysed", len(r) == 1 and live.snapshot()["mode"] == "live")
for i in range(200, 249): clock.t += 0.01; live.add_sample(i, *rate_rows[i])
expect("49 more samples: no new window; the 50th makes the next one", live.tick() == [] and (live.add_sample(249, *rate_rows[249]) or True) and len(live.tick()) == 1)

print("4. lost samples")
x = np.tile([0, 0, 1, 0, 0, 0], (1200, 1)).astype(float)
live = Live(models, tmp / "g.csv", clock, wall)
got = stream(live, x, drop=lambda n: 300 <= n < 340 and n % 2 == 0)         # 20 of 200 lost inside some windows: 10%
expect("windows that lost 10% of their samples are skipped and counted, others are analysed", live.skipped > 0 and len(got) < len(gf.windows(x)), "skipped %d, analysed %d of %d" % (live.skipped, len(got), len(gf.windows(x))))
live = Live(models, tmp / "g2.csv", clock, wall)
got = stream(live, x, drop=lambda n: n % 50 == 7 and 300 <= n < 500)        # 4 of 200 lost: 2%
received = 1200 - 4                                                           # 4 samples were lost, so 1196 arrived
expect("a window that lost only 2% is still analysed", live.skipped == 0 and len(got) == (received - 200) // 50 + 1, "skipped %d, analysed %d of the %d that fit" % (live.skipped, len(got), (received - 200) // 50 + 1))

print("5. the stream stops and comes back")
live = Live(models, tmp / "s.csv", clock, wall)
expect("before the first sample it says 'no data'", live.snapshot()["mode"] == "nodata")
stream(live, x[:400])
expect("while it flows the page is live", live.snapshot()["mode"] == "live")
clock.t += 1.6
s = live.snapshot()
expect("1.6 s of silence: 'no data', nothing shown", s["mode"] == "nodata" and s["a"] is None and s["b"] is None, s["mode"])
for i in range(30): clock.t += 0.01; live.add_sample(5000 + i, *x[i])
expect("when it comes back the old samples are forgotten and warming starts again", live.snapshot()["mode"] == "warming" and len(live.buf) == 30 and live.last is None, str(len(live.buf)))

print("6. smoothing")
script = iter([("walk", "walk"), ("run", "walk"), ("walk", "walk"), ("run", "run"), ("run", "walk"), ("bike", "run")])
fake = types.SimpleNamespace(a_segments=models.a_segments, analyze=lambda w: dict(zip(("a", "b"), next(script)), a_name="ax_max", a_value=0.0, a_path=[], b_path=[]))
live = Live(fake, tmp / "sm.csv", clock, wall)
shown = []
for _ in range(6):
    live.pending.append([(i, 0, 0, 1, 0, 0, 0) for i in range(200)]); live.tick(); shown.append(live._shown())
# A's raw answers: walk, run, walk, run, run, bike. Last three each time: [walk] [walk run: tie, newest wins] [walk run walk] [run walk run] [walk run run] [run run bike]
# B's raw answers: walk, walk, walk, run, walk, run.  Last three each time: [walk] [walk walk] [walk walk walk] [walk walk run] [walk run walk] [run walk run]
expect("smoothed: the majority of the last three answers, a tie going to the newest", [s[0] for s in shown] == ["walk", "run", "walk", "run", "run", "run"] and [s[1] for s in shown] == ["walk", "walk", "walk", "walk", "walk", "run"], str(shown))
live.set_smooth(False)
expect("unsmoothed: the latest raw answer", live._shown() == ("bike", "run"))

print("7. test mode: scoring and the log")
script = iter([("walk", "walk"), ("run", "walk"), ("walk", "run"), ("walk", "walk"), ("run", "run")])
live = Live(types.SimpleNamespace(a_segments=models.a_segments, analyze=lambda w: dict(zip(("a", "b"), next(script)), a_name="ax_max", a_value=-0.4, a_path=[], b_path=[])), tmp / "log.csv", clock, wall)
win = [(i, 0, 0, 1, 0, 0, 0) for i in range(200)]
live.pending.append(win); live.tick()
expect("with no one chosen nothing is scored and no log is written", live.tally["windows"] == 0 and not (tmp / "log.csv").exists())
live.set_person("Ann <b>Lee</b>!"); live.set_truth("walk")
expect("the name is cleaned", live.person == "Ann bLeeb")
for _ in range(4): live.pending.append(win); live.tick()
t = live.tally
# the first scripted answer (walk, walk) was used before anyone was chosen; the four scored windows are (run, walk) (walk, run) (walk, walk) (run, run), the truth being walk
expect("4 scored windows: A is right in 2 of them (walk, walk) and B in 2 (walk, walk), counted per model", t["windows"] == 4 and t["a_correct"] == 2 and t["b_correct"] == 2, str((t["windows"], t["a_correct"], t["b_correct"])))
expect("per activity: all 4 windows are 'walk'", t["by_label"]["walk"] == {"n": 4, "a": 2, "b": 2} and t["by_label"]["run"]["n"] == 0, str(t["by_label"]["walk"]))
expect("disagreements: the 2 windows where A and B differ, A right once and B right once", t["disagree"] == {"n": 2, "a_right": 1, "b_right": 1}, str(t["disagree"]))
rows = list(csv.reader(open(tmp / "log.csv", encoding="utf-8")))
expect("the log has a header and one row per scored window, with who, what and both answers", rows[0] == ["time", "person", "truth", "model_a", "model_b", "a_number"] and len(rows) == 5 and rows[1][1:5] == ["Ann bLeeb", "walk", "run", "walk"], str(rows[1]))
try: live.set_truth("swim"); err = None
except ValueError as e: err = str(e)
expect("an unknown activity is refused", err is not None and live.truth == "walk")
live.reset_tally()
expect("reset clears the scores but not the log", live.tally["windows"] == 0 and len(list(csv.reader(open(tmp / "log.csv", encoding="utf-8")))) == 5)
live.set_truth(None)

print("8. what the page is sent")
live = Live(models, tmp / "snap.csv", clock, wall)
if have_data:
    stream(live, load("Marie__run__20261027-034912.csv", 6000)[3000:6000], start_n=3000)
    s = live.snapshot()
    expect("live, with both answers, the number A looked at, and how each tree decided", s["mode"] == "live" and s["a"] in gf.LABELS and s["b"] in gf.LABELS and s["a_name"] == "ax_max" and s["a_value"] is not None and len(s["a_path"]) >= 1 and len(s["b_path"]) >= 2)
    p = s["b_path"][0]
    expect("each question is described in words, with its value and threshold", set(p) == {"name", "text", "unit", "value", "threshold", "yes"} and isinstance(p["text"], str) and len(p["text"]) > 3, str(p))
    expect("history strips hold at most 60 s of windows and the plot arrays at most 100 points", len(s["hist_a"]) <= 120 and len(s["hist_b"]) == len(s["hist_a"]) and 0 < len(s["recent_ax"]) <= 100)
    expect("the number line and its range are sent", len(s["segments"]) == 4 and s["gauge"] == [-1.1, 1.1] and s["labels"] == gf.LABELS)

print("9. the glue: commands, messages, the LED matrix")
live = main.live
cmd, loop = log["handlers"]["cmd"], log["loop"]
def kinds(k): return [m for kk, m in log["messages"] if kk == k]
log["handlers"]["connect"]("sid")
expect("connecting sends the state at once", kinds("state") and kinds("state")[-1]["mode"] == "nodata")
cmd("sid", {"action": "person", "name": "Kendrick"}); cmd("sid", {"action": "truth", "label": "run"})
expect("name and activity set from the page show up in the state", kinds("state")[-1]["person"] == "Kendrick" and kinds("state")[-1]["truth"] == "run")
cmd("sid", {"action": "truth", "label": ""}); expect("an empty choice means 'not testing'", kinds("state")[-1]["truth"] is None)
cmd("sid", {"action": "truth", "label": "swim"}); expect("a bad activity is answered with a warning, not a crash", kinds("notice")[-1]["level"] == "warn")
cmd("sid", {"action": "smooth", "on": False}); expect("smoothing can be switched off from the page", kinds("state")[-1]["smooth"] is False)
cmd("sid", {"action": "reset"}); expect("reset says what it did", "Scores cleared" in kinds("notice")[-1]["text"])
cmd("sid", {"action": "nonsense"}); cmd("sid", None); expect("unknown or empty commands are answered, not fatal", kinds("notice")[-1]["text"] == "Unknown command.")
log["messages"].clear(); log["show"].clear()
loop()
expect("with no data the LED is told to show its idle dot", log["show"] == [(-1, -1)], str(log["show"]))
if have_data:
    x = load("Kendrick__run__20261027-032213.csv", 6000)[3000:6000]
    n = 3000
    for chunk in range(0, 600, 10):
        for r in x[chunk:chunk + 10]: n += 1; clock.t += 0.01; main.on_imu(n, *r)
        loop(); clock.t -= 0.1                                   # loop() sleeps 0.1 s of fake time; the samples above already advanced it
    sent = log["show"][-1]
    expect("with a running recording streaming, the LED is told the two answers (as label numbers)", sent[0] in (0, 1, 2, 3) and sent[1] == 2, str(sent))
    calls = len(log["show"]); loop(); loop()
    expect("it does not repeat the call while nothing changes", len(log["show"]) == calls)
    loops_so_far = 60 + 2
    expect("state messages go out about every other tick", abs(len(kinds("state")) - loops_so_far / 2) <= 2, "%d messages in %d ticks" % (len(kinds("state")), loops_so_far))
    log["show_fails"] = True
    for r in x[600:700]: n += 1; clock.t += 0.01; main.on_imu(n, *r)
    try: loop(); loop(); ok = True
    except Exception: ok = False
    expect("if the LED matrix does not answer, the app keeps running", ok)

print("10. a whole demo: still, walk, run, bike, 20 s each, streamed in real time")
if have_data:
    parts = [("still", "Kendrick__still__20261027-031222.csv"), ("walk", "Kendrick__walk__20261027-031737.csv"), ("run", "Marie__run__20261027-034912.csv"), ("bike", "Marie__bike__20261027-035355.csv")]
    live = Live(models, tmp / "demo.csv", clock, wall)
    t_switch, shownlog, n = {}, [], 0
    for lab, f in parts:
        x = load(f)[2000:4000]
        t_switch[lab] = clock.t
        for i, r in enumerate(x):
            n += 1; clock.t += 0.01; live.add_sample(n, *r)
            if (i + 1) % 10 == 0:
                live.tick(); a, b = live._shown(); shownlog.append((clock.t, lab, a, b))
    def settle(model, lab):
        """seconds after the switch until the shown label is right and stays right for the rest of that part"""
        part = [(t, a if model == 0 else b) for t, l, a, b in shownlog if l == lab]
        for k in range(len(part)):
            if all(v == lab for _, v in part[k:]): return part[k][0] - t_switch[lab]
        return None
    lat = {lab: (settle(0, lab), settle(1, lab)) for lab, _ in parts}
    print("     seconds from the switch until the SMOOTHED label is right for good:   (these recordings were in the training data: a pipeline check, not a score)")
    for lab, (sa, sb) in lat.items(): print("       %-5s  Model A %s   Model B %s" % (lab, "never" if sa is None else "%.1f s" % sa, "never" if sb is None else "%.1f s" % sb))
    expect("Model B shows the right label within 4 s after every change", all(v[1] is not None and v[1] <= 4.0 for v in lat.values()))
    right_b = np.mean([b == l for _, l, a, b in shownlog if _ - t_switch[l] > 4]); right_a = np.mean([a == l for _, l, a, b in shownlog if _ - t_switch[l] > 4])
    expect("after the first 4 s of each part Model B shows the right label almost always", right_b > 0.95, "A %.0f%%, B %.0f%%" % (100 * right_a, 100 * right_b))

time.monotonic, time.sleep = real
print(f"\n{'ALL PASSED' if problems == 0 else 'SOME FAILED'} ({problems} problem{'s' if problems != 1 else ''})")
sys.exit(1 if problems else 0)
