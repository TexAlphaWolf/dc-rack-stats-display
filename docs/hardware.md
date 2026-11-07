# Hardware

The server does not care what displays it. Pick whatever you have.

## Raspberry Pi + 7-inch screen (kiosk)
1. Raspberry Pi OS with desktop, auto-login. Any Pi that runs Chromium is enough.
2. Run rackdisplay on the rack server (not on the Pi) so the Pi only draws a page.
3. Start Chromium full screen at boot, e.g. in `~/.config/autostart/kiosk.desktop`:
   ```
   [Desktop Entry]
   Type=Application
   Name=Rack display
   Exec=chromium --kiosk --noerrdialogs --disable-infobars http://rack-server:8080/
   ```
4. If you set a token, the page cannot send headers from a URL bar; use the token only for
   `/api` clients and keep the page reachable from the rack VLAN, or put the display on a trusted VLAN.
5. Disable screen blanking (`raspi-config` -> Display Options). The page also shifts itself by a
   pixel or two every minute against burn-in.

The layout scales from a 800x480 panel up to a TV: sizes follow `min(width x 0.6, height)`.
Options: `?screen=storage` pins one screen, `?rotate=30` changes the rotation time, arrow keys or a click step.

## Small text displays: ESP32 + SSD1306 OLED
`firmware/esp32-oled/` fetches `/api/lcd.txt` over Wi-Fi and draws it on a 128x64 SSD1306 (25 columns x 8 rows) with U8g2.

1. Copy `config.example.h` to `config.h` (git-ignored) and fill in Wi-Fi, server URL and token.
2. Run rackdisplay with `--host 0.0.0.0` and a token.
3. Wire the OLED to the default I2C pins, build with the Arduino IDE or `arduino-cli` for `esp32:esp32:esp32`.

Other text displays (16x2, 20x4 HD44780): fetch `/api/lcd.txt?cols=16&rows=2` from any microcontroller
and print the lines; pages are separated by form feed (`\f`), lines by `\n`.

**Status:** the sketch is compiled in CI on every push, but has not been run on real hardware by the
author. Treat it as a tested starting point, not a finished product.
