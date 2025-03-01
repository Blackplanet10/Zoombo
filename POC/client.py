import pickle
import struct
import cv2
import socket
import threading
import numpy as np
import time


import packet_structure

# Server Configuration
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5000

# Frame settings
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

PIP_WIDTH = 180  # Picture-in-Picture (your video) width
PIP_HEIGHT = 135  # Picture-in-Picture height

TARGET_FPS = 15

JPEG_QUALITY = 30  # Compression level (lower = more compression, 40 is a good balance)

empty_frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)

# Variable to store the last received partner frame
partner_frame = empty_frame.copy()


def receive_video(sock):
    global partner_frame
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
            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)

            if frame is not None:
                partner_frame = frame  # Update global variable
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print("Received invalid frame data.")

        except Exception as e:
            print(f"Error receiving video: {e}")
            break

    cv2.destroyAllWindows()


def main():

    global partner_frame
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
            small_frame = cv2.resize(frame, (PIP_WIDTH, PIP_HEIGHT))


            _, compressed_frame = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            frame_data = compressed_frame.tobytes()  # Convert to byte format

            # Send frame
            try:
                sock.sendall(struct.pack("Q", len(frame_data)))
                sock.sendall(frame_data)
            except Exception as e:
                print(f"Error sending video: {e}")
                break


            x_offset = FRAME_WIDTH - PIP_WIDTH - 20  # 20px margin from right
            y_offset = 20  # 20px margin from top

            background = partner_frame.copy()
            background[y_offset:y_offset + PIP_HEIGHT, x_offset:x_offset + PIP_WIDTH] = small_frame

            #Display combined frame
            cv2.imshow("Video Chat", background)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    sock.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
