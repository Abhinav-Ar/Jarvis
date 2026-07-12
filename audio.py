"""Microphone phrase capture with simple energy-based voice detection."""

from __future__ import annotations

import collections
import os
import queue
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd


class PhraseRecorder:
    def __init__(self) -> None:
        self.rate = int(os.getenv("JARVIS_SAMPLE_RATE", "16000"))
        self.block_ms = 50
        self.blocksize = self.rate * self.block_ms // 1000
        self.threshold = float(os.getenv("JARVIS_ENERGY_THRESHOLD", "500"))
        self.silence_blocks = max(1, int(float(os.getenv("JARVIS_SILENCE_SECONDS", "0.8")) * 1000 / self.block_ms))
        self.max_blocks = max(1, int(float(os.getenv("JARVIS_MAX_PHRASE_SECONDS", "30")) * 1000 / self.block_ms))
        device = os.getenv("JARVIS_INPUT_DEVICE")
        self.device = int(device) if device and device.isdigit() else device or None

    @staticmethod
    def devices() -> str:
        return str(sd.query_devices())

    def listen(self) -> Path:
        chunks: queue.Queue[bytes] = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            chunks.put(bytes(indata))

        pre_roll = collections.deque(maxlen=6)
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
