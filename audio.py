"""Microphone phrase capture with simple energy-based voice detection."""

from __future__ import annotations

import collections
import os
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd


class PhraseRecorder:
    def __init__(self) -> None:
        self.rate = int(os.getenv("JARVIS_SAMPLE_RATE", "16000"))
        self.block_ms = 20
        self.blocksize = self.rate * self.block_ms // 1000
        self.threshold = float(os.getenv("JARVIS_ENERGY_THRESHOLD", "500"))
        self.silence_blocks = max(1, int(float(os.getenv("JARVIS_SILENCE_SECONDS", "1.4")) * 1000 / self.block_ms))
        self.max_blocks = max(1, int(float(os.getenv("JARVIS_MAX_PHRASE_SECONDS", "30")) * 1000 / self.block_ms))
        device = os.getenv("JARVIS_INPUT_DEVICE")
        self.device = int(device) if device and device.isdigit() else device or None

    @staticmethod
    def devices() -> str:
        return str(sd.query_devices())

    def listen(self, on_speech_start=None) -> Path:
        chunks: queue.Queue[bytes] = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            chunks.put(bytes(indata))

        # Preserve 300 ms before the threshold crossing so initial consonants survive.
        pre_roll = collections.deque(maxlen=max(1, 300 // self.block_ms))
        recorded: list[bytes] = []
        speaking = False
        quiet = 0
        with sd.RawInputStream(
            samplerate=self.rate,
            blocksize=self.blocksize,
            device=self.device,
            channels=1,
            dtype="int16",
            callback=callback,
        ):
            while len(recorded) < self.max_blocks:
                chunk = chunks.get()
                level = float(np.abs(np.frombuffer(chunk, dtype=np.int16).astype(np.int32)).mean())
                if not speaking:
                    pre_roll.append(chunk)
                    if level >= self.threshold:
                        speaking = True
                        recorded.extend(pre_roll)
                        if on_speech_start is not None:
                            on_speech_start()
                else:
                    recorded.append(chunk)
                    quiet = quiet + 1 if level < self.threshold else 0
                    if quiet >= self.silence_blocks:
                        break

        path = Path(tempfile.gettempdir()) / "jarvis-input.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.rate)
            wav.writeframes(b"".join(recorded))
        return path


class BargeInMonitor:
    """Detect sustained nearby speech while Jarvis is playing audio."""

    def __init__(self) -> None:
        self.rate = int(os.getenv("JARVIS_SAMPLE_RATE", "16000"))
        self.block_ms = 20
        self.blocksize = self.rate * self.block_ms // 1000
        self.minimum_threshold = float(os.getenv("JARVIS_BARGE_IN_THRESHOLD", "450"))
        self.threshold_ratio = float(os.getenv("JARVIS_BARGE_IN_THRESHOLD_RATIO", "1.7"))
        self.required_blocks = max(2, int(float(os.getenv("JARVIS_BARGE_IN_SECONDS", "0.12")) * 1000 / self.block_ms))
        self.grace_seconds = float(os.getenv("JARVIS_BARGE_IN_GRACE_SECONDS", "0.5"))
        self.triggered = threading.Event()
        self.phrase_complete = threading.Event()
        self._loud_blocks = 0
        self._quiet_blocks = 0
        self._started = 0.0
        self._baseline = 0.0
        self._baseline_samples = 0
        self.last_level = 0.0
        self._pre_roll = collections.deque(maxlen=max(1, 300 // self.block_ms))
        self._recorded: list[bytes] = []
        self._phrase_threshold = float(os.getenv("JARVIS_ENERGY_THRESHOLD", "250"))
        self._silence_blocks = max(1, int(float(os.getenv("JARVIS_SILENCE_SECONDS", "1.4")) * 1000 / self.block_ms))
        device = os.getenv("JARVIS_INPUT_DEVICE")
        self.device = int(device) if device and device.isdigit() else device or None
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        chunk = bytes(indata)
        level = float(np.abs(np.frombuffer(chunk, dtype=np.int16).astype(np.int32)).mean())
        self.last_level = level
        if self.triggered.is_set():
            self._recorded.append(chunk)
            self._quiet_blocks = self._quiet_blocks + 1 if level < self._phrase_threshold else 0
            if self._quiet_blocks >= self._silence_blocks:
                self.phrase_complete.set()
            return
        self._pre_roll.append(chunk)
        if time.monotonic() - self._started < self.grace_seconds:
            self._baseline_samples += 1
            weight = 1.0 / self._baseline_samples
            self._baseline = (1.0 - weight) * self._baseline + weight * level
            return
        adaptive_threshold = max(self.minimum_threshold, self._baseline * self.threshold_ratio)
        self._loud_blocks = self._loud_blocks + 1 if level >= adaptive_threshold else 0
        if self._loud_blocks >= self.required_blocks:
            self._recorded.extend(self._pre_roll)
            self.triggered.set()
            print(
                f"Barge-in detected (voice level {level:.0f}, adaptive threshold {adaptive_threshold:.0f}).",
                flush=True,
            )

    def capture_phrase(self) -> Path | None:
        if not self.triggered.is_set():
            return None
        self.phrase_complete.wait(timeout=float(os.getenv("JARVIS_MAX_PHRASE_SECONDS", "30")))
        if not self._recorded:
            return None
        path = Path(tempfile.gettempdir()) / "jarvis-interruption.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.rate)
            wav.writeframes(b"".join(self._recorded))
        return path

    def __enter__(self):
        self._started = time.monotonic()
        self._stream = sd.RawInputStream(
            samplerate=self.rate,
            blocksize=self.blocksize,
            device=self.device,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
