# module to build packets using tamplate

class ClientPacketStructure:
    def VidAud(vid: bytes, aud: bytes) -> bytes:
        """
             Build 201 (Video+Audio) packet:
              201,<VID_LEN:09d>,<AUD_LEN:09d>,<JPEG‑bytes><PCM‑bytes>
        """
        header = f"201,{len(vid):09d},{len(aud):09d},".encode()

        return header + vid + aud

        return str.encode(reqeust)

    def Settings(self):
        request = f"203"
        return str.encode(request)

    @staticmethod
    def Handshake(name: str, client_public: int):
        # Format: "200,handshake,<name>,<client_public>"
        return str.encode(f"200,handshake,{name},{client_public}")

    @staticmethod
    def CreateRoom():  # 204
        return b"204,create_room"

    @staticmethod
    def JoinRoom(code: str):  # 205
        return f"205,join_room,{code}".encode()


class ServerPacketStructure:
    def VidAud(user_id, vid: bytes, aud: bytes)  -> bytes :
        """
            301,<UID:03d>,<VID_LEN:09d>,<AUD_LEN:09d>,<JPEG‑bytes><PCM‑bytes>
        """
        header = f"301,{user_id:03d},{len(vid):09d},{len(aud):09d},".encode()
        return header + vid + aud

    @staticmethod
    def HandshakeResponse(user_id, server_public: int):
        # Format: "300,<user_id>,handshake_ack,<server_public>"
        user_id_str = str(user_id)
        user_id_str = f"{(3 - len(user_id_str)) * '0'}{user_id_str}"
        return str.encode(f"300,{user_id_str},handshake_ack,{server_public}")

    @staticmethod
    def RoomCreated(code: str):  # 304
        return f"304,room_created,{code}".encode()

    @staticmethod
    def JoinAck(code: str):  # 305
        return f"305,join_ack,{code}".encode()


CODES = {
    #200 client codes
    201: "Video and Audio",
    202: "Text Message",
    203: "Request settings File",
    204: "Create room request",
    205: "Join room request",

    #300 server codes
    301: "User ID, Video and Audio",
    302: "User ID, Text Message",
    303: "Send settings File",
    304: "Room created (code)",
    305: "Joined room ack"

    #400 codes for both server and client

}
