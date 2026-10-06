/*
 * LM1 strobe smoke test for ESP32-S3. No serial needed.
 * GPIO 4 -> ULN2003 IN1..IN4 (tied together) -> IR ring.
 *
 * Repeats forever:
 *   1. 3 s of nothing (ring must be off)
 *   2. 6 slow blinks, 500 ms on / 500 ms off   -> check the wiring by eye/phone
 *   3. 5 s of 4-flash bursts at 120 Hz, 30 us pulses, 1 ms apart
 *      (looks steady on a phone camera; dimmer than the slow blinks)
 * IR is invisible: look at the ring through a phone camera.
 */
#include <Arduino.h>

constexpr int LED_PIN = 4;
constexpr uint32_t RMT_HZ = 1000000;  // 1 us per tick
constexpr uint16_t PULSE_US = 30;
constexpr uint16_t SPACING_US = 1000;  // start to start
constexpr size_t FLASHES = 4;
constexpr uint32_t BURST_HZ = 120;

void burst() {
  rmt_data_t sym[FLASHES];
  for (size_t i = 0; i < FLASHES; i++) {
    sym[i].level0 = 1;
    sym[i].duration0 = PULSE_US;
    sym[i].level1 = 0;
    sym[i].duration1 = (i + 1 < FLASHES) ? (SPACING_US - PULSE_US) : 1;
  }
  rmtWrite(LED_PIN, sym, FLASHES, RMT_WAIT_FOR_EVER);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);  // ring off until we say so
  if (!rmtInit(LED_PIN, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_1, RMT_HZ)) Serial.println("RMT init failed");
}

void loop() {
  Serial.println("phase 1: idle, ring should be OFF");
  delay(3000);

  Serial.println("phase 2: slow blinks");
  for (int i = 0; i < 6; i++) {
    rmt_data_t on = {(uint32_t)0};
    on.level0 = 1; on.duration0 = 32000; on.level1 = 1; on.duration1 = 0;
    // 500 ms on via plain GPIO; the RMT channel owns the pin, so drive it with a long pulse train
    for (int k = 0; k < 15; k++) rmtWrite(LED_PIN, &on, 1, RMT_WAIT_FOR_EVER);  // 15 x 32 ms ~ 480 ms
    rmt_data_t off = {(uint32_t)0};
    off.level0 = 0; off.duration0 = 32000; off.level1 = 0; off.duration1 = 0;
    for (int k = 0; k < 15; k++) rmtWrite(LED_PIN, &off, 1, RMT_WAIT_FOR_EVER);
  }

  Serial.println("phase 3: 4-flash bursts at 120 Hz");
  uint32_t period = 1000000UL / BURST_HZ;
  uint32_t end = millis() + 5000;
  uint32_t next = micros();
  while ((int32_t)(millis() - end) < 0) {
    if ((int32_t)(micros() - next) >= 0) {
      burst();
      next += period;
    }
  }
}
