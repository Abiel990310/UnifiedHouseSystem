"""
Vitals extraction from long CSI time series using FFT.

Breathing and heart rate are extracted by finding dominant frequency
peaks in the CSI amplitude time series within physiological ranges.
"""

import numpy as np
import logging
from collections import deque

logger = logging.getLogger(__name__)

N_SUBCARRIERS = 56
CSI_RATE_HZ   = 10   # frames per second


class VitalsExtractor:
    """
    Maintains a long sliding window of motion-sensitive CSI amplitudes and
    extracts breathing + heart rate via FFT peak picking.
    """

    def __init__(
        self,
        breathing_window: int = 300,   # 30s at 10Hz
        heart_window: int = 600,        # 60s at 10Hz
        breathing_range_hz: tuple = (0.1, 0.5),
        heart_range_hz: tuple = (0.8, 3.0),
        sample_rate_hz: float = CSI_RATE_HZ,
    ) -> None:
        self._br_win   = breathing_window
        self._hr_win   = heart_window
        self._br_range = breathing_range_hz
        self._hr_range = heart_range_hz
        self._fs       = sample_rate_hz

        # Store mean amplitude variance across nodes (scalar per frame)
        self._motion_series: deque[float] = deque(maxlen=heart_window)

    def update(self, motion_window: np.ndarray) -> None:
        """
        Ingest a batch of motion variance values.
        motion_window: [T, N_nodes] from SystemState.get_motion_window()
        """
        # Use mean across nodes as the vitals signal
        for row in motion_window:
            self._motion_series.append(float(row.mean()))

    def extract(self) -> dict:
        """
        Run FFT-based peak picking and return vitals.

        Returns dict: breathing_rate (bpm), heart_rate (bpm),
                      breathing_confidence, heart_confidence
        """
        series = np.array(self._motion_series, dtype=np.float32)
        if len(series) < self._br_win:
            return {
                "breathing_rate": 0.0, "heart_rate": 0.0,
                "breathing_confidence": 0.0, "heart_confidence": 0.0,
            }

        # Detrend (remove mean drift)
        series = series - series.mean()

        # ── Breathing rate (use last 30s) ──────────────────────────────────
        br_sig   = series[-self._br_win:]
        br_rate, br_conf = self._fft_peak(br_sig, self._br_range[0], self._br_range[1])

        # ── Heart rate (use full window) ───────────────────────────────────
        hr_sig = series[-min(len(series), self._hr_win):]
        # Bandpass: subtract breathing component first
        hr_sig = self._bandpass_subtract(hr_sig, 0.0, self._hr_range[0])
        hr_rate, hr_conf = self._fft_peak(hr_sig, self._hr_range[0], self._hr_range[1])

        return {
            "breathing_rate":      round(br_rate * 60.0, 1),  # Hz → bpm
            "heart_rate":          round(hr_rate * 60.0, 1),
            "breathing_confidence": round(br_conf, 3),
            "heart_confidence":     round(hr_conf, 3),
        }

    def _fft_peak(self, signal: np.ndarray, f_low: float, f_high: float) -> tuple[float, float]:
        """Return (dominant_frequency_hz, confidence_0_1) within [f_low, f_high]."""
        N      = len(signal)
        window = np.hanning(N)
        fft    = np.abs(np.fft.rfft(signal * window))
        freqs  = np.fft.rfftfreq(N, d=1.0 / self._fs)

        mask    = (freqs >= f_low) & (freqs <= f_high)
        if not mask.any():
            return 0.0, 0.0

        fft_band = fft[mask]
        freqs_band = freqs[mask]

        peak_idx  = int(np.argmax(fft_band))
        peak_freq = float(freqs_band[peak_idx])
        peak_amp  = float(fft_band[peak_idx])

        # Confidence: ratio of peak amplitude to band total
        band_total = float(fft_band.sum()) + 1e-8
        confidence = float(np.clip(peak_amp / band_total, 0.0, 1.0))

        return peak_freq, confidence

    def _bandpass_subtract(self, signal: np.ndarray, f_low: float, f_high: float) -> np.ndarray:
        """Remove frequency components below f_high (crude high-pass via FFT zero-out)."""
        N      = len(signal)
        freqs  = np.fft.rfftfreq(N, d=1.0 / self._fs)
        fft    = np.fft.rfft(signal)
        fft[freqs < f_high] = 0.0
        return np.fft.irfft(fft, n=N).astype(np.float32)
