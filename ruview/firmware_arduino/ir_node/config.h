#pragma once

// ============================================================
//  EDIT THESE — your WiFi + Pi IP
// ============================================================

#define WIFI_SSID       "蝦家"
#define WIFI_PASSWORD   "12345678"
#define MQTT_BROKER_IP  "192.168.1.189"   // Pi IP (same as other nodes)
#define NODE_ID         "ir_1"

// ============================================================
//  Hardware
//  IR transmitter data pin — wire LED (long leg) → D4 via 33Ω
// ============================================================
#define IR_PIN  4   // GPIO 4 (D4 on most ESP32 dev boards)

// ============================================================
//  IR Brand selection — uncomment ONE ac and ONE light brand
// ============================================================

// Air conditioner
#define IR_AC_DAIKIN          // Daikin (most common)
// #define IR_AC_MITSUBISHI   // Mitsubishi MSZ
// #define IR_AC_SAMSUNG      // Samsung Wind-Free
// #define IR_AC_LG           // LG Inverter

// Room light — comment out if your light uses a wall switch
#define IR_LIGHT_PANASONIC_NEC   // Panasonic HH series (NEC protocol)
// #define IR_LIGHT_XIAOMI_NEC    // Xiaomi Yeelight ceiling

// ──────────────────────────────────────────────────────────
//  Panasonic HH light NEC codes — edit to match your remote.
//  How to find your codes: flash an IR receiver sketch,
//  point your remote at it, press each button, read the hex
//  from Serial Monitor.
// ──────────────────────────────────────────────────────────
#define LIGHT_ON_CODE   0x40BF40BF   // NEC 32-bit
#define LIGHT_OFF_CODE  0x40BFC03F

// ============================================================
//  Advanced — no need to change
// ============================================================
#define MQTT_PORT        1883
