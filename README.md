# ME193 Gait Identifier

A wearable that tells whether you are **standing still, walking, running or biking**. It is an Arduino UNO Q with an MPU-6050 motion sensor (3-axis accelerometer + 3-axis gyroscope) strapped to the ankle, and it classifies each 2 second window of motion with a decision tree. No neural networks.

![pipeline](gait-identifier/results/pipeline.png)

## Results

Two models are compared to see what the extra sensor information is worth:

- **Model A** looks at one number: the peak acceleration along the shin (`ax_max`).
- **Model B** looks at all six IMU outputs (34 features per window).

| Test | Model A | **Model B** |
|---|---|---|
| **New person** (train on one, test on the other) | 65–83% | **97%** |
| **New recording** (same two people) | 85% | **98%** |

The range for Model A on a new person runs from a fair estimate to an optimistic one; [gait-identifier/README.md](gait-identifier/README.md) explains why. Data: 2 people × 4 activities × 2 recordings × 120 s.

## What's in the repo

Everything lives in [gait-identifier](gait-identifier/): the training and evaluation code, the recorded data, the results, and the three apps that run on the UNO Q (copy a folder from `apps/` into Arduino App Lab as an app).

| Folder | What it does |
|---|---|
| [gait-identifier/apps/gait-imu-check](gait-identifier/apps/gait-imu-check/) | Checks the MPU-6050 is wired and working: guided still/shake/rotate self-test, PASS/FAIL |
| [gait-identifier/apps/gait-recorder](gait-identifier/apps/gait-recorder/) | Records labelled CSV files (still, walk, run, bike), controlled from a web page on a phone or laptop |
| [gait-identifier/apps/gait-live](gait-identifier/apps/gait-live/) | **The live demo**: both models side by side on a web page and the LED matrix, with a test mode that scores each model on whoever is wearing it |

Each folder has its own README with setup and run instructions.

## Quick start

```
cd gait-identifier
pip install -r requirements.txt
python train_gait.py          # evaluates both models, writes results/ and models/gait_models.json
python run_all_tests.py       # every test in the project
python sync_live_app.py       # after retraining: copies the new models into the live app
```

## Status

Training, evaluation and all three apps are built and tested on a computer against stand-ins for the board. The live app has not yet been run on the real board.
