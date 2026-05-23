#pragma once

// ============================================================
//  EDIT THESE 4 LINES — everything else can stay as-is
// ============================================================

#define WIFI_SSID        "蝦家"          // Your WiFi name
#define WIFI_PASSWORD    "your_password" // Your WiFi password
#define MQTT_BROKER_IP   "192.168.1.100" // Your Pi's IP address
#define NODE_ID          "node_1"        // node_1 / node_2 / node_3

// ============================================================
//  Advanced settings (no need to change these)
// ============================================================

#define MQTT_PORT        1883
#define PUBLISH_RATE_HZ  10      // how many times per second to send data
#define N_SUBCARRIERS    56      // WiFi subcarriers captured per frame
