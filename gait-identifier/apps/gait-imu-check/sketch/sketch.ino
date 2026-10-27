// Gait identifier - step 1 - UNO Q microcontroller side.
//
// Reads an MPU-6050 (3-axis accelerometer + 3-axis gyroscope) over I2C at 100 Hz and sends EVERY reading to Python:
//     Bridge.notify("imu", n, ax, ay, az, gx, gy, gz)
//         n  = sample counter (so Python can see a missed sample)
//         a* = acceleration in g (1.0 = gravity),  g* = rotation in degrees per second
// Python can also ask  Bridge.call("imu_status")  for one line saying what was found.
//
// WIRING (the UNO Q header is 3.3 V logic, so power the module from 3V3, NOT 5V):
//     MPU-6050 VCC -> 3V3      GND -> GND      SDA -> SDA      SCL -> SCL      (AD0 and INT: leave unconnected)
//   SDA and SCL are the two header pins next to AREF. With a Qwiic cable set TRY_QWIIC to 1 below.
#include <Arduino_RouterBridge.h>
#include <Wire.h>

#ifndef TRY_QWIIC
#define TRY_QWIIC 0          // 1 = if nothing answers on the header pins, also look on the Qwiic connector (Wire1)
#endif
#ifndef I2C_HZ
#define I2C_HZ 100000        // 100 kHz is the safe choice for a longer cable to an ankle; 400000 is fine on short wires
#endif

const uint8_t  REG_WHO_AM_I = 0x75, REG_PWR_MGMT_1 = 0x6B, REG_SMPLRT_DIV = 0x19, REG_CONFIG = 0x1A,
               REG_GYRO_CONFIG = 0x1B, REG_ACCEL_CONFIG = 0x1C, REG_ACCEL_XOUT_H = 0x3B;
const uint32_t PERIOD_US = 10000;       // 100 samples per second
const float    ACCEL_LSB_PER_G   = 2048.0f;   // +-16 g range: running impacts at the ankle are several g
const float    GYRO_LSB_PER_DPS  = 16.4f;     // +-2000 degrees/second range

TwoWire *bus = nullptr;
uint8_t  addr = 0;
bool     ok = false;
char     status[96] = "starting";
uint32_t counter = 0;
uint32_t next_us = 0;
uint8_t  failures = 0;

// ---- plain I2C helpers -------------------------------------------------------------------------------------------
bool write_reg(TwoWire &w, uint8_t a, uint8_t reg, uint8_t value) {
  w.beginTransmission(a);
  w.write(reg);
  w.write(value);
  return w.endTransmission() == 0;
}

bool read_regs(TwoWire &w, uint8_t a, uint8_t reg, uint8_t *buf, uint8_t n) {
  w.beginTransmission(a);
  w.write(reg);
  if (w.endTransmission(false) != 0) return false;         // repeated start
  if (w.requestFrom(a, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) buf[i] = w.read();
  return true;
}

// ---- conversions (kept separate so they are easy to test) ----------------------------------------------------------
int16_t be16(const uint8_t *p) { return (int16_t)(((uint16_t)p[0] << 8) | p[1]); }
float   raw_to_g(int16_t raw)   { return raw / ACCEL_LSB_PER_G; }
float   raw_to_dps(int16_t raw) { return raw / GYRO_LSB_PER_DPS; }

// ---- find and configure the sensor ---------------------------------------------------------------------------------
bool try_device(TwoWire &w, const char *name, uint8_t a) {
  uint8_t who = 0;
  if (!read_regs(w, a, REG_WHO_AM_I, &who, 1)) return false;           // nothing answered at this address
  write_reg(w, a, REG_PWR_MGMT_1, 0x80);                               // reset
  delay(100);
  bool good = write_reg(w, a, REG_PWR_MGMT_1, 0x01)                    // wake up, clock from the gyro
           && write_reg(w, a, REG_SMPLRT_DIV, 9)                       // 1 kHz / (1 + 9) = 100 Hz
           && write_reg(w, a, REG_CONFIG, 3)                           // low-pass filter at about 44 Hz
           && write_reg(w, a, REG_GYRO_CONFIG, 0x18)                   // +-2000 dps
           && write_reg(w, a, REG_ACCEL_CONFIG, 0x18);                 // +-16 g
  if (!good) return false;
  delay(50);
  bus = &w;
  addr = a;
  snprintf(status, sizeof(status), "sensor found on %s at 0x%02X (WHO_AM_I = 0x%02X)", name, a, who);
  return true;
}

bool begin_imu() {
  Wire.begin();
  Wire.setClock(I2C_HZ);
  if (try_device(Wire, "Wire (SDA/SCL pins)", 0x68)) return true;
  if (try_device(Wire, "Wire (SDA/SCL pins)", 0x69)) return true;
#if TRY_QWIIC
  Wire1.begin();
  Wire1.setClock(I2C_HZ);
  if (try_device(Wire1, "Wire1 (Qwiic)", 0x68)) return true;
  if (try_device(Wire1, "Wire1 (Qwiic)", 0x69)) return true;
#endif
  snprintf(status, sizeof(status), "NO SENSOR FOUND: check the wiring (3V3, GND, SDA, SCL)");
  return false;
}

String imu_status() { return String(status); }

void setup() {
  Bridge.begin();
  Bridge.provide_safe("imu_status", imu_status);
  ok = begin_imu();
  next_us = micros() + PERIOD_US;
}

void loop() {
  if (!ok) {                                   // keep looking, once a second, so plugging the sensor in later works
    delay(1000);
    ok = begin_imu();
    next_us = micros() + PERIOD_US;
    return;
  }
  int32_t wait_us = (int32_t)(next_us - micros());
  if (wait_us > 1500) { delay(1); return; }    // not time yet: let the other tasks run
  if (wait_us > 0) delayMicroseconds(wait_us);
  next_us += PERIOD_US;
  if ((int32_t)(micros() - next_us) > (int32_t)(5 * PERIOD_US)) next_us = micros() + PERIOD_US;   // after a long stall: do not rush

  uint8_t b[14];                               // accel x,y,z, temperature, gyro x,y,z (each 16 bits, high byte first)
  if (!read_regs(*bus, addr, REG_ACCEL_XOUT_H, b, 14)) {
    if (++failures >= 20) {                    // the sensor stopped answering: look for it again
      snprintf(status, sizeof(status), "sensor stopped answering: looking again");
      ok = false;
    }
    return;
  }
  failures = 0;
  Bridge.notify("imu", counter++,
                raw_to_g(be16(&b[0])), raw_to_g(be16(&b[2])), raw_to_g(be16(&b[4])),
                raw_to_dps(be16(&b[8])), raw_to_dps(be16(&b[10])), raw_to_dps(be16(&b[12])));
}
