# server.py
import socket
import threading
import struct
import time
import random

import packet_structure as pst
from User import User  # Ensure your User class accepts a name

# Diffie–Hellman public parameters (must be the same as on the client)
p = 0xE95E4A5F737059DC60DF5991D45029409E60FC09
g = 2

HOST = "0.0.0.0"
PORT = 5000
clients = []


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

        # Add the client to the list and continue with further processing...
        clients.append(client_socket)
        while True:
            time.sleep(1)
    except Exception as e:
        print("Error handling client:", e)
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"Server listening on {HOST}:{PORT}")

    while True:
        client_socket, client_address = server.accept()
        print(f"Client {client_address} connected")
        threading.Thread(target=handle_client, args=(client_socket,), daemon=True).start()


if __name__ == "__main__":
    main()
