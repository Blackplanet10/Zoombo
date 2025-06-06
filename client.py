from __future__ import annotations
import sys, json, struct, socket, threading, base64, secrets, queue, time, collections
from html import escape
from typing import final

import cv2, numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyaudio


from encryption import generate_rsa_keypair, rsa_decrypt, aes_decrypt, aes_encrypt
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

        # Pass name to homewindow
        self.home = HomeWindow(name)
        self.home.show()
        self.close()


class HomeWindow(QtWidgets.QMainWindow, Ui_home):
    def __init__(self, user_name: str):
        print("DEBUG(Home): initializing HomeWindow with user_name:", user_name)
        super().__init__();
        self.setupUi(self)

        self.user_name = user_name

        self.connectButton.clicked.connect(self._join)
        self.connectButton_2.clicked.connect(self._create)

    def _join(self):
        code = self.Name.text().strip().upper()
        if not code:
            return
        self._enter(room_code=code, is_create=False)

    def _create(self):
        # room_code can be None when creating
        self._enter(room_code=None, is_create=True)

    def _enter(self, room_code: str | None, is_create: bool):
        try:
            sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
            public_key, private_key = generate_rsa_keypair()

            # 1) REGISTER (plaintext) → get {"type":"welcome", …}
            _send(sock, {
                "type": "register",
                "name": self.user_name,
                "public_key": public_key
            })
            welcome = _recv(sock)
            if welcome.get("type") != "welcome":
                raise Exception("Registration failed")

            user_id = welcome["user_id"]
            enc_session = base64.b64decode(welcome["sym_key"])
            session_key = rsa_decrypt(enc_session, private_key)
            # (We ignore session_key beyond satisfying the protocol.)

            # 2) SEND create_room / join (plaintext)
            if is_create:
                _send(sock, {
                    "type": "create_room",
                    "name": self.user_name,
                    "user_id": user_id
                })
            else:
                _send(sock, {
                    "type": "join",
                    "room_code": room_code,
                    "name": self.user_name,
                    "user_id": user_id
                })

            # 3a) WAIT for plaintext "sym_key"
            room_sym_key = None
            nonce_bytes = None
            final_room = room_code


            while True:
                response = _recv(sock)
                kind = response.get("type")

                if kind == "reject":
                    raise Exception(response.get("reason", "Join/create failed"))

                if kind == "room_created":
                    # only if you created the room; record its code and keep looping
                    final_room = response["room_code"]
                    continue

                if kind == "sym_key":
                    # Decrypt AES key
                    enc_room_b64 = response["data"]
                    enc_room = base64.b64decode(enc_room_b64)
                    room_sym_key = rsa_decrypt(enc_room, private_key)

                    # Parse nonce from hex→bytes
                    nonce_hex = response.get("nonce", "")
                    if not nonce_hex:
                        raise Exception("No nonce from server")
                    nonce_bytes = bytes.fromhex(nonce_hex)
                    break

                # ignore any stray "status" that might slip in plaintext
                continue



            # 3b) WAIT for exactly one AES‐encrypted blob containing "room_created"+"initial_status"
            while True:
                response = _recv(sock)
                if response.get("type") != "aes_blob":
                    # not the right envelope—ignore until we get one
                    continue
                enc_blob = base64.b64decode(response["data"])
                plain = aes_decrypt(enc_blob, room_sym_key, nonce_bytes)
                inner = json.loads(plain.decode())

                if inner.get("type") != "room_created":
                    # if somehow it's not "room_created", ignore
                    continue

                # Now we have: {"type":"room_created","room_code":…,"initial_status":…,"user_id":…}
                final_room = inner["room_code"]
                initial_stat = inner.get("initial_status", "")
                # (Optionally display initial_stat in HomeWindow or print it)
                print(f"DEBUG(Home): initial_status = {initial_stat}")
                break

                # Sanity check
                if room_sym_key is None or nonce_bytes is None or (not final_room):
                    raise Exception("Failed to negotiate room key")
            # 4) Launch ChatRoom with AES key + nonce
            self.chat_room = ChatRoom(
                sock=sock,
                user_id=user_id,
                user_name=self.user_name,
                room_code=final_room,
                sym_key=room_sym_key,
                nonce=nonce_bytes,
                private_key=private_key
            )
            self.chat_room.show()
            self.close()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Room Error", str(e))



# ───────────────────  CHAT ROOM  ──────────────────────
class ChatRoom(QtWidgets.QMainWindow, Ui_MainWindow):
    frame_ready = QtCore.pyqtSignal(str, object)

    def __init__(self,
                 sock: socket.socket,
                 user_id: str,
                 user_name: str,
                 room_code: str,
                 sym_key: bytes,
                 nonce: bytes,
                 private_key):
        super().__init__(); self.setupUi(self)


        # ─── 1) State ────────────────────────────────────────────────────────────
        self.sock = sock
        self.user_id = user_id
        self.user_name = user_name
        self.room_code = room_code
        self.sym_key = sym_key          # <-- The ROOM’s AES key
        self.nonce = nonce              # <-- The ROOM’s AES nonce
        self.private_key = private_key  # <-- We keep this only if you expect any future RSA decrypts
        self._user_names = {user_id: user_name}

        print(f"DEBUG(ChatRoom): user_id={user_id}, user_name={user_name}, room_code={room_code}")

        # ─── 2) UI setup ──────────────────────────────────────────────────────────
        self.setWindowTitle(f"Room {room_code} – {user_name}")
        self.label.setText(f"ROOM ID: {room_code}")
        self.frame_ready.connect(self._show_frame)

        self._force_close = False
        self._camera_on = True
        self._mic_on = True

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

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        self._play_q = queue.Queue(maxsize=20)


        # ─── 4) Open camera / start timers / start audio if needed ───────────────
        self._open_camera(0)  # or whatever cam_idx you want by default
        self.audio_io = AudioIO(self._send_audio_chunk, self._play_q, input_dev=None)

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
            self.cameraButton.setChecked(True)

    # ── camera click ──────────────────────────────────────
    def _toggle_camera(self):
        self._camera_on = not self._camera_on
        icon = "camera_green.png" if self._camera_on else "camera_red.png"
        self.cameraButton.setIcon(QtGui.QIcon(f"{IMG(icon)}"))
        if not self._camera_on:
            self._show_blank(self.user_name)

        _send(self.sock, {
            "type": "camera",
            "from": self.user_id,
            "name": self.user_name,
            "state": self._camera_on
        })

    # ── mic click ─────────────────────────────────────────
    def _toggle_mic(self):
        self._mic_on = not self._mic_on
        icon = "mic_green.png" if self._mic_on else "mic_red.png"
        self.micButton.setIcon(QtGui.QIcon(f"{IMG(icon)}"))
        _send(self.sock, {"type": "mute", "from": self.user_id, "name": self.user_name, "state": not self._mic_on})
        self._update_mute_badge(self.user_name, not self._mic_on)

    # ── settings: change devices at run time ──────────
    def _change_devices(self):
        dlg = DeviceSelectDialog(self)
        cam, mic = dlg.get()
        if cam is None:
            return
        self._cam_idx, self._mic_idx = cam, mic
        self._open_camera(cam)

        # Always recreate AudioIO, even if currently muted
        if self.audio_io:
            self.audio_io.close()
        # Recreate AudioIO with latest mic index
        if self.sym_key:
            self.audio_io = AudioIO(self._send_audio_chunk, self._play_q, input_dev=self._mic_idx)

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
        if not self._camera_on or not hasattr(self, "cap") or not self.cap.isOpened():
            return
        ok, frame = self.cap.read()
        if not ok:
            return
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        # Encode JPEG
        ok2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
        if not ok2:
            return

        # **Encrypt the raw JPEG bytes with room AES key + nonce**
        enc = aes_encrypt(buf.tobytes(), self.sym_key, self.nonce)
        _send(self.sock, {
            "type": "frame",
            "from": self.user_id,
            "name": self.user_name,
            "ts": time.time(),
            "data": base64.b64encode(enc).decode()
        })
        self.frame_ready.emit(self.user_name, cv2.flip(frame, 1))

    def _send_audio_chunk(self, pcm: bytes):
        if self.sym_key is None:
            return
        if not self._mic_on:
            pcm = b"-1"

        enc = aes_encrypt(pcm, self.sym_key, self.nonce)
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
                try:
                    msg = _recv(self.sock)
                except ConnectionError:
                    break
                kind = msg.get("type")

                if kind == "aes_blob":
                    try:
                        enc_blob = base64.b64decode(msg["data"])
                        plain = aes_decrypt(enc_blob, self.sym_key, self.nonce)
                        inner = json.loads(plain.decode())
                    except Exception:
                        continue

                    kind = inner.get("type")


                # get key when welcome
                if kind in ("welcome", "sym_key"):
                    self.user_id = msg.get("user_id", self.user_id)
                    self._user_names[self.user_id] = self.user_name
                    if kind == "sym_key" and "data" in msg:
                        enc_b64 = msg["data"]
                        enc_bytes = base64.b64decode(enc_b64)
                        self.sym_key = rsa_decrypt(enc_bytes, self.private_key)

                        enc_nonce = msg["nonce"]
                        enc_nonce_bytes = base64.b64decode(enc_nonce)
                        self.nonce = bytes.fromhex(enc_nonce_bytes)
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
                elif kind == "camera":
                    self._handle_camera_state(msg["from"], msg["state"])
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
        # Set gray background
        scn.setBackgroundBrush(QtGui.QColor("#4C2C76"))
        # Optionally, show a camera-off pixmap in the center
        icon_path = IMG("camera_gray.png")  # Add a suitable icon to your imgs/
        if os.path.exists(icon_path):
            pix = QtGui.QPixmap(icon_path)
            scn.addPixmap(pix)
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
        pcm = aes_decrypt(raw, self.sym_key, self.nonce)
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
        frame = cv2.imdecode(np.frombuffer(aes_decrypt(raw, self.sym_key, self.nonce),
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
            print("showing badage")
        else:
            badge.hide()

    def _handle_camera_state(self, sender: str, camera_on: bool):
        if not camera_on:
            self._show_blank(sender)
        else:
            # You may want to display a default image or wait for next frame.
            pass

    # ── chat UI ───────────────────────────────────────
    def _append_chat(self, sender: str, text: str):
        self.textBrowser.append(f"<b>{escape(sender)}:</b> {escape(text)}")

    # ── video display ─────────────────────────────────
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

        camera_off = not getattr(self, "_camera_states", {}).get(sender, True)
        muted = getattr(self, "_remote_muted", {}).get(sender, False)
        # Draw overlay badge/icon on top of the frame if needed
        if camera_off:
            # Show camera-off icon in center
            icon_path = IMG("camera_gray.png")  # Add a suitable icon to your imgs/
            if os.path.exists(icon_path):
                icon_pix = QtGui.QPixmap(icon_path)
                icon_item = scn.addPixmap(icon_pix)
                icon_item.setOffset(
                    (view.width() - icon_pix.width()) // 2,
                    (view.height() - icon_pix.height()) // 2
                )
        elif muted:
            # Show mute badge in a corner (e.g. top-right)
            icon_path = IMG("mic_red.png")
            if os.path.exists(icon_path):
                icon_pix = QtGui.QPixmap(icon_path)
                icon_item = scn.addPixmap(icon_pix)
                icon_item.setOffset(view.width() - icon_pix.width() - 10, 10)

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

        # When user leaves, notify server, then jump back to Home
        try:
            _send(self.sock, {
                "type": "leave",
                "user_id": self.user_id,
                "room_code": self.room_code
            })
        except Exception:
            pass

            # 2) Then, stop the camera timer and release camera
        try:
            self._frame_timer.stop()
            self.cap.release()
        except Exception:
            pass

            # 3) Now stop the audio capture thread
        try:
            # This calls AudioIO.close(), which sets _running=False and joins the thread
            self.audio_io.close()
        except Exception:
                pass

        try:
            self.sock.close()
        except Exception:
            pass

        print("opening home window")

        self.home = HomeWindow(self.user_name)
        self.home.show()


        # Allow the QMainWindow to close
        super().closeEvent(ev)


# ───────────────── entry‑point ────────────────────────
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    Win = WelcomeWindow(); Win.show()
    sys.exit(app.exec_())