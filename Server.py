# server.py
import socket
import threading
import struct
import time
import random

import packet_structure as pst
from User import User  # Ensure your User class accepts a name
from room_manager import RoomManager

# Diffie–Hellman public parameters (must be the same as on the client)
p = 0xE95E4A5F737059DC60DF5991D45029409E60FC09
g = 2

HOST = "0.0.0.0"
PORT = 5000
clients = []
rooms = RoomManager()
sockets = {}                    # socket → {"user":User, "room":str}

def broadcast_room_size(room_code: str):
    count = len(rooms.members(room_code))
    pkt   = pst.ServerPacketStructure.RoomSize(count)
    envelope = struct.pack("Q", len(pkt)) + pkt
    for s, meta in sockets.items():
        if meta["room"] == room_code:
            s.sendall(envelope)


def handle_client(client_socket):
    try:
        # --- Receive handshake header (8 bytes) ---
        payload_size = struct.calcsize("Q")
        header = b""
        while len(header) < payload_size:
            packet = client_socket.recv(payload_size - len(header))
            if not packet:
                print("Client disconnected during handshake.")
                return
            header += packet
        packet_length = struct.unpack("Q", header)[0]

        # --- Receive handshake packet ---
        handshake_data = b""
        while len(handshake_data) < packet_length:
            handshake_data += client_socket.recv(packet_length - len(handshake_data))

        # Expected format: "200,handshake,<name>,<A>"
        if handshake_data.startswith(b"200"):
            handshake_str = handshake_data.decode('utf-8')
            parts = handshake_str.split(',', 3)
            if len(parts) < 4:
                print("Handshake packet malformed, missing fields.")
                return
            client_name = parts[2]
            try:
                A = int(parts[3])
            except ValueError:
                print("Invalid client public value.")
                return
            print("Received handshake from client with name:", client_name)
            # Create a new User object with the provided name
            user = User(client_name)
            user_id = user.id

            # --- Diffie–Hellman: Server generates secret and computes public value ---
            b = random.randint(2, p - 2)
            B = pow(g, b, p)
            shared_key = pow(A, b, p)
            print("Shared key established for user", client_name, ":", shared_key)

            # --- Build handshake acknowledgment ---
            ack_packet = pst.ServerPacketStructure.HandshakeResponse(user_id, B)
            ack_header = struct.pack("Q", len(ack_packet))
            client_socket.sendall(ack_header + ack_packet)
            print("Sent handshake response to client.")
        else:
            print("Expected handshake but got:", handshake_data)
            return



        # ---------------- main recv loop ---------------- #

        clients.append({"sock": client_socket, "user": user})
        sockets[client_socket] = {"user": user, "room": None}

        while True:
        # --- 8‑byte length prefix ---
            header = client_socket.recv(struct.calcsize("Q"))

            if not header:
                break
            pkt_len = struct.unpack("Q", header)[0]
            data = b""

            while len(data) < pkt_len:
                chunk = client_socket.recv(pkt_len - len(data))
                if not chunk:
                    break
                data += chunk

          # ---------------- packet switcher ----------------

            if data.startswith(b"204"):  # create room
                code = rooms.create_room(user)
                sockets[client_socket]["room"] = code
                reply = pst.ServerPacketStructure.RoomCreated(code)
                client_socket.sendall(struct.pack("Q", len(reply)) + reply)
                broadcast_room_size(code)

            elif data.startswith(b"205"):  # join room
                code = data.decode().split(',')[2]
                if rooms.join_room(code, user):
                    sockets[client_socket]["room"] = code
                    broadcast_room_size(code)
                    reply = pst.ServerPacketStructure.JoinAck(code)
                else:
                    reply = b"405,join_error"
                client_socket.sendall(struct.pack("Q", len(reply)) + reply)

            elif data.startswith(b"201"):  # video+audio
                header_str, payload = data.split(b',', 3)[0:3], data.split(b',', 3)[3]
                vid_len = int(header_str[1])
                aud_len = int(header_str[2])
                vid = payload[:vid_len]
                aud = payload[vid_len:vid_len + aud_len]

                room_code = sockets[client_socket]["room"]
                if room_code:
                    pkt = pst.ServerPacketStructure.VidAud(user_id, vid, aud)
                    envelope = struct.pack("Q", len(pkt)) + pkt
                    for s, meta in sockets.items():
                        if meta["room"] == room_code and s is not client_socket:
                            s.sendall(envelope)



    except Exception as e:
        print("Error handling client:", e)
    finally:
        meta = sockets.pop(client_socket, None)
        if meta and meta["room"]:
            rooms.leave_room(meta["room"], meta["user"])
            broadcast_room_size(meta["room"])
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(5)
    # print(f"Server listening on {HOST}:{PORT}")
    print(f"Server listening on {socket.gethostbyname(socket.gethostname())}:{PORT}")


    while True:
        client_socket, client_address = server.accept()
        print(f"Client {client_address} connected")
        threading.Thread(target=handle_client, args=(client_socket,), daemon=True).start()


if __name__ == "__main__":
    main()