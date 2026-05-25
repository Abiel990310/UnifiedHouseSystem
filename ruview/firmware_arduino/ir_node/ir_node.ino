/*
 * IR Node — HTTP-controlled AC + light blaster
 *
 * Libraries (install via Arduino Library Manager):
 *   - IRremoteESP8266  by crankyoldgit
 *   - ArduinoJson      by Benoit Blanchon
 *
 * Board:   ESP32 Dev Module (the plain ESP32, not S3)
 * Edit config.h with your WiFi credentials before uploading.
 *
 * HTTP API (all return JSON):
 *   POST /ac     {"power":"on","mode":"cool","temp":25,"fan":"auto"}
 *   POST /light  {"power":"on"}
 *   GET  /status
 *
 * Modes: cool / heat / fan / dry / auto
 * Fan:   auto / low / med / high
 * Temp:  16 – 30 (°C)
 */

#include <WiFi.h>
#include <WebServer.h>
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

// ── Web server ────────────────────────────────────────────────────────────────
WebServer server(80);

// ── State ─────────────────────────────────────────────────────────────────────
struct {
  bool   ac_power  = false;
  char   ac_mode[8] = "cool";
  uint8_t ac_temp  = 25;
  char   ac_fan[8] = "auto";
  bool   light_on  = false;
} state;

// ── Helpers ───────────────────────────────────────────────────────────────────

void sendAC() {
#ifdef IR_AC_DAIKIN
  ac.setPower(state.ac_power);
  if (strcmp(state.ac_mode, "cool") == 0) ac.setMode(kDaikinCool);
  else if (strcmp(state.ac_mode, "heat") == 0) ac.setMode(kDaikinHeat);
  else if (strcmp(state.ac_mode, "fan")  == 0) ac.setMode(kDaikinFan);
  else if (strcmp(state.ac_mode, "dry")  == 0) ac.setMode(kDaikinDry);
  else                                          ac.setMode(kDaikinAuto);
  ac.setTemp(state.ac_temp);
  if (strcmp(state.ac_fan, "low")  == 0) ac.setFan(kDaikinFanMin);
  else if (strcmp(state.ac_fan, "med")  == 0) ac.setFan(3);
  else if (strcmp(state.ac_fan, "high") == 0) ac.setFan(kDaikinFanMax);
  else                                        ac.setFan(kDaikinFanAuto);
  ac.send();
#elif defined(IR_AC_MITSUBISHI)
  ac.setPower(state.ac_power);
  if (strcmp(state.ac_mode, "cool") == 0) ac.setMode(kMitsubishiAcCool);
  else if (strcmp(state.ac_mode, "heat") == 0) ac.setMode(kMitsubishiAcHeat);
  else if (strcmp(state.ac_mode, "dry")  == 0) ac.setMode(kMitsubishiAcDry);
  else if (strcmp(state.ac_mode, "fan")  == 0) ac.setMode(kMitsubishiAcFan);
  else                                          ac.setMode(kMitsubishiAcAuto);
  ac.setTemp(state.ac_temp);
  if (strcmp(state.ac_fan, "low")  == 0) ac.setFan(kMitsubishiAcFanSilent);
  else if (strcmp(state.ac_fan, "high") == 0) ac.setFan(kMitsubishiAcFanRealMax);
  else                                        ac.setFan(kMitsubishiAcFanAuto);
  ac.send();
#else
  // Generic fallback: just sends power off/on via Daikin as placeholder
  Serial.println("[IR] AC brand not configured — define IR_AC_* in config.h");
#endif
}

void sendLight(bool on) {
#ifdef IR_LIGHT_PANASONIC_NEC
  uint64_t code = on ? LIGHT_ON_CODE : LIGHT_OFF_CODE;
  irsend.sendNEC(code, 32);
  Serial.printf("[IR] Light %s  code=0x%08X\n", on ? "ON" : "OFF", (uint32_t)code);
#else
  Serial.println("[IR] Light brand not configured — define IR_LIGHT_* in config.h");
#endif
}

String buildStatus() {
  StaticJsonDocument<256> doc;
  doc["node_id"]     = NODE_ID;
  doc["online"]      = true;
  JsonObject ac_obj  = doc.createNestedObject("ac");
  ac_obj["power"]    = state.ac_power ? "on" : "off";
  ac_obj["mode"]     = state.ac_mode;
  ac_obj["temp"]     = state.ac_temp;
  ac_obj["fan"]      = state.ac_fan;
  JsonObject light_obj = doc.createNestedObject("light");
  light_obj["power"] = state.light_on ? "on" : "off";
  String out;
  serializeJson(doc, out);
  return out;
}

// ── Route handlers ────────────────────────────────────────────────────────────

void handleStatus() {
  server.send(200, "application/json", buildStatus());
}

void handleAC() {
  if (!server.hasArg("plain")) { server.send(400, "application/json", "{\"error\":\"no body\"}"); return; }
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, server.arg("plain")) != DeserializationError::Ok) {
    server.send(400, "application/json", "{\"error\":\"bad json\"}"); return;
  }

  if (doc.containsKey("power")) state.ac_power = (strcmp(doc["power"] | "off", "on") == 0);
  if (doc.containsKey("mode"))  strlcpy(state.ac_mode, doc["mode"] | "cool", sizeof(state.ac_mode));
  if (doc.containsKey("temp"))  state.ac_temp = constrain((int)(doc["temp"] | 25), 16, 30);
  if (doc.containsKey("fan"))   strlcpy(state.ac_fan, doc["fan"] | "auto", sizeof(state.ac_fan));

  sendAC();
  server.send(200, "application/json", buildStatus());
  Serial.printf("[AC] power=%s mode=%s temp=%d fan=%s\n",
    state.ac_power ? "on" : "off", state.ac_mode, state.ac_temp, state.ac_fan);
}

void handleLight() {
  if (!server.hasArg("plain")) { server.send(400, "application/json", "{\"error\":\"no body\"}"); return; }
  StaticJsonDocument<64> doc;
  if (deserializeJson(doc, server.arg("plain")) != DeserializationError::Ok) {
    server.send(400, "application/json", "{\"error\":\"bad json\"}"); return;
  }

  bool on = (strcmp(doc["power"] | "off", "on") == 0);
  state.light_on = on;
  sendLight(on);
  server.send(200, "application/json", buildStatus());
}

void handleNotFound() {
  server.send(404, "application/json", "{\"error\":\"not found\"}");
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

// ── Setup + loop ──────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== IR Node %s ===\n", NODE_ID);

  irsend.begin();
#if defined(IR_AC_DAIKIN) || defined(IR_AC_MITSUBISHI) || defined(IR_AC_SAMSUNG) || defined(IR_AC_LG)
  ac.begin();
#endif

  connectWiFi();

  server.on("/status", HTTP_GET,  handleStatus);
  server.on("/ac",     HTTP_POST, handleAC);
  server.on("/light",  HTTP_POST, handleLight);
  server.onNotFound(handleNotFound);
  server.begin();

  Serial.printf("HTTP server ready at http://%s/\n", WiFi.localIP().toString().c_str());
  Serial.println("Routes: GET /status  POST /ac  POST /light");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  server.handleClient();
}
