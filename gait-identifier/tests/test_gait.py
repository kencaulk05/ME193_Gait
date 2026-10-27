"""Tests for the gait identifier.   python tests/test_gait.py     (takes about a minute: it trains everything several times)"""
import csv
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gait_features as gf
import gait_predict
import train_gait as tg

problems = 0


def expect(label, cond, detail=""):
    global problems
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"   [{detail}]" if detail else ""))
    problems += (not cond)


print("1. windows")
x = np.arange(1000 * 6, dtype=float).reshape(1000, 6)
w = gf.windows(x)
expect("1000 samples make 17 windows of 200 (a new one every 50)", w.shape == (17, 200, 6), str(w.shape))
expect("window k is exactly samples 50k .. 50k+200", all(np.array_equal(w[k], x[50 * k:50 * k + 200]) for k in range(17)))
expect("the last window ends inside the data, never past it", w[-1][-1][0] == x[-1][0] - 0 or w[-1][-1][0] <= x[-1][0])
expect("data shorter than one window gives no windows", gf.windows(x[:150]).shape[0] == 0)

print("2. the one-number features")
t = np.linspace(0, 2, 200, endpoint=False)
win = np.zeros((200, 6))
win[:, 0] = -1.0 + 0.5 * np.sin(2 * np.pi * 1.0 * t)
expect("max, min and maxabs of a known signal", abs(gf.peak(win, 0, "max") + 0.5) < 1e-3 and abs(gf.peak(win, 0, "min") + 1.5) < 1e-3 and abs(gf.peak(win, 0, "maxabs") - 1.5) < 1e-3,
       str((round(gf.peak(win, 0, "max"), 3), round(gf.peak(win, 0, "min"), 3), round(gf.peak(win, 0, "maxabs"), 3))))
expect("nine candidates: three axes times three kinds of peak", len(gf.PEAK_CANDIDATES) == 9 and gf.peak_name(0, "max") == "ax_max")

print("3. the all-sensor features")
expect("34 numbers, and 34 names", len(gf.features_b(win)) == 34 == len(gf.FEATURE_NAMES_B))
sine = np.zeros((200, 6)); sine[:, 2] = 1.0 + 0.8 * np.sin(2 * np.pi * 2.0 * t)
f = dict(zip(gf.FEATURE_NAMES_B, gf.features_b(sine)))
expect("a 2 Hz movement is found at 2.0 Hz and is strongly rhythmic", abs(f["acc_freq"] - 2.0) < 1e-6 and f["acc_rhythm"] > 0.3, "%.2f Hz, rhythm %.2f" % (f["acc_freq"], f["acc_rhythm"]))
noise = np.random.RandomState(1).normal(0, 1, (200, 6))
fn = dict(zip(gf.FEATURE_NAMES_B, gf.features_b(noise)))
expect("noise is far less rhythmic than a steady movement", fn["acc_rhythm"] < 0.5 * f["acc_rhythm"], "%.2f vs %.2f" % (fn["acc_rhythm"], f["acc_rhythm"]))
flat = np.zeros((200, 6)); flat[:, 0] = -0.95
ff = dict(zip(gf.FEATURE_NAMES_B, gf.features_b(flat)))
expect("a perfectly still window has (practically) zero spread and does not crash the rhythm measure", ff["ax_std"] < 1e-9 and ff["acc_std"] < 1e-9 and np.isfinite(ff["acc_rhythm"]), "ax_std %.1e, acc_std %.1e, rhythm %.2f" % (ff["ax_std"], ff["acc_std"], ff["acc_rhythm"]))

print("4. loading recordings")
tmp = Path(tempfile.mkdtemp())
def fake_recording(name, n=1000):
    with open(tmp / name, "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh); wr.writerow(["n", "ax", "ay", "az", "gx", "gy", "gz"])
        for i in range(n): wr.writerow([i, i, 0, 0, 0, 0, 0])
rows = [("a__walk__1.csv", "a", "walk", "2026-01-01 10:00:00", 0.0), ("a__walk__2.csv", "a", "walk", "2026-01-01 10:05:00", 0.0),
        ("a__run__1.csv", "a", "run", "2026-01-01 10:10:00", 7.5)]
with open(tmp / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh); wr.writerow(["file", "subject", "label", "note", "start", "seconds", "samples", "dropped", "lost_pct"])
    for name, who, lab, start, lost in rows:
        fake_recording(name); wr.writerow([name, who, lab, "", start, 10, 1000, 0, lost])
recs, skipped = tg.load_recordings(tmp)
expect("a recording with 7.5% lost samples is skipped and reported", skipped == ["a__run__1.csv"] and len(recs) == 2, str(skipped))
expect("one second is trimmed from each end", len(recs[0]["x"]) == 1000 - 2 * tg.TRIM and recs[0]["x"][0][0] == tg.TRIM)
expect("a person's first and second recording of an activity are sessions 0 and 1", [r["session"] for r in recs] == [0, 1])

print("5. the real data")
recs, skipped = tg.load_recordings(ROOT / "data")
W, y, person, session = tg.make_windows(recs)
A, B = tg.compute_features(W)
expect("16 recordings, none skipped, balanced classes", len(recs) == 16 and not skipped and len(set(np.bincount(y))) == 1, str(np.bincount(y)))
rec_of_window = np.concatenate([[i] * len(gf.windows(r["x"])) for i, r in enumerate(recs)])
expect("every window belongs to exactly one recording (none spans two)", len(rec_of_window) == len(y))

print("6. the splits never share a person or a recording")
people = sorted(set(person))
for p in people:
    tr, te = np.where(person != p)[0], np.where(person == p)[0]
    expect("new-person test of %s: nobody in both sets" % p, not (set(person[tr]) & set(person[te])) and not (set(tr) & set(te)))
for s in (0, 1):
    tr, te = np.where(session != s)[0], np.where(session == s)[0]
    expect("new-recording test (session %d held out): no recording in both sets" % s, not (set(rec_of_window[tr]) & set(rec_of_window[te])))

print("7. the held-out person cannot influence any choice")
tr, te = np.where(person != people[0])[0], np.where(person == people[0])[0]
base = tg.evaluate_split(tr, te, A, B, y, person, session, by="session")
shuf = tg.evaluate_split(tr, te, A, B, y, person, session, by="session", shuffle_test_labels=True)
expect("shuffling the held-out labels changes the score but not the chosen feature, the selection score, or a single prediction",
       base["feature"] == shuf["feature"] and base["selection_score"] == shuf["selection_score"] and np.array_equal(base["pred_a"], shuf["pred_a"]) and np.array_equal(base["pred_b"], shuf["pred_b"]) and base["acc_b"] != shuf["acc_b"],
       "feature %s; Model B %.2f -> %.2f when its test labels are shuffled" % (base["feature"], base["acc_b"], shuf["acc_b"]))
B2, A2 = B.copy(), A.copy()
B2[te] = np.random.RandomState(0).normal(0, 50, B2[te].shape); A2[te] = np.random.RandomState(1).normal(0, 50, A2[te].shape)
wrecked = tg.evaluate_split(tr, te, A2, B2, y, person, session, by="session")
expect("replacing the held-out person's features with garbage changes nothing the models learned", wrecked["feature"] == base["feature"] and wrecked["selection_score"] == base["selection_score"])
shuf_acc = np.mean([tg.evaluate_split(tr, te, A, B, y, person, session, by="session", shuffle_test_labels=True, seed=s)["acc_b"] for s in range(5)])
expect("with shuffled labels the score falls to guessing (about 25%), so the test really measures something", 0.15 < shuf_acc < 0.35, "%.0f%%" % (100 * shuf_acc))

print("8. the models on the board")
final = tg.final_models(A, B, y, person, session)
data = tg.export_models(final, Path(tempfile.mkdtemp()) / "m.json")
da, db = data["model_a"], data["model_b"]
c = final["feature_index"]
same_a = all(gait_predict.predict_tree(da["tree"], [A[i, c]]) == p for i, p in enumerate(final["clf_a"].predict(A[:, [c]])))
same_b = all(gait_predict.predict_tree(db["tree"], list(B[i])) == p for i, p in enumerate(final["clf_b"].predict(B)))
expect("the exported Model A gives scikit-learn's answer on all %d windows" % len(y), same_a)
expect("the exported Model B gives scikit-learn's answer on all %d windows" % len(y), same_b)
models = gait_predict.GaitModels(ROOT / "models" / "gait_models.json")
w = gf.windows(recs[0]["x"])[10]
expect("the file in models/ loads and predicts from a raw window", models.predict(w) == (models.predict_a(w), models.predict_b(w)) and models.predict(w)[0] in gf.LABELS)
agree = np.mean([models.predict_b(wi) == gf.LABELS[yi] for wi, yi in zip(W[::25], y[::25])])
expect("on its own training data the shipped Model B is nearly perfect (a sanity check, not a score)", agree > 0.97, "%.0f%%" % (100 * agree))
thr = sorted((t_, i) for i, (t_, f_) in enumerate(zip(da["tree"]["threshold"], da["tree"]["feature"])) if f_ >= 0)
expect("Model A has three thresholds on one number", len(thr) == 3 and da["feature"] == final["feature"], str([round(t_, 3) for t_, _ in thr]))

print("9. repeatable, and the write-up matches the numbers")
out1, out2 = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
for out in (out1, out2):
    sys.argv = ["train_gait.py", "--results", str(out / "r"), "--models", str(out / "m"), "--no-figures"]
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()): tg.main()
expect("training twice gives identical results and models", (out1 / "r" / "results.json").read_text(encoding="utf-8") == (out2 / "r" / "results.json").read_text(encoding="utf-8") and (out1 / "m" / "gait_models.json").read_text(encoding="utf-8") == (out2 / "m" / "gait_models.json").read_text(encoding="utf-8"))
shipped = json.loads((ROOT / "results" / "results.json").read_text(encoding="utf-8"))
expect("the results in the repo are the ones this code produces", shipped == json.loads((out1 / "r" / "results.json").read_text(encoding="utf-8")))
readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
need = []
for key in ("new_person", "new_recording"):
    for col in ("acc_a", "acc_a_fixed", "acc_b"):
        need.append("%.0f%%" % (100 * np.mean([r[col] for r in shipped[key]])))
expect("every average accuracy quoted in the README matches results.json", all(n in readme for n in need), "looked for " + ", ".join(sorted(set(need))))

print(f"\n{'ALL PASSED' if problems == 0 else 'SOME FAILED'} ({problems} problem{'s' if problems != 1 else ''})")
sys.exit(1 if problems else 0)
