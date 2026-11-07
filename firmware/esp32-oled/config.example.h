// Copy this file to config.h and fill it in. config.h is ignored by git.
#pragma once

#define WIFI_SSID "your-wifi"
#define WIFI_PASS "your-password"

// The rackdisplay server, as the ESP32 sees it. Start it with --host 0.0.0.0 and a token.
#define SERVER_URL "http://192.168.1.10:8080"
#define API_TOKEN ""            // same as [server] token; leave empty if none

#define PAGE_SECONDS 5          // time each page stays on screen
#define REFRESH_SECONDS 10      // how often the pages are fetched again
