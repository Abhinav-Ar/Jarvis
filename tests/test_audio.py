import time
import unittest

import numpy as np

from audio import BargeInMonitor


class BargeInTests(unittest.TestCase):
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
