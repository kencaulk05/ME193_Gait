# Host-side tests (no board needed)

They check the logic on a normal computer, against stand-ins for the UNO Q: a fake MPU-6050 on a fake I2C bus and a fake Bridge for the sketch, and a fake `arduino.app_utils` with a synthetic sample stream for the Python app.

```
g++ -std=c++17 -I stubs -o test_sketch test_sketch.cpp && ./test_sketch          # the sketch: registers, units, 100 Hz timing, sensor missing / late / dying
g++ -std=c++17 -DTRY_QWIIC=1 -I stubs -o test_sketch_qwiic test_sketch.cpp && ./test_sketch_qwiic   # the same with the Qwiic bus enabled
python test_python.py                                                              # the guided self-test: a healthy sensor and six faults
```

What they cannot show: that the real MPU-6050, the real I2C wiring and the real Bridge behave like the stand-ins. That is what the app's own self-test on the board is for.
