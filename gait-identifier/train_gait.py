"""Train and evaluate the two gait models.        python train_gait.py

Reads  data/   (manifest.csv + one CSV per recording, made by the Gait Recorder app)
Writes results/ (figures, summary.md, results.json)  and  models/gait_models.json (what the board loads).

Model A: ONE number per window: the peak acceleration in one direction (which axis and which kind of peak is chosen from the data).
Model B: ALL six IMU outputs: 34 numbers per window (average, spread, lowest, highest, rhythm).
Both are decision trees, so the only difference between them is what they are allowed to look at.

How honesty is kept:
  * every split is by PERSON or by RECORDING, never by window (neighbouring windows overlap and look alike);
  * the choice of Model A's feature uses only the training windows, never the windows being tested;
  * the settings of both trees are simple and fixed here; they were not tuned on the test results.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

import gait_features as gf
from gait_predict import predict_tree  # noqa: F401  (the board's predictor; the tests compare it with scikit-learn)

HERE = Path(__file__).resolve().parent
TRIM = 100               # samples dropped at each end of every recording: starting and stopping are not the activity
MAX_LOST_PCT = 2.0       # recordings with more lost samples than this are not used
TREE_A = dict(max_leaf_nodes=4, random_state=0)                       # one number, four classes: at most three thresholds
TREE_B = dict(max_depth=4, min_samples_leaf=20, random_state=0)
COLORS = {"still": "#7a8699", "walk": "#1f6feb", "run": "#cf222e", "bike": "#1a7f37"}


# ---- data ---------------------------------------------------------------------------------------------------------------
def load_recordings(data_dir):
    """Read the manifest and every good recording. Returns (recordings, names of files that were skipped)."""
    rows = list(csv.DictReader(open(Path(data_dir) / "manifest.csv", newline="")))
    recs, skipped, seen = [], [], {}
    for r in sorted(rows, key=lambda r: r["start"]):
        if float(r["lost_pct"]) > MAX_LOST_PCT:
            skipped.append(r["file"])
            continue
        x = np.loadtxt(Path(data_dir) / r["file"], delimiter=",", skiprows=1, usecols=range(1, 7))
        key = (r["subject"], r["label"])
        session = seen.get(key, 0)                  # 0 = this person's first recording of this activity, 1 = the second
        seen[key] = session + 1
        recs.append({"file": r["file"], "person": r["subject"], "label": r["label"], "session": session, "x": x[TRIM:-TRIM]})
    return recs, skipped


def make_windows(recs):
    """Every window of every recording, with who, what and which recording it came from. A window never spans two recordings."""
    W, y, person, session = [], [], [], []
    for r in recs:
        w = gf.windows(r["x"])
        W.append(w)
        y += [gf.LABELS.index(r["label"])] * len(w)
        person += [r["person"]] * len(w)
        session += [r["session"]] * len(w)
    return np.concatenate(W), np.array(y), np.array(person), np.array(session)


def compute_features(W):
    A = np.array([[gf.peak(w, a, s) for a, s in gf.PEAK_CANDIDATES] for w in W])       # (n, 9): every candidate one-number feature
    B = np.array([gf.features_b(w) for w in W])                                        # (n, 34)
    return A, B


# ---- choosing Model A's feature, from training data only ------------------------------------------------------------------
def choose_peak(train_idx, A, y, person, session, by):
    """Pick which one-number feature to use, looking ONLY at the training windows.
    by='session': train on one of the two recordings of everything, test on the other, both ways (used when only one person is in training).
    by='person':  train on one person, test on another (used when several people are in training)."""
    from sklearn.tree import DecisionTreeClassifier
    groups = session if by == "session" else person
    scores = []
    for c in range(A.shape[1]):
        accs = []
        for g in np.unique(groups[train_idx]):
            tr, te = train_idx[groups[train_idx] != g], train_idx[groups[train_idx] == g]
            if len(tr) == 0 or len(te) == 0:
                continue
            clf = DecisionTreeClassifier(**TREE_A).fit(A[tr][:, [c]], y[tr])
            accs.append(float((clf.predict(A[te][:, [c]]) == y[te]).mean()))
        scores.append(np.mean(accs) if accs else 0.0)
    best = int(np.argmax(scores))
    return best, float(scores[best])


# ---- evaluation ---------------------------------------------------------------------------------------------------------
def evaluate_split(train_idx, test_idx, A, B, y, person, session, by, shuffle_test_labels=False, seed=0, fixed_c=None):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier
    c, selection_score = choose_peak(train_idx, A, y, person, session, by)
    clf_a = DecisionTreeClassifier(**TREE_A).fit(A[train_idx][:, [c]], y[train_idx])
    clf_b = DecisionTreeClassifier(**TREE_B).fit(B[train_idx], y[train_idx])
    forest = RandomForestClassifier(n_estimators=100, min_samples_leaf=20, random_state=0).fit(B[train_idx], y[train_idx])
    y_test = y[test_idx].copy()
    if shuffle_test_labels:                         # used by a test: the held-out labels must not influence any choice
        np.random.RandomState(seed).shuffle(y_test)
    pa, pb, pf = clf_a.predict(A[test_idx][:, [c]]), clf_b.predict(B[test_idx]), forest.predict(B[test_idx])
    result = {"feature": gf.peak_name(*gf.PEAK_CANDIDATES[c]), "feature_index": c, "selection_score": selection_score,
              "acc_a": float((pa == y_test).mean()), "acc_b": float((pb == y_test).mean()), "acc_forest": float((pf == y_test).mean()),
              "y_test": y_test, "pred_a": pa, "pred_b": pb}
    if fixed_c is not None:
        # The deployed Model A: its feature was chosen using ALL the data, including the people being tested here, so this is optimistic.
        clf_fixed = DecisionTreeClassifier(**TREE_A).fit(A[train_idx][:, [fixed_c]], y[train_idx])
        pfix = clf_fixed.predict(A[test_idx][:, [fixed_c]])
        result.update(acc_a_fixed=float((pfix == y_test).mean()), pred_a_fixed=pfix)
    return result


def run_protocols(A, B, y, person, session, fixed_c=None):
    people = sorted(set(person))
    out = {"new_person": [], "new_recording": []}
    for p in people:                                # train on everyone else, test on this person
        tr, te = np.where(person != p)[0], np.where(person == p)[0]
        r = evaluate_split(tr, te, A, B, y, person, session, by="session", fixed_c=fixed_c)
        r.update(train=", ".join(q for q in people if q != p), test=p)
        out["new_person"].append(r)
    for s in (0, 1):                                # same people, a recording they were not trained on
        tr, te = np.where(session != s)[0], np.where(session == s)[0]
        r = evaluate_split(tr, te, A, B, y, person, session, by="person", fixed_c=fixed_c)
        r.update(train="recording %d of everyone" % (1 - s + 1), test="recording %d of everyone" % (s + 1))
        out["new_recording"].append(r)
    return out


def final_models(A, B, y, person, session):
    """Fit both models on ALL the data (this is what the board uses)."""
    from sklearn.tree import DecisionTreeClassifier
    idx = np.arange(len(y))
    c, score = choose_peak(idx, A, y, person, session, by="person")
    return {"feature_index": c, "feature": gf.peak_name(*gf.PEAK_CANDIDATES[c]), "selection_score": score,
            "clf_a": DecisionTreeClassifier(**TREE_A).fit(A[:, [c]], y),
            "clf_b": DecisionTreeClassifier(**TREE_B).fit(B, y)}


# ---- export for the board ---------------------------------------------------------------------------------------------
def tree_to_dict(clf):
    t = clf.tree_
    return {"left": [int(v) for v in t.children_left], "right": [int(v) for v in t.children_right],
            "feature": [int(v) for v in t.feature], "threshold": [float(v) for v in t.threshold],
            "leaf": [int(clf.classes_[int(np.argmax(v))]) for v in t.value[:, 0, :]]}


def export_models(final, out_path):
    axis, stat = gf.PEAK_CANDIDATES[final["feature_index"]]
    data = {"fs": gf.FS, "window_samples": gf.WIN, "step_samples": gf.STEP, "labels": gf.LABELS,
            "model_a": {"feature": final["feature"], "axis": axis, "stat": stat, "tree": tree_to_dict(final["clf_a"])},
            "model_b": {"features": gf.FEATURE_NAMES_B, "tree": tree_to_dict(final["clf_b"])}}
    Path(out_path).write_text(json.dumps(data, indent=1))
    return data


# ---- figures --------------------------------------------------------------------------------------------------------------
def recolor_tree(artists):
    """Give each tree node the colour of its activity (paler when the node is mixed), matching the other figures."""
    import re
    from matplotlib.colors import to_rgb
    for a in artists:
        text = a.get_text()
        m, v = re.search(r"class = (\w+)", text), re.search(r"value = \[([^\]]+)\]", text)
        if not m or not v:
            continue
        purity = max(float(t) for t in v.group(1).split(","))
        strength = max(0.0, (purity - 0.4) / 0.6)
        base = to_rgb(COLORS[m.group(1)])
        a.get_bbox_patch().set_facecolor(tuple(1 - strength * 0.7 * (1 - c) for c in base))


def figures(recs, W, y, person, A, B, protocols, final, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    from sklearn.metrics import confusion_matrix
    from sklearn.tree import plot_tree
    out = Path(out)
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})

    # 1. what the sensor sees
    fig, axes = plt.subplots(2, 4, figsize=(14, 5.2), sharex=True)
    for j, lab in enumerate(gf.LABELS):
        r = next(r for r in recs if r["label"] == lab and r["person"] == recs[0]["person"] and r["session"] == 0)
        seg = r["x"][3000:3400]
        t = np.arange(len(seg)) / gf.FS
        axes[0, j].plot(t, seg[:, 0], color=COLORS[lab], lw=1.4)
        axes[1, j].plot(t, np.linalg.norm(seg[:, 3:], axis=1), color=COLORS[lab], lw=1.4)
        axes[0, j].set_title(lab, color=COLORS[lab], fontweight="bold")
        axes[0, j].set_ylim(-4.5, 4.5)
        axes[1, j].set_ylim(0, 800)
        axes[1, j].set_xlabel("seconds")
        if j == 0:
            axes[0, j].set_ylabel("ax: acceleration along\nthe shin (g)")
            axes[1, j].set_ylabel("rotation speed\n(degrees/second)")
    fig.suptitle("What the ankle sensor sees: 4 seconds of each activity (%s)" % recs[0]["person"], fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "signals.png", dpi=150)
    plt.close(fig)

    # 2. Model A: why one number is not enough
    c = final["feature_index"]
    thresholds = sorted(t for t, f in zip(final["clf_a"].tree_.threshold, final["clf_a"].tree_.feature) if f >= 0)
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    lo, hi = np.percentile(A[:, c], [0.5, 99.5])
    bins = np.linspace(lo, hi, 55)
    for i, lab in enumerate(gf.LABELS):
        ax.hist(A[y == i, c], bins=bins, alpha=0.6, color=COLORS[lab], label=lab)
    for th in thresholds:
        ax.axvline(th, color="black", ls="--", lw=1.2)
        ax.text(th, ax.get_ylim()[1] * 0.97, " %.2f g" % th, rotation=90, va="top", ha="left", fontsize=9)
    ax.set_xlabel("Model A's one number: %s (g), the peak in each 2 second window" % final["feature"])
    ax.set_ylabel("number of windows")
    ax.set_title("Where the activities fall on that one number (dashed = the model's thresholds)", fontweight="bold")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "model_a_peak_histogram.png", dpi=150)
    plt.close(fig)

    # 3. confusion matrices, pooled over the "new person" tests
    yt = np.concatenate([r["y_test"] for r in protocols["new_person"]])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    for ax, key, name in zip(axes, ("pred_a_fixed", "pred_b"), ("Model A: one number (%s)" % final["feature"], "Model B: all six outputs")):
        yp = np.concatenate([r[key] for r in protocols["new_person"]])
        cm = confusion_matrix(yt, yp, labels=range(4))
        pct = cm / cm.sum(axis=1, keepdims=True) * 100
        ax.imshow(pct, cmap="Blues", vmin=0, vmax=100)
        for i in range(4):
            for j in range(4):
                ax.text(j, i, "%.0f%%\n(%d)" % (pct[i, j], cm[i, j]), ha="center", va="center", color="white" if pct[i, j] > 55 else "black", fontsize=10)
        ax.set_xticks(range(4)); ax.set_xticklabels(gf.LABELS); ax.set_yticks(range(4)); ax.set_yticklabels(gf.LABELS)
        ax.set_xlabel("predicted"); ax.set_ylabel("what they were really doing")
        note = "optimistic: its number was chosen using both people" if key == "pred_a_fixed" else "on a person it never saw"
        ax.set_title("%s\n%.0f%% correct, %s" % (name, 100 * (yt == yp).mean(), note), fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "confusion_matrices.png", dpi=150)
    plt.close(fig)

    # 4. accuracy comparison
    fig, ax = plt.subplots(figsize=(10, 5.2))
    groups = [("new person\n(train on one, test on the other)", protocols["new_person"]), ("new recording\n(same two people)", protocols["new_recording"])]
    for g, (label, runs) in enumerate(groups):
        for m, (key, name, color) in enumerate((("acc_a", "Model A, feature chosen fairly", "#e9c28f"), ("acc_a_fixed", "Model A, deployed feature (optimistic)", "#d1862b"), ("acc_b", "Model B: all six outputs", "#1f6feb"))):
            vals = [100 * r[key] for r in runs]
            x = g + (m - 1) * 0.27
            ax.bar(x, np.mean(vals), width=0.25, color=color, label=name if g == 0 else None)
            ax.scatter([x] * len(vals), vals, color="black", s=14, zorder=3)
            ax.text(x, 4, "%.0f%%" % np.mean(vals), ha="center", fontweight="bold", color="white" if key != "acc_a" else "black")
    ax.axhline(25, color="gray", ls=":", lw=1); ax.text(0.57, 26, "guessing = 25%", color="gray", ha="center", fontsize=9, bbox=dict(fc="white", ec="none", pad=1.5))
    ax.set_xticks(range(2)); ax.set_xticklabels([g[0] for g in groups]); ax.set_ylim(0, 112); ax.set_ylabel("windows classified correctly (%)")
    ax.set_title("Dots are the individual tests; bars are their average", fontweight="bold")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "accuracy_comparison.png", dpi=150)
    plt.close(fig)

    # 5. the two trees
    fig, ax = plt.subplots(figsize=(9, 4.4))
    recolor_tree(plot_tree(final["clf_a"], feature_names=[final["feature"] + " (g)"], class_names=gf.LABELS, filled=False, rounded=True, impurity=False, proportion=True, fontsize=10, ax=ax))
    ax.set_title("Model A: the final tree (one number, so only thresholds)", fontweight="bold")
    fig.tight_layout(); fig.savefig(out / "tree_model_a.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(22, 9))
    recolor_tree(plot_tree(final["clf_b"], feature_names=gf.FEATURE_NAMES_B, class_names=gf.LABELS, filled=False, rounded=True, impurity=False, proportion=True, fontsize=9, ax=ax))
    ax.set_title("Model B: the final tree (all six outputs)", fontweight="bold")
    fig.tight_layout(); fig.savefig(out / "tree_model_b.png", dpi=130); plt.close(fig)

    # 6. the system, as a picture
    fig, ax = plt.subplots(figsize=(13, 4.8))
    ax.axis("off"); ax.set_xlim(0, 13); ax.set_ylim(0, 5)
    def box(x, y, w, h, text, color):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.15", fc=color, ec="#33415c", lw=1.3))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=10)
    def arrow(x0, y0, x1, y1):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->", lw=1.6, color="#33415c"))
    box(0.1, 1.8, 2.2, 1.4, "IMU on the ankle\nMPU-6050\n100 readings/second\nax ay az gx gy gz", "#e8f1ff")
    box(3.0, 1.8, 2.0, 1.4, "2 second window\nnew one every\n0.5 seconds", "#eef7ee")
    box(5.8, 3.0, 2.8, 1.5, "MODEL A\none number:\npeak of %s\n-> thresholds" % final["feature"], "#fff1dc")
    box(5.8, 0.5, 2.8, 1.5, "MODEL B\nall six outputs:\n34 numbers\n-> decision tree", "#e1ecff")
    box(9.4, 1.8, 1.7, 1.4, "label:\nstill / walk /\nrun / bike", "#f3e8ff")
    box(11.5, 1.8, 1.4, 1.4, "LED matrix\nand web page", "#ffe8e8")
    arrow(2.35, 2.5, 2.95, 2.5); arrow(5.05, 2.7, 5.75, 3.6); arrow(5.05, 2.3, 5.75, 1.4)
    arrow(8.65, 3.6, 9.35, 2.8); arrow(8.65, 1.4, 9.35, 2.2); arrow(11.15, 2.5, 11.45, 2.5)
    ax.text(6.5, 4.8, "Both models are decision trees: the only difference is what they are allowed to look at.", ha="center", fontsize=10, style="italic")
    fig.tight_layout(); fig.savefig(out / "pipeline.png", dpi=150); plt.close(fig)


# ---- the written summary ----------------------------------------------------------------------------------------------
def write_summary(recs, skipped, W, y, person, protocols, final, out):
    from sklearn.metrics import confusion_matrix
    lines = []
    add = lines.append
    add("# Results\n")
    add("**Data:** %d recordings (%s), %d windows of 2 seconds (every 0.5 s) after trimming 1 s from each end of every recording. %s\n" % (
        len(recs), ", ".join(sorted(set(person))), len(y), ("Skipped for lost samples: " + ", ".join(skipped)) if skipped else "No recording was skipped."))
    add("Neighbouring windows overlap by 75%, so the number of independent test windows is about a quarter of the counts below; read differences of a few percent as noise.\n")
    add("## Accuracy\n")
    add("| Test | Model A, feature chosen from the training data only (fair) | Model A, feature `%s` chosen using everyone (optimistic) | Model B (all six outputs) | Extra: random forest on B's numbers |" % final["feature"])
    add("|---|---|---|---|---|")
    for key, title in (("new_person", "New person"), ("new_recording", "New recording, same people")):
        for r in protocols[key]:
            add("| %s: trained on %s, tested on %s | %.1f%% (it chose %s) | %.1f%% | %.1f%% | %.1f%% |" % (title, r["train"], r["test"], 100 * r["acc_a"], r["feature"], 100 * r["acc_a_fixed"], 100 * r["acc_b"], 100 * r["acc_forest"]))
        add("| **%s, average** | **%.1f%%** | **%.1f%%** | **%.1f%%** | %.1f%% |" % (title, 100 * np.mean([r["acc_a"] for r in protocols[key]]), 100 * np.mean([r["acc_a_fixed"] for r in protocols[key]]), 100 * np.mean([r["acc_b"] for r in protocols[key]]), 100 * np.mean([r["acc_forest"] for r in protocols[key]])))
    add("\n'New person' is the hard test: it is what your graders will be. With only two people, Model A's number can be chosen fairly only from ONE person's recordings, and that choice does not transfer (first column). The model on the board uses `%s`, chosen with both people's data, so its second-column score is optimistic. The truth for a new person lies between the two columns; a third person recorded would settle it.\n" % final["feature"])
    yt = np.concatenate([r["y_test"] for r in protocols["new_person"]])
    add("## What each model gets wrong (new-person tests, pooled; rows = what really happened)\n")
    for key, name in (("pred_a", "Model A, fair feature choice"), ("pred_a_fixed", "Model A, the deployed feature (optimistic)"), ("pred_b", "Model B")):
        yp = np.concatenate([r[key] for r in protocols["new_person"]])
        cm = confusion_matrix(yt, yp, labels=range(4))
        add("**%s**\n" % name)
        add("| really \\ predicted | " + " | ".join(gf.LABELS) + " | correct |")
        add("|---|" + "---|" * 5)
        for i, lab in enumerate(gf.LABELS):
            add("| %s | " % lab + " | ".join(str(v) for v in cm[i]) + " | %.0f%% |" % (100 * cm[i, i] / cm[i].sum()))
        add("")
    add("## The final models (trained on all the data, for the board)\n")
    t = [(th, f) for th, f in zip(final["clf_a"].tree_.threshold, final["clf_a"].tree_.feature) if f >= 0]
    add("* **Model A** looks at `%s` only. Thresholds: %s g.\n" % (final["feature"], ", ".join("%.2f" % th for th, _ in sorted(t))))
    imp = sorted(zip(gf.FEATURE_NAMES_B, final["clf_b"].feature_importances_), key=lambda p: -p[1])
    add("* **Model B** uses these numbers (share of the tree's decisions): %s.\n" % ", ".join("`%s` %.0f%%" % (n, 100 * v) for n, v in imp if v > 0.005))
    add("The final models were trained on everything, so they have no honest test score of their own: the tables above are the evidence.\n")
    Path(out).write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data"))
    ap.add_argument("--results", default=str(HERE / "results"))
    ap.add_argument("--models", default=str(HERE / "models"))
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()
    Path(args.results).mkdir(parents=True, exist_ok=True)
    Path(args.models).mkdir(parents=True, exist_ok=True)
    recs, skipped = load_recordings(args.data)
    W, y, person, session = make_windows(recs)
    print("%d recordings, %d windows (%s)" % (len(recs), len(y), ", ".join("%s %d" % (l, (y == i).sum()) for i, l in enumerate(gf.LABELS))))
    A, B = compute_features(W)
    final = final_models(A, B, y, person, session)
    print("final Model A feature:", final["feature"])
    protocols = run_protocols(A, B, y, person, session, fixed_c=final["feature_index"])
    for key in protocols:
        for r in protocols[key]:
            print("%-14s train %-22s test %-22s A %.3f (%s)  A-fixed %.3f  B %.3f  forest %.3f" % (key, r["train"], r["test"], r["acc_a"], r["feature"], r["acc_a_fixed"], r["acc_b"], r["acc_forest"]))
    export_models(final, Path(args.models) / "gait_models.json")
    write_summary(recs, skipped, W, y, person, protocols, final, Path(args.results) / "summary.md")
    serial = {k: [{kk: vv for kk, vv in r.items() if kk not in ("y_test", "pred_a", "pred_b", "pred_a_fixed")} for r in v] for k, v in protocols.items()}
    (Path(args.results) / "results.json").write_text(json.dumps(serial, indent=1))
    if not args.no_figures:
        figures(recs, W, y, person, A, B, protocols, final, args.results)
    print("done: results in", args.results, "| models in", args.models)


if __name__ == "__main__":
    main()
