# led3cFlask.py
# ESP32 RGB LED (PIN 23/22/21) 제어 - Binary Frame + CRC16-IBM
# + COM 포트 자동 검색

from flask import Flask, request, redirect, url_for, render_template
import serial
import time
from serial.tools import list_ports   # ★ 포트 자동 검색용

BAUD_RATE = 115200

ser = None          # 실제 시리얼 객체
SERIAL_PORT = None  # 자동으로 찾은 포트 이름을 저장

# ===== COM 포트 자동 검색 =====
def find_serial_port() -> str:

    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("사용 가능한 시리얼 포트가 없습니다.")

    print("== 사용 가능한 시리얼 포트 목록 ==")
    for p in ports:
        print(f"  {p.device} : {p.description}")

    # 설명(Description)에 USB/UART/CP210/CH340/ESP32 등의 단어가 들어간 포트 우선 선택
    for p in ports:
        desc = (p.description or "").lower()
        if ("usb" in desc or "uart" in desc or
            "cp210" in desc or "ch340" in desc or
            "silicon labs" in desc or "esp32" in desc or
            "arduino" in desc):
            print(f"=> 자동 선택된 포트: {p.device} ({p.description})")
            return p.device

    # 위 조건이 안 맞으면, 일단 첫 번째 포트를 사용
    print(f"=> 조건에 맞는 포트를 못 찾았습니다. 첫 번째 포트 사용: {ports[0].device}")
    return ports[0].device

def get_serial():
    """시리얼 포트를 한 번만 열어서 재사용."""
    global ser, SERIAL_PORT

    # 이미 열려 있으면 그대로 사용
    if ser is not None and getattr(ser, "is_open", False):
        return ser

    # 아직 포트를 모르면 자동 검색
    if SERIAL_PORT is None:
        SERIAL_PORT = find_serial_port()

    print(f"시리얼 포트 열기: {SERIAL_PORT} (baud={BAUD_RATE})")
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(2)  # ESP32 리셋 후 안정화 시간
    return ser

# ===== CRC16-IBM (poly 0xA001, init 0xFFFF) =====
def crc16_ibm(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

# ===== 프레임 빌더 =====
LED_NO_MAP = {
    "red": 0x01,
    "green": 0x02,
    "blue": 0x03,
    "all": 0x0F,
}

def build_frame(color: str, value: int) -> bytes:
    """
    Frame (PC -> ESP32):
    | 0xAA | LEN(0x02) | LED No. | Value | CRC_L | CRC_H |
    """
    led_no = LED_NO_MAP[color]
    value = max(0, min(100, value))   # 0~100 범위로 제한

    sof = 0xAA
    length = 0x02  # payload: [LED No][Value]

    frame = bytearray([sof, length, led_no, value])
    crc = crc16_ibm(frame)          # SOF~Value 에 대해 계산
    frame.append(crc & 0xFF)        # LSB
    frame.append((crc >> 8) & 0xFF) # MSB
    return bytes(frame)

# ===== Flask 앱 =====
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/led", methods=["POST"])
def led_control():
    color = request.form.get("color")   # red / green / blue / all
    state = request.form.get("state")   # on / off

    if color not in LED_NO_MAP or state not in ("on", "off"):
        return "Bad request", 400

    # ON → 100%, OFF → 0%
    value = 100 if state == "on" else 0

    try:
        s = get_serial()
        frame = build_frame(color, value)
        print(f"TX({color}, {state}) -> {frame.hex(' ')}")
        s.write(frame)
        s.flush()
    except Exception as e:
        print("Serial error:", e)
        return f"Serial error: {e}", 500

    return redirect(url_for("index"))

if __name__ == "__main__":
    # 같은 공유기 안 다른 기기에서도 접속 가능하게 host=0.0.0.0
    app.run(debug=True, host="0.0.0.0", port=5000)
