#include "csi_capture.h"
#include "feature_extract.h"

#include "esp_wifi.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include <math.h>
#include <string.h>

static const char *TAG = "csi_capture";

/* Subcarrier index map: HT20 usable subcarriers (56 total).
   Indices are within the 64-point OFDM symbol.
   DC (index 0) and guard bands are excluded.
   Pilots at ±7, ±21 are included — they still carry channel info. */
static const int8_t CSI_SUBCARRIER_IDX[CSI_SUBCARRIER_COUNT] = {
    /* left side: -28 to -1 (stored as 36..63 in buf) */
    -28,-27,-26,-25,-24,-23,-22,-21,-20,-19,-18,-17,-16,
    -15,-14,-13,-12,-11,-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,
    /* right side: +1 to +28 (stored as 1..28 in buf) */
     1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13,
    14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
    27, 28
};

/* Smoothing ring buffers (one per subcarrier) */
static float s_amp_buf[CSI_SUBCARRIER_COUNT][CSI_SMOOTH_WINDOW];
static uint8_t s_buf_head = 0;
static uint32_t s_frame_count = 0;

static QueueHandle_t s_csi_queue = NULL;

/* ── Helpers ─────────────────────────────────────────────────────────────── */

static inline float _smooth(int sc, float new_val)
{
    s_amp_buf[sc][s_buf_head] = new_val;
    float sum = 0.0f;
    for (int i = 0; i < CSI_SMOOTH_WINDOW; i++) sum += s_amp_buf[sc][i];
    return sum / CSI_SMOOTH_WINDOW;
}

/* Map a logical subcarrier index (-28..+28) to a byte offset in info->buf.
   ESP32 CSI buf layout: buf[2*k], buf[2*k+1] = (imag, real) of subcarrier k.
   k=0..27 correspond to subcarriers +1..+28
   k=36..63 correspond to subcarriers -28..-1  */
static inline int _buf_index(int sc_idx)
{
    if (sc_idx > 0) return sc_idx - 1;          /* k = sc_idx - 1 */
    return 64 + sc_idx;                          /* k = 64 + sc_idx */
}

/* ── CSI callback ────────────────────────────────────────────────────────── */

static void IRAM_ATTR csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf || info->len < 128) return;
    if (!s_csi_queue) return;

    csi_frame_t frame;
    memset(&frame, 0, sizeof(frame));
    strncpy(frame.node_id, RUVIEW_NODE_ID, sizeof(frame.node_id) - 1);
    frame.timestamp_ms = (uint32_t)(esp_timer_get_time() / 1000ULL);
    frame.rssi         = info->rx_ctrl.rssi;
    frame.channel      = info->rx_ctrl.channel;
    frame.valid        = true;

    /* Extract amplitude and phase for each usable subcarrier */
    const int8_t *buf = info->buf;
    float amp_sum = 0.0f, amp_sq_sum = 0.0f;

    for (int i = 0; i < CSI_SUBCARRIER_COUNT; i++) {
        int k      = _buf_index(CSI_SUBCARRIER_IDX[i]);
        float imag = (float)buf[2 * k];
        float real = (float)buf[2 * k + 1];

        float amp   = sqrtf(real * real + imag * imag);
        float phase = atan2f(imag, real);

        float smooth_amp    = _smooth(i, amp);
        frame.amplitude[i]  = smooth_amp;
        frame.phase[i]      = phase;

        amp_sum    += smooth_amp;
        amp_sq_sum += smooth_amp * smooth_amp;
    }

    /* Motion variance: variance of amplitude across subcarriers */
    float mean    = amp_sum / CSI_SUBCARRIER_COUNT;
    frame.motion_variance = (amp_sq_sum / CSI_SUBCARRIER_COUNT) - (mean * mean);

    s_buf_head = (s_buf_head + 1) % CSI_SMOOTH_WINDOW;
    s_frame_count++;

    /* Drop oldest if queue full (non-blocking push) */
    if (xQueueSendFromISR(s_csi_queue, &frame, NULL) == errQUEUE_FULL) {
        csi_frame_t discard;
        xQueueReceiveFromISR(s_csi_queue, &discard, NULL);
        xQueueSendFromISR(s_csi_queue, &frame, NULL);
    }
}

/* ── Public API ──────────────────────────────────────────────────────────── */

void csi_capture_init(void *queue)
{
    s_csi_queue = (QueueHandle_t)queue;
    memset(s_amp_buf, 0, sizeof(s_amp_buf));
    s_buf_head   = 0;
    s_frame_count = 0;

    wifi_csi_config_t csi_cfg = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = false,   /* raw channel, no smoothing by hardware */
        .manu_scale        = false,
        .shift             = 0,
        .dump_ack_en       = true,    /* capture ACK frames too — more CSI samples */
    };

    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

    ESP_LOGI(TAG, "CSI capture started on node %s (channel %d)",
             RUVIEW_NODE_ID, csi_cfg.channel_filter_en);
}

void csi_capture_stop(void)
{
    esp_wifi_set_csi(false);
    esp_wifi_set_csi_rx_cb(NULL, NULL);
    ESP_LOGI(TAG, "CSI capture stopped. Total frames: %lu", (unsigned long)s_frame_count);
}
