import packet_structure as pst

#   open seperate threads for:
# sending video and audio
# receving video and audio
# receving other requests that are not so often (text and such)



## Client.py
import sys
import struct
import socket
import threading
import random
import cv2, numpy as np, pyaudio, json, queue, time
from PyQt5.QtGui import QImage, QPixmap

from PyQt5 import QtCore

from PyQt5.QtCore import QTimer
from PyQt5 import QtWidgets
from GUI.welcome import Ui_welcome  # Adjust the import as needed
from GUI.home import Ui_home  # Adjust the import as needed
import packet_structure as pst
from GUI import room

# Diffie–Hellman public parameters (for demonstration only)
p = 0xE95E4A5F737059DC60DF5991D45029409E60FC09  # a 160-bit prime
g = 2

# import JSONMutex as jsm
# SERVER_HOST = jsm.JSONMutex("settins\clinet_settings.json").read_json()["SERVER_HOST"]
# SERVER_PORT = jsm.JSONMutex("settins\clinet_settings.json").read_json()["SERVER_PORT"]

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000

with open("settings/client_settings.json") as f:
    cfg = json.load(f)
FPS       = cfg["TARGET_FPS"]
WIDTH     = cfg["FRAME_WIDTH"]
HEIGHT    = cfg["FRAME_HEIGHT"]
QUALITY   = cfg["JPEG_QUALITY"]
CHUNK     = 960                # 20ms @ 48kHz, 1×16‑bit mono
A_RATE    = 48000


def connect_to_server(name: str):
    try:
        # --- Diffie–Hellman: Client generates its secret and public value ---
        a = random.randint(2, p - 2)
        A = pow(g, a, p)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_HOST, SERVER_PORT))

        # Build handshake packet including the client's name and its public value A
        handshake_packet = pst.ClientPacketStructure.Handshake(name, A)
        header = struct.pack("Q", len(handshake_packet))
        sock.sendall(header + handshake_packet)
        print("Handshake sent to server.")

        # --- Receive handshake response ---
        response_header = sock.recv(struct.calcsize("Q"))
        if not response_header:
            print("No response received from server.")
            return None, None
        response_length = struct.unpack("Q", response_header)[0]
        response_data = b""
        while len(response_data) < response_length:
            chunk = sock.recv(response_length - len(response_data))
            if not chunk:
                print("Connection closed prematurely.")
                return None, None
            response_data += chunk

        # Expected format: "300,<user_id>,handshake_ack,<B>"
        if response_data.startswith(b"300"):
            print("Handshake acknowledged by server.")
            response_str = response_data.decode('utf-8')
            parts = response_str.split(',', 3)
            if len(parts) >= 4:
                try:
                    B = int(parts[3])
                except ValueError:
                    print("Invalid public value received.")
                    return None, None
                # Compute the shared key: (B)^a mod p
                shared_key = pow(B, a, p)
                print("Shared key established:", shared_key)
                return sock, shared_key
            else:
                print("Malformed handshake response.")
                return None, None
        else:
            print("Unexpected response:", response_data)
            return None, None
    except Exception as e:
        print("Error connecting to server:", e)
        return None, None

class PreviewEmitter(QtCore.QObject):
    """
    Thread‑safe bridge: StreamSender (worker thread) → Qt GUI (main thread)
    """



    frameReady = QtCore.pyqtSignal(QPixmap)

class CountEmitter(QtCore.QObject):
    updated = QtCore.pyqtSignal(int)

class StreamSender(threading.Thread):
    def __init__(self, sock, running_flag,preview_emitter):
        super().__init__(daemon=True)
        self.sock, self.running = sock, running_flag
        self.preview = preview_emitter
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.audio = pyaudio.PyAudio().open(A_RATE, 1, pyaudio.paInt16, input=True,
                                            frames_per_buffer=CHUNK)

    def run(self):
        while self.running.is_set():
            ret, frame = self.cap.read()
            if not ret:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            _, buf = cv2.imencode(".jpg", frame,
                                  [int(cv2.IMWRITE_JPEG_QUALITY), QUALITY])
            jpeg = buf.tobytes()

            # ------------- local preview -------------
            h, w, _ = frame.shape
            img = QImage(frame.data, w, h, 3 * w, QImage.Format_RGB888)
            pix = QPixmap.fromImage(img)
            self.preview.frameReady.emit(pix)
            # -----------------------------------------

            pcm  = self.audio.read(CHUNK, exception_on_overflow=False)
            pkt  = pst.ClientPacketStructure.VidAud(jpeg, pcm)
            self.sock.sendall(struct.pack("Q", len(pkt)) + pkt)
            time.sleep(1 / FPS)

class StreamReceiver(threading.Thread):
    def __init__(self, sock, running_flag, room_window):
        super().__init__(daemon=True)
        self.sock, self.running, self.ui = sock, running_flag, room_window
        self.sinks = {}                          # uid → (audio stream, last_frame)

    def run(self):
        pa = pyaudio.PyAudio()
        while self.running.is_set():
            hdr = self.sock.recv(struct.calcsize("Q"))
            if not hdr:
                break
            l = struct.unpack("Q", hdr)[0]
            data = b""
            while len(data) < l:
                data += self.sock.recv(l - len(data))
            if not data.startswith(b"301"):
                continue

            if data.startswith(b"306"):
                n = int(data.decode().split(',')[2])
                self.ui.parent().count_emitter.updated.emit(n)
                continue

            parts = data.split(b',', 4)
            uid      = int(parts[1])
            vid_len  = int(parts[2])
            aud_len  = int(parts[3])
            payload  = parts[4]
            jpeg = payload[:vid_len]
            pcm  = payload[vid_len:vid_len + aud_len]

            # --- video ---
            nparr = np.frombuffer(jpeg, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            h, w, _ = frame.shape
            img = QImage(frame.data, w, h, 3 * w, QImage.Format_BGR888)
            pix = QPixmap.fromImage(img)

            # pick a graphicsView slot deterministically
            views = [self.ui.graphicsView, self.ui.graphicsView_2,
                     self.ui.graphicsView_3, self.ui.graphicsView_4,
                     self.ui.graphicsView_5, self.ui.graphicsView_6]
            view = views[uid % len(views)]
            if view.scene() is None:
                view.setScene(QtWidgets.QGraphicsScene())
            view.scene().clear()
            view.scene().addPixmap(pix)
            view.fitInView(view.sceneRect(), QtCore.Qt.KeepAspectRatio)

            # --- audio ---
            if uid not in self.sinks:
                self.sinks[uid] = pa.open(A_RATE, 1, pyaudio.paInt16,
                                          output=True, frames_per_buffer=CHUNK)
            self.sinks[uid].write(pcm)


class HomeWindow(QtWidgets.QMainWindow):
    def __init__(self,sock, shared_key):
        super().__init__()
        self.sock = sock
        self.shared_key = shared_key
        self.ui = Ui_home()
        self.ui.setupUi(self)

        self.ui.connectButton.clicked.connect(self.join_room)        # "Join Room"
        self.ui.connectButton_2.clicked.connect(self.create_room)    # "Create New Room"

        # ---------- networking helpers ---------- #

    def _send_and_wait(self, payload: bytes):
        hdr = struct.pack("Q", len(payload))
        self.sock.sendall(hdr + payload)
        r_hdr = self.sock.recv(struct.calcsize("Q"))
        if not r_hdr:
            return None
        length = struct.unpack("Q", r_hdr)[0]
        resp = b""

        while len(resp) < length:
            resp += self.sock.recv(length - len(resp))

        return resp

        # ---------- UI callbacks ---------- #

    def create_room(self):
        resp = self._send_and_wait(pst.ClientPacketStructure.CreateRoom())

        if resp and resp.startswith(b"304"):
            code = resp.decode().split(',')[2]
            QtWidgets.QMessageBox.information(self, "Room created", f"Give this code to friends:\n\n{code}")
            self.open_room_window(code)

    def join_room(self):
        code = self.ui.Name.text().strip().upper()

        if not code:
            QtWidgets.QMessageBox.warning(self, "Join room", "Enter a room code.")
            return

        resp = self._send_and_wait(pst.ClientPacketStructure.JoinRoom(code))
        if resp and resp.startswith(b"305"):
            self.open_room_window(code)
        else:
            QtWidgets.QMessageBox.critical(self, "Join room", "Room not found.")


    def open_room_window(self, code: str):
        self.room_window = room.MainWindow()
        self.room_window.setWindowTitle(f"Room {code}")
        self.room_window.show()

        self.count_emitter = CountEmitter()
        self.count_emitter.updated.connect(lambda n: self.room_window.roomCount.setText(f"Participants: {n}"))

        # ---------- media threads ----------
        self.running = threading.Event()
        self.running.set()

        self.preview_emitter = PreviewEmitter()
        # pick ANY graphicsView you want for the selfie; here we use graphicsView_0
        selfie_view = self.room_window.graphicsView  # adapt if your .ui names differ
        if selfie_view.scene() is None:
            selfie_view.setScene(QtWidgets.QGraphicsScene())

        def _update_selfie(pix):
            selfie_view.scene().clear()
            selfie_view.scene().addPixmap(pix)
            selfie_view.fitInView(selfie_view.sceneRect(), QtCore.Qt.KeepAspectRatio)

        self.preview_emitter.frameReady.connect(_update_selfie)

        self.sender = StreamSender(self.sock, self.running, self.preview_emitter)
        self.receiver = StreamReceiver(self.sock, self.running, self.room_window)
        self.sender.start()
        self.receiver.start()

    def closeEvent(self, e):
        if hasattr(self, "running"):
            self.running.clear()
        super().closeEvent(e)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_welcome()
        self.ui.setupUi(self)
        # Connect button signals
        self.ui.quitButton.clicked.connect(self.on_quit_pressed)
        self.ui.connectButton.clicked.connect(self.on_connect_pressed)
        self.sock = None  # The connection socket
        self.shared_key = None  # The shared symmetric key



    def on_quit_pressed(self):
        self.close()

    def on_connect_pressed(self):
        name = self.ui.Name.text().strip()
        if not name:
            self.ui.warning.setText("Need to input name")
            return
        else:
            self.ui.warning.setText("")
        print("Connect button pressed with name:", name)
        # Perform handshake in a separate thread
        threading.Thread(target=self.do_handshake, args=(name,), daemon=True).start()

    def do_handshake(self, name: str):
        sock, shared_key = connect_to_server(name)
        if sock and shared_key:
            self.sock = sock
            self.shared_key = shared_key
            print("Encrypted handshake successful; connection established.")
            # Schedule open_home_window to be called in the main thread
            QTimer.singleShot(0, self.open_home_window)
        else:
            print("Handshake failed.")

    def open_home_window(self):
        # Create an instance of the ChatWindow passing the connection info.
        self.home_window = HomeWindow(self.sock, self.shared_key)
        print("opened widnow")
        # Show the new window.
        self.home_window.show()
        print("opened widnow")
        # Hide the current welcome window.
        self.hide()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


def call_loop():
    #   create a socket

    #   connect to server
    #   send a request to server for connection
    #   wait for server to accept
    #   start sending and receiving video and audio
    #   start sending and receiving other requests

    #   close connection
    pass

if __name__ == "__main__":
    main()