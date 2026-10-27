#include "stubs/Arduino.h"
#include "stubs/Wire.h"
#include "stubs/Arduino_RouterBridge.h"
#include "stubs/Arduino_LED_Matrix.h"
uint32_t sim_us = 0; TwoWire Wire, Wire1; std::vector<Notification> notifications; BridgeClass Bridge;
#include "../sketch/sketch.ino"
#include <cmath>
#include <cstdlib>
static int failures_seen = 0;
#define CHECK(cond, ...) do { bool c_ = (cond); printf("  %-4s ", c_ ? "ok" : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!c_) failures_seen++; } while (0)
static void put16(uint8_t *p, int16_t v) { p[0] = (uint16_t)v >> 8; p[1] = (uint16_t)v & 0xFF; }
static void reset_world() { matrix = Arduino_LED_Matrix(); sim_us = 0; notifications.clear(); Wire = TwoWire(); Wire1 = TwoWire(); ok = false; counter = 0; failures = 0; bus = nullptr; addr = 0; snprintf(status, sizeof(status), "starting"); }
static void run(double seconds) { uint32_t end = sim_us + (uint32_t)(seconds * 1e6); while (sim_us < end) { loop(); sim_us += 20; } }   // each loop() pass costs ~20 us
static void still_motion(uint32_t, uint8_t *d) { put16(d + 0, 0); put16(d + 2, 0); put16(d + 4, 2048); put16(d + 8, 0); put16(d + 10, 0); put16(d + 12, 0); }

int main() {
  printf("1. sensor at 0x68 on the header pins: configuration, units and timing\n");
  reset_world(); Wire.dev.present = true; Wire.dev.addr = 0x68; Wire.dev.motion = [](uint32_t t, uint8_t *d) {
    put16(d + 0, 1024);            // ax = 0.5 g
    put16(d + 2, -2048);           // ay = -1.0 g
    put16(d + 4, 2048);            // az = +1.0 g
    put16(d + 8, 1640);            // gx = 100 dps
    put16(d + 10, -3280);          // gy = -200 dps
    put16(d + 12, 16);             // gz = 16/16.4 dps
  };
  setup(); run(2.0);
  CHECK(strstr(status, "0x68") && strstr(status, "Wire (SDA/SCL"), "status says: \"%s\"", status);
  auto reg = [&](uint8_t r) { for (int i = (int)Wire.dev.writes.size() - 1; i >= 0; i--) if (Wire.dev.writes[i].first == r) return (int)Wire.dev.writes[i].second; return -1; };
  CHECK(reg(0x6B) == 0x01, "PWR_MGMT_1 = 0x%02X (awake, gyro clock; a reset write came first: %s)", reg(0x6B), Wire.dev.writes.size() > 0 && Wire.dev.writes[0].second == 0x80 ? "yes" : "NO");
  CHECK(reg(0x19) == 9, "SMPLRT_DIV = %d (100 Hz)", reg(0x19));
  CHECK(reg(0x1A) == 3, "CONFIG = %d (44 Hz low-pass)", reg(0x1A));
  CHECK(reg(0x1B) == 0x18 && reg(0x1C) == 0x18, "gyro +-2000 dps (0x%02X) and accel +-16 g (0x%02X)", reg(0x1B), reg(0x1C));
  CHECK(Wire.clock == I2C_HZ, "I2C clock %u Hz", Wire.clock);
  size_t n = notifications.size();
  CHECK(n >= 198 && n <= 202, "%zu readings in 2 simulated seconds (expected 200)", n);
  bool consecutive = true; for (size_t i = 0; i < n; i++) if (notifications[i].args[0] != (double)i) consecutive = false;
  CHECK(consecutive, "the counter runs 0,1,2,... with no gaps");
  const auto &a = notifications[10].args;
  CHECK(fabs(a[1] - 0.5) < 1e-6 && fabs(a[2] + 1.0) < 1e-6 && fabs(a[3] - 1.0) < 1e-6, "accel in g: %.3f %.3f %.3f (expected 0.5 -1 1)", a[1], a[2], a[3]);
  CHECK(fabs(a[4] - 100.0) < 0.01 && fabs(a[5] + 200.0) < 0.01 && fabs(a[6] - 16 / 16.4) < 0.01, "gyro in dps: %.2f %.2f %.2f (expected 100 -200 0.98)", a[4], a[5], a[6]);
  double worst = 0; for (size_t i = 1; i < n; i++) worst = fmax(worst, fabs((notifications[i].at_us - notifications[i - 1].at_us) / 1000.0 - 10.0));
  CHECK(worst < 0.1, "spacing between readings: 10 ms +- %.3f ms", worst);
  CHECK(Bridge.status_fn && strstr(Bridge.status_fn().c_str(), "0x68"), "Python can ask imu_status and gets: \"%s\"", Bridge.status_fn ? Bridge.status_fn().c_str() : "(not registered)");

  printf("2. sensor at 0x69 (AD0 high)\n");
  reset_world(); Wire.dev.present = true; Wire.dev.addr = 0x69; Wire.dev.motion = still_motion; setup(); run(0.5);
  CHECK(strstr(status, "0x69") && notifications.size() > 40, "found at 0x69 and streaming (%zu readings)", notifications.size());

  printf("3. nothing connected, plugged in 3 s later\n");
  reset_world(); Wire.dev.addr = 0x68; Wire.dev.motion = still_motion; setup(); run(2.5);
  CHECK(strstr(status, "NO SENSOR FOUND") && notifications.empty(), "reports: \"%s\" and sends nothing", status);
  uint32_t plugged_at = sim_us; Wire.dev.present = true; run(3.0);
  double delay_s = notifications.empty() ? -1 : (notifications[0].at_us - plugged_at) / 1e6;
  CHECK(strstr(status, "0x68") && delay_s >= 0 && delay_s <= 1.4 && notifications.size() > 150, "after plugging in, streaming started %.2f s later (it retries once a second) and went on (%zu readings)", delay_s, notifications.size());

  printf("4. the sensor stops answering for a moment, then returns\n");
  reset_world(); Wire.dev.present = true; Wire.dev.motion = still_motion; setup(); run(1.0);
  size_t before = notifications.size(); Wire.dev.present = false; run(1.0);
  CHECK(notifications.size() == before && (strstr(status, "looking again") || strstr(status, "NO SENSOR")), "readings stop and the status says: \"%s\"", status);
  Wire.dev.present = true; run(2.5);
  CHECK(notifications.size() > before + 100, "it recovers by itself (%zu new readings)", notifications.size() - before);

  printf("5. a long stall (the board was busy for 1 s): no burst of catch-up readings\n");
  reset_world(); Wire.dev.present = true; Wire.dev.motion = still_motion; setup(); run(1.0);
  sim_us += 1000000; size_t b2 = notifications.size(); run(0.05);
  CHECK(notifications.size() - b2 <= 6, "%zu readings in the 50 ms after the stall (a rush would be 100)", notifications.size() - b2);
  run(1.0); double gaps = 0; for (size_t i = notifications.size() - 50; i < notifications.size(); i++) gaps = fmax(gaps, fabs((notifications[i].at_us - notifications[i - 1].at_us) / 1000.0 - 10.0));
  CHECK(gaps < 0.1, "and the spacing is back to 10 ms");

  printf("6. sensor on the Qwiic bus (built with TRY_QWIIC=%d)\n", TRY_QWIIC);
#if TRY_QWIIC
  reset_world(); Wire1.dev.present = true; Wire1.dev.motion = still_motion; setup(); run(0.5);
  CHECK(strstr(status, "Wire1 (Qwiic)") && notifications.size() > 40, "found on Wire1: \"%s\"", status);
#else
  reset_world(); Wire1.dev.present = true; Wire1.dev.motion = still_motion; setup(); run(0.5);
  CHECK(strstr(status, "NO SENSOR") && notifications.empty(), "with TRY_QWIIC=0 a sensor on Wire1 is NOT looked for (as intended): \"%s\"", status);
#endif

  printf("7. the LED matrix: two letters, one per model\n");
  reset_world(); Wire.dev.present = true; Wire.dev.motion = still_motion; setup();
  auto lit = [&]() { int n = 0; for (int i = 0; i < 104; i++) if (matrix.last[i]) n++; return n; };
  auto at = [&](int c, int r) { return matrix.last[r * 13 + c]; };
  // The four letters as ASCII art, written out separately from the sketch: X = lit.
  const char *ART[4][7] = {{".XXX.", "X...X", "X....", ".XXX.", "....X", "X...X", ".XXX."},     // S  still
                           {"X...X", "X...X", "X...X", "X.X.X", "X.X.X", "XX.XX", "X...X"},     // W  walk
                           {"XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"},     // R  run
                           {"XXXX.", "X...X", "X...X", "XXXX.", "X...X", "X...X", "XXXX."}};    // B  bike
  CHECK(matrix.begun && matrix.bits == 8, "the matrix is started in 8-bit grayscale, as in the sumo app and the recorder");
  CHECK(lit() == 1 && at(6, 3) == 120, "after setup it shows one dim dot in the middle (%d lit)", lit());
  CHECK(Bridge.led_fn != nullptr, "the show function is registered for Python");
  bool all_ok = true;
  for (int i = 0; i < 4; i++) {
    Bridge.led_fn(i, -1);
    int expected = 0; bool match = true;
    for (int r = 0; r < 7; r++) for (int c = 0; c < 5; c++) { bool on = ART[i][r][c] == 'X'; expected += on; match &= (at(c, r) == (on ? 255 : 0)); }
    for (int r = 0; r < 8; r++) for (int c = 5; c < 13; c++) match &= at(c, r) == 0;                          // nothing on the right, nor in the gap
    for (int c = 0; c < 13; c++) match &= at(c, 7) == 0;                                                     // the bottom row stays dark
    if (!(match && lit() == expected)) all_ok = false;
  }
  CHECK(all_ok, "Model A's letters S, W, R, B on the LEFT half match the ASCII art pixel for pixel");
  all_ok = true;
  for (int i = 0; i < 4; i++) {
    Bridge.led_fn(-1, i);
    bool match = true; int expected = 0;
    for (int r = 0; r < 7; r++) for (int c = 0; c < 5; c++) { bool on = ART[i][r][c] == 'X'; expected += on; match &= (at(8 + c, r) == (on ? 255 : 0)); }
    for (int r = 0; r < 8; r++) for (int c = 0; c < 8; c++) match &= at(c, r) == 0;
    if (!(match && lit() == expected)) all_ok = false;
  }
  CHECK(all_ok, "Model B's letters on the RIGHT half (columns 8 to 12) match too, with nothing on the left");
  Bridge.led_fn(1, 2);
  bool div = true; for (int r = 1; r <= 5; r++) div &= at(6, r) == 120;
  CHECK(div && at(6, 0) == 0 && at(6, 6) == 0 && at(6, 7) == 0, "when A says walk and B says run, both letters show with a dotted divider between them");
  { int w_pixels = 18, r_pixels = 18; CHECK(lit() == w_pixels + r_pixels + 5, "...and nothing else is lit (%d pixels)", lit()); }
  Bridge.led_fn(2, 2);
  { bool none = true; for (int r = 0; r < 8; r++) none &= at(6, r) == 0; CHECK(none && lit() == 36, "when they agree there is no divider (%d lit)", lit()); }
  Bridge.led_fn(-1, 3);  CHECK(lit() == 20 && at(6, 3) == 0, "only B has an answer: its letter, no divider, no dot (%d lit)", lit());
  Bridge.led_fn(-1, -1); CHECK(lit() == 1 && at(6, 3) == 120, "no answers: the dim dot");
  Bridge.led_fn(9, 7);   CHECK(lit() == 1 && at(6, 3) == 120, "indices that are not 0 to 3 are treated as 'no answer', not drawn as garbage");
  Bridge.led_fn(5, 2);   { int r_only = 0; for (int i = 0; i < 104; i++) if (matrix.last[i]) r_only++; CHECK(r_only == 18, "a bad index on one side leaves just the other side's letter (%d lit)", r_only); }
  int draws0 = matrix.draws; run(1.0);
  CHECK(matrix.draws == draws0, "the 100 Hz IMU loop does not touch the matrix");
  CHECK(notifications.size() >= 98, "and the IMU stream is unaffected by it (%zu readings in a second)", notifications.size());

  printf("\n%s (%d problem%s)\n", failures_seen ? "SOME FAILED" : "ALL PASSED", failures_seen, failures_seen == 1 ? "" : "s");
  return failures_seen ? 1 : 0;
}
