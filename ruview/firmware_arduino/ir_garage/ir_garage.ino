/*
 * IR Capture + Garage Door Sender — ESP32-C3 Super Mini
 *
 * Step 1 — Capture: point garage remote at TSOP, press its button.
 *           Serial prints the code. Copy the >> send line.
 * Step 2 — Paste that line into sendGarage() below, reflash.
 * Step 3 — Press the BOOT button on the C3 to open/close the garage.
 *
 * Library:  IRremoteESP8266 by crankyoldgit
 * Board:    ESP32C3 Dev Module  (USB CDC On Boot → Enabled)
 *
 * Wiring:
 *   TSOP1136 OUT  →  GPIO 4    (receiver — for code capture)
 *   TSOP1136 GND  →  GND right pin per your datasheet
 *   TSOP1136 VCC  →  3.3V
 *
 *   IR LED anode  →  47Ω  →  VIN 5V
 *   IR LED cathode →  2N2222 Collector
 *   2N2222 Base   →  100Ω  →  GPIO 3
 *   2N2222 Emitter →  GND
 *
 *   BOOT button   →  GPIO 9 (built-in, active LOW)
 */

#include <IRrecv.h>
#include <IRsend.h>
#include <IRutils.h>

const uint16_t RECV_PIN   = 4;
const uint16_t SEND_PIN   = 3;
const uint8_t  BUTTON_PIN = 9;

IRrecv irrecv(RECV_PIN, 1024, 15, true);
IRsend irsend(SEND_PIN);
decode_results results;

// ── STEP 2: paste your captured line here ─────────────────────────────────────
void sendGarage() {
  // Examples — replace with your actual line from Serial output:
  //   irsend.sendNEC(0x20DF10EF, 32);
  //   irsend.sendSAMSUNG(0xE0E040BF, 32);
  //   irsend.sendRaw(rawData, sizeof(rawData) / sizeof(rawData[0]), 38);
  irsend.sendNEC(0x00000000, 32);   // ← replace this
}
// ─────────────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== Garage Remote ===");
  Serial.println("BOOT button  → send garage code");
  Serial.println("Point remote → TSOP to capture code\n");

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  irsend.begin();
  irrecv.enableIRIn();
}

bool lastBtn = HIGH;

void loop() {
  // BOOT button → send garage
  bool btn = digitalRead(BUTTON_PIN);
  if (btn == LOW && lastBtn == HIGH) {
    Serial.println("Sending...");
    sendGarage();
    Serial.println("Done.");
    delay(300);
  }
  lastBtn = btn;

  // TSOP receiver → print captured code
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
}
