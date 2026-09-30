# Import everything as necessary 
import ctypes
import ctypes.wintypes
import socket
import time
import cv2
import mss
import numpy as np

# Fixing dpi awareness for personal monitor (Mine is high-res Q)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# Config, can be easily changed if needed
LIVESPLIT_HOST = "127.0.0.1"
LIVESPLIT_PORT = 16834

START_THRESHOLD = 0.78
VICTORY_THRESHOLD = 0.83

START_CONSECUTIVE_REQUIRED = 2
VICTORY_CONSECUTIVE_REQUIRED = 3

# Sets bounds for the victory screen detection box.
# This is a box in the center of the screen that is scaled to the current resolution.
VICTORY_BOX_1080P = (650, 360, 620, 300)

STATE_IDLE = 0
STATE_RUNNING = 1


class LiveSplitClient:

    def __init__(self, host=LIVESPLIT_HOST, port=LIVESPLIT_PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.connect()

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            print(f"[+] Connected to LiveSplit Server on {self.host}:{self.port}")
        except ConnectionRefusedError:
            print("[-] Could not connect to LiveSplit. Start TCP Server first!")
            self.sock = None

    def send_command(self, cmd: str):
        if self.sock:
            try:
                self.sock.sendall(f"{cmd}\r\n".encode("utf-8"))
            except Exception as e:
                print(f"[-] Socket error: {e}")
                self.sock = None

    def start(self):
        self.send_command("starttimer")

    def split(self):
        self.send_command("split")

    def reset(self):
        self.send_command("reset")


def get_game_canvas_rect(window_name="LimbusCompany"):
    """Locks onto the pure in-game render canvas (excluding title bar & borders)."""
    hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
    if hwnd:
        client_rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client_rect))
        pt = ctypes.wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))

        w = client_rect.right - client_rect.left
        h = client_rect.bottom - client_rect.top
        return {"left": pt.x, "top": pt.y, "width": w, "height": h}
    return None


def get_victory_roi(canvas_rect, box_1080p):
    bx, by, bw, bh = box_1080p
    scale_x = canvas_rect["width"] / 1920.0
    scale_y = canvas_rect["height"] / 1080.0

    return {
        "left": int(canvas_rect["left"] + bx * scale_x),
        "top": int(canvas_rect["top"] + by * scale_y),
        "width": int(bw * scale_x),
        "height": int(bh * scale_y),
    }


def match_template(sct, capture_box, template_gray):
    screenshot = np.array(sct.grab(capture_box))
    screen_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2GRAY)

    if (
        template_gray.shape[0] > screen_gray.shape[0]
        or template_gray.shape[1] > screen_gray.shape[1]
    ):
        return 0.0

    result = cv2.matchTemplate(
        screen_gray, template_gray, cv2.TM_CCOEFF_NORMED
    )
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return max_val


def load_image(filename_base):
    for ext in [".webp", ".png", ".jpg"]:
        img = cv2.imread(filename_base + ext, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            return img
    return None


def main():
    ls = LiveSplitClient()
    if not ls.sock:
        return

    start_template = load_image("start_trigger")
    victory_template = load_image("victory_trigger")

    if start_template is None or victory_template is None:
        print("[-] Error: Missing trigger images in this folder.")
        return

    state = STATE_IDLE
    consecutive_hits = 0
    print("[+] Limbus Auto-Splitter Active (DPI-Aware + Client Canvas Lock)!")
    print("[+] Press Ctrl+C to exit.\n")

    with mss.mss() as sct:
        while True:
            canvas = get_game_canvas_rect("LimbusCompany")
            if not canvas or canvas["width"] <= 0:
                print("\r[-] Waiting for Limbus Company to be open...", end="")
                time.sleep(1.0)
                continue

            # 1. Scans full screen for winrate icon (can be anything else if need be, just adjust input image)
            # 1. If icon is found, initiate
            if state == STATE_IDLE:
                val = match_template(sct, canvas, start_template)
                print(
                    f"\r[IDLE] Waiting for START... Match: {val:.2f} (Need {START_THRESHOLD}, Hits: {consecutive_hits}/{START_CONSECUTIVE_REQUIRED})",
                    end="",
                )

                if val >= START_THRESHOLD:
                    consecutive_hits += 1
                    if consecutive_hits >= START_CONSECUTIVE_REQUIRED:
                        print(
                            f"\n[!] Confirmed START (Score: {val:.2f}) -> Starting Timer"
                        )
                        ls.reset()
                        time.sleep(0.05)
                        ls.start()
                        state = STATE_RUNNING
                        consecutive_hits = 0
                        time.sleep(2.0)
                else:
                    consecutive_hits = 0

            # 2. After initiation, waits for victory by scanning the center box (scans for 100ms to make sure)
            elif state == STATE_RUNNING:
                roi = get_victory_roi(canvas, VICTORY_BOX_1080P)
                val = match_template(sct, roi, victory_template)
                print(
                    f"\r[RUNNING] In Battle... Match: {val:.2f} (Need {VICTORY_THRESHOLD}, Hits: {consecutive_hits}/{VICTORY_CONSECUTIVE_REQUIRED})",
                    end="",
                )

                if val >= VICTORY_THRESHOLD:
                    consecutive_hits += 1
                    if consecutive_hits >= VICTORY_CONSECUTIVE_REQUIRED:
                        print(
                            f"\n[!] Confirmed VICTORY (Score: {val:.2f}) -> SPLITTING"
                        )
                        ls.split()
                        state = STATE_IDLE
                        consecutive_hits = 0
                        time.sleep(3.0)
                else:
                    consecutive_hits = 0

            time.sleep(0.033)


if __name__ == "__main__":
    main()