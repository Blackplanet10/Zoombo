import socket
import threading

# Server Configuration
HOST = '0.0.0.0'
PORT = 5000

clients = []


def handle_client(client_socket, client_address):
    while True:
        try:
            # Wait for another client to connect
            if len(clients) < 2:
                continue  # Wait until another client is available

            # Determine the other client
            other_client = clients[1] if clients[0] == client_socket else clients[0]

            # Receive video data from one client and send to the other
            data = client_socket.recv(1024)
            if not data:
                break
            if other_client:
                other_client.send(data)
        except Exception as e:
            print(f"Error handling client {client_address}: {e}")
            break

    # Remove the client and close the connection
    clients.remove(client_socket)
    client_socket.close()

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
