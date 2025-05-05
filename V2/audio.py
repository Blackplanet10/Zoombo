"""Minimal helper around *PyAudio* so the main client logic stays clean."""

import pyaudio, threading, queue, time
from typing import Callable

RATE   = 16000        # 16‑kHz mono 16‑bit PCM  → 256kbps raw
CHUNK  = 320         # samples per frame  (≈64ms)
FORMAT = pyaudio.paInt16
CHANNELS = 1

class AudioIO:
    """Bi‑directional microphone / speaker streams with callback hooks."""

    def __init__(self,
                 on_capture: Callable[[bytes], None],
                 playing_queue: queue.Queue[bytes]):
        self.p = pyaudio.PyAudio()
        self.on_capture = on_capture
        self.play_q = playing_queue

        self.in_stream = self.p.open(format=FORMAT,
                                     channels=CHANNELS,
                                     rate=RATE,
                                     input=True,
                                     frames_per_buffer=CHUNK)
        self.out_stream = self.p.open(format=FORMAT,
                                      channels=CHANNELS,
                                      rate=RATE,
                                      output=True)

        self._running = True
        self._t_in  = threading.Thread(target=self._capture_loop, daemon=True)
        self._t_out = threading.Thread(target=self._playback_loop, daemon=True)
        self._t_in.start();  self._t_out.start()

    def _capture_loop(self):
        while self._running:
            data = self.in_stream.read(CHUNK, exception_on_overflow=False)
            self.on_capture(data)

    def _playback_loop(self):
        AUDIO_DELAY = 0.06  # 60 ms – lets video catch up
        ...
        while self._running:
            try:
                frame, ts = self.play_q.get(timeout=0.1)
                # wait so that audio ts + delay ≈ real time
                wait = (ts + AUDIO_DELAY) - time.time()
                if wait > 0:
                    time.sleep(wait)
                self.out_stream.write(frame)
            except queue.Empty:
                pass

    def close(self):
        self._running = False
        time.sleep(0.2)
        self.in_stream.close(); self.out_stream.close(); self.p.terminate()


