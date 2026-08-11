import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from scripts.run_live_gui import SerialSignalSource


class FakeSerialPort:
    def __init__(self):
        self.buffer = b""
        self.reset_called = False

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, n):
        data = self.buffer[:n]
        self.buffer = self.buffer[n:]
        return data

    def reset_input_buffer(self):
        self.reset_called = True
        self.buffer = b""

    def close(self):
        pass


class SerialSignalSourceTests(unittest.TestCase):
    def make_source(self, fs=250.0, chunk_seconds=0.04):
        fake_port = FakeSerialPort()

        def serial_factory(*args, **kwargs):
            return fake_port

        fake_serial_module = types.SimpleNamespace(Serial=serial_factory)
        patcher = patch.dict(sys.modules, {"serial": fake_serial_module})
        patcher.start()
        self.addCleanup(patcher.stop)
        source = SerialSignalSource("COM1", 115200, fs=fs, chunk_seconds=chunk_seconds)
        return source, fake_port

    def test_serial_source_returns_latest_short_live_chunk(self):
        source, fake_port = self.make_source(fs=250.0, chunk_seconds=0.04)
        lines = [
            f"S,{i},{i * 4000},{500 + i},0,0\n".encode("ascii")
            for i in range(30)
        ]
        fake_port.buffer = b"".join(lines)

        chunk = source.read_chunk()

        self.assertEqual(chunk.samples.size, 10)
        np.testing.assert_array_equal(chunk.samples, np.arange(520, 530, dtype=float))
        self.assertEqual(source.tracker.snapshot().valid_samples, 30)
        self.assertTrue(fake_port.reset_called)

    def test_serial_source_preserves_partial_line_until_newline(self):
        source, fake_port = self.make_source()
        fake_port.buffer = b"S,1,4000,"

        first = source.read_chunk()
        self.assertEqual(first.samples.size, 0)

        fake_port.buffer = b"512,0,0\n"
        second = source.read_chunk()
        np.testing.assert_array_equal(second.samples, np.asarray([512.0]))

    def test_serial_source_records_raw_packets_and_metadata(self):
        fake_port = FakeSerialPort()

        def serial_factory(*args, **kwargs):
            return fake_port

        fake_serial_module = types.SimpleNamespace(Serial=serial_factory)
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(sys.modules, {"serial": fake_serial_module}):
            source = SerialSignalSource("COM1", 115200, record_output_dir=tmpdir)
            fake_port.buffer = b"S,0,0,500,0,0\nmalformed\nS,1,4000,501,0,0\n"

            chunk = source.read_chunk()
            source.close()

            np.testing.assert_array_equal(chunk.samples, np.asarray([500.0, 501.0]))
            log_files = sorted(__import__("pathlib").Path(tmpdir).glob("*_ad8232_live_log.csv"))
            meta_files = sorted(__import__("pathlib").Path(tmpdir).glob("*_live_metadata.json"))
            self.assertEqual(len(log_files), 1)
            self.assertEqual(len(meta_files), 1)
            self.assertIn("malformed", log_files[0].read_text())
            self.assertIn('"valid_samples": 2', meta_files[0].read_text())


if __name__ == "__main__":
    unittest.main()
