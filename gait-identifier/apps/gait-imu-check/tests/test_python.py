import contextlib, importlib.util, io, math, random, sys, time, types

def load_app(clock):
    """Import the app's main.py with a stand-in for arduino.app_utils and a fake clock."""
    calls = {"provided": {}, "status_calls": 0}
    app_utils = types.ModuleType("arduino.app_utils")
    class Bridge:
        @staticmethod
        def provide(name, handler): calls["provided"][name] = handler
        @staticmethod
        def call(name, *a, timeout=10):
            calls["status_calls"] += 1
            if name == "imu_status": return "sensor found on Wire (SDA/SCL pins) at 0x68 (WHO_AM_I = 0x68)"
            raise ValueError("no such method")
    class App:
        @staticmethod
        def run(user_loop=None): calls["loop"] = user_loop
    app_utils.Bridge, app_utils.App = Bridge, App
    pkg = types.ModuleType("arduino"); pkg.app_utils = app_utils
    sys.modules["arduino"], sys.modules["arduino.app_utils"] = pkg, app_utils
    real_mono, real_sleep = time.monotonic, time.sleep
    time.monotonic = lambda: clock[0]
    time.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    spec = importlib.util.spec_from_file_location("gait_main", str(__import__("pathlib").Path(__file__).resolve().parent.parent / "python" / "main.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    finally:
        time.monotonic, time.sleep = real_mono, real_sleep
    return mod, calls

def run(name, make_sample, rate=100, drop_every=0, silent=False, seconds=42):
    clock = [1000.0]
    mod, calls = load_app(clock)
    real_mono, real_sleep = time.monotonic, time.sleep
    time.monotonic = lambda: clock[0]
    time.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    out, n, rng = io.StringIO(), 0, random.Random(5)
    try:
        with contextlib.redirect_stdout(out):
            for sec in range(seconds):
                if not silent:
                    for k in range(rate):
                        n += 1
                        if drop_every and n % drop_every == 0: continue          # a reading lost on its way
                        calls["provided"]["imu"](n, *make_sample(sec, rng))
                calls["loop"]()                                                  # one tick: sleeps a second, then prints
    finally:
        time.monotonic, time.sleep = real_mono, real_sleep
    return out.getvalue()

def noise(r, s): return r.uniform(-s, s)
def phase(sec): return "STILL" if 10 <= sec < 18 else "SHAKE" if 20 <= sec < 28 else "ROTATE" if 30 <= sec < 38 else "idle"
def healthy(sec, r, still_g=1.0, shake_peak=4.5, spin_peak=300.0):
    p = phase(sec)
    if p == "SHAKE":   return (noise(r, shake_peak), noise(r, shake_peak), 1 + noise(r, shake_peak), noise(r, 40), noise(r, 40), noise(r, 40))
    if p == "ROTATE":  return (noise(r, 0.3), noise(r, 0.3), still_g + noise(r, 0.3), noise(r, spin_peak), noise(r, spin_peak), noise(r, spin_peak))
    return (noise(r, 0.01), noise(r, 0.01), still_g + noise(r, 0.01), noise(r, 1.5), noise(r, 1.5), noise(r, 1.5))

def verdicts(text):
    block = text.split("SELF-TEST ================")[-1] if "SELF-TEST" in text else ""
    return [l.strip() for l in block.splitlines() if l.strip().startswith(("PASS", "FAIL"))], [l.strip() for l in block.splitlines() if "ALL PASSED" in l or "Some checks failed" in l]

problems = 0
def expect(label, cond, detail=""):
    global problems
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"   [{detail}]" if detail else "")); problems += (not cond)

print("1. a healthy sensor: still, shake, rotate")
t = run("good", healthy)
v, final = verdicts(t)
expect("all four verdicts are PASS", len(v) == 4 and all(x.startswith("PASS") for x in v), "; ".join(x[:60] for x in v))
expect("it says the IMU is ready", any("ready for recording" in x for x in final))
expect("it printed the sensor status from the sketch", "sensor status: sensor found on Wire" in t)
expect("each phase was announced", all(w in t for w in (">>> Put the sensor FLAT", ">>> STILL", ">>> SHAKE", ">>> ROTATE")))
print("     sample lines:"); [print("       " + l) for l in t.splitlines() if l.startswith("t=") and any(k in l for k in ("[STILL]", "[SHAKE]", "[ROTATE]"))][:0]
for l in [x for x in t.splitlines() if x.startswith("t=")][12:14] + [x for x in t.splitlines() if x.startswith("t=")][24:25] + [x for x in t.splitlines() if x.startswith("t=")][33:34]: print("       " + l)

print("2. nothing arrives at all (sensor not wired)")
t = run("none", healthy, silent=True)
v, final = verdicts(t)
expect("one FAIL that says no samples arrived and points at the wiring", len(v) == 1 and v[0].startswith("FAIL") and "No samples" in v[0] and "wiring" in v[0])

print("3. 5% of the readings are lost on the way")
t = run("drops", healthy, drop_every=20)
v, final = verdicts(t)
expect("the rate line FAILs and shows the lost fraction", v and v[0].startswith("FAIL") and "lost" in v[0], v[0][:100] if v else "")

print("4. only 50 readings a second")
t = run("slow", healthy, rate=50)
v, final = verdicts(t)
expect("the rate line FAILs", v and v[0].startswith("FAIL") and "50 samples" in v[0], v[0][:80] if v else "")

print("5. gravity reads 0.5 g (a range or scale problem)")
t = run("scale", lambda s, r: healthy(s, r, still_g=0.5))
v, final = verdicts(t)
still = [x for x in v if "STILL" in x]
expect("STILL FAILs with the scale hint", still and still[0].startswith("FAIL") and "range or scale" in still[0], still[0][:110] if still else "")

print("6. a weak shake and a lazy rotation")
t = run("weak", lambda s, r: healthy(s, r, shake_peak=0.6, spin_peak=60.0))
v, final = verdicts(t)
shake = [x for x in v if "SHAKE" in x]; rot = [x for x in v if "ROTATE" in x]
expect("SHAKE FAILs with 'shake harder'", shake and shake[0].startswith("FAIL") and "harder" in shake[0], shake[0][:90] if shake else "")
expect("ROTATE FAILs with 'turn it faster'", rot and rot[0].startswith("FAIL") and "faster" in rot[0], rot[0][:90] if rot else "")
expect("and the summary tells you to fix and restart", any("Some checks failed" in x for x in final))

print("7. the sensor is vibrating during the STILL phase")
t = run("vib", lambda s, r: healthy(s, r) if phase(s) != "STILL" else (noise(r, 0.3), noise(r, 0.3), 1 + noise(r, 0.3), noise(r, 40), noise(r, 40), noise(r, 40)))
v, final = verdicts(t)
still = [x for x in v if "STILL" in x]
expect("STILL FAILs and says to keep it flat and still", still and still[0].startswith("FAIL") and "still" in still[0].lower(), still[0][:110] if still else "")

print(f"\n{'ALL PASSED' if problems == 0 else 'SOME FAILED'} ({problems} problem{'s' if problems != 1 else ''})")
