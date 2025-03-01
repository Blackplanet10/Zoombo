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

class ServerPacketStructure:
    def VidAud(user_id,vid: bytes, aud: bytes):
        vid_len = f"{(9 - len(vid)) * '0'}{vid}"
        aud_len = f"{(9 - len(aud)) * '0'}{aud}"
        user_id = str(user_id)
        user_id = f"{(3 - len(user_id)) * '0'}{user_id}"

        reqeust = f"301,{user_id},{vid_len},{aud_len},"  # len 24 to read after 301

        return str.encode(reqeust)



CODES ={
    #200 client codes
    201: "Video and Audio",
    202: "Text Message",
    202: "Request settings File",




    #300 server codes
    301: "User ID, Video and Audio",
    302: "User ID, Text Message",
    303: "Send settings File"



    #400 codes for both server and client

    }