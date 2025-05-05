"""PyQt5 desktop client – run one instance per participant."""

from __future__ import annotations
import sys, json, struct, socket, threading, base64, secrets, time

import cv2, numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui

from encryption import generate_rsa_keypair, rsa_decrypt, xor_bytes
from gui.welcome import Ui_welcome
from gui.home import Ui_home
from gui.room import MainWindow as RoomUI  # already a QMainWindow subclass

# -------- settings --------
with open("settings/client_settings.json", "r") as f:
    CFG = json.load(f)

SERVER_HOST: str = CFG["SERVER_HOST"]
SERVER_PORT: int = CFG["SERVER_PORT"]
TARGET_FPS: int  = CFG["TARGET_FPS"]
WIDTH: int       = CFG["FRAME_WIDTH"]
HEIGHT: int      = CFG["FRAME_HEIGHT"]
JPEG_Q: int      = CFG["JPEG_QUALITY"]

# -------- low‑level net helpers --------

def _send(sock: socket.socket, payload: dict):
    blob = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(blob)) + blob)

def _recv(sock: socket.socket) -> dict:
    hdr = sock.recv(4)
    if not hdr:
        raise ConnectionError
    (length,) = struct.unpack("!I", hdr)
    buf = b""
    while len(buf) < length:
        part = sock.recv(length - len(buf))
        if not part:
            raise ConnectionError
        buf += part
    return json.loads(buf.decode())

# =====================================================
#                GUI  –  Windows
# =====================================================

class WelcomeWindow(QtWidgets.QMainWindow, Ui_welcome):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.connectButton.clicked.connect(self._go_next)
        self.quitButton.clicked.connect(QtWidgets.qApp.quit)

    def _go_next(self):
        name = self.Name.text().strip()
        if not name:
            self.warning.setText("Please enter your name ⤴")
            return
        self.home = HomeWindow(name)
        self.home.show()
        self.close()


class HomeWindow(QtWidgets.QMainWindow, Ui_home):
    def __init__(self, user_name: str):
        super().__init__()
        self.setupUi(self)
        self.user_name = user_name
        self.label.setText(f"Hello {user_name} !")
        self.connectButton.clicked.connect(self._join_room)
        self.connectButton_2.clicked.connect(self._create_room)

    def _join_room(self):
        code = self.Name.text().strip().upper()
        if not code:
            QtWidgets.QMessageBox.warning(self, "Room", "Enter a room code")
            return
        self._launch_room(code)

    def _create_room(self):
        code = ''.join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        self._launch_room(code)

    def _launch_room(self, code: str):
        self.room = ChatRoom(self.user_name, code)
        self.room.show()
        self.close()


# =====================================================
#                Chat Room (main class)
# =====================================================

class ChatRoom(RoomUI):
    def __init__(self, user_name: str, room_code: str):
        super().__init__()

        # ---------------- crypto / net setup ----------------
        self.public_key, self.private_key = generate_rsa_keypair()
        self.sym_key: bytes | None = None

        # ----‑‑‑‑‑‑‑‑‑‑  INSERT THIS BLOCK EARLIER  ‑‑‑‑‑‑‑‑‑‑----
        self._view_slots = [
            self.graphicsView, self.graphicsView_2, self.graphicsView_3,
            self.graphicsView_4, self.graphicsView_5, self.graphicsView_6,
        ]
        self._view_map: dict[str, QtWidgets.QGraphicsView] = {}
        # -----------------------------------------------------

        self.sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
        _send(self.sock, {
            "type": "join",
            "room_code": room_code,
            "name": user_name,
            "public_key": self.public_key,
        })

        self._receiver = threading.Thread(target=self._recv_loop, daemon=True)
        self._receiver.start()

        # ---------------- camera setup ----------------
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

        self._frame_timer = QtCore.QTimer()
        self._frame_timer.timeout.connect(self._capture_frame)
        self._frame_timer.start(int(1000 / TARGET_FPS))

        # mapping sender‑name ↦ QGraphicsView placeholder
        self._view_slots = [
            self.graphicsView, self.graphicsView_2, self.graphicsView_3,
            self.graphicsView_4, self.graphicsView_5, self.graphicsView_6,
        ]
        self._view_map: dict[str, QtWidgets.QGraphicsView] = {}

    # ------------------------------------------------- networking loop
    def _recv_loop(self):
        try:
            while True:
                msg = _recv(self.sock)
                kind = msg.get("type")
                if kind == "sym_key":
                    enc_int = msg["data"]
                    self.sym_key = rsa_decrypt(enc_int, self.private_key)
                    print("🔑 Symmetric key established!")
                elif kind == "frame" and self.sym_key:
                    self._handle_remote_frame(msg["from"], msg["data"])
        except ConnectionError:
            pass  # server closed / network error – silently exit thread

    # ------------------------------------------------- capture & send
    def _capture_frame(self):
        if self.sym_key is None:
            return  # not ready yet
        ok, frame = self.cap.read()
        if not ok:
            return
        frame = cv2.resize(frame, (WIDTH, HEIGHT))

        # JPEG‑encode
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
        if not ok:
            return
        enc = xor_bytes(buf.tobytes(), self.sym_key)
        payload = base64.b64encode(enc).decode()
        _send(self.sock, {"type": "frame", "from": self.user_name, "data": payload})

        self._show_frame(self.user_name, frame)

    # ------------------------------------------------- remote frames
    def _handle_remote_frame(self, sender: str, payload_b64: str):
        raw_enc = base64.b64decode(payload_b64)
        jpeg_bytes = xor_bytes(raw_enc, self.sym_key)
        np_buf = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)
        if frame is not None:
            self._show_frame(sender, frame)

    # ------------------------------------------------- display helpers
    def _show_frame(self, sender: str, frame):
        view = self._view_map.get(sender)
        if view is None and self._view_slots:
            view = self._view_slots.pop(0)
            self._view_map[sender] = view
        if view is None:
            return  # no empty slots – ignore

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
        scene = QtWidgets.QGraphicsScene()
        scene.addPixmap(QtGui.QPixmap.fromImage(img))
        view.setScene(scene)

    # ------------------------------------------------- cleanup
    def closeEvent(self, event):
        try:
            self._frame_timer.stop()
            if self.cap.isOpened():
                self.cap.release()
            self.sock.close()
        except Exception:
            pass
        super().closeEvent(event)

# =====================================================
#                    entry‑point
# =====================================================

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    win = WelcomeWindow()     # keep a variable so it doesn’t vanish
    win.show()

    sys.exit(app.exec_())
