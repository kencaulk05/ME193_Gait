# Gait identifier, step 1: is the IMU alive?

An MPU-6050 (3-axis accelerometer + 3-axis gyroscope) on an Arduino UNO Q. The sketch reads it 100 times a second and sends every reading to Python; the Python app runs a short guided self-test and then keeps printing one line a second.

## Wiring

The UNO Q header is **3.3 V logic**, so power the module from **3V3, not 5V**.

| MPU-6050 pin | UNO Q |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | SDA (header pin next to AREF) |
| SCL | SCL (header pin next to AREF) |
| AD0, INT, XDA, XCL | leave unconnected |

With a Qwiic cable instead, set `TRY_QWIIC` to `1` at the top of `sketch/sketch.ino`.

## Run

In Arduino App Lab create a new app, replace its `sketch.ino` and `main.py` with the ones here (the app needs no bricks), and press Run. Watch the **Python** tab and follow the instructions it prints: 10 s get ready, 8 s still, 8 s shake, 8 s rotate, then PASS/FAIL for each.

## If something is off

| You see | Try |
|---|---|
| `NO SENSOR FOUND` | Check 3V3, GND, SDA, SCL; the sketch keeps looking once a second, so you can fix the wiring while it runs |
| App Lab complains about `Wire1` | Set `TRY_QWIIC` back to `0` |
| Far fewer than 100 samples a second | Shorter or firmer wires; keep `I2C_HZ` at 100000 |
| Gravity is not about 1.00 g when still | Report it: it means a range or scale problem |
