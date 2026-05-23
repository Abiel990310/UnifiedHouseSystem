#include "ota.h"
#include "config.h"
#include "mqtt_publish.h"

#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_https_ota.h"
#include "esp_http_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ota";

static void ota_task(void *arg)
{
    ESP_LOGI(TAG, "Checking for firmware update at %s", RUVIEW_OTA_URL);

    esp_http_client_config_t http_cfg = {
        .url            = RUVIEW_OTA_URL,
        .timeout_ms     = 10000,
        .keep_alive_enable = true,
    };

    esp_https_ota_config_t ota_cfg = {
        .http_config = &http_cfg,
    };

    esp_err_t ret = esp_https_ota(&ota_cfg);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA update successful. Restarting...");
        mqtt_publish_status(-1, false);
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
    } else if (ret == ESP_ERR_NOT_FOUND) {
        ESP_LOGI(TAG, "No new firmware available.");
    } else {
        ESP_LOGW(TAG, "OTA check failed: %s", esp_err_to_name(ret));
    }
    vTaskDelete(NULL);
}

void ota_check_and_update(void)
{
    xTaskCreate(ota_task, "ota_task", TASK_STACK_OTA, NULL, TASK_PRIO_OTA, NULL);
}
