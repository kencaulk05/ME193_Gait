# Gait identifier, step 2: the recorder

Turns the IMU stream into labelled CSV files: still, walk, run, bike. You control it from a web page on a phone or laptop, so the unit can stay on your ankle.

## Run

Copy this folder into Arduino App Lab as an app (same layout as the sumo-vision app) and press Run. Then open `http://<board-ip>:7000` on a phone or laptop on the same network.

## Record

1. Type who is wearing it, tap an activity, choose a duration (60 s is a good start), press **START**.
2. A 5 second countdown gives you time to get into position (start walking during it, so recording starts in the middle of the activity).
3. The LED matrix on the board shows the state: dots counting down, a bar filling up while recording, a tick when saved.
4. Stopping early keeps what was recorded if it is at least 2 seconds long.

If the page says **No IMU data**, run the `gait-imu-check` app first.

## Files

Saved in `assets/data/`, which the page serves, so every file has a download link. **Prepare zip of everything** makes one download.

| File | Contents |
|---|---|
| `<person>__<activity>__<date>-<time>.csv` | `n, ax, ay, az, gx, gy, gz`: sample counter, acceleration in g, rotation in degrees/second, 100 samples per second |
| `manifest.csv` | one row per recording: person, activity, note, start time, seconds, samples, samples lost |

`n` counts samples, so a jump in it means readings were lost. More than 2% lost and the page flags the file **RECORD AGAIN**.

## Recording well

- Mount the unit exactly as it will be in the demo, and record everything with that same unit.
- Several minutes per activity, ideally from more than one person: the model is judged on people it has not seen.
- Ignore about the first and last second of every file when training.
- The table on the page shows seconds per person and activity (good files only) so you can see if the data set is balanced.

See `tests/README.md` for how the code was tested, and what could not be.
