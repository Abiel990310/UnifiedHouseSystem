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
 * Command JSON examples:
 *   {"preset":"chill"}
 *   {"preset":"custom","r":255,"g":80,"b":0,"brightness":150}
 *   {"preset":"off"}
 *   {"brightness":100}   // change brightness only, keep current preset
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include "config.h"

// ── NeoPixel ───────────────────────────────────────────────────────────────
Adafruit_NeoPixel strip(NUM_LEDS, LED_PIN, NEO_GRB + NEO_KHZ800);

// ── MQTT ───────────────────────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

char topic_set[48];
char topic_all[32] = "home/led/all/set";
char topic_status[48];

// ── LED state ──────────────────────────────────────────────────────────────
struct {
  char    preset[16] = "off";
  uint8_t r = 0, g = 0, b = 0;
  uint8_t brightness = 160;
} ledState;

// Pattern timing
unsigned long lastPatternMs = 0;
float         phase         = 0.0f;
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

uint32_t hsvToRgb(float h, float s, float v) {
  // h 0..360, s/v 0..1
  int   hi = (int)(h / 60) % 6;
  float f  = h / 60 - (int)(h / 60);
  float p  = v * (1 - s);
  float q  = v * (1 - f * s);
  float t  = v * (1 - (1 - f) * s);
  float R, G, B;
  switch (hi) {
    case 0: R=v; G=t; B=p; break;
    case 1: R=q; G=v; B=p; break;
    case 2: R=p; G=v; B=t; break;
    case 3: R=p; G=q; B=v; break;
    case 4: R=t; G=p; B=v; break;
    default:R=v; G=p; B=q; break;
  }
  return strip.Color((uint8_t)(R*255), (uint8_t)(G*255), (uint8_t)(B*255));
}

// ── Preset patterns ────────────────────────────────────────────────────────
void pattern_off()    { setAll(0, 0, 0); }

void pattern_chill() {
  // Slow breathing warm white — 4s cycle
  phase += 0.025f;
  float b = (sinf(phase) + 1.0f) / 2.0f;
  setAll((uint8_t)(255 * b), (uint8_t)(200 * b), (uint8_t)(120 * b));
}

void pattern_focus() {
  // Bright cool white, steady
  setAll(230, 240, 255);
}

void pattern_sleep() {
  // Dim warm red that slowly breathes, very gentle
  phase += 0.008f;
  float b = (sinf(phase) + 1.0f) / 2.0f * 0.4f + 0.05f;
  setAll((uint8_t)(200 * b), (uint8_t)(60 * b), 0);
}

void pattern_party() {
  // Fast rainbow cycle
  hue += 256;   // NeoPixel wheel speed
  uint32_t c = strip.ColorHSV(hue);
  for (int i = 0; i < NUM_LEDS; i++)
    strip.setPixelColor(i, strip.gamma32(c));
  strip.show();
}

void pattern_sunset() {
  // Orange → purple slow fade
  phase += 0.015f;
  float t = (sinf(phase) + 1.0f) / 2.0f;
  uint8_t r = 255;
  uint8_t g = (uint8_t)(60 * (1.0f - t));
  uint8_t b = (uint8_t)(180 * t);
  setAll(r, g, b);
}

void pattern_ocean() {
  // Blue ↔ cyan wave
  phase += 0.02f;
  float t = (sinf(phase) + 1.0f) / 2.0f;
  setAll(0, (uint8_t)(180 * t), (uint8_t)(200 + 55 * (1.0f - t)));
}

void pattern_custom() {
  setAll(ledState.r, ledState.g, ledState.b);
}

void runPattern() {
  String p = String(ledState.preset);
  if      (p == "chill")  pattern_chill();
  else if (p == "focus")  pattern_focus();
  else if (p == "sleep")  pattern_sleep();
  else if (p == "party")  pattern_party();
  else if (p == "sunset") pattern_sunset();
  else if (p == "ocean")  pattern_ocean();
  else if (p == "custom") pattern_custom();
  else                    pattern_off();
}

bool isAnimated() {
  String p = String(ledState.preset);
  return p=="chill" || p=="sleep" || p=="party" || p=="sunset" || p=="ocean";
}

// ── MQTT message handler ───────────────────────────────────────────────────
void onMessage(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) return;

  if (doc.containsKey("preset")) {
    strlcpy(ledState.preset, doc["preset"] | "off", sizeof(ledState.preset));
    phase = 0; hue = 0;  // reset animation
  }
  if (doc.containsKey("r"))          ledState.r = (uint8_t)constrain((int)doc["r"], 0, 255);
  if (doc.containsKey("g"))          ledState.g = (uint8_t)constrain((int)doc["g"], 0, 255);
  if (doc.containsKey("b"))          ledState.b = (uint8_t)constrain((int)doc["b"], 0, 255);
  if (doc.containsKey("brightness")) {
    ledState.brightness = (uint8_t)constrain((int)doc["brightness"], 0, MAX_BRIGHTNESS);
  }

  // Apply immediately for non-animated presets
  if (!isAnimated()) runPattern();

  Serial.printf("[%s] preset=%s bright=%d\n",
    NODE_ID, ledState.preset, ledState.brightness);
}

// ── WiFi ───────────────────────────────────────────────────────────────────
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);   // modem sleep — saves ~30% power when idle
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
      // Publish online status (retained)
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

  // Boot flash: brief white to confirm it's alive
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

  // Run animation at appropriate rate
  unsigned long now = millis();
  unsigned long interval = isAnimated() ? 50 : 1000;  // 20fps or 1fps idle

  if (now - lastPatternMs >= interval) {
    lastPatternMs = now;
    if (isAnimated()) runPattern();
  }

  // Heartbeat every 15s
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
