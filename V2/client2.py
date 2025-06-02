# -*- coding: utf-8 -*-
"""
client.py – Modern protocol-based client for video chat app.
Replaces the old client.py.  Now every message after handshake is XOR-encrypted.
"""

import sys, json, struct, socket, threading, base64, secrets, queue, time, collections
from html import escape
import cv2, numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyaudio

from audio import AudioIO
from gui.welcome import Ui_welcome
from gui.home import Ui_home
from gui.room import Ui_MainWindow

from encryption import generate_rsa_keypair, rsa_encrypt, rsa_decrypt, xor_bytes
import pathlib, os
ROOT = pathlib.Path(__file__).resolve().parent
IMG  = lambda n: os.fspath(ROOT / ("imgs" if ROOT.name == "gui" else "gui/imgs") / n)

# ──────────────── settings ────────────────
with open("settings/client_settings.json") as f:
    CFG = json.load(f)
SERVER_HOST, SERVER_PORT = CFG["SERVER_HOST"], CFG["SERVER_PORT"]
TARGET_FPS   = CFG["TARGET_FPS"]
WIDTH, HEIGHT = CFG["FRAME_WIDTH"], CFG["FRAME_HEIGHT"]
JPEG_Q       = CFG["JPEG_QUALITY"]

# ─────────────── net helpers ─────────────
def _send(sock: socket.socket, payload: dict, key: bytes = None):
    """
    Always prepend length; if key is provided, XOR-encrypt the payload.
    """
    blob = json.dumps(payload).encode()
    if key:
        blob = xor_bytes(blob, key)
    sock.sendall(struct.pack("!I", len(blob)) + blob)

def _recv(sock: socket.socket, key: bytes = None) -> dict:
    """
    Read 4-byte length, then the payload. If key is provided, XOR-decrypt before JSON.
    """
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
    if key:
        buf = xor_bytes(buf, key)
    return json.loads(buf.decode())

# ────────── DeviceSelectDialog (unchanged) ──────────
class DeviceSelectDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select devices")
        self.setModal(True)
        lay = QtWidgets.QFormLayout(self)

        # cameras
        self.cam_combo, self.cam_indices = QtWidgets.QComboBox(), []
        for idx in range(10):
            cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
            if not cap.isOpened():
                cap.open(idx, cv2.CAP_DSHOW)
            if cap.isOpened():
                self.cam_combo.addItem(f"Camera {idx}")
                self.cam_indices.append(idx)
            cap.release()
        if not self.cam_indices:
            self.cam_combo.addItem("Default (0)")
            self.cam_indices.append(0)
        lay.addRow("Webcam:", self.cam_combo)

        # microphones
        self.mic_combo, self.mic_indices = QtWidgets.QComboBox(), []
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                self.mic_combo.addItem(info.get("name", f"Mic {i}"))
                self.mic_indices.append(i)
        pa.terminate()
        if not self.mic_indices:
            self.mic_combo.addItem("Default")
            self.mic_indices.append(None)
        lay.addRow("Microphone:", self.mic_combo)

        btns = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        box  = QtWidgets.QDialogButtonBox(btns, parent=self)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        lay.addRow(box)

    def get(self) -> tuple[int, int | None] | tuple[None, None]:
        if self.exec_() == QtWidgets.QDialog.Accepted:
            cam = self.cam_indices[self.cam_combo.currentIndex()]
            mic = self.mic_indices[self.mic_combo.currentIndex()]
            return cam, mic
        return None, None

# ────────────── WelcomeWindow ──────────────
class WelcomeWindow(QtWidgets.QMainWindow, Ui_welcome):
    def __init__(self):
        super().__init__(); self.setupUi(self)
        self.connectButton.clicked.connect(self._connect)
        self.quitButton.clicked.connect(QtWidgets.QApplication.quit)

    def _connect(self):
        name = self.Name.text().strip()
        if not name:
            self.warning.setText("Enter your name")
            return
        try:
            # 1) Generate RSA keys
            self.public_key, self.private_key = generate_rsa_keypair()

            # 2) Open socket, send plaintext "hello"
            sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
            _send(sock, {"type": "hello", "name": name, "public_key": self.public_key})

            # 3) Receive plaintext "welcome" with user_id + encrypted sym_key
            msg = _recv(sock)
            if msg.get("type") != "welcome":
                QtWidgets.QMessageBox.critical(self, "Error", "Handshake failed")
                return

            user_id = msg["user_id"]
            sym_key = rsa_decrypt(msg["sym_key"], self.private_key)

            # 4) Pass everything to HomeWindow
            self.home = HomeWindow(sock, name, user_id, sym_key, self.public_key, self.private_key)
            self.home.show(); self.close()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not connect: {e}")

# ──────────────── HomeWindow ────────────────
class HomeWindow(QtWidgets.QMainWindow, Ui_home):
    def __init__(self, sock, user_name, user_id, sym_key, public_key, private_key):
        super().__init__(); self.setupUi(self)
        self.sock = sock
        self.user_name = user_name
        self.user_id = user_id
        self.sym_key = sym_key
        self.public_key = public_key
        self.private_key = private_key

        self.connectButton.clicked.connect(self._join)
        self.connectButton_2.clicked.connect(self._create)

    def _join(self):
        code = self.Name.text().strip().upper()
        if code:
            self._enter(code, is_create=False)

    def _create(self):
        self._enter(None, is_create=True)

    def _enter(self, room_code, is_create):
        try:
            self.chat_room = ChatRoom(
                self.sock,
                self.user_id,
                self.user_name,
                self.sym_key,
                self.public_key,
                self.private_key,
                room_code=room_code,
                is_create=is_create
            )
            self.chat_room.show()
            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Room Error", str(e))

# ──────────────── ChatRoom ────────────────
class ChatRoom(QtWidgets.QMainWindow, Ui_MainWindow):
    frame_ready = QtCore.pyqtSignal(str, object)

    def __init__(self,
                 sock,
                 user_id: str,
                 user_name: str,
                 sym_key: bytes,
                 public_key: tuple[int,int],
                 private_key: tuple[int,int],
                 room_code: str = None,
                 is_create: bool = False,
                 cam_idx: int = 0,
                 mic_idx: int = None):
        super().__init__()
        self.setupUi(self)

        # ── 1) State ───────────────────────────
        self.sock = sock
        self.user_id = user_id
        self.user_name = user_name
        self.sym_key = sym_key
        self.public_key = public_key
        self.private_key = private_key
        self.room_code = room_code
        self._cam_idx, self._mic_idx = cam_idx, mic_idx
        self._camera_on, self._mic_on = True, True
        self._play_q = queue.Queue(maxsize=20)
        self.audio_io = None
        self._pending_vid = collections.defaultdict(list)
        self._user_names = {user_id: user_name}
        self._force_close = False

        # ── 2) GUI Setup ───────────────────────
        self.setWindowTitle(
            f"Room {room_code or ''} – {user_name}" if not is_create else "Creating room…"
        )
        self.label.setText(
            f"ROOM ID: {room_code or ''}" if not is_create else "Creating room…"
        )
        self.frame_ready.connect(self._show_frame)

        # Buttons / toggles
        self.micButton.toggled.connect(self._toggle_mic)
        self.cameraButton.toggled.connect(self._toggle_camera)
        self.SettingsButton.clicked.connect(self._change_devices)
        self.sendButton.clicked.connect(self._send_text)
        self.leaveButton.clicked.connect(self._confirm_leave)

        self.cameraButton.setIcon(QtGui.QIcon(IMG("camera_green.png")))
        self.micButton.setIcon(QtGui.QIcon(IMG("mic_green.png")))

        self.cameraButton.clicked.connect(self._toggle_camera)
        self.micButton.clicked.connect(self._toggle_mic)

        # Video slots
        self._view_slots = [
            self.graphicsView_1,
            self.graphicsView_2,
            self.graphicsView_3,
            self.graphicsView_4
        ]
        self._view_map: dict[str, QtWidgets.QGraphicsView] = {}

        # ── 3) Create or Join Room ─────────────
        if is_create:
            # Send encrypted create_room
            _send(self.sock,
                  { "type": "create_room", "user_id": self.user_id },
                  self.sym_key)

            # Receive encrypted response
            msg = _recv(self.sock, self.sym_key)
            if msg.get("type") != "room_created":
                QtWidgets.QMessageBox.critical(self, "Server", "Room creation failed")
                raise Exception(msg.get("reason", "Room creation failed"))
            self.room_code = msg["room_code"]
            self.setWindowTitle(f"Room {self.room_code} – {user_name}")
            self.label.setText(f"ROOM ID: {self.room_code}")

        else:
            # Send encrypted join_room
            _send(self.sock,
                  { "type": "join_room", "user_id": self.user_id, "room_code": room_code },
                  self.sym_key)

            # Receive encrypted response
            msg = _recv(self.sock, self.sym_key)
            if msg.get("type") != "join_ok":
                QtWidgets.QMessageBox.critical(self, "Server", "Join failed")
                raise Exception(msg.get("reason", "Join failed"))

        # ── 4) Start Receiver Thread ───────────
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # ── 5) Open Camera ─────────────────────
        self._open_camera(cam_idx)

        # ── 6) Start Frame Timer ───────────────
        self._frame_timer = QtCore.QTimer(self)
        self._frame_timer.timeout.connect(self._capture_frame)
        self._frame_timer.start(int(1000 / TARGET_FPS))


    # ───────────────── Camera Helpers ─────────────────
    def _open_camera(self, idx: int):
        if hasattr(self, "cap") and self.cap.isOpened():
            self.cap.release()
        self.cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap.open(idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap.open(idx)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        else:
            QtWidgets.QMessageBox.warning(self, "Camera",
                                          "Selected camera couldn’t be opened. Video disabled.")
            self._camera_on = False
            self.cameraButton.setChecked(True)

    def _toggle_camera(self):
        self._camera_on = not self._camera_on
        icon = "camera_green.png" if self._camera_on else "camera_red.png"
        self.cameraButton.setIcon(QtGui.QIcon(IMG(icon)))
        if not self._camera_on:
            self._show_blank(self.user_name)

    # ───────────────── Mic Helpers ────────────────────
    def _toggle_mic(self):
        self._mic_on = not self._mic_on
        icon = "mic_green.png" if self._mic_on else "mic_red.png"
        self.micButton.setIcon(QtGui.QIcon(IMG(icon)))
        _send(self.sock,
              { "type": "mute",
                "from": self.user_id, "name": self.user_name,
                "state": not self._mic_on },
              self.sym_key)
        self._update_mute_badge(self.user_name, not self._mic_on)

    # ───────────────── Device Change ─────────────────
    def _change_devices(self):
        dlg = DeviceSelectDialog(self)
        cam, mic = dlg.get()
        if cam is None:
            return
        self._cam_idx, self._mic_idx = cam, mic
        self._open_camera(cam)
        if self.audio_io:
            self.audio_io.close()
            self.audio_io = None
            if self.sym_key:
                self._start_audio()

    # ─────────────── Leave Confirmation ───────────────
    def _confirm_leave(self):
        ans = QtWidgets.QMessageBox.question(
            self, "Leave room", "Are you sure you want to leave the call?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if ans == QtWidgets.QMessageBox.Yes:
            self.close()

    # ───────────────── Frame Capture ─────────────────
    def _capture_frame(self):
        if self.sym_key is None or not self._camera_on or not self.cap.isOpened():
            return
        ok, frame = self.cap.read()
        if not ok:
            return
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
        if not ok:
            return
        enc = xor_bytes(buf.tobytes(), self.sym_key)
        _send(self.sock,
              { "type": "frame",
                "from": self.user_id, "name": self.user_name,
                "ts": time.time(),
                "data": base64.b64encode(enc).decode() },
              self.sym_key)
        self.frame_ready.emit(self.user_name, cv2.flip(frame, 1))

    # ───────────── Audio Send ─────────────────
    def _start_audio(self):
        if self.audio_io is None:
            self.audio_io = AudioIO(self._send_audio_chunk, self._play_q,
                                    input_dev=self._mic_idx)

    def _send_audio_chunk(self, pcm: bytes):
        if self.sym_key is None:
            return
        if not self._mic_on:
            pcm = b"-1"
        enc = xor_bytes(pcm, self.sym_key)
        _send(self.sock,
              { "type": "audio",
                "from": self.user_id, "name": self.user_name,
                "ts": time.time(),
                "data": base64.b64encode(enc).decode() },
              self.sym_key)

    # ───────────── Text Chat ─────────────────
    def _send_text(self):
        txt = self.messageBox.toPlainText().strip()
        if not txt:
            return
        self.messageBox.clear()
        self._append_chat("You", txt)
        _send(self.sock,
              { "type": "chat",
                "from": self.user_id, "name": self.user_name,
                "text": txt },
              self.sym_key)

    # ─────────── Receive Loop ─────────────────
    def _recv_loop(self):
        try:
            while True:
                msg = _recv(self.sock, self.sym_key)
                kind = msg.get("type")

                # decrypt sym_key for others (if you broadcast when joining)
                if kind == "sym_key":
                    self.user_id = msg.get("user_id", self.user_id)
                    self.sym_key = rsa_decrypt(msg["data"], self.private_key)
                    self._start_audio()
                    continue

                if "user_id" in msg and "name" in msg:
                    self._user_names[msg["user_id"]] = msg["name"]

                if kind == "frame":
                    self._handle_frame(msg["from"], msg["data"], msg["ts"])
                elif kind == "audio":
                    self._handle_audio(msg["from"], msg["data"], msg["ts"])
                elif kind == "chat":
                    sender_id = msg.get("from")
                    sender_name = self._user_names.get(sender_id, sender_id)
                    self._append_chat(sender_name, msg["text"])
                elif kind == "mute":
                    self._update_mute_badge(msg["from"], msg["state"])
                elif kind == "join":
                    self._handle_user_join(msg["user_id"], msg.get("name", msg["user_id"]))
                elif kind == "leave":
                    self._handle_user_leave(msg["from"], msg.get("name", msg["from"]))
                elif kind == "status":
                    self._append_chat("System", msg.get("text", ""))
                elif kind == "reject":
                    QtWidgets.QMessageBox.critical(self, "Server", msg.get("reason", "Rejected"))
                    self.close()
                    return
        except ConnectionError:
            pass

    # ───────────────── Get Name Label ─────────────────
    def _get_name_label(self, view):
        idx = list(self._view_map.values()).index(view)
        return getattr(self, f"nameLabel{idx}")

    # ───────────────── Show Blank Frame ────────────────
    def _show_blank(self, sender):
        view = self._view_map.get(sender)
        if not view:
            return
        scn = QtWidgets.QGraphicsScene()
        scn.setBackgroundBrush(QtGui.QColor("#4C2C76"))
        view.setScene(scn)
        lbl = self._get_name_label(view)
        lbl.setText(sender)
        lbl.resize(view.width(), 24)
        lbl.move(view.x(), view.y() + view.height() - 24)

    # ──────────────── Handle Join ─────────────────
    def _handle_user_join(self, user_id: str, name: str):
        self._append_chat("System", f"{name} has joined the call.")
        if user_id in self._view_map:
            view = self._view_map.pop(user_id)
            scn = QtWidgets.QGraphicsScene()
            view.setScene(scn)
            lbl = self._get_name_label(view)
            lbl.setText("")
            lbl.hide()
            self._view_slots.insert(0, view)

    # ──────────────── Handle Leave ─────────────────
    def _handle_user_leave(self, user_id: str, name: str):
        self._append_chat("System", f"{name} has left the call.")
        if user_id in self._view_map:
            view = self._view_map[user_id]
            lbl = self._get_name_label(view)
            lbl.setText("")
            lbl.hide()
            scn = QtWidgets.QGraphicsScene()
            view.setScene(scn)
            self._view_map.pop(user_id)
            self._view_slots.insert(0, view)

    # ───────────────── Handle Audio ───────────────────
    def _handle_audio(self, sender: str, payload_b64: str, ts: float):
        raw = base64.b64decode(payload_b64)
        pcm = xor_bytes(raw, self.sym_key)
        try:
            self._play_q.put_nowait((pcm, ts))
        except queue.Full:
            pass
        vid_q = self._pending_vid[sender]
        while vid_q and vid_q[0][0] <= ts:
            _, frame = vid_q.pop(0)
            self.frame_ready.emit(sender, frame)

    # ───────────────── Handle Frame ───────────────────
    def _handle_frame(self, sender: str, payload_b64: str, ts: float):
        raw = base64.b64decode(payload_b64)
        frame = cv2.imdecode(np.frombuffer(xor_bytes(raw, self.sym_key),
                                           np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            self._pending_vid[sender].append((ts, frame))

    # ───────────────── Update Mute Badge ──────────────
    def _update_mute_badge(self, sender: str, muted: bool):
        view = self._view_map.get(sender)
        if not view:
            return
        idx = list(self._view_map.values()).index(view)
        badge = getattr(self, f"muteBadge{idx}")
        if muted:
            badge.move(view.x() + view.width() - badge.width() - 6,
                       view.y() + 6)
            badge.show()
        else:
            badge.hide()

    # ───────────────── Append Chat ─────────────────────
    def _append_chat(self, sender: str, text: str):
        self.textBrowser.append(f"<b>{escape(sender)}:</b> {escape(text)}")

    # ───────────────── Show Frame ─────────────────────
    def _show_frame(self, sender: str, frame):
        view = self._view_map.get(sender)
        if view is None and self._view_slots:
            view = self._view_slots.pop(0)
            self._view_map[sender] = view
        if view is None:
            return

        lbl = self._get_name_label(view)
        lbl.setText(sender)
        lbl.adjustSize()
        lbl.move(view.mapTo(self, QtCore.QPoint(6, view.height() - lbl.height() - 6)))
        lbl.show()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(qimg)

        scn = QtWidgets.QGraphicsScene()
        item = scn.addPixmap(pix)
        item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        view.setScene(scn)
        view.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        view.fitInView(item, QtCore.Qt.KeepAspectRatio)

        # update mute icon
        self._update_mute_badge(sender,
            sender != self.user_name and not self._mic_on
            if sender == self.user_name
            else getattr(self, "_remote_muted", {}).get(sender, False)
        )

        lbl = self._get_name_label(view)
        lbl.setText(sender)
        lbl.resize(view.width(), 24)
        lbl.move(view.x(), view.y() + view.height() - 24)

    # ───────────────── Cleanup on Close ────────────────
    def closeEvent(self, ev: QtGui.QCloseEvent):
        if not self._force_close:
            ans = QtWidgets.QMessageBox.question(
                self, "Leave room",
                "Are you sure you want to leave the call?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if ans == QtWidgets.QMessageBox.No:
                ev.ignore()
                return

        try:
            self._frame_timer.stop()
            if hasattr(self, 'cap') and self.cap.isOpened():
                self.cap.release()
            if self.audio_io:
                self.audio_io.close()
            # Send encrypted bye
            _send(self.sock, {"type": "bye", "user_id": self.user_id}, self.sym_key)
            self.sock.close()
        except Exception:
            pass

        try:
            # Re-open HomeWindow if desired (new handshake)
            self.home = HomeWindow(None, self.user_name, self.user_id, None, self.public_key, self.private_key)
            self.home.show()
        except Exception:
            pass

        super().closeEvent(ev)

# ───────────────── entry-point ────────────────────────
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    Win = WelcomeWindow()
    Win.show()
    sys.exit(app.exec_())
