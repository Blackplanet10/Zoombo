import socket, threading, json, struct, secrets
from typing import Dict, List, Tuple
from encryption import rsa_encrypt
import string, random
import secrets
import base64


with open("settings/server_settings.json") as f:
    SETTINGS = json.load(f)
HOST, PORT = SETTINGS["SERVER_HOST"], SETTINGS["SERVER_PORT"]

#HELPERS-------------------------

def generate_room_code(length=6):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(random.choices(chars, k=length))

def _send(sock: socket.socket, payload: dict):
    data = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(data)) + data)

def _recv(sock: socket.socket) -> dict:
    hdr = b""
    while len(hdr) < 4:
        part = sock.recv(4 - len(hdr))
        if not part:
            raise ConnectionError
        hdr += part
    (ln,) = struct.unpack("!I", hdr)
    buf = b""
    while len(buf) < ln:
        part = sock.recv(ln - len(buf))
        if not part:
            raise ConnectionError
        buf += part
    return json.loads(buf.decode())

#CLASSES-----------------------------

class Client(threading.Thread):
    def __init__(self, sock, addr, server):
        super().__init__(daemon=True)
        self.sock, self.addr, self.server = sock, addr, server
        self.room_code = None
        self.name = None
        self.user_id = secrets.token_hex(16)  # Unique user ID
        self.pub_key = None

    def run(self):
        try:
            # 1. Registration: must be the first message
            first = _recv(self.sock)
            if first["type"] != "register":
                _send(self.sock, {"type": "reject", "reason": "Must register first"})
                self.sock.close()
                return

            self.user_id = secrets.token_hex(16)
            self.name = first["name"]
            _send(self.sock, {"type": "welcome", "user_id": self.user_id})

            # 2. Wait for join/create_room request
            second = _recv(self.sock)
            if second["type"] == "create_room":
                # Generate unique room code
                while True:
                    code = generate_room_code()
                    if code not in self.server.rooms:
                        break

                self.room_code = str(code)
                self.name = second["name"]
                self.pub_key = tuple(second["public_key"])
                room = self.server.get_room(self.room_code, create=True)
                room.add(self, self.pub_key)
                _send(self.sock, {"type": "room_created", "room_code": code})

            elif second["type"] == "join":
                print(second)
                self.room_code = second["room_code"].upper()
                self.name = second["name"]
                self.pub_key = tuple(second["public_key"])
                # Only join if the room exists
                if self.room_code not in self.server.rooms:
                    _send(self.sock, {"type": "reject", "reason": "Room does not exist"})
                    self.sock.close()
                    return
                room = self.server.get_room(self.room_code, create=False)
                if not room.add(self, self.pub_key):
                    return
                # Optionally: send confirmation message here if needed
            else:
                _send(self.sock, {"type": "reject", "reason": "Must join or create room after registration"})
                self.sock.close()
                return

            # 3. Main message loop
            while True:
                msg = _recv(self.sock)
                if msg.get("type") == "leave":
                    break  # Explicit leave request
                room.broadcast(msg, exclude=self)
        except ConnectionError:
            pass
        finally:
            if getattr(self, "room_code", None):
                self.server.drop(self.room_code, self)
            self.sock.close()

    def send(self, msg):
        try:
            _send(self.sock, msg)
        except OSError:
            pass

class Room:
    def __init__(self, code):
        self.code = code
        self.sym_key = secrets.token_bytes(16)  # 128‑bit
        self.nonce = secrets.token_bytes(8)      # 64‑bit nonce
        self.clients: Dict[str, Client] = {}
        self._lock = threading.Lock()

    def add(self, cl: Client, pub_key):
        with self._lock:
            if len(self.clients) >= 4:
                cl.send({"type": "reject", "reason": "Room is full"})
                cl.sock.close()
                return False
            self.clients[cl.user_id] = cl
        enc = rsa_encrypt(self.sym_key, pub_key)  # enc is bytes
        enc_b64 = base64.b64encode(enc).decode('ascii')  # Convert bytes to base64 string
        cl.send({"type": "sym_key", "data": enc_b64, "user_id": cl.user_id, "nonce": self.nonce.hex()})
        self.broadcast({"type": "status", "text": f"{cl.name} joined.", "user_id": cl.user_id})
        return True

    def drop(self, cl: Client):
        with self._lock:
            self.clients.pop(cl.user_id, None)
        self.broadcast({"type": "leave", "from": cl.user_id, "name": cl.name})

    def broadcast(self, msg, exclude=None):
        for c in list(self.clients.values()):
            if c is not exclude:
                 c.send(msg)

class Server:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self._lock = threading.Lock()

    def get_room(self, code, create=False):
        with self._lock:
            if code not in self.rooms and create:
                self.rooms[code] = Room(code)
            return self.rooms[code]

    def drop(self, code, cl):
        with self._lock:
            if code in self.rooms:
                self.rooms[code].drop(cl)
                if not self.rooms[code].clients:
                    del self.rooms[code]
                    print(f"Room {code} is empty and has been removed.")

    def serve_forever(self):
        with socket.create_server((HOST, PORT)) as srv:
            print(f"Server listening on {socket.gethostbyname(socket.gethostname())}:{PORT}")
            while True:
                sock, addr = srv.accept(); Client(sock, addr, self).start()

if __name__ == "__main__":
    Server().serve_forever()