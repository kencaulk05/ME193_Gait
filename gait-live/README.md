# Gait Live: the live demo

Runs on the UNO Q. It reads the ankle IMU and, every half second, shows what **Model A** (one number) and **Model B** (all six outputs) think the wearer is doing: still, walk, run or bike. Both answers appear on a web page and on the LED matrix, so you can watch the two models agree and disagree in real time.

## Run it

1. Copy this folder into Arduino App Lab as an app (same layout as the other apps) and press Run. The wiring is the same as in `gait-imu-check`.
2. Open `http://<board-ip>:7000` on a phone or laptop on the same network.
3. For the first two seconds it collects data ("warming up"), then it answers every half second.

## What you see

* **Two cards, side by side.** The big label is each model's answer. Model A's card shows the one number it looks at (`ax_max`, the highest value of the shin axis in the last 2 seconds) as a marker on a number line split into still, walk, run and bike. Both cards list the questions their tree asked to reach the answer.
* **History strips.** The last 60 seconds, one block per half second, for each model. Model A's blocks flicker where its stretches overlap; Model B's are steadier.
* **The sensor plot.** The shin axis and the rotation speed for the last 3 seconds, with Model A's thresholds as dashed lines.
* **The LED matrix.** Model A's answer on the left and Model B's on the right, as one letter each (S still, W walk, R run, B bike). A dotted divider appears when they disagree.
* **Smoothing.** The big labels (and the LED) use the majority of the last three answers, so one odd half second does not flash up. Switch it off on the page to see every raw answer. The scores below always use every raw window.

## Test mode: scoring the models on a person

1. Type the person's name.
2. Tap what they are **really doing** (still, walking, running or biking), then let them do it for 20 to 30 seconds.
3. Read the live score for each model. The table shows the score per activity, and the sentence underneath shows what happens when the models disagree.
4. Tap another activity, or "Clear scores" before the next person.

Every scored window is also appended to `assets/data/live_log.csv` (time, person, what they were doing, Model A, Model B, Model A's number), and the page links to it. The log is not cleared by "Clear scores".

A window is scored every half second, so 20 seconds is about 40 windows. Neighbouring windows overlap, so treat differences of a few percent as noise.

## How it works

* The sketch reads the MPU-6050 at 100 Hz and sends every reading to Python.
* Python keeps the last 200 samples and cuts a window every 50 new samples, exactly as in training (`gait_features.py`, the same file the training script uses).
* Both models are decision trees exported by the training script as plain numbers (`gait_models.json`) and run by `gait_predict.py`, so the board needs no machine-learning library.
* If more than 5% of a window's samples were lost on the way, that window is skipped rather than guessed.

## Files

| | |
|---|---|
| `sketch/sketch.ino` | IMU at 100 Hz (identical to the code that ran in the recorder) and the two-letter LED display |
| `python/main.py` | Window buffer, both models, smoothing, scoring, log, and the link to the page and the LED |
| `python/gait_features.py`, `gait_predict.py`, `gait_models.json` | Copies of the repo's shared code and trained models. Run `python sync_live_app.py` in the repo root after retraining |
| `assets/` | The web page |
| `tests/` | See `tests/README.md` |

## What was tested, and what was not

Tested on a normal computer, with a fake Arduino, a fake sensor and a simulated browser: on all 752 windows of the 16 recordings the live code gives exactly the same answers as the offline code; warming up, lost samples, a stream that stops and returns, smoothing, scoring, the log, every command from the page, the LED letters pixel by pixel, and the page itself.

**Not yet tested on the real board:** the LED letters on the real matrix, the page on a phone, and the log download link. The first run should check those three. The sensor code, the 100 Hz stream, the page-to-board messages and the LED call from the loop use the same patterns that already ran in `gait-recorder`.

Models were trained on two people. The live accuracy on a new person is exactly what test mode measures.
