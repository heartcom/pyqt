# ledSensorFlask.py
# Flask 기반 센서 모니터 + LED 제어 서버
#
# - TCP 서버(포트 60010)로 PyQt 클라이언트와 통신
# - 클라이언트에서 보내는 "temp,humi,nh3,h2s\n" CSV 수신
# - 최근 시계열 데이터를 메모리에 저장
# - Flask 웹 페이지에서 값/그래프 표시
# - 웹에서 RED/GREEN/BLUE 버튼을 누르면 CRC16 프레임으로 LED 제어

import socket
import threading
from collections import deque
from datetime import datetime

from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ----- 센서 데이터 / LED 상태 공유 변수 -----
max_points = 200

data = {
    "time": deque(maxlen=max_points),
    "temp": deque(maxlen=max_points),
    "humi": deque(maxlen=max_points),
    "nh3": deque(maxlen=max_points),
    "h2s": deque(maxlen=max_points),
}

latest = {
    "temp": None,
    "humi": None,
    "nh3": None,
    "h2s": None,
}

# LED 상태 (True = ON, False = OFF)
led_states = {
    "red": False,
    "green": False,
    "blue": False,
}

data_lock = threading.Lock()

# TCP 클라이언트 소켓 (PyQt 클라이언트)
client_sock = None
client_sock_lock = threading.Lock()

# LED 번호 매핑
LED_NO = {
    "red": 0x01,
    "green": 0x02,
    "blue": 0x03,
}

SOF = 0xAA


# ----- CRC / 프레임 유틸 -----
def crc16_ibm(data_bytes: bytes, poly: int = 0xA001, init: int = 0xFFFF) -> int:
    """CRC16-IBM(Modbus) 계산 (poly 0xA001, init 0xFFFF, little-endian)."""
    crc = init
    for b in data_bytes:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_frame(led_no: int, value: int) -> bytes:
    """SOF / LEN / LED No / Value / CRC16(LSB,MSB) 프레임 생성."""
    payload = bytes([led_no & 0xFF, value & 0xFF])
    length = len(payload)  # CMD+PAYLOAD 길이
    header = bytes([SOF, length]) + payload
    crc = crc16_ibm(header)
    crc_bytes = bytes([crc & 0xFF, (crc >> 8) & 0xFF])  # little-endian
    return header + crc_bytes


# ----- TCP 서버 (센서 수신) -----
def handle_sensor_line(line: str):
    """클라이언트에서 한 줄 수신했을 때 처리."""
    parts = line.split(",")
    if len(parts) != 4:
        print("잘못된 형식:", line)
        return
    try:
        temp = float(parts[0])
        humi = float(parts[1])
        nh3 = float(parts[2])
        h2s = float(parts[3])
    except ValueError:
        print("숫자 변환 실패:", line)
        return

    ts = datetime.now().strftime("%H:%M:%S")

    with data_lock:
        data["time"].append(ts)
        data["temp"].append(temp)
        data["humi"].append(humi)
        data["nh3"].append(nh3)
        data["h2s"].append(h2s)

        latest["temp"] = temp
        latest["humi"] = humi
        latest["nh3"] = nh3
        latest["h2s"] = h2s


def tcp_server():
    """PyQt 클라이언트와 통신하는 TCP 서버 (백그라운드 스레드)."""
    global client_sock

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 60010))
    srv.listen(1)

    print("[TCP] Listening on 0.0.0.0:60010")

    while True:
        conn, addr = srv.accept()
        print(f"[TCP] Client connected from {addr}")

        with client_sock_lock:
            # 기존 연결이 있으면 닫고 새 연결로 교체
            if client_sock is not None:
                try:
                    client_sock.close()
                except OSError:
                    pass
            client_sock = conn

        buffer = b""
        try:
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    print("[TCP] Client disconnected")
                    break
                buffer += chunk
                # 줄 단위 파싱
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        line_str = line.decode("utf-8", errors="ignore").strip()
                    except UnicodeDecodeError:
                        continue
                    if line_str:
                        print("[TCP RX]", line_str)
                        handle_sensor_line(line_str)
        except OSError as e:
            print("[TCP] Error:", e)
        finally:
            with client_sock_lock:
                if client_sock is conn:
                    client_sock = None
            try:
                conn.close()
            except OSError:
                pass


# ----- Flask 라우트 -----
@app.route("/")
def index():
    with data_lock:
        latest_copy = latest.copy()
        led_copy = led_states.copy()
    return render_template("index.html", latest=latest_copy, led_states=led_copy)


@app.route("/data")
def get_data():
    """그래프/현재값 갱신용 JSON."""
    with data_lock:
        payload = {
            "time": list(data["time"]),
            "temp": list(data["temp"]),
            "humi": list(data["humi"]),
            "nh3": list(data["nh3"]),
            "h2s": list(data["h2s"]),
            "latest": latest,
            "led_states": led_states,
        }
    return jsonify(payload)


@app.route("/toggle_led/<color>", methods=["POST"])
def toggle_led(color):
    """웹 버튼으로 LED 토글 → PyQt 클라이언트로 CRC 프레임 전송."""
    color = color.lower()
    if color not in led_states:
        return jsonify({"ok": False, "error": "invalid_color"}), 400

    with data_lock:
        led_states[color] = not led_states[color]
        on = led_states[color]

    led_no = LED_NO[color]
    value = 0x64 if on else 0x00
    frame = build_frame(led_no, value)

    sent = False
    with client_sock_lock:
        if client_sock is not None:
            try:
                client_sock.sendall(frame)
                sent = True
                print(f"[TCP TX LED {color.upper()}]", frame.hex(" "))
            except OSError as e:
                print("[TCP] send error:", e)
                sent = False

    return jsonify({"ok": True, "on": on, "sent": sent, "led_states": led_states})


if __name__ == "__main__":
    # TCP 서버 스레드 시작
    t = threading.Thread(target=tcp_server, daemon=True)
    t.start()

    # Flask 서버 실행
    # (필요하면 host/port 조정)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
