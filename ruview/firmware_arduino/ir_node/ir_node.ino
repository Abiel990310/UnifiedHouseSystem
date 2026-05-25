/*
 * IR Node — MQTT-controlled AC + light blaster
 *
 * Libraries (install via Arduino Library Manager):
 *   - IRremoteESP8266  by crankyoldgit
 *   - PubSubClient     by Nick O'Leary
 *   - ArduinoJson      by Benoit Blanchon
 *
 * Board:   ESP32 Dev Module
 * Edit config.h with your WiFi + MQTT broker IP before uploading.
 * Set NODE_ID to "ir_1" (or ir_2 if you have more than one).
 *
 * MQTT command topic:  home/ir/<NODE_ID>/set
 * MQTT broadcast:      home/ir/all/set
 *
 * Command JSON examples:
 *   {"device":"ac","power":"on","mode":"cool","temp":25,"fan":"auto"}
 *   {"device":"ac","power":"off"}
 *   {"device":"ac","temp":22}           // change temp only
 *   {"device":"light","power":"on"}
 *   {"device":"light","power":"off"}
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <IRsend.h>

#ifdef IR_AC_DAIKIN
  #include <ir_Daikin.h>
#elif defined(IR_AC_MITSUBISHI)
  #include <ir_Mitsubishi.h>
#elif defined(IR_AC_SAMSUNG)
  #include <ir_Samsung.h>
#elif defined(IR_AC_LG)
  #include <ir_LG.h>
#endif

#include "config.h"

// ── IR sender ─────────────────────────────────────────────────────────────────
IRsend irsend(IR_PIN);

#ifdef IR_AC_DAIKIN
  IRDaikinESP ac(IR_PIN);
#elif defined(IR_AC_MITSUBISHI)
  IRMitsubishiAC ac(IR_PIN);
#elif defined(IR_AC_SAMSUNG)
  IRSamsungAc ac(IR_PIN);
#elif defined(IR_AC_LG)
  IRLgAc ac(IR_PIN);
#endif

// ── MQTT ──────────────────────────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

char topic_set[48];
char topic_all[32]    = "home/ir/all/set";
char topic_status[48];

// ── State ─────────────────────────────────────────────────────────────────────
struct {
  bool    ac_power  = false;
  char    ac_mode[8] = "cool";
  uint8_t ac_temp   = 25;
  char    ac_fan[8] = "auto";
  bool    light_on  = false;
} state;

// ── IR helpers ────────────────────────────────────────────────────────────────
void sendAC() {
#ifdef IR_AC_DAIKIN
  ac.setPower(state.ac_power);
  if      (strcmp(state.ac_mode, "cool") == 0) ac.setMode(kDaikinCool);
  else if (strcmp(state.ac_mode, "heat") == 0) ac.setMode(kDaikinHeat);
  else if (strcmp(state.ac_mode, "fan")  == 0) ac.setMode(kDaikinFan);
  else if (strcmp(state.ac_mode, "dry")  == 0) ac.setMode(kDaikinDry);
  else                                          ac.setMode(kDaikinAuto);
  ac.setTemp(state.ac_temp);
  if      (strcmp(state.ac_fan, "low")  == 0) ac.setFan(kDaikinFanMin);
  else if (strcmp(state.ac_fan, "med")  == 0) ac.setFan(3);
  else if (strcmp(state.ac_fan, "high") == 0) ac.setFan(kDaikinFanMax);
  else                                        ac.setFan(kDaikinFanAuto);
  ac.send();
#elif defined(IR_AC_MITSUBISHI)
  ac.setPower(state.ac_power);
  if      (strcmp(state.ac_mode, "cool") == 0) ac.setMode(kMitsubishiAcCool);
  else if (strcmp(state.ac_mode, "heat") == 0) ac.setMode(kMitsubishiAcHeat);
  else if (strcmp(state.ac_mode, "dry")  == 0) ac.setMode(kMitsubishiAcDry);
  else if (strcmp(state.ac_mode, "fan")  == 0) ac.setMode(kMitsubishiAcFan);
  else                                          ac.setMode(kMitsubishiAcAuto);
  ac.setTemp(state.ac_temp);
  if      (strcmp(state.ac_fan, "low")  == 0) ac.setFan(kMitsubishiAcFanSilent);
  else if (strcmp(state.ac_fan, "high") == 0) ac.setFan(kMitsubishiAcFanRealMax);
  else                                        ac.setFan(kMitsubishiAcFanAuto);
  ac.send();
#else
  Serial.println("[IR] AC brand not configured — define IR_AC_* in config.h");
#endif
  Serial.printf("[AC] power=%s mode=%s temp=%d fan=%s\n",
    state.ac_power ? "on" : "off", state.ac_mode, state.ac_temp, state.ac_fan);
}

void sendLight(bool on) {
#ifdef IR_LIGHT_PANASONIC_NEC
  irsend.sendNEC(on ? LIGHT_ON_CODE : LIGHT_OFF_CODE, 32);
#else
  Serial.println("[IR] Light brand not configured — define IR_LIGHT_* in config.h");
#endif
  Serial.printf("[Light] %s\n", on ? "ON" : "OFF");
}

// ── MQTT message handler ──────────────────────────────────────────────────────
void onMessage(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) return;

  const char* device = doc["device"] | "";

  if (strcmp(device, "ac") == 0) {
    if (doc.containsKey("power")) state.ac_power = (strcmp(doc["power"] | "off", "on") == 0);
    if (doc.containsKey("mode"))  strlcpy(state.ac_mode, doc["mode"] | "cool", sizeof(state.ac_mode));
    if (doc.containsKey("temp"))  state.ac_temp  = (uint8_t)constrain((int)(doc["temp"] | 25), 16, 30);
    if (doc.containsKey("fan"))   strlcpy(state.ac_fan,  doc["fan"]  | "auto", sizeof(state.ac_fan));
    sendAC();

  } else if (strcmp(device, "light") == 0) {
    if (doc.containsKey("power")) {
      state.light_on = (strcmp(doc["power"] | "off", "on") == 0);
      sendLight(state.light_on);
    }
  }
}

// ── WiFi ──────────────────────────────────────────────────────────────────────
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

// ── Setup + loop ──────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== IR Node %s ===\n", NODE_ID);

  snprintf(topic_set,    sizeof(topic_set),    "home/ir/%s/set",    NODE_ID);
  snprintf(topic_status, sizeof(topic_status), "home/ir/%s/status", NODE_ID);

  irsend.begin();
#if defined(IR_AC_DAIKIN) || defined(IR_AC_MITSUBISHI) || defined(IR_AC_SAMSUNG) || defined(IR_AC_LG)
  ac.begin();
#endif

  connectWiFi();

  mqtt.setServer(MQTT_BROKER_IP, MQTT_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setKeepAlive(30);
  connectMQTT();

  Serial.printf("Ready. Listening on %s\n", topic_set);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected())             connectMQTT();
  mqtt.loop();

  // Heartbeat every 30s
  static unsigned long lastHB = 0;
  unsigned long now = millis();
  if (now - lastHB >= 30000) {
    lastHB = now;
    char msg[128];
    snprintf(msg, sizeof(msg),
      "{\"node_id\":\"%s\",\"online\":true,\"type\":\"ir\","
      "\"ac_power\":\"%s\",\"ac_temp\":%d,\"light\":\"%s\",\"rssi\":%d}",
      NODE_ID, state.ac_power ? "on" : "off", state.ac_temp,
      state.light_on ? "on" : "off", WiFi.RSSI());
    mqtt.publish(topic_status, msg, true);
  }
}
