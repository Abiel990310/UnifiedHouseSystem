#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_wifi_types.h"
#include "config.h"

/*
 * CSI capture module.
 *
 * Registers the WiFi CSI callback, processes raw int8 IQ data into
 * float amplitude/phase arrays, and pushes csi_frame_t onto a FreeRTOS
 * queue that the MQTT publish task drains.
 */

typedef struct {
    char     node_id[16];
    uint32_t timestamp_ms;        /* esp_timer_get_time() / 1000 */
    float    amplitude[CSI_SUBCARRIER_COUNT];
    float    phase[CSI_SUBCARRIER_COUNT];
    float    motion_variance;     /* mean variance of amplitude across subcarriers */
    int8_t   rssi;
    uint8_t  channel;
    bool     valid;
} csi_frame_t;

/**
 * Initialize CSI capture.
 *
 * Must be called after esp_wifi_start() with the station connected.
 * @param queue  FreeRTOS queue handle where csi_frame_t items are pushed.
 */
void csi_capture_init(void *queue);

/** Stop CSI capture (deregisters callback). */
void csi_capture_stop(void);
