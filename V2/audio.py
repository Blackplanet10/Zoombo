import pyaudio, threading, queue, time
from typing import Callable

RATE   = 16_000
CHUNK  = 320          # 20ms
FORMAT = pyaudio.paInt16
CHANNELS = 1

class AudioIO:
    """Bi‑directional audio with selectable devices."""

    def __init__(self,
                 on_capture: Callable[[bytes], None],
                 play_q: queue.Queue[tuple[bytes, float]],
                 input_dev: int | None = None,
                 output_dev: int | None = None):
        self.p = pyaudio.PyAudio()
        self.on_capture = on_capture
        self.play_q = play_q

        self.in_stream = self.p.open(format=FORMAT,
                                     channels=CHANNELS,
                                     rate=RATE,
                                     input=True,
                                     input_device_index=input_dev,
                                     frames_per_buffer=CHUNK)
        self.out_stream = self.p.open(format=FORMAT,
                                      channels=CHANNELS,
                                      rate=RATE,
                                      output=True,
                                      output_device_index=output_dev)

        self._running = True
        threading.Thread(target=self._cap_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _cap_loop(self):
        while self._running:
            data = self.in_stream.read(CHUNK, exception_on_overflow=False)
            self.on_capture(data)

    def _play_loop(self):
        DELAY = 0.06  # 60ms sync cushion
        while self._running:
            try:
                frame, ts = self.play_q.get(timeout=0.1)
                wait = (ts + DELAY) - time.time()
                if wait > 0:
                    time.sleep(wait)
                self.out_stream.write(frame)
            except queue.Empty:
                pass

    def close(self):
        self._running = False; time.sleep(0.2)
        self.in_stream.close(); self.out_stream.close(); self.p.terminate()