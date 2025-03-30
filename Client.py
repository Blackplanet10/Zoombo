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

from PyQt5 import QtWidgets
from GUI.welcome import Ui_welcome  # Adjust the import as needed
import packet_structure as pst

# Diffie–Hellman public parameters (for demonstration only)
p = 0xE95E4A5F737059DC60DF5991D45029409E60FC09  # a 160-bit prime
g = 2

# import JSONMutex as jsm
# SERVER_HOST = jsm.JSONMutex("settins\clinet_settings.json").read_json()["SERVER_HOST"]
# SERVER_PORT = jsm.JSONMutex("settins\clinet_settings.json").read_json()["SERVER_PORT"]

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000


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
            # Continue with further communication using self.shared_key for symmetric encryption.
        else:
            print("Handshake failed.")


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