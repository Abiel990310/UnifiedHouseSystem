#pragma once

// ============================================================
//  EDIT THESE — everything else can stay as-is
// ============================================================

#define WIFI_SSID       "蝦家"
#define WIFI_PASSWORD   "12345678"
#define MQTT_BROKER_IP  "192.168.1.189"   // Pi IP
#define NODE_ID         "led_1"            // led_1 / led_2 / led_3

// ============================================================
//  LED hardware
//  ESP32-S3-DevKitC-1 onboard RGB = GPIO 48
//  If you attach an external strip, change LED_PIN to that pin
// ============================================================
#define LED_PIN   48
#define NUM_LEDS  1     // 1 = onboard only, increase for a strip

// ============================================================
//  Advanced — no need to change
// ============================================================
#define MQTT_PORT        1883
#define MAX_BRIGHTNESS   250   // onboard WS2812B is rated for 255; 250 is safe
