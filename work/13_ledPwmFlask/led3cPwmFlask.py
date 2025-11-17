# led3cPwmFlask.py
# ESP32 3색 LED(PWM) 제어용 Flask 서버
# - R/G/B 각각 0~100% 밝기 설정
# - PC <-> ESP32 통신은 기존 Binary Frame + CRC16-IBM 방식 사용

from flask import Flask, render_template, request, redirect, url_for
import serial
import time
from serial.tools import list_ports  # COM 포트 자동 검색

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

    # 설명에 USB, UART, CP210, CH340, ESP32, Arduino 등이 들어가면 우선 선택
    for p in ports:
        desc = (p.description or "").lower()
        if ("usb" in desc or "uart" in desc or
            "cp210" in desc or "ch340" in desc or
            "silicon labs" in desc or "esp32" in desc or
            "arduino" in desc):
            print(f"=> 자동 선택된 포트: {p.device} ({p.description})")
            return p.device

    # 없으면 첫 번째 포트 사용
    print(f"=> 조건에 맞는 포트를 못 찾았습니다. 첫 번째 포트 사용: {ports[0].device}")
    return ports[0].device

def get_serial():
    """시리얼 포트를 한 번만 열어서 재사용."""
    global ser, SERIAL_PORT

    if ser is not None and getattr(ser, "is_open", False):
        return ser

    if SERIAL_PORT is None:
        SERIAL_PORT = find_serial_port()

    print(f"시리얼 포트 열기: {SERIAL_PORT} (baud={BAUD_RATE})")
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(2)  # ESP32 리셋 후 안정화 시간
    return ser

# ===== CRC16-IBM (MODBUS형, poly 0xA001, init 0xFFFF) =====
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
    - Value : 0 ~ 100 (PWM duty 비율, %)
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


def send_led_value(color: str, value: int):
    """지정한 색(color)에 value(0~100) PWM 값을 전송."""
    s = get_serial()
    frame = build_frame(color, value)
    print(f"TX {color.upper()}={value:3d} -> {frame.hex(' ')}")
    s.write(frame)
    s.flush()
    time.sleep(0.01)  # 너무 빠르게 연속 전송되는 것 방지 (필요시 조절)

# ===== Flask 앱 =====
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    # 쿼리스트링으로 전달된 값이 있으면 그대로 표시, 없으면 0
    r = request.args.get("r", default=0, type=int)
    g = request.args.get("g", default=0, type=int)
    b = request.args.get("b", default=0, type=int)
    return render_template("index.html", r_value=r, g_value=g, b_value=b)

@app.route("/set_rgb", methods=["POST"])
def set_rgb():
    # 폼에서 넘어온 값 읽기 (없으면 0)
    r = request.form.get("r", "0")
    g = request.form.get("g", "0")
    b = request.form.get("b", "0")

    try:
        r = int(r)
        g = int(g)
        b = int(b)
    except ValueError:
        # 숫자가 아닌 값이 들어오면 0으로 처리
        r = g = b = 0

    # 0~100 범위로 제한
    r = max(0, min(100, r))
    g = max(0, min(100, g))
    b = max(0, min(100, b))

    try:
        # R, G, B 순서로 각각 한 프레임씩 전송
        send_led_value("red", r)
        send_led_value("green", g)
        send_led_value("blue", b)
    except Exception as e:
        print("Serial error:", e)
        # 에러가 나더라도 화면은 표시
        # 필요하다면 에러 메시지를 화면으로 전달하도록 확장 가능

    # 현재 설정값을 쿼리스트링으로 전달하여 입력창에 그대로 남게 함
    return redirect(url_for("index", r=r, g=g, b=b))

if __name__ == "__main__":
    # 같은 네트워크의 다른 기기에서도 접속 가능
    app.run(debug=True, host="0.0.0.0", port=5000)
