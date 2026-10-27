# Tests (no board needed)

They check the logic on a normal computer, against stand-ins for the UNO Q and for a browser.

```
python test_recorder.py                       # python/main.py: recording, saving, lost samples, files, zip, commands, the LED sequence
g++ -std=c++17 -I stubs -o test_sketch test_sketch.cpp && ./test_sketch                              # the sketch: registers, units, 100 Hz timing, sensor missing/late/dying, LED patterns
g++ -std=c++17 -DTRY_QWIIC=1 -I stubs -o test_sketch_qwiic test_sketch.cpp && ./test_sketch_qwiic   # the same with the Qwiic bus enabled
npm install jsdom && node test_page.js        # the web page, in a simulated browser: buttons, messages, file list, plot, hostile file names
```

What they cannot show: that the real MPU-6050, the real I2C wiring, the real Bridge, the real LED matrix and a real phone browser behave like the stand-ins. That is what the first recording on the board is for.
