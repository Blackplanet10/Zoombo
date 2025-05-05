"""
server.py – The central *signalling* & relay server.

How it works (high‑level)
─────────────────────────
1. When the **first** client arrives for a new room, we create:
       • a random 128‑bit *symmetric* key for that room
       • an empty participant list
2. Each subsequent client joining the room sends their RSA public key.
   The server encrypts the room key with it → client decrypts locally.
3. Clients send JPEG frames *already XOR‑encrypted* with the room key.
   The server simply forwards those opaque frames to everybody else.
   (The server could decrypt, but it chooses not to – up to the assignment!)
"""

import socket, threading, json, struct, secrets, string
from typing import Dict, List, Tuple

from encryption import rsa_encrypt

# -------- settings --------
with open("settings/server_settings.json", "r") as f:
    SETTINGS = json.load(f)

HOST: str = SETTINGS["SERVER_HOST"]
PORT: int = SETTINGS["SERVER_PORT"]

# -------- utility helpers --------

def _send(sock: socket.socket, payload: dict):
    data = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(data)) + data)

def _recv(sock: socket.socket) -> dict:
    header = sock.recv(4)
    if not header:
        raise ConnectionError
    (length,) = struct.unpack("!I", header)
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError
        data += chunk
    return json.loads(data.decode())

# -------- room / client classes --------

class Client(threading.Thread):
    def __init__(self, sock: socket.socket, addr: Tuple[str, int], server: "Server"):
        super().__init__(daemon=True)
        self.sock = sock;  self.addr = addr;  self.server = server
        self.room_code: str | None = None
        self.name: str | None = None

    def run(self):
        try:
            join_msg = _recv(self.sock)
            assert join_msg["type"] == "join"
            self.room_code = join_msg["room_code"].upper()
            self.name = join_msg["name"]
            pub_key = tuple(join_msg["public_key"])

            room = self.server.get_room(self.room_code, create=True)
            room.add_client(self, pub_key)

            # relay loop – everything else we receive is forwarded to peers
            while True:
                msg = _recv(self.sock)
                room.broadcast(msg, exclude=self)
        except (ConnectionError, OSError, AssertionError, json.JSONDecodeError):
            pass
        finally:
            if self.room_code:
                self.server.remove_client(self.room_code, self)
            self.sock.close()

    # called by Room.broadcast
    def send(self, msg: dict):
        try:
            _send(self.sock, msg)
        except OSError:
            pass

class Room:
    def __init__(self, code: str):
        self.code = code
        self.sym_key = secrets.token_bytes(16)  # 128‑bit key per room
        self.clients: List[Client] = []
        self._lock = threading.Lock()

    def add_client(self, client: Client, client_pub):
        with self._lock:
            self.clients.append(client)

        enc_key = rsa_encrypt(self.sym_key, client_pub)
        client.send({"type": "sym_key", "data": enc_key})
        self.broadcast({"type": "status", "text": f"{client.name} joined."})

    def remove_client(self, client: Client):
        with self._lock:
            if client in self.clients:
                self.clients.remove(client)
        self.broadcast({"type": "status", "text": f"{client.name} left."})

    def broadcast(self, msg: dict, exclude: Client | None = None):
        for c in list(self.clients):
            if c is not exclude:
                c.send(msg)

class Server:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self._lock = threading.Lock()

    def get_room(self, code: str, create=False) -> Room:
        with self._lock:
            if code not in self.rooms and create:
                self.rooms[code] = Room(code)
            return self.rooms[code]

    def remove_client(self, code: str, client: Client):
        with self._lock:
            if code in self.rooms:
                room = self.rooms[code]
                room.remove_client(client)
                if not room.clients:
                    del self.rooms[code]

    def serve_forever(self):
        with socket.create_server((HOST, PORT)) as srv:
            print(f"🟢 Server listening on {HOST}:{PORT}")
            while True:
                sock, addr = srv.accept()
                Client(sock, addr, self).start()

if __name__ == "__main__":
    Server().serve_forever()