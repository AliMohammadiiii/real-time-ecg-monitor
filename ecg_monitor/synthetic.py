from __future__ import annotations

import numpy as np


def synthetic_ecg(
    duration_s: float,
    sampling_rate: float,
    heart_rate_bpm: float = 72.0,
    noise_std: float = 0.015,
    seed: int = 7,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate a simple ECG-like signal and exact R locations for tests."""
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, duration_s, 1.0 / sampling_rate)
    rr = 60.0 / heart_rate_bpm
    r_times = np.arange(0.6, duration_s - 0.4, rr)
    signal = np.zeros_like(t)

    def add_wave(center: float, amp: float, width: float) -> None:
        nonlocal signal
        signal += amp * np.exp(-0.5 * ((t - center) / width) ** 2)

    for r_time in r_times:
        add_wave(r_time - 0.18, 0.10, 0.035)
        add_wave(r_time - 0.035, -0.16, 0.012)
        add_wave(r_time, 1.00, 0.014)
        add_wave(r_time + 0.045, -0.22, 0.016)
        add_wave(r_time + 0.26, 0.32, 0.060)

    baseline = 0.07 * np.sin(2.0 * np.pi * 0.33 * t)
    powerline = 0.015 * np.sin(2.0 * np.pi * 50.0 * t)
    noise = rng.normal(0.0, noise_std, size=t.size)
    return signal + baseline + powerline + noise, np.asarray(np.round(r_times * sampling_rate), dtype=int)
