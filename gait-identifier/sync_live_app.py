"""Copy the shared code and the trained models into the live app, so the board runs exactly what was trained and tested here.

    python sync_live_app.py        (run it again after every  python train_gait.py)
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "apps" / "gait-live" / "python"
FILES = [("gait_features.py", "gait_features.py"), ("gait_predict.py", "gait_predict.py"), ("models/gait_models.json", "gait_models.json")]

if __name__ == "__main__":
    for src, dst in FILES:
        shutil.copyfile(ROOT / src, APP / dst)
        print("copied", src, "->", (APP / dst).relative_to(ROOT))
