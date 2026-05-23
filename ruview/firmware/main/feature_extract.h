#pragma once

#include "csi_capture.h"
#include <stdint.h>

/*
 * Feature extraction helpers.
 *
 * Compute signal statistics used by the hub's RuVector model
 * to detect people, estimate pose, and extract vitals.
 */

typedef struct {
    float mean_amplitude;
    float variance;
    float max_amplitude;
    float min_amplitude;
    float spectral_energy;   /* sum of squared amplitudes (Parseval proxy) */
} csi_stats_t;

/** Compute statistics over an amplitude array. */
void feature_compute_stats(const float *amplitude, int n, csi_stats_t *out);

/** Compute amplitude differential between two consecutive frames (motion delta). */
float feature_motion_delta(const float *prev_amp, const float *curr_amp, int n);
