# module to build packets using tamplate



class ClientPacketStructure:
    def __int__(self):
        return True

    def VidAud(self, vid:bytes, aud:bytes):

        vid_len = f"{(9-len(vid)) * '0'}{vid}"
        aud_len = f"{(9-len(aud)) * '0'}{aud}"

        reqeust = f"201,{vid_len},{aud_len}," # len 20 to read after 201

        return reqeust


class ServerPacketStructure:
    def __int__(self):
        return True

    def VidAud(self, user_id,vid: bytes, aud: bytes):
        vid_len = f"{(9 - len(vid)) * '0'}{vid}"
        aud_len = f"{(9 - len(aud)) * '0'}{aud}"
        user_id = f"{(3 - len(user_id)) * '0'}{user_id}"

        reqeust = f"301,{user_id},{vid_len},{aud_len},"  # len 20 to read after 201

        return reqeust



CODES ={
    #200 client codes
    201: "Video and Audio",





    #300 server codes
    301: "User ID, Video and Audio",




    #400 codes for both server and client

    }