/*
 * LM1 strobe bench test for ESP32-S3 (Arduino-ESP32 core 3.x).
 *
 * Fires bursts of short pulses on LED_PIN using the RMT peripheral, so the
 * pulse timing comes from hardware (1 us ticks) and not from the CPU.
 * LED_PIN -> ULN2003 IN1..IN4 (tied together) -> IR ring switched to ground.
 *
 * Optionally watches a camera STROBE output on STROBE_IN_PIN (external 1-4.7k
 * pull-up to 3.3 V, active LOW) and prints exposure width and period.
 *
 * Serial 115200, one command per line:
 *   help
 *   p <us>            pulse width (2..500 us, default 30)
 *   f <n> <us>        n flashes, start-to-start spacing <us>
 *   i <us> <us> ...   uneven start-to-start spacings (flashes = args + 1)
 *   fire              one burst
 *   run <hz>          repeat a burst at this rate (1..300)
 *   stop
 *   strobe on|off     print STROBE input statistics once a second
 *   show              print current settings
 *
 * Board settings: ESP32S3 Dev Module. If you use the native USB port, set
 * "USB CDC On Boot: Enabled".
 */
#include <Arduino.h>

constexpr int LED_PIN = 4;
constexpr int STROBE_IN_PIN = 5;
constexpr uint32_t RMT_HZ = 1000000;  // 1 us per tick
constexpr size_t MAX_FLASHES = 32;
constexpr uint32_t MAX_TICKS = 32767;  // RMT duration field is 15 bits
constexpr float MAX_DUTY = 0.10f;      // refuse settings above 10 % on-time

uint16_t pulseUs = 30;
uint32_t spacingUs[MAX_FLASHES - 1] = {1000, 1000, 1000};
size_t flashCount = 4;

bool running = false;
uint32_t runPeriodUs = 0;
uint32_t lastBurstUs = 0;

bool strobeMonitor = false;
volatile uint32_t sLastFall = 0, sCount = 0, sSumPeriod = 0, sSumWidth = 0;
volatile uint32_t sMinWidth = 0xFFFFFFFF, sMaxWidth = 0, sPeriods = 0;

void IRAM_ATTR strobeIsr() {
  uint32_t now = micros();
  if (digitalRead(STROBE_IN_PIN) == LOW) {
    if (sLastFall) {
      sSumPeriod += now - sLastFall;
      sPeriods++;
    }
    sLastFall = now;
  } else if (sLastFall) {
    uint32_t w = now - sLastFall;
    sSumWidth += w;
    sCount++;
    if (w < sMinWidth) sMinWidth = w;
    if (w > sMaxWidth) sMaxWidth = w;
  }
}

uint32_t burstLengthUs() {
  uint32_t total = pulseUs;
  for (size_t i = 0; i + 1 < flashCount; i++) total += spacingUs[i];
  return total;
}

float dutyAt(float hz) { return hz * flashCount * pulseUs / 1e6f; }

void fireBurst() {
  rmt_data_t sym[MAX_FLASHES];
  for (size_t i = 0; i < flashCount; i++) {
    sym[i].level0 = 1;
    sym[i].duration0 = pulseUs;
    sym[i].level1 = 0;
    sym[i].duration1 = (i + 1 < flashCount) ? (spacingUs[i] - pulseUs) : 1;
  }
  rmtWrite(LED_PIN, sym, flashCount, RMT_WAIT_FOR_EVER);
}

bool spacingsValid() {
  for (size_t i = 0; i + 1 < flashCount; i++) {
    if (spacingUs[i] <= pulseUs || spacingUs[i] - pulseUs > MAX_TICKS) return false;
  }
  return true;
}

void show() {
  Serial.printf("pulse %u us, %u flashes, burst %lu us\n", pulseUs, (unsigned)flashCount,
                (unsigned long)burstLengthUs());
  Serial.print("start-to-start spacings (us):");
  for (size_t i = 0; i + 1 < flashCount; i++) Serial.printf(" %lu", (unsigned long)spacingUs[i]);
  Serial.println();
  if (running) Serial.printf("running at %.1f Hz, duty %.2f %%\n", 1e6f / runPeriodUs,
                             dutyAt(1e6f / runPeriodUs) * 100.0f);
}

void handleLine(char *line) {
  char *cmd = strtok(line, " \t");
  if (!cmd) return;
  if (!strcmp(cmd, "help")) {
    Serial.println("p <us> | f <n> <us> | i <us>... | fire | run <hz> | stop | strobe on|off | show");
  } else if (!strcmp(cmd, "p")) {
    char *a = strtok(nullptr, " \t");
    long v = a ? atol(a) : 0;
    if (v < 2 || v > 500) { Serial.println("pulse must be 2..500 us"); return; }
    pulseUs = v;
    if (!spacingsValid()) Serial.println("warning: a spacing is now <= pulse width");
    show();
  } else if (!strcmp(cmd, "f")) {
    char *a = strtok(nullptr, " \t");
    char *b = strtok(nullptr, " \t");
    long n = a ? atol(a) : 0, s = b ? atol(b) : 0;
    if (n < 1 || n > (long)MAX_FLASHES || s <= pulseUs) {
      Serial.println("usage: f <1..32> <spacing us, greater than pulse>");
      return;
    }
    flashCount = n;
    for (long k = 0; k + 1 < n; k++) spacingUs[k] = s;
    show();
  } else if (!strcmp(cmd, "i")) {
    uint32_t tmp[MAX_FLASHES - 1];
    size_t n = 0;
    for (char *t = strtok(nullptr, " \t"); t && n < MAX_FLASHES - 1; t = strtok(nullptr, " \t"))
      tmp[n++] = atol(t);
    if (n == 0) { Serial.println("usage: i <us> <us> ..."); return; }
    for (size_t k = 0; k < n; k++)
      if (tmp[k] <= pulseUs || tmp[k] - pulseUs > MAX_TICKS) {
        Serial.println("each spacing must exceed the pulse width");
        return;
      }
    for (size_t k = 0; k < n; k++) spacingUs[k] = tmp[k];
    flashCount = n + 1;
    show();
  } else if (!strcmp(cmd, "fire")) {
    if (!spacingsValid()) { Serial.println("invalid spacings"); return; }
    fireBurst();
    Serial.println("fired");
  } else if (!strcmp(cmd, "run")) {
    char *a = strtok(nullptr, " \t");
    float hz = a ? atof(a) : 0;
    if (hz < 1 || hz > 300) { Serial.println("rate must be 1..300 Hz"); return; }
    if (!spacingsValid()) { Serial.println("invalid spacings"); return; }
    if (dutyAt(hz) > MAX_DUTY) { Serial.println("refused: duty above 10 %"); return; }
    if (burstLengthUs() >= 1e6f / hz) { Serial.println("refused: burst longer than the period"); return; }
    runPeriodUs = 1e6f / hz;
    running = true;
    show();
  } else if (!strcmp(cmd, "stop")) {
    running = false;
    Serial.println("stopped");
  } else if (!strcmp(cmd, "strobe")) {
    char *a = strtok(nullptr, " \t");
    strobeMonitor = a && !strcmp(a, "on");
    Serial.println(strobeMonitor ? "strobe monitor on" : "strobe monitor off");
  } else if (!strcmp(cmd, "show")) {
    show();
  } else {
    Serial.println("unknown command, type help");
  }
}

void printStrobeStats() {
  noInterrupts();
  uint32_t count = sCount, periods = sPeriods, sumW = sSumWidth, sumP = sSumPeriod;
  uint32_t minW = sMinWidth, maxW = sMaxWidth;
  sCount = sPeriods = sSumPeriod = sSumWidth = 0;
  sMinWidth = 0xFFFFFFFF;
  sMaxWidth = 0;
  interrupts();
  if (!count) { Serial.println("STROBE: no pulses seen"); return; }
  Serial.printf("STROBE: %lu exposures/s, width avg %lu min %lu max %lu us, period avg %lu us\n",
                (unsigned long)count, (unsigned long)(sumW / count), (unsigned long)minW,
                (unsigned long)maxW, periods ? (unsigned long)(sumP / periods) : 0UL);
}

void setup() {
  Serial.begin(115200);
  pinMode(STROBE_IN_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(STROBE_IN_PIN), strobeIsr, CHANGE);
  if (!rmtInit(LED_PIN, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_1, RMT_HZ)) {
    Serial.println("RMT init failed");
  }
  delay(500);
  Serial.println("LM1 strobe test ready. LED output starts LOW. Type help.");
  show();
}

void loop() {
  static String buf;
  static uint32_t lastStats = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) {
        char line[96];
        buf.toCharArray(line, sizeof line);
        handleLine(line);
        buf = "";
      }
    } else if (buf.length() < 90) {
      buf += c;
    }
  }
  if (running && (uint32_t)(micros() - lastBurstUs) >= runPeriodUs) {
    lastBurstUs = micros();
    fireBurst();
  }
  if (strobeMonitor && millis() - lastStats >= 1000) {
    lastStats = millis();
    printStrobeStats();
  }
}
