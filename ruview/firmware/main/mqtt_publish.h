#pragma once

#include "csi_capture.h"
#include "esp_mqtt_client.h"

/*
 * MQTT publish module.
 *
 * Manages the MQTT client lifecycle and serializes csi_frame_t
 * structs to JSON for publication to the hub broker.
 */

/** Initialize and start the MQTT client. Call after WiFi is connected. */
void mqtt_publish_init(void);

/** Stop the MQTT client. */
void mqtt_publish_deinit(void);

/**
 * Serialize a CSI frame to JSON and publish it.
 * Topic: ruview/node/<NODE_ID>/csi
 * QoS 0 (fire-and-forget, optimized for throughput).
 */
void mqtt_publish_csi(const csi_frame_t *frame);

/** Publish a heartbeat status message (called every 10s). */
void mqtt_publish_status(int8_t rssi, bool csi_active);

/** Returns true if the MQTT client is currently connected. */
bool mqtt_is_connected(void);
