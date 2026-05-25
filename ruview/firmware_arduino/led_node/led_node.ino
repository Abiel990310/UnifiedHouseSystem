/*
 * RuView LED Node — Mood lighting via MQTT
 *
 * Libraries (install via Arduino Library Manager):
 *   - Adafruit NeoPixel  by Adafruit
 *   - PubSubClient       by Nick O'Leary
 *   - ArduinoJson        by Benoit Blanchon
 *
 * Board:   ESP32S3 Dev Module
 * Edit config.h with your WiFi password and node ID before uploading.
 *
 * MQTT command topic:  home/led/<NODE_ID>/set
 * MQTT broadcast:      home/led/all/set
 *
 * Presets: off, chill, focus, sleep, party, sunset, ocean, custom,
 *          aurora, fire, candle, zen, neon, midnight, rose, galaxy,
 *          morning, disco
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include "config.h"

Adafruit_NeoPixel strip(NUM_LEDS, LED_PIN, NEO_GRB + NEO_KHZ800);

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

char topic_set[48];
char topic_all[32] = "home/led/all/set";
char topic_status[48];

struct {
  char    preset[16] = "off";
  uint8_t r = 0, g = 0, b = 0;
  uint8_t brightness = 160;
} ledState;

unsigned long lastPatternMs = 0;
float         phase         = 0.0f;
float         phase2        = 0.0f;   // second oscillator for richer effects
uint16_t      hue           = 0;

// ── Colour helpers ─────────────────────────────────────────────────────────
void setAll(uint8_t r, uint8_t g, uint8_t b) {
  uint8_t scale = ledState.brightness;
  uint32_t c = strip.Color(
    (uint16_t)r * scale / 255,
    (uint16_t)g * scale / 255,
    (uint16_t)b * scale / 255
  );
  for (int i = 0; i < NUM_LEDS; i++) strip.setPixelColor(i, c);
  strip.show();
}

// ── Original presets ────────────────────────────────────────────────────────

void pattern_off() { setAll(0, 0, 0); }

void pattern_chill() {
  // Slow warm white breathing — 4s cycle
  phase += 0.025f;
  float b = (sinf(phase) + 1.0f) / 2.0f;
  setAll((uint8_t)(255*b), (uint8_t)(200*b), (uint8_t)(120*b));
}

void pattern_focus() {
  // Bright crisp cool white — steady, zero flicker
  setAll(230, 240, 255);
}

void pattern_sleep() {
  // Very dim warm red, ultra-slow breathing — won't wake you
  phase += 0.008f;
  float b = (sinf(phase) + 1.0f) / 2.0f * 0.35f + 0.04f;
  setAll((uint8_t)(200*b), (uint8_t)(50*b), 0);
}

void pattern_party() {
  // Smooth rainbow spin
  hue += 256;
  uint32_t c = strip.ColorHSV(hue);
  for (int i = 0; i < NUM_LEDS; i++) strip.setPixelColor(i, strip.gamma32(c));
  strip.show();
}

void pattern_sunset() {
  // Orange → deep purple slow tide
  phase += 0.014f;
  float t = (sinf(phase) + 1.0f) / 2.0f;
  setAll(255, (uint8_t)(55*(1.0f-t)), (uint8_t)(190*t));
}

void pattern_ocean() {
  // Blue ↔ cyan breathing wave
  phase += 0.02f;
  float t = (sinf(phase) + 1.0f) / 2.0f;
  setAll(0, (uint8_t)(180*t), (uint8_t)(200 + 55*(1.0f-t)));
}

void pattern_custom() { setAll(ledState.r, ledState.g, ledState.b); }

// ── New presets ─────────────────────────────────────────────────────────────

void pattern_aurora() {
  // Northern lights — two de-synced sine waves in green + violet
  phase  += 0.011f;
  phase2 += 0.017f;
  float g_val = (sinf(phase)  + 1.0f) / 2.0f;
  float v_val = (sinf(phase2) + 1.0f) / 2.0f;
  setAll((uint8_t)(110*v_val), (uint8_t)(220*g_val), (uint8_t)(160*v_val + 40*g_val));
}

void pattern_fire() {
  // Crackling fire — fast random warm flicker
  phase += 0.08f;
  float base    = (sinf(phase) + 1.0f) / 2.0f * 0.3f + 0.6f;
  float crackle = (float)random(80, 100) / 100.0f;
  float f = base * crackle;
  setAll((uint8_t)(255*f), (uint8_t)(90*f*f), 0);
}

void pattern_candle() {
  // Gentle candlelight — slower, warmer, softer flicker
  phase += 0.04f;
  float base   = (sinf(phase) + 1.0f) / 2.0f * 0.25f + 0.65f;
  float breath = (float)random(90, 100) / 100.0f;
  float f = base * breath;
  setAll((uint8_t)(255*f), (uint8_t)(130*f), (uint8_t)(18*f));
}

void pattern_zen() {
  // Very slow deep indigo breathing — 8s cycle, meditative
  phase += 0.006f;
  float b = (sinf(phase) + 1.0f) / 2.0f;
  setAll((uint8_t)(100*b), (uint8_t)(15*b), (uint8_t)(180*b));
}

void pattern_neon() {
  // Fast vivid HSV cycle — saturated neon sweep
  hue += 768;
  uint32_t c = strip.ColorHSV(hue, 255, 255);
  for (int i = 0; i < NUM_LEDS; i++) strip.setPixelColor(i, strip.gamma32(c));
  strip.show();
}

void pattern_midnight() {
  // Deep navy blue, slow dim pulse — almost off
  phase += 0.013f;
  float b = (sinf(phase) + 1.0f) / 2.0f * 0.55f + 0.08f;
  setAll((uint8_t)(8*b), (uint8_t)(18*b), (uint8_t)(140*b));
}

void pattern_rose() {
  // Warm rose-pink breathing — romantic
  phase += 0.02f;
  float b = (sinf(phase) + 1.0f) / 2.0f;
  setAll((uint8_t)(230*b), (uint8_t)(55*b), (uint8_t)(95*b));
}

void pattern_galaxy() {
  // Deep space — two oscillators drifting purple ↔ cobalt
  phase  += 0.009f;
  phase2 += 0.013f;
  float t1 = (sinf(phase)  + 1.0f) / 2.0f;
  float t2 = (sinf(phase2) + 1.0f) / 2.0f;
  setAll((uint8_t)(70*t1 + 15), (uint8_t)(8*t2), (uint8_t)(110*(1.0f-t1) + 80*t2));
}

void pattern_morning() {
  // Sunrise warm glow — very slow climb from amber to soft white
  phase += 0.005f;
  float t = (sinf(phase) + 1.0f) / 2.0f;
  float t2 = t * t;
  setAll((uint8_t)(255*t), (uint8_t)(170*t2), (uint8_t)(60*t2*t));
}

void pattern_disco() {
  // Strobe-style fast random hue jumps
  hue += (uint16_t)random(3000, 9000);
  uint32_t c = strip.ColorHSV(hue, 255, 255);
  for (int i = 0; i < NUM_LEDS; i++) strip.setPixelColor(i, strip.gamma32(c));
  strip.show();
}

// ── Dispatch ───────────────────────────────────────────────────────────────
void runPattern() {
  String p = String(ledState.preset);
  if      (p == "chill")    pattern_chill();
  else if (p == "focus")    pattern_focus();
  else if (p == "sleep")    pattern_sleep();
  else if (p == "party")    pattern_party();
  else if (p == "sunset")   pattern_sunset();
  else if (p == "ocean")    pattern_ocean();
  else if (p == "aurora")   pattern_aurora();
  else if (p == "fire")     pattern_fire();
  else if (p == "candle")   pattern_candle();
  else if (p == "zen")      pattern_zen();
  else if (p == "neon")     pattern_neon();
  else if (p == "midnight") pattern_midnight();
  else if (p == "rose")     pattern_rose();
  else if (p == "galaxy")   pattern_galaxy();
  else if (p == "morning")  pattern_morning();
  else if (p == "disco")    pattern_disco();
  else if (p == "custom")   pattern_custom();
  else                      pattern_off();
}

bool isAnimated() {
  String p = String(ledState.preset);
  return p=="chill"  || p=="sleep"    || p=="party"  || p=="sunset" ||
         p=="ocean"  || p=="aurora"   || p=="fire"   || p=="candle" ||
         p=="zen"    || p=="neon"     || p=="midnight"|| p=="rose"   ||
         p=="galaxy" || p=="morning"  || p=="disco";
}

// ── MQTT message handler ───────────────────────────────────────────────────
void onMessage(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) return;

  if (doc.containsKey("preset")) {
    strlcpy(ledState.preset, doc["preset"] | "off", sizeof(ledState.preset));
    phase = 0; phase2 = 0; hue = 0;
  }
  if (doc.containsKey("r"))          ledState.r = (uint8_t)constrain((int)doc["r"], 0, 255);
  if (doc.containsKey("g"))          ledState.g = (uint8_t)constrain((int)doc["g"], 0, 255);
  if (doc.containsKey("b"))          ledState.b = (uint8_t)constrain((int)doc["b"], 0, 255);
  if (doc.containsKey("brightness")) {
    ledState.brightness = (uint8_t)constrain((int)doc["brightness"], 0, MAX_BRIGHTNESS);
  }

  if (!isAnimated()) runPattern();

  Serial.printf("[%s] preset=%s bright=%d\n",
    NODE_ID, ledState.preset, ledState.brightness);
}

// ── WiFi ───────────────────────────────────────────────────────────────────
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && ++tries < 40) {
    delay(500); Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED) { ESP.restart(); }
  Serial.printf(" connected  IP=%s\n", WiFi.localIP().toString().c_str());
}

// ── MQTT ───────────────────────────────────────────────────────────────────
void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("MQTT...");
    if (mqtt.connect(NODE_ID)) {
      mqtt.subscribe(topic_set);
      mqtt.subscribe(topic_all);
      char msg[80];
      snprintf(msg, sizeof(msg),
        "{\"node_id\":\"%s\",\"online\":true,\"type\":\"led\"}", NODE_ID);
      mqtt.publish(topic_status, msg, true);
      Serial.println(" connected");
    } else {
      Serial.printf(" failed rc=%d  retry 5s\n", mqtt.state());
      delay(5000);
    }
  }
}

// ── setup ──────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== LED Node %s ===\n", NODE_ID);

  snprintf(topic_set,    sizeof(topic_set),    "home/led/%s/set",    NODE_ID);
  snprintf(topic_status, sizeof(topic_status), "home/led/%s/status", NODE_ID);

  strip.begin();
  strip.setBrightness(MAX_BRIGHTNESS);
  strip.clear();
  strip.show();

  connectWiFi();

  mqtt.setServer(MQTT_BROKER_IP, MQTT_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setKeepAlive(30);
  connectMQTT();

  setAll(100, 100, 100);
  delay(300);
  setAll(0, 0, 0);

  Serial.printf("Ready. Listening on %s\n", topic_set);
}

// ── loop ───────────────────────────────────────────────────────────────────
void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected())             connectMQTT();
  mqtt.loop();

  unsigned long now      = millis();
  unsigned long interval = isAnimated() ? 50 : 1000;

  if (now - lastPatternMs >= interval) {
    lastPatternMs = now;
    if (isAnimated()) runPattern();
  }

  static unsigned long lastHeartbeat = 0;
  if (now - lastHeartbeat >= 15000) {
    lastHeartbeat = now;
    char msg[96];
    snprintf(msg, sizeof(msg),
      "{\"node_id\":\"%s\",\"online\":true,\"preset\":\"%s\",\"rssi\":%d}",
      NODE_ID, ledState.preset, WiFi.RSSI());
    mqtt.publish(topic_status, msg, true);
  }
}
