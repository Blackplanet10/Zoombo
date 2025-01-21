import socket
import threading
import struct

# Server Configuration
HOST = '0.0.0.0'
PORT = 5000

clients = []


def handle_client(client_socket):
    try:
        while True:
            if len(clients) < 2:
                continue  # Wait for both clients to connect

            # Identify the other client
            other_client = clients[1] if clients[0] == client_socket else clients[0]

            # Receive frame header
            header = b""
            while len(header) < struct.calcsize("Q"):
                packet = client_socket.recv(8 - len(header))
                if not packet:
                    print("Client disconnected.")
                    return
                header += packet

            # Extract frame size
            frame_size = struct.unpack("Q", header)[0]

            # Receive the full frame
            frame_data = b""
            while len(frame_data) < frame_size:
                packet = client_socket.recv(min(frame_size - len(frame_data), 4096))
                if not packet:
                    print("Client disconnected.")
                    return
                frame_data += packet

            # Relay the frame to the other client
            if other_client:
                other_client.sendall(header + frame_data)
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(2)
    print(f"Server listening on {HOST}:{PORT}")

    while True:
        client_socket, client_address = server.accept()
        print(f"Client {client_address} connected")
        clients.append(client_socket)
        threading.Thread(target=handle_client, args=(client_socket,), daemon=True).start()


if __name__ == "__main__":
    main()
