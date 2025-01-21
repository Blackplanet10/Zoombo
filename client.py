
import pickle
import struct

import cv2
import socket
import threading
import numpy as np


# Server Configuration
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# Frame settings
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

def receive_video(sock):

    data = b""
    payload_size = struct.calcsize("Q")
    while True:
        try:

            while len(data) < payload_size:
                packet = sock.recv(4 * 1024)  # 4k buffer
                if not packet:
                    break
                data += packet
            if not data:
                break

            # Reconstruct frame from data
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("Q", packed_msg_size)[0]

            while len(data) < msg_size:
                data += sock.recv(4*1024) # 4k again

            frame_data = data[:msg_size]
            data = data[msg_size:]

            # Display the video frame

            frame = pickle.loads(frame_data)
            cv2.imshow('Client', frame)


        except Exception as e:
            print(f"Error receiving video: {e}")
            break

def main():
    # Connect to server
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_HOST, SERVER_PORT))
    print(f"Connected to server at {SERVER_HOST}:{SERVER_PORT}")

    # Start video receiving thread
    threading.Thread(target=receive_video, args=(sock,), daemon=True).start()

    # Capture video and send to server
    cap = cv2.VideoCapture(0)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_data = pickle.dumps(frame)
        sock.sendall(struct.pack("Q", len(frame_data)))
        sock.sendall(frame_data)


        # Display own video
        cv2.imshow("Your Video", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    sock.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
