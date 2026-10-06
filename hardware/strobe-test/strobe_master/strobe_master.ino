/*
 * LM1 strobe master for ESP32-S3 (Arduino-ESP32 core 3.x).
 *
 * Runs forever, with no CPU help, using RMT hardware loop mode:
 *   LED_PIN  -> ULN2003 IN1..IN4 -> IR ring, a burst of flashes every frame period
 *   TRIG_PIN -> camera TRIG input (opto): OFF by default, `trig on` enables it
 * The default is the free-running "driver" setup: the camera runs on its own at
 * 242 fps (640x400), the ESP32 fires a burst at the same rate, and the camera
 * exposure is set close to the whole frame period (about 4000 us) so every burst
 * falls inside an exposure. The two clocks drift a little, so now and then a burst
 * straddles the gap between exposures. That costs a few flashes, not the shot.
 * If TRIG is on, both loops have exactly the same period, so the burst keeps a
 * fixed delay after the trigger edge (apart from a constant start skew of a few
 * microseconds that the delay setting absorbs).
 *
 * Optionally watches the camera STROBE output on STROBE_IN_PIN (external 1-4.7k
 * pull-up to 3.3 V, active LOW) and prints exposure width and rate once a second.
 *
 * The Pi service drives it with three modes (a reply line starts with OK or PONG):
 *   mode off | flat | strobe [driver|iron|chip]   ring off / steady / bursts
 *   ping                                         heartbeat, answers PONG mode=...
 *   status                                       answers OK mode=... preset=...
 * Boots in FLAT (steady light). In STROBE started with `mode strobe`, a missing heartbeat
 * (no line from the host for 3 s) drops the ring back to FLAT, so a crashed service can
 * never leave it flashing. The commands below are for bench work and keep working.
 *
 * Serial 115200, one command per line:
 *   help
 *   show                 print settings
 *   preset driver|iron|chip   flash width, count and spacings for ~60-85, ~40-60 or ~15-40 m/s
 *   rate <hz>            bursts (and triggers) per second, 1..1000 (default 242)
 *   tw <us>              trigger pulse width (default 20)
 *   tp <0|1>             1 = trigger pulse is HIGH (idle low), 0 = pulse is LOW (default 1)
 *   d <us>               delay from trigger edge to the first flash (default 0; only used with trig on)
 *   p <us>               flash width, 2..500 (default 15)
 *   f <n> <us>           n flashes, start-to-start spacing <us>
 *   i <us> <us> ...      uneven spacings (flashes = args + 1)
 *   light on|off         flashes on/off while the trigger keeps running (brightness A/B test)
 *   trig on|off          trigger pulses on/off
 *   stop / go            stop or resume both outputs
 *   strobe on|off        print the camera STROBE statistics once a second
 *
 * Board: ESP32S3 Dev Module. Native USB port: set "USB CDC On Boot: Enabled".
 */
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
struct Cfg;
struct Seg;

constexpr char FW_VERSION[] = "0.3.0";
Adafruit_NeoPixel statusPixels(2, 7, NEO_GRB + NEO_KHZ800);
enum StatusState { SEARCHING, BALL_READY, PROCESSING };
StatusState statusState = SEARCHING;
uint32_t statusStarted = 0;

void updateStatusPixels() {
  static uint32_t lastUpdate = 0;
  uint32_t now = millis();
  if (now - lastUpdate < 30) return;
  lastUpdate = now;
  float wave = 0.08f + 0.92f * (0.5f - 0.5f * cosf(6.2831853f * (now - statusStarted) / 2200.0f));
  uint8_t value = statusState == BALL_READY ? 255 : (uint8_t)(255 * wave);
  uint32_t color = statusState == BALL_READY ? statusPixels.Color(255,255,255)
    : statusState == PROCESSING ? statusPixels.Color(value,(uint8_t)(value * 0.32f),0)
    : statusPixels.Color(0,0,value);
  statusPixels.fill(color);
  statusPixels.show();
}

constexpr int TRIG_PIN = 6;
constexpr int LED_PIN = 4;
constexpr int STROBE_IN_PIN = 5;
constexpr uint32_t RMT_HZ = 1000000;  // 1 us per tick
constexpr size_t MAX_FLASHES = 16;
constexpr size_t MAX_SYMBOLS = 48;  // one RMT memory block per channel
constexpr uint32_t MAX_TICKS = 32767;
constexpr float MAX_DUTY = 0.10f;

// Defaults are the "driver" preset for a free-running camera at 242 fps (640x400):
// 15 us flashes (80 m/s blurs 1.2 mm), uneven gaps of 0.7 to 1.0 ms so the copies of
// a 60 to 85 m/s ball do not overlap and each copy's order is unambiguous.
struct Cfg {
  uint32_t rateHz = 242;
  uint32_t trigUs = 20;
  bool trigActiveHigh = true;
  uint32_t delayUs = 0;
  uint32_t pulseUs = 15;
  size_t flashCount = 5;
  uint32_t spacingUs[MAX_FLASHES - 1] = {700, 800, 900, 1000};
};

Cfg cfg;
enum Mode { M_OFF, M_FLAT, M_STROBE };
Mode mode = M_FLAT;
String presetName = "driver";
bool running = false;  // true only in STROBE
bool lightOn = true;
bool trigOn = false;  // the camera TRIG input is not used
bool watchdogArmed = false;
uint32_t lastHostMs = 0;
constexpr uint32_t WATCHDOG_MS = 3000;

struct Seg {
  bool level;
  uint32_t dur;
};

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

uint32_t periodUs(const Cfg &c) { return 1000000UL / c.rateHz; }

uint32_t burstUs(const Cfg &c) {
  uint32_t t = c.pulseUs;
  for (size_t i = 0; i + 1 < c.flashCount; i++) t += c.spacingUs[i];
  return t;
}

const char *validate(const Cfg &c) {
  if (c.rateHz < 1 || c.rateHz > 1000) return "rate must be 1..1000 Hz";
  if (c.pulseUs < 2 || c.pulseUs > 500) return "flash width must be 2..500 us";
  if (c.trigUs < 1 || c.trigUs >= periodUs(c)) return "trigger width must be 1 us .. period";
  if (c.flashCount < 1 || c.flashCount > MAX_FLASHES) return "flashes must be 1..16";
  for (size_t i = 0; i + 1 < c.flashCount; i++)
    if (c.spacingUs[i] <= c.pulseUs) return "each spacing must exceed the flash width";
  if (c.delayUs + burstUs(c) + 10 > periodUs(c)) return "delay + burst must fit inside the period";
  if ((float)c.rateHz * c.flashCount * c.pulseUs / 1e6f > MAX_DUTY) return "refused: LED duty above 10 %";
  return nullptr;
}

// Split long segments, make the count even, then pack two segments per RMT symbol.
size_t pack(const Seg *in, size_t n, rmt_data_t *out) {
  Seg flat[2 * MAX_SYMBOLS];
  size_t m = 0;
  for (size_t i = 0; i < n; i++) {
    uint32_t d = in[i].dur;
    while (d > MAX_TICKS) {
      if (m >= 2 * MAX_SYMBOLS) return 0;
      flat[m++] = {in[i].level, MAX_TICKS};
      d -= MAX_TICKS;
    }
    if (d) {
      if (m >= 2 * MAX_SYMBOLS) return 0;
      flat[m++] = {in[i].level, d};
    }
  }
  if (m & 1) {
    if (m >= 2 * MAX_SYMBOLS || flat[m - 1].dur < 2) return 0;
    flat[m - 1].dur--;
    flat[m] = {flat[m - 1].level, 1};
    m++;
  }
  if (m / 2 > MAX_SYMBOLS) return 0;
  for (size_t s = 0; s < m / 2; s++) {
    out[s].level0 = flat[2 * s].level;
    out[s].duration0 = flat[2 * s].dur;
    out[s].level1 = flat[2 * s + 1].level;
    out[s].duration1 = flat[2 * s + 1].dur;
  }
  return m / 2;
}

void stopAll() {
  rmtWriteLooping(TRIG_PIN, nullptr, 0);
  rmtWriteLooping(LED_PIN, nullptr, 0);
}

// (Re)start both loops together so the trigger/flash phase is the same every time.
bool applyPattern() {
  stopAll();
  rmtSetEOT(TRIG_PIN, cfg.trigActiveHigh ? 0 : 1);
  rmtSetEOT(LED_PIN, 0);
  if (mode == M_FLAT) {  // one very long high symbol, looped: a steady light
    rmt_data_t steady;
    steady.level0 = 1;
    steady.duration0 = MAX_TICKS;
    steady.level1 = 1;
    steady.duration1 = MAX_TICKS;
    return rmtWriteLooping(LED_PIN, &steady, 1);
  }
  if (!running) return true;

  const uint32_t period = periodUs(cfg);
  Seg trig[2] = {{cfg.trigActiveHigh, cfg.trigUs}, {!cfg.trigActiveHigh, period - cfg.trigUs}};
  Seg led[2 * MAX_FLASHES + 2];
  size_t nl = 0;
  if (cfg.delayUs) led[nl++] = {false, cfg.delayUs};
  for (size_t i = 0; i < cfg.flashCount; i++) {
    led[nl++] = {true, cfg.pulseUs};
    if (i + 1 < cfg.flashCount) led[nl++] = {false, cfg.spacingUs[i] - cfg.pulseUs};
  }
  led[nl++] = {false, period - cfg.delayUs - burstUs(cfg)};

  rmt_data_t trigSym[MAX_SYMBOLS], ledSym[MAX_SYMBOLS];
  size_t nt = pack(trig, 2, trigSym);
  size_t nls = pack(led, nl, ledSym);
  if (!nt || !nls) {
    Serial.println("pattern does not fit in the RMT memory block");
    return false;
  }
  bool ok = true;
  if (trigOn) ok &= rmtWriteLooping(TRIG_PIN, trigSym, nt);
  if (lightOn) ok &= rmtWriteLooping(LED_PIN, ledSym, nls);
  if (!ok) Serial.println("rmtWriteLooping failed");
  return ok;
}

// Validate a changed config; keep the old one if it is rejected.
void commit(const Cfg &candidate) {
  const char *err = validate(candidate);
  if (err) {
    Serial.printf("rejected: %s\n", err);
    return;
  }
  cfg = candidate;
  applyPattern();
}

const char *modeName() { return mode == M_STROBE ? "strobe" : mode == M_FLAT ? "flat" : "off"; }

void printStatus() {
  Serial.printf("OK mode=%s preset=%s rate=%lu pulse=%lu flashes=%u\n", modeName(), presetName.c_str(),
                (unsigned long)cfg.rateHz, (unsigned long)cfg.pulseUs, (unsigned)cfg.flashCount);
}

void show() {
  Serial.printf("%s | rate %lu Hz (period %lu us) | trig %s %lu us | light %s\n",
                mode == M_STROBE ? "STROBE" : mode == M_FLAT ? "FLAT" : "OFF", (unsigned long)cfg.rateHz, (unsigned long)periodUs(cfg),
                cfg.trigActiveHigh ? "active-high" : "active-low", (unsigned long)cfg.trigUs,
                lightOn ? "on" : "off");
  Serial.printf("delay %lu us | %u flashes of %lu us | burst %lu us | duty %.2f %% | trig %s\n",
                (unsigned long)cfg.delayUs, (unsigned)cfg.flashCount, (unsigned long)cfg.pulseUs,
                (unsigned long)burstUs(cfg),
                100.0f * cfg.rateHz * cfg.flashCount * cfg.pulseUs / 1e6f, trigOn ? "on" : "off");
  Serial.print("start-to-start spacings (us):");
  for (size_t i = 0; i + 1 < cfg.flashCount; i++) Serial.printf(" %lu", (unsigned long)cfg.spacingUs[i]);
  Serial.println();
}

bool flagArg(const char *a, bool &out) {
  if (!a) return false;
  if (!strcmp(a, "on")) { out = true; return true; }
  if (!strcmp(a, "off")) { out = false; return true; }
  return false;
}

void handleLine(char *line) {
  char *cmd = strtok(line, " \t");
  if (!cmd) return;
  char *a = strtok(nullptr, " \t");
  Cfg next = cfg;
  if (!strcmp(cmd, "led") && a) {
    StatusState nextState;
    if (!strcmp(a,"searching")) nextState = SEARCHING;
    else if (!strcmp(a,"ready")) nextState = BALL_READY;
    else if (!strcmp(a,"processing")) nextState = PROCESSING;
    else { Serial.println("ERR led searching|ready|processing"); return; }
    if (statusState != nextState) { statusState = nextState; statusStarted = millis(); }
    Serial.printf("OK led=%s firmware=%s\n",a,FW_VERSION);
  } else if (!strcmp(cmd, "help")) {
    Serial.println("rate tw tp d p f i light trig stop go strobe show  (see the header comment)");
  } else if (!strcmp(cmd, "show")) {
    show();
  } else if (!strcmp(cmd, "rate") && a) {
    next.rateHz = atol(a); commit(next); show();
  } else if (!strcmp(cmd, "tw") && a) {
    next.trigUs = atol(a); commit(next); show();
  } else if (!strcmp(cmd, "tp") && a) {
    next.trigActiveHigh = atol(a) != 0; commit(next); show();
  } else if (!strcmp(cmd, "d") && a) {
    next.delayUs = atol(a); commit(next); show();
  } else if (!strcmp(cmd, "p") && a) {
    next.pulseUs = atol(a); commit(next); show();
  } else if (!strcmp(cmd, "f") && a) {
    char *b = strtok(nullptr, " \t");
    long n = atol(a), s = b ? atol(b) : 0;
    if (n < 1 || n > (long)MAX_FLASHES || s < 1) { Serial.println("usage: f <1..16> <us>"); return; }
    next.flashCount = n;
    for (long k = 0; k + 1 < n; k++) next.spacingUs[k] = s;
    commit(next); show();
  } else if (!strcmp(cmd, "i") && a) {
    size_t n = 0;
    for (char *t = a; t && n < MAX_FLASHES - 1; t = strtok(nullptr, " \t")) next.spacingUs[n++] = atol(t);
    next.flashCount = n + 1;
    commit(next); show();
  } else if (!strcmp(cmd, "preset") && a) {
    if (!strcmp(a, "driver")) {  // ~60-85 m/s
      next.pulseUs = 15; next.flashCount = 5; next.delayUs = 0;
      uint32_t s[4] = {700, 800, 900, 1000};
      memcpy(next.spacingUs, s, sizeof s);
    } else if (!strcmp(a, "iron")) {  // ~40-60 m/s
      next.pulseUs = 20; next.flashCount = 4; next.delayUs = 0;
      uint32_t s[3] = {900, 1000, 1100};
      memcpy(next.spacingUs, s, sizeof s);
    } else if (!strcmp(a, "chip")) {  // ~15-40 m/s: 2 flashes 2.1 ms apart (burst gap 2.0 ms)
      next.pulseUs = 30; next.flashCount = 2; next.delayUs = 0;
      next.spacingUs[0] = 2100;
    } else {
      Serial.println("presets: driver, iron, chip");
      return;
    }
    presetName = a;
    commit(next); show();
  } else if (!strcmp(cmd, "light")) {
    bool v;
    if (!flagArg(a, v)) { Serial.println("usage: light on|off"); return; }
    lightOn = v; applyPattern(); show();
  } else if (!strcmp(cmd, "trig")) {
    bool v;
    if (!flagArg(a, v)) { Serial.println("usage: trig on|off"); return; }
    trigOn = v; applyPattern(); show();
  } else if (!strcmp(cmd, "stop")) {
    watchdogArmed = false; mode = M_OFF; running = false; applyPattern(); show();
  } else if (!strcmp(cmd, "go")) {
    watchdogArmed = false; mode = M_STROBE; running = true; applyPattern(); show();
  } else if (!strcmp(cmd, "ping")) {
    Serial.printf("PONG mode=%s\n", modeName());
  } else if (!strcmp(cmd, "status")) {
    printStatus();
  } else if (!strcmp(cmd, "mode") && a) {
    char *b = strtok(nullptr, " \t");
    if (!strcmp(a, "off")) {
      watchdogArmed = false; mode = M_OFF; running = false;
    } else if (!strcmp(a, "flat")) {
      watchdogArmed = false; mode = M_FLAT; running = false;
    } else if (!strcmp(a, "strobe")) {
      if (b) {  // reuse the preset command for the pattern
        char line2[24];
        snprintf(line2, sizeof line2, "preset %s", b);
        handleLine(line2);
        if (presetName != b) { Serial.println("ERR unknown preset"); return; }
      }
      const char *err2 = validate(cfg);
      if (err2) { Serial.printf("ERR %s\n", err2); return; }
      mode = M_STROBE; running = true; watchdogArmed = true;
    } else {
      Serial.println("ERR usage: mode off|flat|strobe [driver|iron|chip]");
      return;
    }
    applyPattern();
    printStatus();
  } else if (!strcmp(cmd, "strobe")) {
    bool v;
    if (!flagArg(a, v)) { Serial.println("usage: strobe on|off"); return; }
    strobeMonitor = v;
  } else {
    Serial.println("unknown or incomplete command, type help");
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
  if (!count) { Serial.println("STROBE: no exposures seen"); return; }
  Serial.printf("STROBE: %lu exposures/s, width avg %lu min %lu max %lu us, period avg %lu us\n",
                (unsigned long)count, (unsigned long)(sumW / count), (unsigned long)minW,
                (unsigned long)maxW, periods ? (unsigned long)(sumP / periods) : 0UL);
}

void setup() {
  Serial.begin(115200);
  statusPixels.begin();
  statusPixels.setBrightness(24);
  statusPixels.fill(statusPixels.Color(0, 0, 255));
  statusPixels.show();
  pinMode(STROBE_IN_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(STROBE_IN_PIN), strobeIsr, CHANGE);
  bool ok = rmtInit(TRIG_PIN, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_1, RMT_HZ);
  ok &= rmtInit(LED_PIN, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_1, RMT_HZ);
  if (!ok) Serial.println("RMT init failed");
  delay(1000);
  Serial.println("LM1 light controller. Boots in FLAT, type help for commands.");
  Serial.printf("Firmware %s; status LEDs GPIO 7, searching\n", FW_VERSION);
  applyPattern();
  show();
}

void loop() {
  updateStatusPixels();
  static String buf;
  static uint32_t lastStats = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) {
        char line[96];
        buf.toCharArray(line, sizeof line);
        lastHostMs = millis();
        handleLine(line);
        buf = "";
      }
    } else if (buf.length() < 90) {
      buf += c;
    }
  }
  if (watchdogArmed && mode == M_STROBE && millis() - lastHostMs > WATCHDOG_MS) {
    watchdogArmed = false;
    mode = M_FLAT;
    running = false;
    applyPattern();
    Serial.println("WATCHDOG no host for 3 s, back to flat light");
  }
  if (strobeMonitor && millis() - lastStats >= 1000) {
    lastStats = millis();
    printStrobeStats();
  }
}
