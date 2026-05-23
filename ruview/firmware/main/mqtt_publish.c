#include "mqtt_publish.h"
#include "config.h"

#include "esp_log.h"
#include "mqtt_client.h"
#include "cJSON.h"

#include <stdio.h>
#include <string.h>

static const char *TAG = "mqtt_publish";

static esp_mqtt_client_handle_t s_client = NULL;
static volatile bool s_connected = false;

/* Pre-built topic strings */
static char s_topic_csi[64];
static char s_topic_status[64];

/* ── Event handler ───────────────────────────────────────────────────────── */

static void mqtt_event_handler(void *handler_args, esp_event_base_t base,
                                int32_t event_id, void *event_data)
{
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)event_data;
    switch ((esp_mqtt_event_id_t)event_id) {
        case MQTT_EVENT_CONNECTED:
            s_connected = true;
            ESP_LOGI(TAG, "Connected to broker %s:%d", RUVIEW_MQTT_BROKER_IP, RUVIEW_MQTT_BROKER_PORT);
            mqtt_publish_status(-1, false);
            break;
        case MQTT_EVENT_DISCONNECTED:
            s_connected = false;
            ESP_LOGW(TAG, "Disconnected from broker — will auto-reconnect");
            break;
        case MQTT_EVENT_ERROR:
            ESP_LOGE(TAG, "MQTT error");
            break;
        default:
            break;
    }
}

/* ── Public API ──────────────────────────────────────────────────────────── */

void mqtt_publish_init(void)
{
    snprintf(s_topic_csi,    sizeof(s_topic_csi),    RUVIEW_TOPIC_CSI,    RUVIEW_NODE_ID);
    snprintf(s_topic_status, sizeof(s_topic_status), RUVIEW_TOPIC_STATUS, RUVIEW_NODE_ID);

    char broker_uri[64];
    snprintf(broker_uri, sizeof(broker_uri), "mqtt://%s:%d",
             RUVIEW_MQTT_BROKER_IP, RUVIEW_MQTT_BROKER_PORT);

    esp_mqtt_client_config_t cfg = {
        .broker.address.uri          = broker_uri,
        .credentials.client_id       = RUVIEW_NODE_ID,
        .network.reconnect_timeout_ms = 5000,
        .network.timeout_ms           = 10000,
        .session.keepalive            = 30,
        .buffer.size                  = 4096,
    };

    s_client = esp_mqtt_client_init(&cfg);
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(s_client);
    ESP_LOGI(TAG, "MQTT client started → %s", broker_uri);
}

void mqtt_publish_deinit(void)
{
    if (s_client) {
        esp_mqtt_client_stop(s_client);
        esp_mqtt_client_destroy(s_client);
        s_client = NULL;
    }
}

void mqtt_publish_csi(const csi_frame_t *frame)
{
    if (!s_connected || !s_client || !frame->valid) return;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "n",  frame->node_id);
    cJSON_AddNumberToObject(root, "t",  (double)frame->timestamp_ms);
    cJSON_AddNumberToObject(root, "r",  frame->rssi);
    cJSON_AddNumberToObject(root, "ch", frame->channel);
    cJSON_AddNumberToObject(root, "mv", (double)frame->motion_variance);

    /* Amplitude array — quantize to 3 decimal places to save bytes */
    cJSON *amp = cJSON_CreateArray();
    for (int i = 0; i < CSI_SUBCARRIER_COUNT; i++) {
        cJSON_AddItemToArray(amp, cJSON_CreateNumber(
            (double)((int)(frame->amplitude[i] * 100 + 0.5f)) / 100.0));
    }
    cJSON_AddItemToObject(root, "a", amp);

    /* Phase array */
    cJSON *phs = cJSON_CreateArray();
    for (int i = 0; i < CSI_SUBCARRIER_COUNT; i++) {
        cJSON_AddItemToArray(phs, cJSON_CreateNumber(
            (double)((int)(frame->phase[i] * 1000 + 0.5f)) / 1000.0));
    }
    cJSON_AddItemToObject(root, "p", phs);

    char *json_str = cJSON_PrintUnformatted(root);
    if (json_str) {
        esp_mqtt_client_publish(s_client, s_topic_csi, json_str, 0, 0, 0);
        cJSON_free(json_str);
    }
    cJSON_Delete(root);
}

void mqtt_publish_status(int8_t rssi, bool csi_active)
{
    if (!s_client) return;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "node_id",    RUVIEW_NODE_ID);
    cJSON_AddBoolToObject(root,   "online",      true);
    cJSON_AddBoolToObject(root,   "csi_active",  csi_active);
    cJSON_AddNumberToObject(root, "rssi",        rssi);

    char *json_str = cJSON_PrintUnformatted(root);
    if (json_str) {
        /* Retain=1 so Pi gets current state on reconnect */
        esp_mqtt_client_publish(s_client, s_topic_status, json_str, 0, 1, 1);
        cJSON_free(json_str);
    }
    cJSON_Delete(root);
}

bool mqtt_is_connected(void)
{
    return s_connected;
}
