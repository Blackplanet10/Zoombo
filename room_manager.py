# room_manager.py
import random, string, threading


class RoomManager:
    """
    Thread‑safe in‑memory room registry.
    Code format: 6 chars [A‑Z0‑9]; feel free to tweak length or charset.
    """
    def __init__(self) -> None:
        self._rooms: dict[str, list] = {}          # code → [User]
        self._lock = threading.Lock()

    # ---------- public API ---------- #

    def create_room(self, owner):
        """Generate an unused code and register the owner as first member."""
        with self._lock:
            code = self._fresh_code()
            self._rooms[code] = [owner]
        return code

    def join_room(self, code: str, user) -> bool:
        """Add user to existing room, return success flag."""
        with self._lock:
            if code in self._rooms:
                self._rooms[code].append(user)
                return True
        return False

    def members(self, code: str):
        with self._lock:
            return list(self._rooms.get(code, []))

    # ---------- helpers ---------- #

    def _fresh_code(self, k: int = 6):
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=k))
            if code not in self._rooms:
                return code
