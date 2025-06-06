import socket, threading, json, struct, secrets
from typing import Dict, List, Tuple
from encryption import rsa_encrypt, aes_encrypt, aes_decrypt, generate_rsa_keypair
import string, random
import secrets
import base64


with open("settings/server_settings.json") as f:
    SETTINGS = json.load(f)
HOST, PORT = SETTINGS["SERVER_HOST"], SETTINGS["SERVER_PORT"]

#HELPERS-------------------------

def generate_room_code(length=6) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(random.choices(chars, k=length))

def _send(sock: socket.socket, payload: dict):
    data = json.dumps(payload).encode()
    sock.sendall(struct.pack("!I", len(data)) + data)

def _send_encrypted(sock: socket.socket, payload: dict, sym_key: bytes, nonce: bytes):
    """
    Encrypt `payload` using AES with `sym_key` and `nonce`, then send it.
    """
    blob = json.dumps(payload).encode()
    enc = aes_encrypt(blob, sym_key, nonce)
    enc_b64 = base64.b64encode(enc).decode("ascii")
    msg = {"type": "aes_blob", "data": enc_b64}
    _send(sock, msg)

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


def _recv_encrypted(sock: socket.socket, sym_key: bytes, nonce: bytes) -> dict:
    """
    Receive an AES-encrypted message, decrypt it using `sym_key` and `nonce`,
    and return the decoded JSON object.
    """
    msg = _recv(sock)
    if msg.get("type") != "aes_blob":
        raise ValueError("Expected 'aes_blob' type")

    enc_b64 = msg["data"]
    enc_bytes = base64.b64decode(enc_b64)
    plain = aes_decrypt(enc_bytes, sym_key, nonce)
    return json.loads(plain.decode())

#CLASSES-----------------------------

class Client(threading.Thread):
    """
    A client represents a connected user in the server.
    """

    def __init__(self, sock, addr, server):
        super().__init__(daemon=True)
        self.sock, self.addr, self.server = sock, addr, server
        self.room_code = None
        self.name = ""
        self.user_id = secrets.token_hex(16)  # Unique user ID
        self.sym_key = None
        self.nonce = secrets.token_bytes(8)

    def run(self):
        try:
            # 0. Initial handshake: must exchange symmetric key first. If not, reject.
            first = _recv(self.sock)
            if first["type"] == "exchange_sym":
                self.sym_key = secrets.token_bytes(16)
                enc_key = rsa_encrypt(self.sym_key, first["public_key"])
                sym_key_b64 = base64.b64encode(enc_key).decode("ascii")
                _send(self.sock, {
                    "type": "exchange_sym_response",
                    "sym_key": sym_key_b64,
                    "nonce": self.nonce.hex()
                })

            else:
                _send(self.sock, {"type": "reject", "reason": "Must exchange symmetric key first "})
                self.sock.close()
                return

            # 1. Wait for registration request to get ID from server.
            msg = _recv_encrypted(self.sock, self.sym_key, self.nonce)
            if msg["type"] == "register":
                self.user_id = secrets.token_hex(16)
                self.name = msg["name"]
                register_response = {
                    "type": "register_response",
                    "user_id": self.user_id
                }
                _send_encrypted(self.sock, register_response, self.sym_key, self.nonce)
            else:
                # If not a registration request, reject and close.
                _send_encrypted(self.sock, {"type": "reject", "reason": "Must register first"}, self.sym_key, self.nonce)
                self.sock.close()
                return

            # 2. Wait for join/create_room request.
            room_code = self.create_or_join_room()
            room = self.server.get_room(room_code, create=False)

            # 3. Main message loop
            while True:
                msg = _recv_encrypted(self.sock, self.sym_key, self.nonce)
                if msg.get("type") == "leave":
                    break  # Explicit leave request
                room.broadcast(msg, exclude_client_id=self.user_id)
        except ConnectionError:
            pass
        finally:
            self.server.drop(self.room_code, self)
            self.sock.close()

    def send(self, msg):
        try:
            _send_encrypted(self.sock, msg, self.sym_key, self.nonce)
        except OSError:
            pass

    def create_or_join_room(self):
        """
        Wait for a message from the client to either create a new room or join an existing one.
        :returns: The room code if a room is created or joined, otherwise None.
        """
        msg = _recv_encrypted(self.sock, self.sym_key, self.nonce)
        if msg["type"] == "create_room":
            # Generate unique room code
            code = generate_room_code()
            while code in self.server.rooms:
                code = generate_room_code()

            self.room_code = code
            room = self.server.get_room(self.room_code, create=True)
            room.add(self)
            print("Room created:", self.room_code)
            _send_encrypted(self.sock, {"type": "room_created", "room_code": code}, self.sym_key, self.nonce)
            # Wait for the client to join the room after creation.
            return self.create_or_join_room()

        elif msg["type"] == "join":
            # Check if the room exists, if not reject and close the connection.
            room_code = msg["room_code"].upper()
            if room_code not in self.server.rooms:
                payload = {
                    "type": "reject",
                    "reason": "Room does not exist"
                }
                _send_encrypted(self.sock, payload, self.sym_key, self.nonce)
                self.sock.close()
                return None

            # Room code exists, so join it.
            self.room_code = room_code
            room = self.server.get_room(self.room_code, create=False)
            if not room.add(self):
                return None

            # Send confirmation of joining the room.
            payload = {
                "type": "room_joined",
                "room_code": self.room_code,
                "user_id": self.user_id
            }
            _send_encrypted(self.sock, payload, self.sym_key, self.nonce)
            return self.room_code

        else:
            _send_encrypted(self.sock, {"type": "reject", "reason": "Must join or create room after registration"},
                            self.sym_key, self.nonce)
            self.sock.close()
            return None


class Room:
    def __init__(self, code):
        self.code = code
        self.clients: Dict[str, Client] = {}
        self._lock = threading.Lock()

    def add(self, client: Client) -> bool:
        """
        1) Add `client` to this room’s client list.
        2) Broadcast the same “status” to any existing members in the room.
        """

        with self._lock:
            # If the room is full, reject the client.
            if len(self.clients) >= 4:
                client.send({"type": "reject", "reason": "Room is full"})
                client.sock.close()
                return False

            # 1) Add the client to the room's client list.
            self.clients[client.user_id] = client

        # 2) Broadcast a 'status' message to all clients in the room.
        inner = {
            "type": "status",
            "room_code": self.code,
            "initial_status": f"{client.name} joined.",
            "user_id": client.user_id
        }
        self.broadcast(inner, client.user_id)

        return True

    def drop(self, cl: "Client"):
        with self._lock:
            if cl.user_id in self.clients:
                self.clients.pop(cl.user_id, None)
        # Plaintext "leave" is fine (or you could AES-encrypt it if you prefer)
        self.broadcast({"type": "leave", "from": cl.user_id, "name": cl.name})

    def broadcast(self, msg: dict, exclude_client_id: str = None):
        """
        Broadcast a message to all clients in this room, except the one with `exclude_client_id`.
        """
        with self._lock:
            for c in list(self.clients.values()):
                if c.user_id != exclude_client_id:
                    c.send(msg)

class Server:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self._lock = threading.Lock()

    def get_room(self, code, create=False) -> Room:
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