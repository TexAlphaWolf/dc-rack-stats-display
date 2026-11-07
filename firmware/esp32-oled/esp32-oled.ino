// rackdisplay on an ESP32 with a 128x64 SSD1306 OLED (I2C).
//
// Fetches /api/lcd.txt from the rackdisplay server and shows it page after page. The server does
// all the work (collecting, thresholds, formatting), so this sketch stays small and the same
// frames also fit a 20x4 LCD: only the font and the cols/rows below change.
//
// Wiring (default ESP32 I2C): SDA = GPIO21, SCL = GPIO22, 3V3, GND.
// Libraries: U8g2 (Library Manager). Board: "ESP32 Dev Module".

#include <HTTPClient.h>
#include <U8g2lib.h>
#include <WiFi.h>
#include <Wire.h>

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

// 5x8 pixel characters on 128x64 pixels: 25 columns and 8 rows.
static const int COLS = 25;
static const int ROWS = 8;
static const int LINE_HEIGHT = 8;

U8G2_SSD1306_128X64_NONAME_F_HW_I2C display(U8G2_R0, /* reset=*/U8X8_PIN_NONE);

static String pages = "";       // pages separated by \f, lines by \n
static unsigned long fetchedAt = 0;
static unsigned long pageShownAt = 0;
static int pageIndex = 0;
static bool lastFetchFailed = false;

static void drawMessage(const char *line1, const char *line2) {
  display.clearBuffer();
  display.setFont(u8g2_font_5x8_tf);
  display.drawStr(0, LINE_HEIGHT, line1);
  display.drawStr(0, LINE_HEIGHT * 2 + 2, line2);
  display.sendBuffer();
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  drawMessage("rackdisplay", "connecting to WiFi...");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 20000) {
    delay(250);
  }
}

static bool fetchPages() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
    if (WiFi.status() != WL_CONNECTED) return false;
  }
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/lcd.txt?cols=" + COLS + "&rows=" + ROWS;
  http.begin(url);
  http.setTimeout(4000);
  if (strlen(API_TOKEN) > 0) http.addHeader("Authorization", String("Bearer ") + API_TOKEN);
  int code = http.GET();
  bool ok = (code == 200);
  if (ok) pages = http.getString();
  http.end();
  return ok;
}

// Returns page number `index` (0-based) of the text, or "" when there is no such page.
static String pageAt(const String &text, int index) {
  int start = 0;
  for (int i = 0; i < index; i++) {
    start = text.indexOf('\f', start);
    if (start < 0) return "";
    start++;
  }
  int end = text.indexOf('\f', start);
  return end < 0 ? text.substring(start) : text.substring(start, end);
}

static int pageCount(const String &text) {
  int n = text.length() ? 1 : 0;
  for (unsigned int i = 0; i < text.length(); i++) {
    if (text[i] == '\f') n++;
  }
  return n;
}

static void drawPage(const String &page) {
  display.clearBuffer();
  display.setFont(u8g2_font_5x8_tf);
  int row = 0;
  int start = 0;
  while (row < ROWS) {
    int end = page.indexOf('\n', start);
    String line = end < 0 ? page.substring(start) : page.substring(start, end);
    display.drawStr(0, (row + 1) * LINE_HEIGHT - 1, line.c_str());
    row++;
    if (end < 0) break;
    start = end + 1;
  }
  if (lastFetchFailed) display.drawStr(COLS * 5 - 5, LINE_HEIGHT - 1, "!");  // data is old
  display.sendBuffer();
}

void setup() {
  display.begin();
  connectWifi();
  lastFetchFailed = !fetchPages();
  fetchedAt = millis();
  pageShownAt = 0;
}

void loop() {
  unsigned long now = millis();
  if (now - fetchedAt >= REFRESH_SECONDS * 1000UL) {
    lastFetchFailed = !fetchPages();
    fetchedAt = now;
  }
  if (pages.length() == 0) {
    drawMessage("no data from server", SERVER_URL);
    delay(1000);
    return;
  }
  if (pageShownAt == 0 || now - pageShownAt >= PAGE_SECONDS * 1000UL) {
    int count = pageCount(pages);
    pageIndex = count ? (pageIndex + (pageShownAt == 0 ? 0 : 1)) % count : 0;
    drawPage(pageAt(pages, pageIndex));
    pageShownAt = now;
  }
  delay(100);
}
