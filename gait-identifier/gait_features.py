"""Windows and features, shared by the training script and the live app (numpy only).

The IMU sends 100 samples a second: ax, ay, az (acceleration in g) and gx, gy, gz (rotation in degrees/second).
A window is 2 seconds (200 samples); a new window starts every 0.5 seconds.
"""
import numpy as np

FS = 100                 # samples per second
WIN = 200                # samples in a window: 2 seconds
STEP = 50                # samples between windows: 0.5 seconds
CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]
LABELS = ["still", "walk", "run", "bike"]


def windows(x, win=WIN, step=STEP):
    """Cut an (n, 6) array into overlapping windows: shape (count, win, 6). A window never runs past the end."""
    x = np.asarray(x, dtype=float)
    if len(x) < win:
        return np.empty((0, win, x.shape[1]))
    return np.array([x[i:i + win] for i in range(0, len(x) - win + 1, step)])


# ---- Model A: one number, the peak acceleration in one direction -----------------------------------------------------
PEAK_CANDIDATES = [(axis, stat) for axis in range(3) for stat in ("max", "min", "maxabs")]


def peak_name(axis, stat):
    return "%s_%s" % (CHANNELS[axis], stat)


def peak(w, axis, stat):
    """The peak of one acceleration axis in a window: its highest value, its lowest value, or its largest size."""
    a = w[:, axis]
    if stat == "max":
        return float(a.max())
    if stat == "min":
        return float(a.min())
    return float(np.abs(a).max())


# ---- Model B: all six outputs ------------------------------------------------------------------------------------------
FEATURE_NAMES_B = ([f"{c}_{s}" for c in CHANNELS for s in ("mean", "std", "min", "max")]
                   + ["acc_mean", "acc_std", "acc_max", "gyro_mean", "gyro_std", "gyro_max"]
                   + ["acc_freq", "acc_rhythm", "gyro_freq", "gyro_rhythm"])


def rhythm(signal):
    """(dominant frequency in Hz between 0.5 and 5, how much of the signal's strength is in that one frequency)."""
    s = signal - signal.mean()
    spectrum = np.abs(np.fft.rfft(s * np.hanning(len(s))))
    freqs = np.fft.rfftfreq(len(s), 1.0 / FS)
    band = (freqs >= 0.5) & (freqs <= 5.0)
    k = int(np.argmax(spectrum[band]))
    return float(freqs[band][k]), float(spectrum[band][k] / (spectrum[1:].sum() + 1e-9))


def features_b(w):
    """34 numbers describing a window using every IMU output."""
    f = []
    for c in range(6):
        v = w[:, c]
        f += [v.mean(), v.std(), v.min(), v.max()]
    acc = np.linalg.norm(w[:, :3], axis=1)
    gyro = np.linalg.norm(w[:, 3:], axis=1)
    f += [acc.mean(), acc.std(), acc.max(), gyro.mean(), gyro.std(), gyro.max()]
    f += list(rhythm(acc)) + list(rhythm(gyro))
    return [float(v) for v in f]
