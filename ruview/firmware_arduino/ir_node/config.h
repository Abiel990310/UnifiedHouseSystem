#pragma once

// ============================================================
//  EDIT THESE — your WiFi + Pi IP
// ============================================================

#define WIFI_SSID       "蝦家"
#define WIFI_PASSWORD   "12345678"
#define NODE_ID         "ir_node"

// ============================================================
//  Hardware
//  IR transmitter data pin — wire LED (long leg) → D4 via 33Ω
// ============================================================
#define IR_PIN       4   // GPIO 4 (D4 on most ESP32 dev boards)

// ============================================================
//  IR Brand selection — uncomment ONE ac and ONE light brand
// ============================================================

// Air conditioner
#define IR_AC_DAIKIN          // Daikin (most common)
// #define IR_AC_MITSUBISHI   // Mitsubishi MSZ
// #define IR_AC_SAMSUNG      // Samsung Wind-Free
// #define IR_AC_LG           // LG Inverter

// Room light (via IR remote)
// Comment all out if your light uses a wall switch instead
#define IR_LIGHT_PANASONIC_NEC   // Panasonic HH series (NEC protocol)
// #define IR_LIGHT_XIAOMI_NEC    // Xiaomi Yeelight ceiling

// ──────────────────────────────────────────────────────────
//  Panasonic HH light NEC codes (edit to match your remote)
// ──────────────────────────────────────────────────────────
//  How to find your codes: flash ESP32 with an IR receiver
//  sketch, point your remote at it, press each button,
//  and read the hex value from Serial Monitor.
#define LIGHT_ON_CODE    0x40BF40BF   // NEC 32-bit
#define LIGHT_OFF_CODE   0x40BFC03F
