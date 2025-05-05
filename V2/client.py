from __future__ import annotations
import sys, json, struct, socket, threading, base64, secrets, queue
import cv2, numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui

from encryption import generate_rsa_keypair, rsa_decrypt, xor_bytes
from audio import AudioIO, RATE, CHUNK
from welcome import Ui_welcome
from home import Ui_home
from room import MainWindow as RoomUI

with open("client_settings.json") as f:
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
            self.warning.setText("Enter your name ⤴")
            return
        self.home = HomeWindow(name); self.home.show(); self.close()

class HomeWindow(QtWidgets.QMainWindow, Ui_home):
    def __init__(self, user_name):
        super().__init__(); self.setupUi(self)
        self.user_name = user_name
        self.label.setText(f"Hello {user_name} !")
        self.connectButton.clicked.connect(self._join)
        self.connectButton_2.clicked.connect(self._create)
    def _join(self):
        code = self.Name.text().strip().upper()
        if code:
            self._launch(code)
    def _create(self):
        code = ''.join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        self._launch(code)
    def _launch(self, code):
        try:
            self.room = ChatRoom(self.user_name, code)
        except ConnectionRefusedError:
            QtWidgets.QMessageBox.critical(self, "Server", "Cannot reach server")
            return
        self.room.show(); self.close()

# =====================================================
# ChatRoom – now with audio
# =====================================================

class ChatRoom(RoomUI):
    frame_ready = QtCore.pyqtSignal(str, object)   # sender, cv2 frame

    def __init__(self, user_name, room_code):
        super().__init__()
        self.user_name, self.room_code = user_name, room_code
        self.setWindowTitle(f"Room {room_code} – {user_name}")

        # view mapping *before* threads
        self._view_slots = [self.graphicsView, self.graphicsView_2, self.graphicsView_3,
                            self.graphicsView_4, self.graphicsView_5, self.graphicsView_6]
        self._view_map: dict[str, QtWidgets.QGraphicsView] = {}
        self.frame_ready.connect(self._show_frame)

        # crypto / net
        self.public_key, self.private_key = generate_rsa_keypair()
        self.sym_key: bytes | None = None
        self.sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
        _send(self.sock, {"type": "join", "room_code": room_code, "name": user_name,
                          "public_key": self.public_key})

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # camera
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self._frame_timer = QtCore.QTimer(); self._frame_timer.timeout.connect(self._capture_frame)
        self._frame_timer.start(int(1000 / TARGET_FPS))

        # audio – queues & threads spun up *after* sym key arrives
        self._play_q: queue.Queue[bytes] = queue.Queue(maxsize=20)
        self.audio_io: AudioIO | None = None

    # ------------------- networking -------------------
    def _recv_loop(self):
        try:
            while True:
                msg = _recv(self.sock)
                kind = msg.get("type")
                if kind == "sym_key":
                    enc = msg["data"]; self.sym_key = rsa_decrypt(enc, self.private_key)
                    print("🔑 key ready – starting audio")
                    self._start_audio()
                elif kind == "frame" and self.sym_key:
                    self._handle_frame(msg["from"], msg["data"])
                elif kind == "audio" and self.sym_key:
                    self._handle_audio(msg["data"])
        except ConnectionError:
            pass

    # ------------------- audio helper ------------------
    def _start_audio(self):
        if self.audio_io is None:
            self.audio_io = AudioIO(self._send_audio_chunk, self._play_q)

    def _send_audio_chunk(self, pcm: bytes):
        if self.sym_key is None:
            return
        enc = xor_bytes(pcm, self.sym_key)
        _send(self.sock, {"type": "audio", "data": base64.b64encode(enc).decode()})

    def _handle_audio(self, payload_b64: str):
        raw = base64.b64decode(payload_b64)
        pcm = xor_bytes(raw, self.sym_key)
        try:
            self._play_q.put_nowait(pcm)
        except queue.Full:
            pass  # drop if speaker buffer saturated

    # ------------------- video helpers -----------------
    def _capture_frame(self):
        if self.sym_key is None:
            return
        ok, frame = self.cap.read();
        if not ok:
            return
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
        if not ok:
            return
        enc = xor_bytes(buf.tobytes(), self.sym_key)
        _send(self.sock, {"type": "frame", "from": self.user_name,
                          "data": base64.b64encode(enc).decode()})
        self.frame_ready.emit(self.user_name, frame)

    def _handle_frame(self, sender, payload_b64):
        raw = base64.b64decode(payload_b64)
        jpg = xor_bytes(raw, self.sym_key)
        frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            self.frame_ready.emit(sender, frame)

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
