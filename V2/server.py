import socket, threading, json, struct, secrets
from typing import Dict, List, Tuple
from encryption import rsa_encrypt

with open("settings/server_settings.json") as f:
    SETTINGS = json.load(f)
HOST, PORT = SETTINGS["SERVER_HOST"], SETTINGS["SERVER_PORT"]

# ── helper send/recv unchanged ─────────────────────

def _send(sock: socket.socket, payload: dict):
    data = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(data)) + data)

def _recv(sock: socket.socket) -> dict:
    hdr = sock.recv(4)
    if not hdr:
        raise ConnectionError
    (ln,) = struct.unpack("!I", hdr)
    buf = b""
    while len(buf) < ln:
        part = sock.recv(ln - len(buf))
        if not part:
            raise ConnectionError
        buf += part
    return json.loads(buf.decode())

# ── Client / Room classes – only change: *no* filtering on "audio"  ──

class Client(threading.Thread):
    def __init__(self, sock, addr, server):
        super().__init__(daemon=True)
        self.sock, self.addr, self.server = sock, addr, server
        self.room_code = None
        self.name = None
        self.pub_key = None

    def run(self):
        try:
            first = _recv(self.sock)
            self.room_code = first["room_code"].upper()
            self.name      = first["name"]
            self.pub_key   = tuple(first["public_key"])

            room = self.server.get_room(self.room_code, create=True)
            room.add(self, self.pub_key)

            while True:
                msg = _recv(self.sock)
                if msg.get("type") == "leave":
                    break  # Explicit leave request
                room.broadcast(msg, exclude=self)
        except ConnectionError:
            pass
        finally:
            if self.room_code:
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
        self.clients: List[Client] = []
        self._lock = threading.Lock()

    def add(self, cl: Client, pub_key):
        with self._lock:
            self.clients.append(cl)
        enc = rsa_encrypt(self.sym_key, pub_key)
        cl.send({"type": "sym_key", "data": enc})
        self.broadcast({"type": "status", "text": f"{cl.name} joined."})

    def drop(self, cl: Client):
        with self._lock:
            if cl in self.clients:
                self.clients.remove(cl)
        self.broadcast({"type": "leave", "from": cl.name})

    def broadcast(self, msg, exclude=None):
        for c in list(self.clients):
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

    def serve_forever(self):
        with socket.create_server((HOST, PORT)) as srv:
            print(f"Server listening on {socket.gethostbyname(socket.gethostname())}:{PORT}")
            while True:
                sock, addr = srv.accept(); Client(sock, addr, self).start()

if __name__ == "__main__":
    Server().serve_forever()
