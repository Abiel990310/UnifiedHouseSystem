#pragma once

/*
 * RuView Node — compile-time configuration.
 *
 * Values here can be overridden by Kconfig (menuconfig) — see Kconfig.projbuild.
 * Prefer using `idf.py menuconfig` so credentials stay out of source control.
 */

/* ── Node identity ─────────────────────────────────────────────────────────── */
#ifndef CONFIG_RUVIEW_NODE_ID
#define RUVIEW_NODE_ID          "node_1"
#else
#define RUVIEW_NODE_ID          CONFIG_RUVIEW_NODE_ID
#endif

/* ── WiFi ──────────────────────────────────────────────────────────────────── */
#ifndef CONFIG_RUVIEW_WIFI_SSID
#define RUVIEW_WIFI_SSID        "蝦家"
#else
#define RUVIEW_WIFI_SSID        CONFIG_RUVIEW_WIFI_SSID
#endif

#ifndef CONFIG_RUVIEW_WIFI_PASSWORD
#define RUVIEW_WIFI_PASSWORD    ""
#else
#define RUVIEW_WIFI_PASSWORD    CONFIG_RUVIEW_WIFI_PASSWORD
#endif

#define RUVIEW_WIFI_MAX_RETRY   10

/* ── MQTT ──────────────────────────────────────────────────────────────────── */
#ifndef CONFIG_RUVIEW_MQTT_BROKER_IP
#define RUVIEW_MQTT_BROKER_IP   "192.168.1.100"
#else
#define RUVIEW_MQTT_BROKER_IP   CONFIG_RUVIEW_MQTT_BROKER_IP
#endif

#ifndef CONFIG_RUVIEW_MQTT_BROKER_PORT
#define RUVIEW_MQTT_BROKER_PORT 1883
#else
#define RUVIEW_MQTT_BROKER_PORT CONFIG_RUVIEW_MQTT_BROKER_PORT
#endif

/* MQTT topic templates — filled with RUVIEW_NODE_ID at runtime */
#define RUVIEW_TOPIC_CSI        "ruview/node/%s/csi"
#define RUVIEW_TOPIC_STATUS     "ruview/node/%s/status"

/* ── CSI capture ───────────────────────────────────────────────────────────── */
/* Number of usable subcarriers in HT20 mode (after removing pilots/DC) */
#define CSI_SUBCARRIER_COUNT    56

/* Sliding average window for amplitude smoothing */
#define CSI_SMOOTH_WINDOW       5

/* Publish rate: number of CSI vectors sent per second */
#ifndef CONFIG_RUVIEW_CSI_PUBLISH_RATE_HZ
#define RUVIEW_PUBLISH_RATE_HZ  10
#else
#define RUVIEW_PUBLISH_RATE_HZ  CONFIG_RUVIEW_CSI_PUBLISH_RATE_HZ
#endif

#define RUVIEW_PUBLISH_PERIOD_MS (1000 / RUVIEW_PUBLISH_RATE_HZ)

/* ── OTA ───────────────────────────────────────────────────────────────────── */
#ifndef CONFIG_RUVIEW_OTA_SERVER_URL
#define RUVIEW_OTA_URL          "http://192.168.1.100:8080/api/v1/ota/firmware.bin"
#else
#define RUVIEW_OTA_URL          CONFIG_RUVIEW_OTA_SERVER_URL
#endif

/* Check for OTA updates every N minutes */
#define RUVIEW_OTA_CHECK_INTERVAL_MIN 60

/* ── Task priorities ───────────────────────────────────────────────────────── */
#define TASK_PRIO_CSI           (configMAX_PRIORITIES - 2)
#define TASK_PRIO_MQTT_PUBLISH  (configMAX_PRIORITIES - 3)
#define TASK_PRIO_OTA           (tskIDLE_PRIORITY + 1)

#define TASK_STACK_CSI          4096
#define TASK_STACK_MQTT         6144
#define TASK_STACK_OTA          8192

/* ── Queue sizes ───────────────────────────────────────────────────────────── */
#define CSI_QUEUE_DEPTH         8
