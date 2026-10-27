# Tests (no board needed)

```
python test_live.py                                     # python/main.py: live answers equal the offline ones, warming up, lost samples, smoothing, scoring, the log, the page's messages, the LED, a streamed demo
g++ -std=c++17 -I stubs -o test_sketch test_sketch.cpp && ./test_sketch        # the sketch: IMU registers, units, 100 Hz, and each LED letter pixel by pixel
g++ -std=c++17 -DTRY_QWIIC=1 -I stubs -o test_sketch_qwiic test_sketch.cpp && ./test_sketch_qwiic
npm install jsdom && node test_page.js                  # the web page in a simulated browser
```

The Python test compares the app's copies of the shared code with the repo's originals when the app sits inside the repo (in `apps/gait-live`), and uses the real recordings in `data/` for the equivalence and demo tests; without them, those parts are skipped. From the repo root, `python run_all_tests.py` runs everything.
