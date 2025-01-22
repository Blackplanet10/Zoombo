import pickle
import struct
import cv2
import socket
import threading
import numpy as np
import time

# Server Configuration
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# Frame settings
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
SELF_FRAME_WIDTH = 256
SELF_FRAME_HEIGHT = 192

TARGET_FPS = 15




def receive_video(sock):
    data = b""
    payload_size = struct.calcsize("Q")
    while True:
        try:
            # Receive header
            while len(data) < payload_size:
                packet = sock.recv(4 * 1024)  # 4K buffer
                if not packet:
                    print("Connection closed by server.")
                    return
                data += packet

            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("Q", packed_msg_size)[0]

            # Receive frame data
            while len(data) < msg_size:
                data += sock.recv(4 * 1024)

            frame_data = data[:msg_size]
            data = data[msg_size:]

            # Deserialize and display frame
            frame = pickle.loads(frame_data)

            if isinstance(frame, np.ndarray):
                cv2.imshow("Received Video", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print("Received invalid frame data.")

        except Exception as e:
            print(f"Error receiving video: {e}")
            break

    cv2.destroyAllWindows()


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_HOST, SERVER_PORT))
    print(f"Connected to server at {SERVER_HOST}:{SERVER_PORT}")

    threading.Thread(target=receive_video, args=(sock,), daemon=True).start()

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    last_frame_time = time.time()
    frame_delay = 1 / TARGET_FPS

    while cap.isOpened():

        current_time = time.time()

        # Only process frames when the target frame interval has passed
        if current_time - last_frame_time >= frame_delay:
            last_frame_time = current_time

            ret, frame = cap.read()
            if not ret:
                print("Failed to capture frame from webcam.")
                break

            # Resize and encode frame
            frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            frame_self = cv2.resize(frame, (SELF_FRAME_WIDTH, SELF_FRAME_HEIGHT))

            frame_data = pickle.dumps(frame)

            # Send frame
            try:
                sock.sendall(struct.pack("Q", len(frame_data)))
                sock.sendall(frame_data)
            except Exception as e:
                print(f"Error sending video: {e}")
                break

            # Display own video
            cv2.imshow("Your Video", frame_self)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    sock.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
