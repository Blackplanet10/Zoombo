from __future__ import annotations
import sys, json, struct, socket, threading, base64, secrets, queue, time, collections
import cv2, numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyaudio

from encryption import generate_rsa_keypair, rsa_decrypt, xor_bytes
from audio import AudioIO
from gui.welcome import Ui_welcome
from gui.home import Ui_home
from gui.room import MainWindow as RoomUI



with open("settings/client_settings.json") as f:
    CFG = json.load(f)
SERVER_HOST, SERVER_PORT = CFG["SERVER_HOST"], CFG["SERVER_PORT"]
TARGET_FPS = CFG["TARGET_FPS"]
WIDTH, HEIGHT = CFG["FRAME_WIDTH"], CFG["FRAME_HEIGHT"]
JPEG_Q = CFG["JPEG_QUALITY"]

# -------- net helpers --------

def _send(sock, payload):
    blob = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(blob)) + blob)

def _recv(sock):
    hdr = sock.recv(4)
    if not hdr:
        raise ConnectionError
    ln, = struct.unpack("!I", hdr)
    buf = b""
    while len(buf) < ln:
        part = sock.recv(ln - len(buf))
        if not part:
            raise ConnectionError
        buf += part
    return json.loads(buf.decode())

#--------------- dialog pick camera and mic ---------------

class DeviceSelectDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select devices")
        layout = QtWidgets.QFormLayout(self)

        # ---------- cameras ----------
        self.cam_combo = QtWidgets.QComboBox()
        self.cam_indices = []
        for idx in range(10):
            cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)  # try modern Media Foundation
            if not cap.isOpened():
                cap.open(idx, cv2.CAP_DSHOW)  # fall back to DirectShow
            if cap.isOpened():
                self.cam_combo.addItem(f"Camera {idx}")
                self.cam_indices.append(idx)
            cap.release()
        if not self.cam_indices:
            self.cam_combo.addItem("Default (0)"); self.cam_indices.append(0)
        layout.addRow("Webcam:", self.cam_combo)

        # ---------- microphones ----------
        self.mic_combo = QtWidgets.QComboBox()
        self.mic_indices = []
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                name = info.get("name", f"Mic {i}")
                self.mic_combo.addItem(name)
                self.mic_indices.append(i)
        pa.terminate()
        if not self.mic_indices:
            self.mic_combo.addItem("Default"); self.mic_indices.append(None)
        layout.addRow("Microphone:", self.mic_combo)

        # buttons
        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept); btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def get_selection(self):
        if self.exec_() == QtWidgets.QDialog.Accepted:
            cam = self.cam_indices[self.cam_combo.currentIndex()]
            mic = self.mic_indices[self.mic_combo.currentIndex()]
            return cam, mic
        return None, None

# =====================================================
# GUI windows (WelcomeWindow & HomeWindow unchanged) …
# =====================================================

class WelcomeWindow(QtWidgets.QMainWindow, Ui_welcome):
    def __init__(self):
        super().__init__(); self.setupUi(self)
        self.connectButton.clicked.connect(self._go)
        self.quitButton.clicked.connect(QtWidgets.qApp.quit)
    def _go(self):
        name = self.Name.text().strip();
        if not name:
            self.warning.setText("Enter your name ⤴"); return
        self.home = HomeWindow(name); self.home.show(); self.close()

class HomeWindow(QtWidgets.QMainWindow, Ui_home):
    def __init__(self, user_name):
        super().__init__(); self.setupUi(self)
        self.user_name = user_name
        self.label.setText(f"Hello {user_name} !")
        self.connectButton.clicked.connect(self._join)
        self.connectButton_2.clicked.connect(self._create)
    def _join(self):
        code = self.Name.text().strip().upper();
        if code: self._launch(code)
    def _create(self):
        code = ''.join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        self._launch(code)
    def _launch(self, code):
        dlg = DeviceSelectDialog(); cam_idx, mic_idx = dlg.get_selection()
        if cam_idx is None:  # user cancelled
            return
        try:
            self.room = ChatRoom(self.user_name, code, cam_idx, mic_idx)
        except ConnectionRefusedError:
            QtWidgets.QMessageBox.critical(self, "Server", "Cannot reach server"); return
        self.room.show(); self.close()


# =====================================================
# ChatRoom – now with audio
# =====================================================

class ChatRoom(RoomUI):
    frame_ready = QtCore.pyqtSignal(str, object)

    def __init__(self, user_name, room_code, cam_idx: int, mic_idx: int | None):
        super().__init__()

        # 1) attributes needed by background threads -----------------
        self._mic_idx = mic_idx
        self._play_q: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=20)
        self.audio_io = None
        self._pending_vid = collections.defaultdict(list)

        # 2) GUI‑related members -------------------------------------
        self.user_name, self.room_code = user_name, room_code
        self.setWindowTitle(f"Room {room_code} – {user_name}")
        self._view_slots = [
            self.graphicsView, self.graphicsView_2, self.graphicsView_3,
            self.graphicsView_4, self.graphicsView_5, self.graphicsView_6
        ]
        self._view_map: dict[str, QtWidgets.QGraphicsView] = {}
        self.frame_ready.connect(self._show_frame)

        # 3) networking / crypto -------------------------------------
        self.public_key, self.private_key = generate_rsa_keypair()
        self.sym_key: bytes | None = None
        self.sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
        _send(self.sock, {
            "type": "join",
            "room_code": room_code,
            "name": user_name,
            "public_key": self.public_key,
        })

        # receiver thread starts only after every attr above exists
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # 4) open the selected camera with graceful fallback ----------
        self.cap = cv2.VideoCapture(cam_idx, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap.open(cam_idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap.open(cam_idx)         # CAP_ANY
        if not self.cap.isOpened():
            QtWidgets.QMessageBox.warning(
                self, "Camera",
                "Selected camera could not be opened – video disabled.")
        else:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

        # video timer -------------------------------------------------
        self._frame_timer = QtCore.QTimer(self)
        self._frame_timer.timeout.connect(self._capture_frame)
        self._frame_timer.start(int(1000 / TARGET_FPS))


    # ------------------- networking -------------------
    def _recv_loop(self):
        try:
            while True:
                msg = _recv(self.sock)
                kind = msg.get("type")
                if kind == "sym_key":
                    self.sym_key = rsa_decrypt(msg["data"], self.private_key); self._start_audio()
                elif kind == "frame" and self.sym_key:
                    self._handle_frame(msg["from"], msg["data"], msg["ts"])
                elif kind == "audio" and self.sym_key:
                    self._handle_audio(msg["from"], msg["data"], msg["ts"])
        except ConnectionError:
            pass


    # ------------------- audio helper ------------------
    def _start_audio(self):
        if self.audio_io is None:
            self.audio_io = AudioIO(self._send_audio_chunk, self._play_q, input_dev=self._mic_idx)


    def _send_audio_chunk(self, pcm: bytes):
        if self.sym_key is None: return
        enc = xor_bytes(pcm, self.sym_key)
        _send(self.sock, {"type": "audio",
                          "from": self.user_name,             # FIX v1.2
                          "ts": time.time(),
                          "data": base64.b64encode(enc).decode()})

    def _handle_audio(self, sender: str, payload_b64: str, ts: float):
        raw = base64.b64decode(payload_b64)
        pcm = xor_bytes(raw, self.sym_key)

        try:
            self._play_q.put_nowait((pcm, ts))  # queue for speaker
        except queue.Full:
            pass

        # pop and display any video frames whose timestamp ≤ this audio ts
        vid_q = self._pending_vid[sender]
        while vid_q and vid_q[0][0] <= ts:
            _, frame = vid_q.pop(0)
            self.frame_ready.emit(sender, frame)

    # ------------------- video helpers -----------------
    def _capture_frame(self):
        if self.sym_key is None: return
        ok, frame = self.cap.read();
        if not ok: return
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
        if not ok: return
        enc = xor_bytes(buf.tobytes(), self.sym_key)
        _send(self.sock, {"type": "frame", "from": self.user_name,
                          "ts": time.time(),
                          "data": base64.b64encode(enc).decode()})
        self.frame_ready.emit(self.user_name, frame)

    def _handle_frame(self, sender, payload_b64, ts):
        raw = base64.b64decode(payload_b64)
        jpg = xor_bytes(raw, self.sym_key)
        frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            # store frame in per‑sender dict until its audio catches up
            self._pending_vid[sender].append((ts, frame))

    # ------------------- UI drawing -------------------
    def _show_frame(self, sender, frame):
        view = self._view_map.get(sender)
        if view is None and self._view_slots:
            view = self._view_slots.pop(0); self._view_map[sender] = view
        if view is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QtGui.QImage(rgb.data, w, h, ch*w, QtGui.QImage.Format_RGB888)
        scn = QtWidgets.QGraphicsScene(); scn.addPixmap(QtGui.QPixmap.fromImage(img))
        view.setScene(scn)

    # ------------------- cleanup ----------------------
    def closeEvent(self, ev):
        try:
            self._frame_timer.stop();
            if self.cap.isOpened(): self.cap.release()
            if self.audio_io: self.audio_io.close()
            self.sock.close()
        except Exception:
            pass
        super().closeEvent(ev)

# =====================================================
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = WelcomeWindow(); win.show()
    sys.exit(app.exec_())
