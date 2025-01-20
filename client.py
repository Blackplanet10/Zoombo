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
    while True:
        try:
            data = sock.recv(1024)
            if not data:
                break

            # Reconstruct frame from data
            nparr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            # Display the video frame
            if frame is not None:
                cv2.imshow("Other Client", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
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

        # Encode frame
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        sock.sendall(buffer)

        # Display own video
        cv2.imshow("Your Video", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    sock.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
