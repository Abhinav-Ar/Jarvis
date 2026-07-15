import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

import audio
from audio import BargeInMonitor


class BargeInTests(unittest.TestCase):
    def test_input_mode_file_switches_microphone_policy(self):
        with TemporaryDirectory() as folder:
            mode = Path(folder) / "input-mode"
            with patch.object(audio, "INPUT_MODE_FILE", mode):
                mode.write_text("push_to_talk")
                self.assertTrue(audio.push_to_talk_enabled())
                mode.write_text("always_listening")
                self.assertFalse(audio.push_to_talk_enabled())

    def test_cloud_delay_does_not_consume_playback_echo_calibration(self):
        monitor = BargeInMonitor()
        monitor.minimum_threshold = 100
        monitor.threshold_ratio = 1.7
        monitor.grace_seconds = 0.5
        monitor._started = time.monotonic() - 5
        monitor.begin_playback()
        speaker = np.full(monitor.blocksize, 700, dtype=np.int16).tobytes()
        monitor._callback(speaker, monitor.blocksize, None, None)
        self.assertFalse(monitor.triggered.is_set())
        self.assertEqual(monitor._baseline, 700)

    def test_playback_echo_sets_adaptive_floor_before_user_speech(self):
        monitor = BargeInMonitor()
        monitor.grace_seconds = 10
        monitor.required_blocks = 2
        monitor.minimum_threshold = 100
        monitor.threshold_ratio = 1.7
        monitor._started = time.monotonic()
        echo = np.full(monitor.blocksize, 400, dtype=np.int16).tobytes()
        for _ in range(5):
            monitor._callback(echo, monitor.blocksize, None, None)
        monitor.grace_seconds = 0
        moderate_echo = np.full(monitor.blocksize, 500, dtype=np.int16).tobytes()
        monitor._callback(moderate_echo, monitor.blocksize, None, None)
        monitor._callback(moderate_echo, monitor.blocksize, None, None)
        self.assertFalse(monitor.triggered.is_set())
        voice = np.full(monitor.blocksize, 1000, dtype=np.int16).tobytes()
        monitor._callback(voice, monitor.blocksize, None, None)
        monitor._callback(voice, monitor.blocksize, None, None)
        self.assertTrue(monitor.triggered.is_set())

    def test_sustained_loud_audio_triggers_interruption(self):
        monitor = BargeInMonitor()
        monitor.grace_seconds = 0
        monitor.required_blocks = 3
        monitor.minimum_threshold = 100
        monitor.threshold_ratio = 0
        monitor._started = time.monotonic() - 1
        loud = np.full(monitor.blocksize, 1000, dtype=np.int16).tobytes()
        for _ in range(3):
            monitor._callback(loud, monitor.blocksize, None, None)
        self.assertTrue(monitor.triggered.is_set())

    def test_single_noise_block_does_not_interrupt(self):
        monitor = BargeInMonitor()
        monitor.grace_seconds = 0
        monitor.required_blocks = 3
        monitor.minimum_threshold = 100
        monitor.threshold_ratio = 0
        monitor._started = time.monotonic() - 1
        loud = np.full(monitor.blocksize, 1000, dtype=np.int16).tobytes()
        monitor._callback(loud, monitor.blocksize, None, None)
        self.assertFalse(monitor.triggered.is_set())


if __name__ == "__main__":
    unittest.main()
