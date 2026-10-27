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


class GaitModels:
    def __init__(self, path=DEFAULT_MODELS):
        data = json.loads(Path(path).read_text())
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
