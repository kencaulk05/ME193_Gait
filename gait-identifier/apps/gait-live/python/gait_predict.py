"""Run the trained models without scikit-learn: this is what the board uses.

    models = GaitModels()                 # reads models/gait_models.json
    a, b = models.predict(window)         # window: (200, 6) array of ax ay az gx gy gz  ->  ("walk", "walk")
"""
import json
import struct
from pathlib import Path

import gait_features as gf

DEFAULT_MODELS = Path(__file__).resolve().parent / "models" / "gait_models.json"


def predict_tree(tree, x):
    """Walk an exported tree. The features are compared as float32, because scikit-learn does the same."""
    node = 0
    while tree["left"][node] != -1:
        v = struct.unpack("f", struct.pack("f", x[tree["feature"][node]]))[0]
        node = tree["left"][node] if v <= tree["threshold"][node] else tree["right"][node]
    return tree["leaf"][node]


def explain_tree(tree, x):
    """Like predict_tree, but also returns the questions the tree asked on the way:
    (the answer, [(feature index, the value it looked at, the threshold, whether the answer was yes), ...])."""
    steps, node = [], 0
    while tree["left"][node] != -1:
        feature, threshold = tree["feature"][node], tree["threshold"][node]
        v = struct.unpack("f", struct.pack("f", x[feature]))[0]
        yes = v <= threshold
        steps.append((feature, float(x[feature]), threshold, yes))
        node = tree["left"][node] if yes else tree["right"][node]
    return tree["leaf"][node], steps


class GaitModels:
    def __init__(self, path=DEFAULT_MODELS):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.labels = data["labels"]
        self.window = data["window_samples"]
        self.model_a, self.model_b = data["model_a"], data["model_b"]

    def predict_a(self, w):
        """Model A: one number, the peak acceleration in one direction."""
        axis, stat = self.model_a["axis"], self.model_a["stat"]
        return self.labels[predict_tree(self.model_a["tree"], [gf.peak(w, axis, stat)])]

    def predict_b(self, w):
        """Model B: all six IMU outputs."""
        return self.labels[predict_tree(self.model_b["tree"], gf.features_b(w))]

    def predict(self, w):
        return self.predict_a(w), self.predict_b(w)

    def analyze(self, w):
        """Everything the live page shows about one window: both answers, the number Model A looked at, and how each tree decided."""
        axis, stat = self.model_a["axis"], self.model_a["stat"]
        a_value = gf.peak(w, axis, stat)
        a_class, a_steps = explain_tree(self.model_a["tree"], [a_value])
        b_features = gf.features_b(w)
        b_class, b_steps = explain_tree(self.model_b["tree"], b_features)
        names_b = self.model_b["features"]
        return {"a": self.labels[a_class], "b": self.labels[b_class], "a_name": self.model_a["feature"], "a_value": a_value,
                "a_path": [(self.model_a["feature"], v, t, yes) for _, v, t, yes in a_steps],
                "b_path": [(names_b[f], v, t, yes) for f, v, t, yes in b_steps]}

    def a_segments(self):
        """Model A as a number line: [(label, lowest value, highest value), ...] from left to right (None = no limit)."""
        ts = sorted(t for t, f in zip(self.model_a["tree"]["threshold"], self.model_a["tree"]["feature"]) if f >= 0)
        edges = [None] + ts + [None]
        probes = [ts[0] - 1.0] + [(ts[i] + ts[i + 1]) / 2 for i in range(len(ts) - 1)] + [ts[-1] + 1.0]
        return [(self.labels[predict_tree(self.model_a["tree"], [p])], edges[i], edges[i + 1]) for i, p in enumerate(probes)]
