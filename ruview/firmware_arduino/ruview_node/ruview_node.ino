/*
 * RuView Node — Arduino sketch for ESP32-S3
 *
 * Libraries required (install via Arduino Library Manager):
 *   - PubSubClient  by Nick O'Leary
 *   - ArduinoJson   by Benoit Blanchon
 *
 * Board: ESP32S3 Dev Module
 * Before flashing, edit config.h with your WiFi password and Pi IP.
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "esp_wifi.h"
#include "esp_timer.h"
#include "config.h"
#include <math.h>

// ── MQTT topics ────────────────────────────────────────────────────────────
char topic_csi[48];
char topic_status[48];

// ── CSI shared state (written by ISR, read by loop) ───────────────────────
static volatile bool     csi_ready       = false;
static volatile int8_t   csi_rssi        = -127;
static volatile uint8_t  csi_channel     = 0;
static float             amplitude[N_SUBCARRIERS];
static float             phase_buf[N_SUBCARRIERS];
static float             motion_variance = 0.0f;

// Smoothing buffers (5-frame moving average)
static float smooth_buf[N_SUBCARRIERS][5];
static uint8_t smooth_head = 0;

// Usable subcarrier index map for HT20 (56 out of 64)
static const int8_t SUBCARRIER_IDX[N_SUBCARRIERS] = {
  -28,-27,-26,-25,-24,-23,-22,-21,-20,-19,-18,-17,-16,
  -15,-14,-13,-12,-11,-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,
    1,  2,  3,  4,  5,  6,  7,  8,  9,10,11,12,13,
   14, 15, 16, 17, 18, 19, 20, 21, 22,23,24,25,26,
   27, 28
};

// ── WiFi + MQTT clients ────────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// ── CSI callback (runs in interrupt context — keep it fast) ───────────────
static void IRAM_ATTR csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
  if (!info || !info->buf || info->len < 128) return;

  const int8_t *buf = info->buf;
  float amp_sum = 0.0f, amp_sq_sum = 0.0f;

  for (int i = 0; i < N_SUBCARRIERS; i++) {
    int sc = SUBCARRIER_IDX[i];
    int k  = (sc > 0) ? (sc - 1) : (64 + sc);

    float imag = (float)buf[2 * k];
    float real = (float)buf[2 * k + 1];

    float amp = sqrtf(real * real + imag * imag);
    float ph  = atan2f(imag, real);

    // 5-frame moving average
    smooth_buf[i][smooth_head] = amp;
    float s = 0;
    for (int j = 0; j < 5; j++) s += smooth_buf[i][j];
    float smoothed = s / 5.0f;

    amplitude[i] = smoothed;
    phase_buf[i] = ph;

    amp_sum    += smoothed;
    amp_sq_sum += smoothed * smoothed;
  }

  smooth_head = (smooth_head + 1) % 5;

  float mean     = amp_sum / N_SUBCARRIERS;
  motion_variance = (amp_sq_sum / N_SUBCARRIERS) - (mean * mean);
  csi_rssi       = info->rx_ctrl.rssi;
  csi_channel    = info->rx_ctrl.channel;
  csi_ready      = true;
}

// ── WiFi connection ────────────────────────────────────────────────────────
void connect_wifi()
{
  Serial.printf("\nConnecting to WiFi: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++tries > 40) {
      Serial.println("\nWiFi failed — restarting...");
      ESP.restart();
    }
  }
  Serial.printf("\nWiFi connected. IP: %s\n", WiFi.localIP().toString().c_str());
}

// ── CSI enable (call after WiFi connects) ─────────────────────────────────
void setup_csi()
{
  wifi_csi_config_t cfg = {
    .lltf_en           = true,
    .htltf_en          = true,
    .stbc_htltf2_en    = true,
    .ltf_merge_en      = true,
    .channel_filter_en = false,
    .manu_scale        = false,
    .shift             = 0,
    .dump_ack_en       = true,
  };
  esp_wifi_set_csi_config(&cfg);
  esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL);
  esp_wifi_set_csi(true);
  memset(smooth_buf, 0, sizeof(smooth_buf));
  Serial.println("CSI capture started.");
}

// ── MQTT connection ────────────────────────────────────────────────────────
void connect_mqtt()
{
  while (!mqtt.connected()) {
    Serial.printf("Connecting to MQTT broker %s...", MQTT_BROKER_IP);
    if (mqtt.connect(NODE_ID)) {
      Serial.println(" connected!");
      // Publish online status (retained so Pi knows we're up even after reconnect)
      String status = String("{\"node_id\":\"") + NODE_ID +
                      "\",\"online\":true,\"csi_active\":true}";
      mqtt.publish(topic_status, status.c_str(), true);
    } else {
      Serial.printf(" failed (rc=%d). Retry in 5s...\n", mqtt.state());
      delay(5000);
    }
  }
}

// ── Build and publish CSI JSON ─────────────────────────────────────────────
void publish_csi()
{
  if (!mqtt.connected()) return;

  // Take a snapshot of the ISR data (disable interrupts briefly)
  portDISABLE_INTERRUPTS();
  float amp_snap[N_SUBCARRIERS], ph_snap[N_SUBCARRIERS];
  float mv_snap     = motion_variance;
  int8_t rssi_snap  = csi_rssi;
  uint8_t ch_snap   = csi_channel;
  memcpy(amp_snap, amplitude,  sizeof(amp_snap));
  memcpy(ph_snap,  phase_buf,  sizeof(ph_snap));
  csi_ready = false;
  portENABLE_INTERRUPTS();

  // Build JSON — allocate on stack (heap is fragile on continuous alloc)
  // Layout: {"n":"node_1","t":1234,"r":-55,"ch":6,"mv":0.05,"a":[...],"p":[...]}
  // Estimated size: ~800 bytes
  static char json_buf[900];
  int pos = 0;

  pos += snprintf(json_buf + pos, sizeof(json_buf) - pos,
    "{\"n\":\"%s\",\"t\":%llu,\"r\":%d,\"ch\":%d,\"mv\":%.3f,\"a\":[",
    NODE_ID,
    (unsigned long long)(esp_timer_get_time() / 1000ULL),
    rssi_snap, ch_snap, mv_snap);

  for (int i = 0; i < N_SUBCARRIERS; i++) {
    pos += snprintf(json_buf + pos, sizeof(json_buf) - pos,
      i < N_SUBCARRIERS - 1 ? "%.2f," : "%.2f", amp_snap[i]);
  }

  pos += snprintf(json_buf + pos, sizeof(json_buf) - pos, "],\"p\":[");

  for (int i = 0; i < N_SUBCARRIERS; i++) {
    pos += snprintf(json_buf + pos, sizeof(json_buf) - pos,
      i < N_SUBCARRIERS - 1 ? "%.3f," : "%.3f", ph_snap[i]);
  }

  snprintf(json_buf + pos, sizeof(json_buf) - pos, "]}");

  mqtt.publish(topic_csi, json_buf);
}

// ── setup() ───────────────────────────────────────────────────────────────
void setup()
{
  Serial.begin(115200);
  delay(500);

  Serial.printf("\n=== RuView Node %s starting ===\n", NODE_ID);

  // Build topic strings
  snprintf(topic_csi,    sizeof(topic_csi),    "ruview/node/%s/csi",    NODE_ID);
  snprintf(topic_status, sizeof(topic_status), "ruview/node/%s/status", NODE_ID);

  connect_wifi();

  // MQTT — increase buffer to fit our ~800-byte JSON payload
  mqtt.setServer(MQTT_BROKER_IP, MQTT_PORT);
  mqtt.setBufferSize(950);
  connect_mqtt();

  setup_csi();

  Serial.printf("Publishing CSI at %d Hz to %s\n", PUBLISH_RATE_HZ, MQTT_BROKER_IP);
}

// ── loop() ────────────────────────────────────────────────────────────────
void loop()
{
  // Reconnect if dropped
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi lost — reconnecting...");
    esp_wifi_set_csi(false);
    connect_wifi();
    setup_csi();
  }
  if (!mqtt.connected()) {
    connect_mqtt();
  }
  mqtt.loop();

  // Publish at PUBLISH_RATE_HZ
  static unsigned long last_publish = 0;
  unsigned long now = millis();
  if (now - last_publish >= (1000 / PUBLISH_RATE_HZ)) {
    last_publish = now;
    if (csi_ready) {
      publish_csi();
    }
  }

  // Heartbeat status every 10 seconds
  static unsigned long last_status = 0;
  if (now - last_status >= 10000) {
    last_status = now;
    int8_t rssi = WiFi.RSSI();
    char status[96];
    snprintf(status, sizeof(status),
      "{\"node_id\":\"%s\",\"online\":true,\"csi_active\":true,\"rssi\":%d}",
      NODE_ID, rssi);
    mqtt.publish(topic_status, status, true);
    Serial.printf("[%s] RSSI=%d dBm  CSI ready=%s\n",
      NODE_ID, rssi, csi_ready ? "yes" : "no");
  }
}
