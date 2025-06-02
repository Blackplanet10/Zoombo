from __future__ import annotations
import sys, json, struct, socket, threading, base64, secrets, queue, time, collections
from html import escape
import cv2, numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyaudio

from encryption import generate_rsa_keypair, rsa_decrypt, xor_bytes
from audio import AudioIO
from gui.welcome import Ui_welcome
from gui.home import Ui_home
from gui.room import Ui_MainWindow


import pathlib, os
ROOT = pathlib.Path(__file__).resolve().parent           # V2 or gui
IMG  = lambda n: os.fspath(ROOT / ("imgs" if ROOT.name == "gui" else "gui/imgs") / n)


# ───────────────────── settings ──────────────────────
with open("settings/client_settings.json") as f:
    CFG = json.load(f)
SERVER_HOST, SERVER_PORT = CFG["SERVER_HOST"], CFG["SERVER_PORT"]
TARGET_FPS   = CFG["TARGET_FPS"]
WIDTH, HEIGHT = CFG["FRAME_WIDTH"], CFG["FRAME_HEIGHT"]
JPEG_Q       = CFG["JPEG_QUALITY"]


# ───────────────────── net helpers ───────────────────
def _send(sock: socket.socket, payload: dict):
    blob = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(blob)) + blob)

def _recv(sock: socket.socket) -> dict:
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


# ────────────────── device picker dialog ─────────────
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


# ─────────────────────basic windows ──────────────────
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
            sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
            _send(sock, {"type": "register", "name": name})
            msg = _recv(sock)
            print(f"Received message: {msg}")
            if msg.get("type") == "welcome" and "user_id" in msg:
                print("approved server registration")
                user_id = msg["user_id"]
                self.home = HomeWindow(sock, name, user_id)
                print(f"Connected as {name} (ID: {user_id})")
                self.home.show()
                self.close()
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "Registration failed")
        except Exception:
            QtWidgets.QMessageBox.critical(self, "Error", "Could not connect to server")


class HomeWindow(QtWidgets.QMainWindow, Ui_home):
    def __init__(self, sock, user_name, user_id):
        super().__init__(); self.setupUi(self)
        self.sock = sock
        self.user_name = user_name
        self.user_id = user_id
        self.connectButton.clicked.connect(self._join)
        self.connectButton_2.clicked.connect(self._create)
        print(f"HomeWindow initialized with socket {sock}, user_name {user_name}, user_id {user_id}")


    def _join(self):
        code = self.Name.text().strip().upper()
        if code:
            self._enter(code, is_create=False)

    def _create(self):
        self._enter(None, is_create=True)

    def _enter(self, room_code, is_create):
        try:
            self.chat_room = ChatRoom(self.sock, self.user_id, self.user_name, room_code, is_create)
            self.chat_room.show()
            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Room Error", str(e))


# ───────────────────  CHAT ROOM  ──────────────────────
class ChatRoom(QtWidgets.QMainWindow, Ui_MainWindow):
    frame_ready = QtCore.pyqtSignal(str, object)

    def __init__(self, sock, user_id: str, user_name: str, room_code: str = None, is_create: bool = False, cam_idx: int = 0, mic_idx: int = None):
        super().__init__();
        self.setupUi(self)

        # 1—state used by threads (must exist first)
        self.user_id = user_id
        self._user_names: dict[str, str] = {user_id: user_name}  # user_id -> display name
        self.user_name, self.room_code = user_name, room_code
        self._cam_idx, self._mic_idx = cam_idx, mic_idx
        self._camera_on, self._mic_on = True, True
        self._play_q: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=20)
        self.audio_io: AudioIO | None = None
        self._pending_vid = collections.defaultdict(list)
        self.sock = sock

        # Generate keys early!
        self.public_key, self.private_key = generate_rsa_keypair()
        self.sym_key: bytes | None = None

        # 2—GUI wiring
        self.setWindowTitle(
            f"Room {room_code} – {user_name}" if room_code and not is_create else "Creating room…"
        )
        self.label.setText(
            f"ROOM ID: {room_code}" if room_code and not is_create else "Creating room…"
        )
        self.frame_ready.connect(self._show_frame)

        self._force_close = False  # Leave button sets this

        # mute / camera Toggles
        self.micButton.toggled.connect(self._toggle_mic)
        self.cameraButton.toggled.connect(self._toggle_camera)
        self.SettingsButton.clicked.connect(self._change_devices)
        self.sendButton.clicked.connect(self._send_text)
        self.leaveButton.clicked.connect(self._confirm_leave)

        self.cameraButton.setIcon(QtGui.QIcon(IMG("camera_green.png")))
        self.micButton.setIcon(QtGui.QIcon(IMG("mic_green.png")))

        self.cameraButton.clicked.connect(self._toggle_camera)
        self.micButton.clicked.connect(self._toggle_mic)

        # graphics‑view slots (4 peers max)
        self._view_slots = [
            self.graphicsView_1,
            self.graphicsView_2,
            self.graphicsView_3,
            self.graphicsView_4
        ]
        self._view_map: dict[str, QtWidgets.QGraphicsView] = {}

        # --- ONLY ONE block for join/create ---
        if is_create:
            print("creating room")
            _send(self.sock, {
                "type": "create_room",
                "user_id": self.user_id,
                "name": self.user_name,
                "public_key": self.public_key,
            })
            initial_responses = []
            while True:
                msg = _recv(self.sock)
                kind = msg.get("type")
                initial_responses.append(msg)
                if kind == "room_created":
                    self.room_code = msg["room_code"]
                    self.setWindowTitle(f"Room {self.room_code} – {user_name}")
                    self.label.setText(f"ROOM ID: {self.room_code}")
                    break
                elif kind == "reject":
                    QtWidgets.QMessageBox.critical(self, "Server", msg.get("reason", "Room creation failed"))
                    raise Exception(msg.get("reason", "Room creation failed"))

            # Now process any initial responses (sym_key, status, etc) in the order received
            for msg in initial_responses:
                kind = msg.get("type")
                if kind == "sym_key":
                    self.user_id = msg.get("user_id", self.user_id)
                    self.sym_key = rsa_decrypt(msg["data"], self.private_key)
                    self._start_audio()
                elif kind == "status":
                    self._append_chat("System", msg.get("text", ""))
                # Add more as needed for your protocol
        else:
            _send(self.sock, {
                "type": "join",
                "room_code": self.room_code,
                "user_id": self.user_id,
                "name": self.user_name,
                "public_key": self.public_key,
            })
            msg = _recv(self.sock)
            if msg.get("type") == "reject":
                QtWidgets.QMessageBox.critical(self, "Server", msg.get("reason", "Join failed"))
                raise Exception(msg.get("reason", "Join failed"))

        # 5—start receive thread
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # 6-camera
        self._open_camera(cam_idx)

        # 7-timer for outgoing frames
        self._frame_timer = QtCore.QTimer(self)
        self._frame_timer.timeout.connect(self._capture_frame)
        self._frame_timer.start(int(1000 / TARGET_FPS))


    # ── camera helpers ────────────────────────────────
    def _open_camera(self, idx: int):
        if hasattr(self, "cap") and self.cap.isOpened():
            self.cap.release()
        self.cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap.open(idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap.open(idx)   # CAP_ANY
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        else:
            QtWidgets.QMessageBox.warning(self, "Camera",
                                          "Selected camera couldn’t be opened. Video disabled.")
            self._camera_on = False
            self.cameraButton.setChecked(True)   # show crossed‑out icon

    # ── camera click ──────────────────────────────────────
    def _toggle_camera(self):
        self._camera_on = not self._camera_on
        icon = "camera_green.png" if self._camera_on else "camera_red.png"
        self.cameraButton.setIcon(QtGui.QIcon(f"{IMG(icon)}"))
        if not self._camera_on:
            self._show_blank(self.user_name)

    # ── mic click ─────────────────────────────────────────
    def _toggle_mic(self):
        self._mic_on = not self._mic_on
        icon = "mic_green.png" if self._mic_on else "mic_red.png"
        self.micButton.setIcon(QtGui.QIcon(f"{IMG(icon)}"))
        _send(self.sock, {"type": "mute",
                          "from": self.user_id, "name": self.user_name,
                          "state": not self._mic_on})

        self._update_mute_badge(self.user_name, not self._mic_on)

    # ── settings: change devices at run time ──────────
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
            if self.sym_key:                    # if key already known
                self._start_audio()

    # ───────────────── leave helper ─────────────────────
    def _confirm_leave(self):
        ans = QtWidgets.QMessageBox.question(
            self, "Leave room", "Are you sure you want to leave the call?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if ans == QtWidgets.QMessageBox.Yes:
            self.close()  # triggers cleanup in closeEvent

    # ── outgoing audio / video ────────────────────────
    def _start_audio(self):
        if self.audio_io is None:
            self.audio_io = AudioIO(self._send_audio_chunk, self._play_q,
                                    input_dev=self._mic_idx)

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
        _send(self.sock, {"type": "frame",
                          "from": self.user_id, "name": self.user_name,
                          "ts": time.time(),
                          "data": base64.b64encode(enc).decode()})
        self.frame_ready.emit(self.user_name, cv2.flip(frame, 1))

    def _send_audio_chunk(self, pcm: bytes):
        if self.sym_key is None:
            return
        if not self._mic_on:
            pcm = b"-1"

        enc = xor_bytes(pcm, self.sym_key)
        _send(self.sock, {"type": "audio",
                              "from": self.user_id, "name": self.user_name,
                              "ts": time.time(),
                              "data": base64.b64encode(enc).decode()})

    # ── outgoing text chat ────────────────────────────
    def _send_text(self):
        txt = self.messageBox.toPlainText().strip()
        if not txt:
            return
        self.messageBox.clear()
        self._append_chat("You", txt)
        _send(self.sock, {"type": "chat",
                          "from": self.user_id, "name": self.user_name,
                          "text": txt})

    #difterbute to helpers
    def _recv_loop(self):
        try:
            while True:
                msg = _recv(self.sock)
                kind = msg.get("type")

                # get key when welcome
                if kind in ("welcome", "sym_key"):
                    self.user_id = msg.get("user_id", self.user_id)
                    self._user_names[self.user_id] = self.user_name
                    if kind == "sym_key" and "data" in msg:
                        self.sym_key = rsa_decrypt(msg["data"], self.private_key)
                        self._start_audio()
                    continue

                # For join/leave/status/chat, always update mapping
                if "user_id" in msg and "name" in msg:
                    self._user_names[msg["user_id"]] = msg["name"]

                if kind == "frame" and self.sym_key:
                    self._handle_frame(msg["from"], msg["data"], msg["ts"])
                elif kind == "audio" and self.sym_key:
                    self._handle_audio(msg["from"], msg["data"], msg["ts"])
                elif kind == "chat":
                    sender_id = msg.get("from")
                    sender_name = self._user_names.get(sender_id, sender_id)
                    self._append_chat(sender_name, msg["text"])
                elif kind == "mute":
                    self._update_mute_badge(msg["from"], msg["state"])
                elif kind == "join":
                    sender_id = msg.get("user_id")
                    sender_name = msg.get("name", sender_id)
                    self._handle_user_join(sender_id, sender_name)
                elif kind == "leave":
                    sender_id = msg.get("from")
                    sender_name = msg.get("name", sender_id)
                    self._handle_user_leave(sender_id, sender_name)
                elif kind == "status":
                    # System message
                    self._append_chat("System", msg.get("text", ""))
                elif kind == "reject":
                    reason = msg.get("reason", "Unknown reason")
                    QtWidgets.QMessageBox.critical(self, "Join failed", reason)
                    self.close()
                    return
        except ConnectionError:
            pass

    def _get_name_label(self, view):
        idx = list(self._view_map.values()).index(view)
        return getattr(self, f"nameLabel{idx}")

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

    # ── incoming helpers ──────────────────────────────

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

            # Make usable by another user
            self._view_slots.insert(0, view)

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

    def _handle_frame(self, sender: str, payload_b64: str, ts: float):
        raw = base64.b64decode(payload_b64)
        frame = cv2.imdecode(np.frombuffer(xor_bytes(raw, self.sym_key),
                                           np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            self._pending_vid[sender].append((ts, frame))

    def _update_mute_badge(self, sender: str, muted: bool):
        view = self._view_map.get(sender)
        if not view:
            return
        idx = list(self._view_map.values()).index(view)
        badge = getattr(self, f"muteBadge{idx}")
        if muted:
            # top‑right corner, 6px padding
            badge.move(view.x() + view.width() - badge.width() - 6,
                       view.y() + 6)
            badge.show()
        else:
            badge.hide()

    # ── chat UI ───────────────────────────────────────
    def _append_chat(self, sender: str, text: str):
        self.textBrowser.append(f"<b>{escape(sender)}:</b> {escape(text)}")

    # ── video display ─────────────────────────────────
    def _show_frame(self, sender: str, frame):
        view = self._view_map.get(sender)
        if view is None and self._view_slots:
            view = self._view_slots.pop(0);
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

        #update mute icon
        self._update_mute_badge(sender, sender != self.user_name and
                                        not self._mic_on if sender == self.user_name else
        getattr(self, "_remote_muted", {}).get(sender, False))

        # position / text of name overlay
        lbl = self._get_name_label(view)
        lbl.setText(sender)
        lbl.resize(view.width(), 24)
        lbl.move(view.x(), view.y() + view.height() - 24)

    def closeEvent(self, ev: QtGui.QCloseEvent):
        if not self._force_close:
            ans = QtWidgets.QMessageBox.question(
                self, "Leave room",
                "Are you sure you want to leave the call?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if ans == QtWidgets.QMessageBox.No:
                ev.ignore()
                return

        try:
            self._frame_timer.stop()
            if hasattr(self, 'cap') and self.cap.isOpened():
                self.cap.release()
            if self.audio_io:
                self.audio_io.close()
            # Send explicit leave message to server
            _send(self.sock, {
                "type": "leave",
                "user_id": self.user_id,
                "room_code": self.room_code
            })
            self.sock.close()  # <--- Properly close the socket here!
        except Exception:
            pass

        # Now create a new connection for HomeWindow
        try:
            sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
            _send(sock, {"type": "register", "name": self.user_name})
            msg = _recv(sock)
            if msg.get("type") == "welcome" and "user_id" in msg:
                user_id = msg["user_id"]
                self.home = HomeWindow(sock, self.user_name, user_id)
                self.home.show()
        except Exception:
            QtWidgets.QMessageBox.critical(self, "Error", "Could not reconnect to server")
        super().closeEvent(ev)


# ───────────────── entry‑point ────────────────────────
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    Win = WelcomeWindow(); Win.show()
    sys.exit(app.exec_())
