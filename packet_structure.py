# module to build packets using tamplate

class ClientPacketStructure:
    def VidAud(vid:bytes, aud:bytes):

        vid_len = f"{(9-len(vid)) * '0'}{len(vid.encode('utf-8'))}"
        aud_len = f"{(9-len(aud)) * '0'}{len(aud.encode('utf-8'))}"

        reqeust = f"201,{vid_len},{aud_len}," # len 20 to read after 201

        return str.encode(reqeust)

    def Settings(self):

        request = f"203"
        return str.encode(request)

    @staticmethod
    def Handshake(name: str, client_public: int):
        # Format: "200,handshake,<name>,<client_public>"
        return str.encode(f"200,handshake,{name},{client_public}")


class ServerPacketStructure:
    def VidAud(user_id,vid: bytes, aud: bytes):
        vid_len = f"{(9 - len(vid)) * '0'}{vid}"
        aud_len = f"{(9 - len(aud)) * '0'}{aud}"
        user_id = str(user_id)
        user_id = f"{(3 - len(user_id)) * '0'}{user_id}"

        reqeust = f"301,{user_id},{vid_len},{aud_len},"  # len 24 to read after 301

        return str.encode(reqeust)

    @staticmethod
    def HandshakeResponse(user_id, server_public: int):
        # Format: "300,<user_id>,handshake_ack,<server_public>"
        user_id_str = str(user_id)
        user_id_str = f"{(3 - len(user_id_str)) * '0'}{user_id_str}"
        return str.encode(f"300,{user_id_str},handshake_ack,{server_public}")


CODES ={
    #200 client codes
    201: "Video and Audio",
    202: "Text Message",
    203: "Request settings File",




    #300 server codes
    301: "User ID, Video and Audio",
    302: "User ID, Text Message",
    303: "Send settings File"



    #400 codes for both server and client

    }