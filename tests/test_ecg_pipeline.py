import unittest

import numpy as np

from ecg_monitor import assess_rhythm, assess_signal_quality, delineate_pqrst, detect_r_peaks, extract_features, preprocess_ecg
from ecg_monitor.features import ECGFeatures
from ecg_monitor.serial_reader import SerialPacketTracker, adc_to_volts, packet_checksum, parse_sample_line, parse_sample_line_safe
from ecg_monitor.synthetic import synthetic_ecg


class ECGPipelineTests(unittest.TestCase):
    def test_detects_synthetic_r_peaks(self):
        fs = 250.0
        signal, expected = synthetic_ecg(duration_s=10.0, sampling_rate=fs, heart_rate_bpm=72.0)
        detected = detect_r_peaks(signal, fs)
        self.assertGreaterEqual(detected.size, expected.size - 1)
        tolerance = int(0.08 * fs)
        matched = 0
        for peak in expected:
            if np.min(np.abs(detected - peak)) <= tolerance:
                matched += 1
        self.assertGreaterEqual(matched, expected.size - 1)

    def test_delineates_markers_and_features(self):
        fs = 250.0
        signal, _ = synthetic_ecg(duration_s=8.0, sampling_rate=fs, heart_rate_bpm=75.0)
        markers = delineate_pqrst(signal, fs)
        features = extract_features(signal, fs, markers)
        self.assertGreaterEqual(len(markers), 8)
        self.assertIsNotNone(features.mean_hr_bpm)
        self.assertAlmostEqual(features.mean_hr_bpm, 75.0, delta=8.0)
        self.assertGreater(features.signal_quality, 0.2)

    def test_filter_branches_preserve_length(self):
        fs = 250.0
        signal, _ = synthetic_ecg(duration_s=4.0, sampling_rate=fs)
        filtered = preprocess_ecg(signal, fs)
        self.assertEqual(filtered.display.size, signal.size)
        self.assertEqual(filtered.qrs.size, signal.size)

    def test_flatline_produces_no_valid_beats(self):
        detected = detect_r_peaks(np.ones(500), 250.0)
        self.assertEqual(detected.size, 0)

    def test_noisy_signal_still_detects_some_r_peaks(self):
        fs = 250.0
        signal, _ = synthetic_ecg(duration_s=8.0, sampling_rate=fs, noise_std=0.05)
        detected = detect_r_peaks(signal, fs)
        self.assertGreaterEqual(detected.size, 6)

    def test_fast_rhythm_does_not_double_detect_excessively(self):
        fs = 250.0
        signal, expected = synthetic_ecg(duration_s=6.0, sampling_rate=fs, heart_rate_bpm=130.0)
        detected = detect_r_peaks(signal, fs)
        self.assertLessEqual(detected.size, expected.size + 1)

    def test_t_wave_like_secondary_peaks_are_suppressed(self):
        fs = 250.0
        n = int(8 * fs)
        idx = np.arange(n)
        signal = np.zeros(n)
        expected = np.arange(int(0.6 * fs), n - int(0.5 * fs), int(1.0 * fs))
        for center in expected:
            signal += 1.0 * np.exp(-0.5 * ((idx - center) / 2.0) ** 2)
            signal += 0.55 * np.exp(-0.5 * ((idx - (center + int(0.32 * fs))) / 7.0) ** 2)
        signal += 0.015 * np.sin(2 * np.pi * 0.5 * idx / fs)

        detected = detect_r_peaks(signal, fs)

        self.assertLessEqual(detected.size, expected.size + 1)
        tolerance = int(0.08 * fs)
        matched = 0
        for peak in expected:
            if np.min(np.abs(detected - peak)) <= tolerance:
                matched += 1
        self.assertGreaterEqual(matched, expected.size - 1)

    def test_r_peaks_are_refined_to_visible_adc_spikes(self):
        fs = 250.0
        n = int(6 * fs)
        t = np.arange(n) / fs
        signal = np.full(n, 517.0)
        expected = np.arange(int(0.5 * fs), n - int(0.5 * fs), int(0.48 * fs))
        idx = np.arange(n)
        for center in expected:
            signal += -45 * np.exp(-0.5 * ((idx - (center - 5)) / 2.0) ** 2)
            signal += 260 * np.exp(-0.5 * ((idx - center) / 1.2) ** 2)
            signal += -55 * np.exp(-0.5 * ((idx - (center + 6)) / 2.5) ** 2)
            signal += 80 * np.exp(-0.5 * ((idx - (center + 42)) / 9.0) ** 2)
        signal += 4 * np.sin(2 * np.pi * 0.4 * t)

        detected = detect_r_peaks(signal, fs)

        self.assertEqual(detected.size, expected.size)
        for peak in detected:
            local = signal[max(0, peak - 5):min(signal.size, peak + 6)]
            self.assertEqual(signal[peak], np.max(local))

    def test_low_sqi_suppresses_pt_markers(self):
        fs = 250.0
        signal, _ = synthetic_ecg(duration_s=6.0, sampling_rate=fs)
        r_peaks = detect_r_peaks(signal, fs)
        markers = delineate_pqrst(signal, fs, r_peaks, sqi_level="poor")
        self.assertTrue(all(m.p is None and m.t is None for m in markers))

    def test_rule_based_assessment_flags_tachycardia(self):
        fs = 250.0
        signal, _ = synthetic_ecg(duration_s=8.0, sampling_rate=fs, heart_rate_bpm=125.0)
        markers = delineate_pqrst(signal, fs)
        features = extract_features(signal, fs, markers)
        assessment = assess_rhythm(features)
        self.assertIn("tachycardia", " ".join(assessment.reasons).lower())

    def test_sqi_suppresses_flatline_analysis(self):
        assessment = assess_signal_quality(np.ones(250), lead_off=False)
        self.assertEqual(assessment.level, "unreliable")
        self.assertFalse(assessment.rate_allowed)

    def test_clean_synthetic_sqi_is_usable(self):
        fs = 250.0
        signal, _ = synthetic_ecg(duration_s=8.0, sampling_rate=fs)
        r_peaks = detect_r_peaks(signal, fs)
        assessment = assess_signal_quality(signal, r_peaks=r_peaks)
        self.assertIn(assessment.level, {"usable_for_rate_qrs", "usable_for_pqrst"})

    def test_lead_off_and_clipping_are_unreliable(self):
        lead = assess_signal_quality(np.arange(250), lead_off=True)
        clip = assess_signal_quality(np.full(250, 1023), adc_min=0, adc_max=1023)
        self.assertEqual(lead.level, "unreliable")
        self.assertEqual(clip.level, "unreliable")

    def test_packet_loss_reduces_sqi(self):
        signal, _ = synthetic_ecg(duration_s=5.0, sampling_rate=250.0)
        assessment = assess_signal_quality(signal, packet_loss_rate=0.08)
        self.assertEqual(assessment.level, "unreliable")

    def test_warning_logic_cases(self):
        brady = ECGFeatures(45.0, np.asarray([1.4, 1.3, 1.4]), 0.03, np.asarray([0.08]), np.asarray([]), 0.8)
        tachy = ECGFeatures(125.0, np.asarray([0.48, 0.47, 0.49]), 0.02, np.asarray([0.08]), np.asarray([]), 0.8)
        irregular = ECGFeatures(80.0, np.asarray([0.7, 1.2, 0.6, 1.1]), 0.30, np.asarray([0.08]), np.asarray([]), 0.8)
        wide = ECGFeatures(75.0, np.asarray([0.8, 0.8, 0.8]), 0.01, np.asarray([0.14, 0.13, 0.08]), np.asarray([]), 0.8)
        poor = ECGFeatures(125.0, np.asarray([0.48, 0.47, 0.49]), 0.02, np.asarray([0.14]), np.asarray([]), 0.1)
        self.assertIn("bradycardia", " ".join(assess_rhythm(brady).reasons).lower())
        self.assertIn("tachycardia", " ".join(assess_rhythm(tachy).reasons).lower())
        self.assertIn("irregular", " ".join(assess_rhythm(irregular).reasons).lower())
        self.assertIn("wide", " ".join(assess_rhythm(wide).reasons).lower())
        self.assertEqual(assess_rhythm(poor).label, "Poor signal / unreliable analysis")

    def test_serial_parsing(self):
        sample = parse_sample_line("S,42,123456,512,1,0")
        self.assertEqual(sample.sequence, 42)
        self.assertEqual(sample.timestamp_us, 123456)
        self.assertEqual(sample.adc_value, 512)
        self.assertTrue(sample.lead_off)
        self.assertTrue(sample.lo_plus)
        self.assertFalse(sample.lo_minus)
        self.assertAlmostEqual(adc_to_volts(512), 2.5024, places=3)

    def test_serial_backward_compat_and_malformed(self):
        old = parse_sample_line("123456,512,0")
        self.assertIsNone(old.sequence)
        self.assertIsNone(parse_sample_line_safe("bad,line"))

    def test_serial_checksum_packets(self):
        checksum = packet_checksum(42, 123456, 512, 1, 0)
        sample = parse_sample_line(f"S,42,123456,512,1,0,{checksum}")
        self.assertTrue(sample.checksum_valid)
        self.assertEqual(sample.checksum, checksum)
        self.assertIsNone(parse_sample_line_safe("S,42,123456,512,1,0,999"))

    def test_serial_tracker_stats(self):
        tracker = SerialPacketTracker()
        bad_checksum = "S,4,16000,503,0,0,999"
        for line in ["S,0,0,500,0,0", "S,1,4000,501,0,0", "S,3,12000,502,0,1", bad_checksum, "bad"]:
            tracker.update_line(line)
        stats = tracker.snapshot()
        self.assertEqual(stats.valid_samples, 3)
        self.assertEqual(stats.malformed_packets, 2)
        self.assertEqual(stats.checksum_errors, 1)
        self.assertEqual(stats.dropped_packets, 1)
        self.assertGreater(stats.packet_loss_rate, 0.0)
        self.assertEqual(stats.lead_off_samples, 1)


if __name__ == "__main__":
    unittest.main()
