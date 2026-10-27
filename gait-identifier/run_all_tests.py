"""Run every test in the project with one command:      python run_all_tests.py

Groups whose tool is not installed are SKIPPED with a message, not failed:
  * the Python tests need  numpy  (and  scikit-learn  for the training tests)
  * the sketch tests need  g++  (they compile the real sketches against a fake Arduino)
  * the page tests need  node  and  jsdom   (npm install jsdom   in any folder, or set NODE_PATH)
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "apps"
results = []                                   # (name, "passed" | "FAILED" | "skipped", detail)


def run(cmd, cwd, env=None):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def record(name, code, out):
    last = [l for l in out.splitlines() if l.strip()][-1:] or ["(no output)"]
    status = "passed" if code == 0 else "FAILED"
    results.append((name, status, last[0].strip()))
    print("  %-8s %s   %s" % (status, name, last[0].strip()[:70]), flush=True)
    if code != 0:
        print("\n".join("      | " + l for l in out.splitlines()[-25:]), flush=True)


def skip(name, why):
    results.append((name, "skipped", why))
    print("  %-8s %s   (%s)" % ("skipped", name, why), flush=True)


print("Python tests")
record("training, models, exports", *run([sys.executable, "tests/test_gait.py"], ROOT))
for app, test in (("gait-live", "test_live.py"), ("gait-recorder", "test_recorder.py"), ("gait-imu-check", "test_python.py")):
    record("%s: python" % app, *run([sys.executable, test], APPS / app / "tests"))

print("\nSketch tests (the real sketches compiled against a fake Arduino, I2C sensor, Bridge and LED matrix)")
gpp = shutil.which("g++")
for app in ("gait-live", "gait-recorder", "gait-imu-check"):
    for qwiic in (0, 1):
        name = "%s: sketch, Qwiic %s" % (app, "on" if qwiic else "off")
        if not gpp:
            skip(name, "g++ not found")
            continue
        exe = Path(tempfile.mkdtemp()) / ("t.exe" if os.name == "nt" else "t")
        code, out = run([gpp, "-std=c++17", "-DTRY_QWIIC=%d" % qwiic, "-I", "stubs", "-o", str(exe), "test_sketch.cpp"], APPS / app / "tests")
        if code != 0:
            record(name + " (compile)", code, out)
            continue
        record(name, *run([str(exe)], APPS / app / "tests"))

print("\nPage tests (the real web pages in a simulated browser)")
node = shutil.which("node")
env = dict(os.environ)
for cand in (ROOT / "node_modules", ROOT / "apps" / "gait-live" / "tests" / "node_modules"):
    if cand.exists():
        env["NODE_PATH"] = str(cand) + os.pathsep + env.get("NODE_PATH", "")
have_jsdom = bool(node) and subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, env=env).returncode == 0
for app in ("gait-live", "gait-recorder"):
    name = "%s: page" % app
    if not node:
        skip(name, "node not found")
    elif not have_jsdom:
        skip(name, "jsdom not installed: run  npm install jsdom")
    else:
        record(name, *run([node, "test_page.js"], APPS / app / "tests", env))

failed = [r for r in results if r[1] == "FAILED"]
skipped = [r for r in results if r[1] == "skipped"]
headline = "SOME FAILED" if failed else ("ALL PASSED" if not skipped else "NO FAILURES (but some groups were skipped)")
print("\n%s: %d groups passed, %d skipped, %d failed" % (headline, len([r for r in results if r[1] == "passed"]), len(skipped), len(failed)))
if skipped:
    print("Skipped groups were not run, so they say nothing either way.")
sys.exit(1 if failed else 0)
