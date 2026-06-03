/*
 * IR Capture — one-shot code dumper for TSOP1136 on ESP32-C3 Super Mini
 *
 * Library: IRremoteESP8266 by crankyoldgit  (Arduino Library Manager)
 * Board:   ESP32C3 Dev Module
 *
 * Wiring:
 *   TSOP1136 OUT  →  GPIO 2
 *   TSOP1136 GND  →  GND
 *   TSOP1136 VCC  →  3.3V
 *
 * Usage:
 *   1. Flash this sketch to the C3.
 *   2. Open Serial Monitor at 115200.
 *   3. Point your Panasonic remote at the TSOP and press the light button.
 *   4. Copy the "sendPanasonic" or "sendRaw" line printed to Serial.
 *   5. Paste the code into ir_node/config.h as LIGHT_ON / LIGHT_OFF.
 */

#include <IRrecv.h>
#include <IRutils.h>

const uint16_t RECV_PIN     = 4;
const uint16_t BUFFER_SIZE  = 1024;
const uint8_t  RECV_TIMEOUT = 15;

IRrecv irrecv(RECV_PIN, BUFFER_SIZE, RECV_TIMEOUT, true);
decode_results results;

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== IR Capture ready ===");
  Serial.println("Point remote at TSOP and press the button.\n");
  irrecv.enableIRIn();
}

void loop() {
  if (!irrecv.decode(&results)) return;

  Serial.println("─────────────────────────────");
  Serial.printf("Protocol : %s\n", typeToString(results.decode_type).c_str());
  Serial.printf("Bits     : %d\n", results.bits);
  Serial.printf("Value    : 0x%llX\n", results.value);

  // Print the ready-to-use send call
  if (results.decode_type == PANASONIC) {
    uint64_t addr = results.address;
    uint64_t data = results.value;
    Serial.printf("\n>> sendPanasonic(0x%04llX, 0x%llX, %d)\n", addr, data, results.bits);
    Serial.println("Copy the line above into config.h as LIGHT_ON or LIGHT_OFF.");
  } else {
    // Unknown / other protocol — print raw timing so you can use sendRaw()
    Serial.println("\nNot recognised as Panasonic. Raw timings (µs):");
    Serial.print("uint16_t rawData[] = {");
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
