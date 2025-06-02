import socket, struct, json, threading, secrets
from encryption import rsa_encrypt, xor_bytes
import secrets


with open("settings/server_settings.json") as f:
    SETTINGS = json.load(f)
HOST, PORT = SETTINGS["SERVER_HOST"], SETTINGS["SERVER_PORT"]

#HELPERS-------------------------

def send(sock, obj, key=None):
    """
    Send a JSON message. If `key` is given, XOR‐encrypt the payload first.
    """
    data = json.dumps(obj).encode()
    if key:
        data = xor_bytes(data, key)
    sock.sendall(struct.pack("!I", len(data)) + data)

def recv(sock, key=None):
    """
    Receive a JSON message. Reads the 4‐byte length prefix, then the payload.
    If `key` is given, XOR‐decrypt the payload before parsing.
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

# ───────────────────── UserSession ──────────────────────

class UserSession:
    def __init__(self, sock, addr, name, user_id, sym_key):
        self.sock = sock
        self.addr = addr
        self.name = name
        self.user_id = user_id
        self.sym_key = sym_key
        self.room = None  # Will hold a Room instance once user joins/creates

# ─────────────────────── Room ──────────────────────────

class Room:
    def __init__(self, code):
        self.code = code
        self.users = set()      # Set of UserSession
        self.lock = threading.Lock()

    def add_user(self, user: UserSession) -> bool:
        with self.lock:
            if len(self.users) >= 4:
                return False
            self.users.add(user)
            user.room = self
            return True

    def remove_user(self, user: UserSession):
        with self.lock:
            self.users.discard(user)
            user.room = None

    def is_empty(self) -> bool:
        return len(self.users) == 0

# ─────────────────────── Server ─────────────────────────

class Server:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.users = {}   # user_id → UserSession
        self.rooms = {}   # room_code → Room
        self.lock = threading.Lock()

    def serve_forever(self):
        with socket.create_server((self.host, self.port)) as srv:
            print(f"Listening on {self.host}:{self.port}")
            while True:
                sock, addr = srv.accept()
                threading.Thread(target=self.handle_client,
                                 args=(sock, addr),
                                 daemon=True).start()

    def handle_client(self, sock: socket.socket, addr):
        user = None
        try:
            # ─── Step 1: Handshake (plaintext) ───
            msg = recv(sock)
            if msg.get("type") != "hello":
                send(sock, {"type": "error", "reason": "Handshake required"})
                sock.close()
                return

            name = msg["name"]
            user_id = secrets.token_hex(16)
            sym_key = secrets.token_bytes(16)
            pub_key = tuple(msg["public_key"])
            enc_sym_key = rsa_encrypt(sym_key, pub_key)
            send(sock, {"type": "welcome", "user_id": user_id, "sym_key": enc_sym_key})

            user = UserSession(sock, addr, name, user_id, sym_key)
            with self.lock:
                self.users[user_id] = user

            # ─── Step 2: Room create/join (encrypted) ───
            msg = recv(sock, sym_key)
            if msg.get("type") == "create_room":
                room_code = self._generate_room_code()
                room = Room(room_code)
                room.add_user(user)
                with self.lock:
                    self.rooms[room_code] = room
                send(sock, {"type": "room_created", "room_code": room_code}, sym_key)

            elif msg.get("type") == "join_room":
                room_code = msg.get("room_code", "").upper()
                with self.lock:
                    room = self.rooms.get(room_code)
                    if room is None or not room.add_user(user):
                        send(sock, {"type": "error", "reason": "Room unavailable"}, sym_key)
                        sock.close()
                        return
                send(sock, {"type": "join_ok", "room_code": room_code}, sym_key)

            else:
                send(sock, {"type": "error", "reason": "Invalid room action"}, sym_key)
                sock.close()
                return

            # ─── Step 3: Main encrypted loop ───
            while True:
                msg = recv(sock, sym_key)
                if msg.get("type") == "bye":
                    break
                # Additional encrypted messages (chat, audio, etc.) go here.
                # Example: broadcast to other users in room
                #   for other in list(user.room.users):
                #       if other is not user:
                #           send(other.sock, msg, other.sym_key)

        except ConnectionError:
            pass

        finally:
            self.cleanup(user)

    def cleanup(self, user: UserSession):
        if not user:
            return

        # Remove from room (defensive check added)
        if user.room:
            room = user.room
            room.remove_user(user)
            with self.lock:
                if room.is_empty():
                    del self.rooms[room.code]

        # Remove user from registry
        with self.lock:
            self.users.pop(user.user_id, None)

        try:
            user.sock.close()
        except Exception:
            pass

    def _generate_room_code(self, length=6) -> str:
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while True:
            code = ''.join(secrets.choice(chars) for _ in range(length))
            with self.lock:
                if code not in self.rooms:
                    return code

if __name__ == "__main__":
    Server(HOST, PORT).serve_forever()

# class Client(threading.Thread):
#     def __init__(self, sock, addr, server):
#         super().__init__(daemon=True)
#         self.sock, self.addr, self.server = sock, addr, server
#         self.room_code = None
#         self.name = None
#         self.user_id = secrets.token_hex(16)  # Unique user ID
#         self.pub_key = None
#
#     def run(self):
#         try:
#             # 1. Registration: must be the first message
#             first = _recv(self.sock)
#             if first["type"] != "register":
#                 _send(self.sock, {"type": "reject", "reason": "Must register first"})
#                 self.sock.close()
#                 return
#
#             self.user_id = secrets.token_hex(16)
#             self.name = first["name"]
#             _send(self.sock, {"type": "welcome", "user_id": self.user_id})
#
#             # 2. Wait for join/create_room request
#             second = _recv(self.sock)
#             if second["type"] == "create_room":
#                 # Generate unique room code
#                 while True:
#                     code = generate_room_code()
#                     if code not in self.server.rooms:
#                         break
#
#                 self.room_code = str(code)
#                 self.name = second["name"]
#                 self.pub_key = tuple(second["public_key"])
#                 room = self.server.get_room(self.room_code, create=True)
#                 room.add(self, self.pub_key)
#                 _send(self.sock, {"type": "room_created", "room_code": code})
#
#             elif second["type"] == "join":
#                 print(second)
#                 self.room_code = second["room_code"].upper()
#                 self.name = second["name"]
#                 self.pub_key = tuple(second["public_key"])
#                 # Only join if the room exists
#                 if self.room_code not in self.server.rooms:
#                     _send(self.sock, {"type": "reject", "reason": "Room does not exist"})
#                     self.sock.close()
#                     return
#                 room = self.server.get_room(self.room_code, create=False)
#                 if not room.add(self, self.pub_key):
#                     return
#                 # Optionally: send confirmation message here if needed
#             else:
#                 _send(self.sock, {"type": "reject", "reason": "Must join or create room after registration"})
#                 self.sock.close()
#                 return
#
#             # 3. Main message loop
#             while True:
#                 msg = _recv(self.sock)
#                 if msg.get("type") == "leave":
#                     break  # Explicit leave request
#                 room.broadcast(msg, exclude=self)
#         except ConnectionError:
#             pass
#         finally:
#             if getattr(self, "room_code", None):
#                 self.server.drop(self.room_code, self)
#             self.sock.close()
#
#     def send(self, msg):
#         try:
#             _send(self.sock, msg)
#         except OSError:
#             pass
#
# class Room:
#     def __init__(self, code):
#         self.code = code
#         self.sym_key = secrets.token_bytes(16)  # 128‑bit
#         self.clients: Dict[str, Client] = {}
#         self._lock = threading.Lock()
#
#     def add(self, cl: Client, pub_key):
#         with self._lock:
#             if len(self.clients) >= 4:
#                 cl.send({"type": "reject", "reason": "Room is full"})
#                 cl.sock.close()
#                 return False
#             self.clients[cl.user_id] = cl
#         enc = rsa_encrypt(self.sym_key, pub_key)
#         cl.send({"type": "sym_key", "data": enc, "user_id": cl.user_id})
#         self.broadcast({"type": "status", "text": f"{cl.name} joined.", "user_id": cl.user_id})
#         return True
#
#     def drop(self, cl: Client):
#         with self._lock:
#             self.clients.pop(cl.user_id, None)
#         self.broadcast({"type": "leave", "from": cl.user_id, "name": cl.name})
#
#     def broadcast(self, msg, exclude=None):
#         for c in list(self.clients.values()):
#             if c is not exclude:
#                  c.send(msg)
#
# class Server:
#     def __init__(self):
#         self.rooms: Dict[str, Room] = {}
#         self._lock = threading.Lock()
#
#     def get_room(self, code, create=False):
#         with self._lock:
#             if code not in self.rooms and create:
#                 self.rooms[code] = Room(code)
#             return self.rooms[code]
#
#     def drop(self, code, cl):
#         with self._lock:
#             if code in self.rooms:
#                 self.rooms[code].drop(cl)
#                 if not self.rooms[code].clients:
#                     del self.rooms[code]
#                     print(f"Room {code} is empty and has been removed.")
#
#     def serve_forever(self):
#         with socket.create_server((HOST, PORT)) as srv:
#             print(f"Server listening on {socket.gethostbyname(socket.gethostname())}:{PORT}")
#             while True:
#                 sock, addr = srv.accept(); Client(sock, addr, self).start()
#
# if __name__ == "__main__":
#     Server().serve_forever()
