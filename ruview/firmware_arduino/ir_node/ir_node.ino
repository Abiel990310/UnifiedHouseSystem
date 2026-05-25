/*
 * IR Node — MQTT-controlled AC + light (Daikin + Panasonic)
 *
 * Libraries (install via Arduino Library Manager):
 *   - IRremoteESP8266  by crankyoldgit
 *   - PubSubClient     by Nick O'Leary
 *   - ArduinoJson      by Benoit Blanchon
 *
 * Board:   ESP32 Dev Module
 *
 * MQTT command topic:  home/ir/<NODE_ID>/set
 * MQTT broadcast:      home/ir/all/set
 *
 * Command JSON:
 *   {"device":"ac","power":"on","mode":"cool","temp":24,"fan":"auto"}
 *   {"device":"ac","power":"off"}
 *   {"device":"ac","temp":22}
 *   {"device":"light","power":"on"}
 *   {"device":"light","power":"off"}
 */

#include <IRsend.h>
#include <ir_Daikin.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "config.h"

// ── IR ────────────────────────────────────────────────────────────────────────
IRsend      irsend(IR_SEND_PIN);
IRDaikinESP daikin(IR_SEND_PIN);

// ── MQTT ──────────────────────────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

char topic_set[48];
char topic_all[32]    = "home/ir/all/set";
char topic_status[48];

// ── State (mirrors your original code defaults) ───────────────────────────────
struct {
  bool    ac_power = false;
  uint8_t ac_mode  = DAIKIN_COOL;
  uint8_t ac_temp  = 24;
  uint8_t ac_fan   = DAIKIN_FAN_AUTO;
  bool    light_on = false;
} state;

// ── Helpers ───────────────────────────────────────────────────────────────────
void applyAC() {
  daikin.setPower(state.ac_power);
  daikin.setMode(state.ac_mode);
  daikin.setTemp(state.ac_temp);
  daikin.setFan(state.ac_fan);
  daikin.send(10);
  Serial.printf("[AC] power=%s mode=%d temp=%d\n",
    state.ac_power ? "on" : "off", state.ac_mode, state.ac_temp);
}

void applyLight(bool on) {
  irsend.sendPanasonic(0x4004, on ? LIGHT_ON : LIGHT_OFF, 40);
  Serial.printf("[Light] %s\n", on ? "ON" : "OFF");
}

uint8_t modeFromStr(const char* s) {
  if (strcmp(s, "heat") == 0) return DAIKIN_HEAT;
  if (strcmp(s, "auto") == 0) return DAIKIN_AUTO;
  return DAIKIN_COOL;
}

const char* modeToStr(uint8_t m) {
  if (m == DAIKIN_HEAT) return "heat";
  if (m == DAIKIN_AUTO) return "auto";
  return "cool";
}

// ── MQTT callback ─────────────────────────────────────────────────────────────
void onMessage(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) return;

  const char* device = doc["device"] | "";

  if (strcmp(device, "ac") == 0) {
    if (doc.containsKey("power")) state.ac_power = (strcmp(doc["power"] | "off", "on") == 0);
    if (doc.containsKey("mode"))  state.ac_mode  = modeFromStr(doc["mode"] | "cool");
    if (doc.containsKey("temp"))  state.ac_temp  = (uint8_t)constrain((int)(doc["temp"] | 24), 16, 30);
    applyAC();

  } else if (strcmp(device, "light") == 0) {
    state.light_on = (strcmp(doc["power"] | "off", "on") == 0);
    applyLight(state.light_on);
  }
}

// ── WiFi ──────────────────────────────────────────────────────────────────────
void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(true);
  Serial.print("WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && ++tries < 40) {
    delay(500); Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED) { ESP.restart(); }
  Serial.printf(" connected  IP=%s\n", WiFi.localIP().toString().c_str());
}

// ── MQTT ──────────────────────────────────────────────────────────────────────
void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("MQTT...");
    if (mqtt.connect(NODE_ID)) {
      mqtt.subscribe(topic_set);
      mqtt.subscribe(topic_all);
      char msg[96];
      snprintf(msg, sizeof(msg),
        "{\"node_id\":\"%s\",\"online\":true,\"type\":\"ir\"}", NODE_ID);
      mqtt.publish(topic_status, msg, true);
      Serial.println(" connected");
    } else {
      Serial.printf(" failed rc=%d  retry 5s\n", mqtt.state());
      delay(5000);
    }
  }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.printf("\n=== IR Node %s ===\n", NODE_ID);

  snprintf(topic_set,    sizeof(topic_set),    "home/ir/%s/set",    NODE_ID);
  snprintf(topic_status, sizeof(topic_status), "home/ir/%s/status", NODE_ID);

  irsend.begin();
  daikin.begin();
  daikin.setPower(false);
  daikin.setMode(DAIKIN_COOL);
  daikin.setTemp(24);
  daikin.setFan(DAIKIN_FAN_AUTO);

  connectWiFi();

  mqtt.setServer(MQTT_BROKER_IP, MQTT_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setKeepAlive(30);
  connectMQTT();

  Serial.printf("Ready. Listening on %s\n", topic_set);
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected())             connectMQTT();
  mqtt.loop();

  static unsigned long lastHB = 0;
  unsigned long now = millis();
  if (now - lastHB >= 30000) {
    lastHB = now;
    char msg[128];
    snprintf(msg, sizeof(msg),
      "{\"node_id\":\"%s\",\"online\":true,\"type\":\"ir\","
      "\"ac_power\":\"%s\",\"ac_temp\":%d,\"ac_mode\":\"%s\","
      "\"light\":\"%s\",\"rssi\":%d}",
      NODE_ID, state.ac_power ? "on" : "off", state.ac_temp,
      modeToStr(state.ac_mode), state.light_on ? "on" : "off", WiFi.RSSI());
    mqtt.publish(topic_status, msg, true);
  }
}
