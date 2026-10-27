"""Gait identifier - step 1 - is the IMU alive and sensible?

The microcontroller sketch reads an MPU-6050 at 100 Hz and calls  imu(n, ax, ay, az, gx, gy, gz)  here:
n = sample counter, a* in g (1.0 = gravity), g* in degrees per second.

This app runs a short guided test on its own (App Lab's Python console shows output but cannot take typing), then keeps printing one
line a second. Watch the PYTHON tab and follow it:

    0 - 10 s   get ready: put the sensor flat on a table and let go
   10 - 18 s   STILL    do not touch it
   20 - 28 s   SHAKE    shake it hard
   30 - 38 s   ROTATE   turn it over and around in your hand
   38 s        PASS or FAIL for each, with a hint if something is off

What it checks: samples arrive at about 100 per second without gaps; when still, the acceleration magnitude is about 1 g (gravity) and
steady and the gyro is near zero; a shake gives several g; a rotation gives a large gyro reading.
"""

import math
import threading
import time

from arduino.app_utils import *

EXPECTED_RATE = 100                      # samples per second the sketch sends
SCHEDULE = [("READY", 0.0, 10.0, "Put the sensor FLAT on a table and let go."),
            ("STILL", 10.0, 18.0, "STILL: do not touch it."),
            ("SHAKE", 20.0, 28.0, "SHAKE: shake it hard, in every direction."),
            ("ROTATE", 30.0, 38.0, "ROTATE: turn it over and around in your hand.")]
TEST_END = 38.0

lock = threading.Lock()
pending = []                             # samples that arrived since the last tick: (time, ax, ay, az, gx, gy, gz)
counters = {"last_n": None, "dropped": 0, "total": 0}


def on_imu(n, ax, ay, az, gx, gy, gz):
    """Called by the microcontroller for every reading. Keep it light: it runs on the Bridge's own thread."""
    now = time.monotonic()
    with lock:
        if counters["last_n"] is not None and 0 < n - counters["last_n"] - 1 < 1000:
            counters["dropped"] += n - counters["last_n"] - 1          # a counter jump means readings were lost on the way
        counters["last_n"] = n
        counters["total"] += 1
        pending.append((now, ax, ay, az, gx, gy, gz))


Bridge.provide("imu", on_imu)


# ---- the numbers -------------------------------------------------------------------------------------------------
def magnitudes(samples):
    """(|acceleration| in g, |rotation| in degrees/second) for each sample."""
    return ([math.sqrt(s[1] ** 2 + s[2] ** 2 + s[3] ** 2) for s in samples],
            [math.sqrt(s[4] ** 2 + s[5] ** 2 + s[6] ** 2) for s in samples])


def mean_std(values):
    if not values:
        return 0.0, 0.0
    m = sum(values) / len(values)
    return m, math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def judge(phases, rates, dropped_fraction):
    """phases: {'STILL': samples, 'SHAKE': samples, 'ROTATE': samples}. Returns [(PASS or FAIL, text)]."""
    out = []
    typical_rate = sorted(rates)[len(rates) // 2] if rates else 0
    if typical_rate == 0:
        return [("FAIL", "No samples arrived at all. Check the wiring (3V3, GND, SDA, SCL) and read the sensor status line above.")]
    ok = 90 <= typical_rate <= 110 and dropped_fraction < 0.02
    out.append(("PASS" if ok else "FAIL",
                f"{typical_rate} samples a second ({dropped_fraction:.1%} lost on the way)" if ok else
                f"{typical_rate} samples a second ({dropped_fraction:.1%} lost): about 100 are expected. If it is far lower, the I2C wiring may be marginal "
                "(shorter wires, or I2C_HZ = 100000 in the sketch) or the Bridge is saturated."))
    amag, gmag = magnitudes(phases.get("STILL", []))
    mean_a, std_a = mean_std(amag)
    still_ok = len(amag) > 100 and 0.90 <= mean_a <= 1.10 and std_a < 0.05 and (max(gmag) if gmag else 999) < 25
    hint = ""
    if len(amag) <= 100:
        hint = " Too few samples in this phase."
    elif mean_a < 0.2:
        hint = " It reads about 0 g: the sensor may be asleep or unpowered."
    elif not 0.90 <= mean_a <= 1.10:
        hint = f" Gravity should read about 1.00 g, not {mean_a:.2f}: a range or scale problem."
    elif std_a >= 0.05 or max(gmag) >= 25:
        hint = " It was moving or vibrating: keep it flat and still on a solid table."
    out.append(("PASS" if still_ok else "FAIL", f"STILL: |a| = {mean_a:.2f} g (spread {std_a:.3f}), gyro at most {max(gmag) if gmag else 0:.0f} deg/s" + ("" if still_ok else "." + hint)))
    amag, _ = magnitudes(phases.get("SHAKE", []))
    peak = max(amag) if amag else 0
    out.append(("PASS" if peak >= 3.0 else "FAIL", f"SHAKE: strongest reading {peak:.1f} g" + ("" if peak >= 3.0 else " (a hard shake should pass 3 g: shake harder, or the range setting is wrong).")))
    _, gmag = magnitudes(phases.get("ROTATE", []))
    spin = max(gmag) if gmag else 0
    out.append(("PASS" if spin >= 150 else "FAIL", f"ROTATE: fastest turn {spin:.0f} deg/s" + ("" if spin >= 150 else " (turn it faster: a quick wrist turn passes 150 deg/s).")))
    return out


# ---- the loop ----------------------------------------------------------------------------------------------------
t0 = time.monotonic()
phase_samples = {"STILL": [], "SHAKE": [], "ROTATE": []}
rates, announced, finished, status_shown = [], set(), False, False
last_status_try = 0.0


def loop():
    global finished, status_shown, last_status_try
    time.sleep(1.0)
    now = time.monotonic()
    with lock:
        batch = pending[:]
        del pending[:]
        dropped, total = counters["dropped"], counters["total"]
    t = now - t0

    if not status_shown and now - last_status_try > 3.0:                  # ask the sketch what it found (once it is running)
        last_status_try = now
        try:
            print("sensor status:", Bridge.call("imu_status", timeout=3))
            status_shown = True
        except Exception as e:
            print("(waiting for the sketch to answer: " + str(e)[:60] + ")")

    amag, gmag = magnitudes(batch)
    mean_a, _ = mean_std(amag)
    line = f"t={t:4.0f}s  {len(batch):3d} samples/s  |a| avg {mean_a:4.2f} g max {max(amag) if amag else 0:4.2f} g  gyro max {max(gmag) if gmag else 0:4.0f} deg/s  lost {dropped}"

    for name, start, end, message in SCHEDULE:
        if start <= t < end:
            if name not in announced:
                announced.add(name)
                print("\n>>> " + message + "\n")
            if name in phase_samples:
                phase_samples[name].extend(batch)
                if len(batch):
                    rates.append(len(batch))
            line += "   [" + name + "]"
    print(line)

    if t >= TEST_END and not finished:
        finished = True
        results = judge(phase_samples, rates, dropped / max(1, total + dropped))
        print("\n================ SELF-TEST ================")
        for verdict, text in results:
            print(f"  {verdict}  {text}")
        print("ALL PASSED: the IMU is ready for recording." if all(v == "PASS" for v, _ in results) else "Some checks failed: read the hints, fix, and restart the app.")
        print("===========================================\n(it keeps printing one line a second)\n")


App.run(user_loop=loop)
