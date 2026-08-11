from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SerialSample:
    sequence: int | None
    timestamp_us: int
    adc_value: int
    lo_plus: bool
    lo_minus: bool
    checksum: int | None = None
    checksum_valid: bool = True

    @property
    def lead_off(self) -> bool:
        return self.lo_plus or self.lo_minus


@dataclass(frozen=True)
class SerialStreamStats:
    total_lines: int
    valid_samples: int
    malformed_packets: int
    dropped_packets: int
    packet_loss_rate: float
    sample_rate_estimate: float | None
    mean_interval_us: float | None
    timing_jitter_us: float | None
    lead_off_samples: int
    checksum_errors: int = 0


class SerialPacketTracker:
    """Tracks packet loss and timing jitter for Arduino CSV ECG packets."""

    def __init__(self) -> None:
        self.total_lines = 0
        self.valid_samples = 0
        self.malformed_packets = 0
        self.dropped_packets = 0
        self.lead_off_samples = 0
        self.checksum_errors = 0
        self._last_sequence: int | None = None
        self._last_timestamp_us: int | None = None
        self._intervals_us: list[int] = []

    def update_line(self, line: str) -> SerialSample | None:
        self.total_lines += 1
        try:
            sample = parse_sample_line(line)
        except (TypeError, ValueError) as exc:
            self.malformed_packets += 1
            if "checksum mismatch" in str(exc).lower():
                self.checksum_errors += 1
            return None
        self.update_sample(sample)
        return sample

    def update_sample(self, sample: SerialSample) -> None:
        self.valid_samples += 1
        if sample.lead_off:
            self.lead_off_samples += 1
        if sample.sequence is not None and self._last_sequence is not None:
            gap = sample.sequence - self._last_sequence
            if gap > 1:
                self.dropped_packets += gap - 1
        self._last_sequence = sample.sequence

        if self._last_timestamp_us is not None:
            interval = sample.timestamp_us - self._last_timestamp_us
            if interval > 0:
                self._intervals_us.append(interval)
        self._last_timestamp_us = sample.timestamp_us

    def snapshot(self) -> SerialStreamStats:
        expected = self.valid_samples + self.dropped_packets
        packet_loss_rate = self.dropped_packets / expected if expected else 0.0
        if self._intervals_us:
            mean_interval = sum(self._intervals_us) / len(self._intervals_us)
            variance = sum((x - mean_interval) ** 2 for x in self._intervals_us) / len(self._intervals_us)
            jitter = math.sqrt(variance)
            sample_rate = 1_000_000.0 / mean_interval if mean_interval > 0 else None
        else:
            mean_interval = None
            jitter = None
            sample_rate = None
        return SerialStreamStats(
            total_lines=self.total_lines,
            valid_samples=self.valid_samples,
            malformed_packets=self.malformed_packets,
            dropped_packets=self.dropped_packets,
            packet_loss_rate=packet_loss_rate,
            sample_rate_estimate=sample_rate,
            mean_interval_us=mean_interval,
            timing_jitter_us=jitter,
            lead_off_samples=self.lead_off_samples,
            checksum_errors=self.checksum_errors,
        )


def packet_checksum(sequence: int, timestamp_us: int, adc_value: int, lo_plus: int, lo_minus: int) -> int:
    """Small XOR checksum for Arduino CSV packets."""
    value = int(sequence) & 0xFFFF
    value ^= int(timestamp_us) & 0xFFFF
    value ^= (int(timestamp_us) >> 16) & 0xFFFF
    value ^= int(adc_value) & 0x03FF
    value ^= (int(lo_plus) & 1) << 10
    value ^= (int(lo_minus) & 1) << 11
    return value & 0xFFFF


def parse_sample_line(line: str) -> SerialSample:
    parts = [part.strip() for part in line.strip().split(",")]
    checksum = None
    checksum_valid = True
    if len(parts) in (6, 7) and parts[0] == "S":
        sequence = int(parts[1])
        timestamp_us = int(parts[2])
        adc_value = int(parts[3])
        lo_plus_raw = int(parts[4])
        lo_minus_raw = int(parts[5])
        if len(parts) == 7:
            checksum = int(parts[6], 0)
            checksum_valid = checksum == packet_checksum(sequence, timestamp_us, adc_value, lo_plus_raw, lo_minus_raw)
    elif len(parts) == 3:
        sequence = None
        timestamp_us = int(parts[0])
        adc_value = int(parts[1])
        lo_plus_raw = int(parts[2])
        lo_minus_raw = 0
    else:
        raise ValueError(f"Expected 'S,seq,timestamp_us,adc_value,lo_plus,lo_minus[,checksum]', got: {line!r}")
    if sequence is not None and sequence < 0:
        raise ValueError("Sequence must be non-negative")
    if timestamp_us < 0:
        raise ValueError("Timestamp must be non-negative")
    if not 0 <= adc_value <= 1023:
        raise ValueError(f"ADC value out of Arduino 10-bit range: {adc_value}")
    if lo_plus_raw not in (0, 1) or lo_minus_raw not in (0, 1):
        raise ValueError("Lead-off flags must be 0 or 1")
    if not checksum_valid:
        raise ValueError("Packet checksum mismatch")
    lo_plus = bool(lo_plus_raw)
    lo_minus = bool(lo_minus_raw)
    return SerialSample(
        sequence=sequence,
        timestamp_us=timestamp_us,
        adc_value=adc_value,
        lo_plus=lo_plus,
        lo_minus=lo_minus,
        checksum=checksum,
        checksum_valid=checksum_valid,
    )


def parse_sample_line_safe(line: str) -> SerialSample | None:
    try:
        return parse_sample_line(line)
    except (TypeError, ValueError):
        return None


def adc_to_volts(adc_value: int, reference_voltage: float = 5.0, adc_max: int = 1023) -> float:
    if not 0 <= adc_value <= adc_max:
        raise ValueError("ADC value out of range")
    return float(adc_value) * reference_voltage / float(adc_max)
