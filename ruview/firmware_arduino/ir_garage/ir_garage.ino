/*
 * Garage Door Remote — ESP32-C3 Super Mini
 *
 * The LEADER LD-668 uses a rolling/hopping code — IR replay is impossible.
 * A 2N2222A transistor is wired across the 叫車 button contacts inside the
 * remote.  A GPIO pulse makes the remote press itself, generating the correct
 * rolling code from its own firmware.
 *
 * Set CAPTURE_MODE 1 only to sniff other IR signals via TSOP (diagnostic).
 * Set CAPTURE_MODE 0 for normal 24/7 use — CPU light-sleeps until button press.
 *
 * Library:  IRremoteESP8266 by crankyoldgit  (only needed for CAPTURE_MODE)
 * Board:    ESP32C3 Dev Module  (USB CDC On Boot → Enabled)
 *
 * Wiring — transistor across remote button (rolling code approach):
 *   2N2222A Base      →  1kΩ  →  GPIO 3
 *   2N2222A Collector →  Remote 叫車 button pad A  (solder thin wire to pad)
 *   2N2222A Emitter   →  Remote 叫車 button pad B  (solder thin wire to pad)
 *   Share GND between ESP32 and the remote's battery negative terminal.
 *
 * Wiring — TSOP (CAPTURE_MODE only):
 *   TSOP OUT  →  GPIO 4
 *   TSOP GND  →  GND (middle pin per datasheet)
 *   TSOP VCC  →  3.3V
 *
 * Wiring — trigger button:
 *   Button leg 1  →  GPIO 6
 *   Button leg 2  →  GND  (diagonal corner of 4-pin button)
 */

// ── Set to 1 to sniff IR codes, 0 for efficient 24/7 running ─────────────────
#define CAPTURE_MODE 0

#include "esp_sleep.h"
#if CAPTURE_MODE
#include <IRrecv.h>
#include <IRutils.h>
#endif

#include <WiFi.h>   // only to disable it

const uint8_t REMOTE_PIN = 3;   // controls 2N2222A across remote button pads
const uint8_t BUTTON_PIN = 6;   // external trigger: one leg → GPIO 6, other → GND

#if CAPTURE_MODE
const uint16_t RECV_PIN = 4;
IRrecv irrecv(RECV_PIN, 1024, 15, true);
decode_results results;
#endif

// ── Simulates a physical button press on the LD-668 remote ───────────────────
void sendGarage() {
  digitalWrite(REMOTE_PIN, HIGH);
  delay(120);                    // hold 120ms — same as a natural press
  digitalWrite(REMOTE_PIN, LOW);
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  setCpuFrequencyMhz(80);   // halve clock — saves power
  WiFi.mode(WIFI_OFF);      // kill radio — saves ~20mA
  btStop();                 // kill BT

  pinMode(REMOTE_PIN, OUTPUT);
  digitalWrite(REMOTE_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

#if CAPTURE_MODE
  Serial.println("\n=== CAPTURE MODE ===");
  Serial.println("Point any remote at TSOP and press its button.");
  irrecv.enableIRIn();
#else
  Serial.println("\n=== Garage Remote ready ===");
  Serial.println("Press button on GPIO 6 to trigger remote. Sleeping between presses.\n");
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
    Serial.println("Pressing remote...");
    sendGarage();
    Serial.println("Done.");
    while (digitalRead(BUTTON_PIN) == LOW) delay(10);  // wait for release
    delay(200);                                         // debounce
  }
#endif
}
