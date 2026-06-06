/*
 * Garage Door IR Remote — ESP32-C3 Super Mini
 *
 * Set CAPTURE_MODE 1 to capture your garage remote code via TSOP.
 * Set CAPTURE_MODE 0 for normal 24/7 use — CPU light-sleeps until button press.
 *
 * Library:  IRremoteESP8266 by crankyoldgit
 * Board:    ESP32C3 Dev Module  (USB CDC On Boot → Enabled)
 *
 * Wiring:
 *   TSOP1136 OUT  →  GPIO 4    (only active in CAPTURE_MODE)
 *   TSOP1136 GND  →  GND (right pin per your datasheet)
 *   TSOP1136 VCC  →  3.3V
 *
 *   IR LED anode  →  47Ω  →  VIN 5V
 *   IR LED cathode →  2N2222 Collector
 *   2N2222 Base   →  100Ω  →  GPIO 3
 *   2N2222 Emitter →  GND
 *
 *   Button leg 1  →  GPIO 6
 *   Button leg 2  →  GND  (diagonal corner of the 4-pin button)
 */

// ── Set to 1 to capture code, 0 for efficient 24/7 running ───────────────────
#define CAPTURE_MODE 1

#include <IRsend.h>
#include <IRutils.h>
#include "esp_sleep.h"
#if CAPTURE_MODE
#include <IRrecv.h>
#endif

#include <WiFi.h>   // only to disable it

const uint16_t SEND_PIN   = 3;
const uint8_t  BUTTON_PIN = 6;   // external button: one leg → GPIO 6, other leg → GND
#if CAPTURE_MODE
const uint16_t RECV_PIN   = 4;
IRrecv irrecv(RECV_PIN, 1024, 15, true);
decode_results results;
#endif

IRsend irsend(SEND_PIN);

// ── FILL THIS IN after capturing ──────────────────────────────────────────────
void sendGarage() {
  // Paste your captured line here. Examples:
  //   irsend.sendNEC(0x20DF10EF, 32);
  //   irsend.sendSAMSUNG(0xE0E040BF, 32);
  //   irsend.sendRaw(rawData, sizeof(rawData)/sizeof(rawData[0]), 38);
  irsend.sendNEC(0x00000000, 32);   // ← replace this
}
// ─────────────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(2000);

  setCpuFrequencyMhz(80);   // halve clock — plenty for IR, saves power
  WiFi.mode(WIFI_OFF);      // kill radio — saves ~20mA
  btStop();                 // kill BT

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  irsend.begin();

#if CAPTURE_MODE
  Serial.println("\n=== CAPTURE MODE ===");
  Serial.println("Point garage remote at TSOP and press its button.");
  Serial.println("Copy the >> send line, paste into sendGarage(), set CAPTURE_MODE 0, reflash.\n");
  irrecv.enableIRIn();
#else
  Serial.println("\n=== Garage Remote ready ===");
  Serial.println("Press BOOT to open/close garage. Sleeping between presses.\n");
  gpio_wakeup_enable((gpio_num_t)BUTTON_PIN, GPIO_INTR_LOW_LEVEL);
  esp_sleep_enable_gpio_wakeup();
#endif
}

void loop() {
#if CAPTURE_MODE
  // ── Capture mode: print any received IR code ────────────────────────────────
  if (!irrecv.decode(&results)) return;

  Serial.println("─────────────────────────────");
  Serial.printf("Protocol : %s\n", typeToString(results.decode_type).c_str());
  Serial.printf("Bits     : %d\n", results.bits);
  Serial.printf("Value    : 0x%llX\n", results.value);

  if (results.decode_type != UNKNOWN) {
    Serial.printf("\n>> irsend.send%s(0x%llX, %d);\n",
      typeToString(results.decode_type).c_str(),
      results.value, results.bits);
  } else {
    Serial.print("\nuint16_t rawData[] = {");
    for (uint16_t i = 1; i < results.rawlen; i++) {
      Serial.printf("%d", results.rawbuf[i] * RAWTICK);
      if (i < results.rawlen - 1) Serial.print(", ");
    }
    Serial.println("};");
    Serial.printf(">> irsend.sendRaw(rawData, %d, 38);\n", results.rawlen - 1);
  }
  Serial.println("─────────────────────────────\n");
  irrecv.resume();

#else
  // ── Running mode: light sleep until button pressed ──────────────────────────
  esp_light_sleep_start();   // ~0.8mA while waiting

  if (digitalRead(BUTTON_PIN) == LOW) {
    Serial.println("Sending...");
    sendGarage();
    Serial.println("Done.");
    while (digitalRead(BUTTON_PIN) == LOW) delay(10);  // wait for release
    delay(200);                                         // debounce
  }
#endif
}
