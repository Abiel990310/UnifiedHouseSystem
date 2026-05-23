#include "feature_extract.h"
#include <math.h>
#include <float.h>

void feature_compute_stats(const float *amplitude, int n, csi_stats_t *out)
{
    float sum = 0.0f, sq_sum = 0.0f;
    float mx = -FLT_MAX, mn = FLT_MAX;

    for (int i = 0; i < n; i++) {
        float a = amplitude[i];
        sum    += a;
        sq_sum += a * a;
        if (a > mx) mx = a;
        if (a < mn) mn = a;
    }

    float mean      = sum / (float)n;
    out->mean_amplitude  = mean;
    out->variance        = (sq_sum / (float)n) - (mean * mean);
    out->max_amplitude   = mx;
    out->min_amplitude   = mn;
    out->spectral_energy = sq_sum;
}

float feature_motion_delta(const float *prev_amp, const float *curr_amp, int n)
{
    float diff_sq = 0.0f;
    for (int i = 0; i < n; i++) {
        float d = curr_amp[i] - prev_amp[i];
        diff_sq += d * d;
    }
    return sqrtf(diff_sq / (float)n);
}
