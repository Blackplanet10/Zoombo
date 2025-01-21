import socket
import threading
import struct

# Server Configuration
HOST = '0.0.0.0'
PORT = 5000

clients = []


def handle_client(client_socket, client_address):
    try:
        while True:
            if len(clients) < 2:
                continue  # Wait until another client is available

            other_client = clients[1] if clients[0] == client_socket else clients[0]
            # Receive frame header
            header = b""
            while len(header) < struct.calcsize("Q"):
                packet = client_socket.recv(8 - len(header))
                if not packet:
                    print("Client disconnected.")
                    return  # Exit the thread
                header += packet

            # Extract frame size
            frame_size = struct.unpack("Q", header)[0]

            # Receive the full frame
            frame_data = b""
            while len(frame_data) < frame_size:
                packet = client_socket.recv(min(frame_size - len(frame_data), 4096))
                if not packet:
                    print("Client disconnected.")
                    return  # Exit the thread
                frame_data += packet

            # Relay the frame to the other client
            if other_client:
                other_client.sendall(header + frame_data)
    except ConnectionAbortedError:
        print("Connection was aborted.")
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        if client_socket in clients:
            clients.remove(client_socket)
        client_socket.close()

def handle_client2(client_socket, client_address):
    while True:
        try:

            if len(clients) < 2:
                continue  # Wait until another client is available

            # Determine the other client
            other_client = clients[1] if clients[0] == client_socket else clients[0]

            header = b""
            while len(header) < struct.calcsize("Q"):
                packet = client_socket.recv(8 - len(header))
                if not packet:
                    return  # Connection closed
                header += packet

            frame_size = struct.unpack("Q", header)[0]

            frame_data = b""
            while len(frame_data) < frame_size:
                packet = client_socket.recv(min(frame_size - len(frame_data), 4096))
                if not packet:
                    return  # Connection closed
                frame_data += packet

            if other_client:
                other_client.sendall(header + frame_data)
        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            if client_socket in clients:
                clients.remove(client_socket)
            client_socket.close()


    # Remove the client and close the connection
    clients.remove(client_socket)
    client_socket.close()
    print(f"Client {client_address} disconnected")


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(2)
    print(f"Server listening on {HOST}:{PORT}")

    while len(clients) < 2:
        client_socket, client_address = server.accept()
        print(f"Client {client_address} connected")
        clients.append(client_socket)
        threading.Thread(target=handle_client, args=(client_socket, client_address)).start()

if __name__ == "__main__":
    main()
