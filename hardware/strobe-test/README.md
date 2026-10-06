# LM1 strobe bench test

Firmware 0.3.0 drives two low-brightness addressable status pixels on GPIO 7:
breathing blue for `led searching`, steady white for `led ready`, and breathing
orange for `led processing`. Pi service 0.62.0 supplies actual ball/processing
state and restores it after reconnect. The breathing cycle is 2.2 seconds.
The original 0.2.0 blue test used the same pixels
(GRB, 800 kHz protocol). This does not identify the connected 12 V strip model;
blue output was visually confirmed by the user. Power comes from the strip's
specified supply, with common ground.

The current Pi connection uses a USB-to-UART adapter. Build with
`CDCOnBoot=default` (disabled) so commands use UART0. The old native-USB
configuration is only appropriate when connected through native USB.

Work in progress on the `strobin-effect` branch. Nothing here touches the Pi service.

| File | What it is |
|---|---|
| `strobe_smoketest/` | ESP32-S3 sketch, no serial needed. Idle, slow blinks, then 120 Hz bursts. First power-up check. |
| `strobe_test/` | ESP32-S3 sketch with serial commands for single bursts and uneven spacing. |
| `strobe_master/` | ESP32-S3 light controller: `mode off\|flat\|strobe [driver\|iron\|chip]`, `ping`, a 3 s watchdog back to steady light, plus the bench commands below. Boots in flat light. This is what the Pi service drives (`PINPOINT_LIGHT_CONTROL=esp32`). |
| `strobe_capture_test.py` | Pi script: compares camera frames with the light off and on, saves images. |

## Wiring (ESP32-S3)

| ESP32 | Goes to |
|---|---|
| GPIO 4 | ULN2003 IN1 to IN4 (joined) |
| GPIO 5 | Camera STROBE `+`, with a 1 to 4.7 kΩ pull-up to 3.3 V (optional) |
| GND | ULN2003 `−`, camera STROBE `−`, 12 V supply `−` |

The camera TRIG input is **not used**. The camera free-runs and the ESP32 flashes
on its own clock. `strobe_master` has a TRIG output on GPIO 6 that is off by default.

## How the free-running setup works

- Camera: 640×400 at 242 fps, exposure about 4000 µs (nearly the whole 4132 µs frame),
  so a burst from the ESP32 almost always lands inside an exposure.
- ESP32 default ("driver" preset): 5 flashes of 15 µs with gaps of 0.7, 0.8, 0.9 and
  1.0 ms, repeated 242 times a second. At 80 m/s a 15 µs flash blurs the ball by 1.2 mm.
  The copies of a 60 to 85 m/s ball do not overlap, and the uneven gaps tell you which
  copy came from which flash.
- The two clocks drift slightly, so some bursts straddle the gap between exposures and
  lose a flash or two. The shot is still there.
- `preset iron` is the same idea for about 40 to 60 m/s.

## Flash the ESP32

```
arduino-cli compile --fqbn esp32:esp32:esp32s3:CDCOnBoot=default strobe_master
arduino-cli upload -p COM5 --fqbn esp32:esp32:esp32s3 strobe_master
```

Open a serial monitor at 115200. It starts flashing on its own. Useful commands:

```
show              current settings
preset driver     60-85 m/s (the boot default);  preset iron for 40-60 m/s
rate 242          bursts per second, match the camera's real frame rate
f 4 1000          4 flashes 1 ms apart
i 700 800 900     uneven spacing (4 flashes)
p 15              15 us flashes
light off / on    flashes off or on
stop / go         stop or resume
strobe on         print the camera STROBE statistics
```

## Test with the camera (on the Pi, dark room)

```
sudo systemctl stop pinpoint
python3 strobe_capture_test.py --serial /dev/ttyACM0
sudo systemctl start pinpoint
```

It sets the ESP32 to the driver preset and the camera's real frame rate, prints the
mean brightness with the light off and on, and says PASS when the flashes are visible. Then wave a small ball through the view and open
`strobe_test_out/on_*.png` to look for separate copies.
