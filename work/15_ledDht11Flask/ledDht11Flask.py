# led3cPwmFlask.py
# ESP32 RGB LED PWM + DHT11 모니터링 Flask 서버
# - 위: R/G/B 0~100% 슬라이더로 LED PWM 제어 (Ajax로 전송)
# - 아래: DHT11 온도/습도 그래프 + 현재 값 표시 (백그라운드 스레드 + 폴링)

from flask import Flask, render_template, request, jsonify
import serial
import time
import threading
from serial.tools import list_ports
from collections import deque

BAUD_RATE = 115200

ser = None           # 전역 시리얼 객체
SERIAL_PORT = None   # 자동으로 찾은 포트 이름

# DHT11 데이터를 저장할 전역 변수
dht_lock = threading.Lock()
dht_last = None                 # (ts, temp, humi)
dht_history = deque(maxlen=120) # 최근 120개 (3초 간격이면 약 6분)


# ===== COM 포트 자동 검색 =====
def find_serial_port() -> str:
    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("사용 가능한 시리얼 포트가 없습니다.")

    print("== 사용 가능한 시리얼 포트 목록 ==")
    for p in ports:
        print(f"  {p.device} : {p.description}")

    # 설명에 USB/UART/CP210/CH340/ESP32/Arduino 등이 있으면 우선 선택
    for p in ports:
        desc = (p.description or "").lower()
        if ("usb" in desc or "uart" in desc or
            "cp210" in desc or "ch340" in desc or
            "silicon labs" in desc or "esp32" in desc or
            "arduino" in desc):
            print(f"=> 자동 선택된 포트: {p.device} ({p.description})")
            return p.device

    # 못 찾으면 첫 번째 포트 사용
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
    ser_obj = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(2)   # ESP32 리셋 후 안정화 시간
    ser = ser_obj
    return ser_obj


# ===== CRC16-IBM =====
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


# ===== LED 프레임 생성 =====
LED_NO_MAP = {"red": 0x01, "green": 0x02, "blue": 0x03, "all": 0x0F}


def build_frame(color: str, value: int) -> bytes:
    """
    PC -> ESP32 (LED 제어)
    | 0xAA | LEN(0x02) | LED No | Value(0~100) | CRC_L | CRC_H |
    """
    led_no = LED_NO_MAP[color]
    value = max(0, min(100, value))

    sof = 0xAA
    length = 0x02

    frame = bytearray([sof, length, led_no, value])
    crc = crc16_ibm(frame)
    frame.append(crc & 0xFF)
    frame.append((crc >> 8) & 0xFF)
    return bytes(frame)


def send_led_value(color: str, value: int):
    """지정한 색상의 PWM 값(0~100)을 ESP32로 전송."""
    s = get_serial()
    frame = build_frame(color, value)
    print(f"TX {color.upper()}={value:3d} -> {frame.hex(' ')}")
    s.write(frame)
    s.flush()
    time.sleep(0.01)


# ===== 백그라운드 스레드: DHT11 프레임 계속 읽기 =====
def serial_reader_loop():
    """
    백그라운드에서 계속 돌면서
    | AA | LEN | payload | CRC_L | CRC_H | 프레임을 읽고,
    LEN=0x02 인 DHT11 프레임이면 temp/humi 를 dht_last / dht_history 에 저장.
    ESP32가 3초마다 DHT11 데이터를 보내는 구조에 맞춤.
    """
    global dht_last

    buf = bytearray()
    expected_len = None

    while True:
        try:
            s = get_serial()

            b = s.read(1)
            if not b:
                continue
            b = b[0]

            # 1) SOF(0xAA) 찾기
            if not buf:
                if b != 0xAA:
                    continue
                buf.append(b)
                continue

            # 2) LEN 바이트
            if len(buf) == 1:
                buf.append(b)
                expected_len = b
                continue

            # 3) payload + CRC 읽기
            buf.append(b)

            # SOF(1) + LEN(1) + payload(expected_len) + CRC(2)
            if expected_len is not None and len(buf) == 2 + expected_len + 2:
                data_no_crc = buf[:-2]
                recv_crc = buf[-2] | (buf[-1] << 8)
                calc_crc = crc16_ibm(data_no_crc)

                if calc_crc != recv_crc:
                    print("CRC mismatch, skip:", buf.hex(" "))
                    buf.clear()
                    expected_len = None
                    continue

                # DHT11 프레임: LEN=0x02, 전체 길이 6바이트
                if expected_len == 0x02 and len(buf) == 6:
                    _, _, temp, humi, _, _ = buf
                    ts = time.time()
                    with dht_lock:
                        dht_last = (ts, float(temp), float(humi))
                        dht_history.append(dht_last)
                    print(f"DHT11 => T={temp}C, H={humi}%")
                else:
                    # 다른 용도의 프레임은 필요시 로그만
                    # print("Non-DHT frame:", buf.hex(" "))
                    pass

                # 다음 프레임을 위해 초기화
                buf.clear()
                expected_len = None

        except Exception as e:
            print("serial_reader_loop error:", e)
            time.sleep(1)
            buf.clear()
            expected_len = None


# ===== Flask 앱 =====
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    # 처음 로딩 시 슬라이더 기본값 0으로 세팅
    return render_template("index.html", r_value=0, g_value=0, b_value=0)

@app.route("/api/set_rgb", methods=["POST"])
def api_set_rgb():
    """
    Ajax로 호출되는 LED PWM 설정 API.
    JSON: {r:0~100, g:0~100, b:0~100}
    응답: {ok:True/False, error:'', r:..., g:..., b:...}
    """
    data = request.get_json(silent=True) or {}

    def to_int(v):
        try:
            return int(v)
        except Exception:
            return 0

    r = to_int(data.get("r", 0))
    g = to_int(data.get("g", 0))
    b = to_int(data.get("b", 0))

    r = max(0, min(100, r))
    g = max(0, min(100, g))
    b = max(0, min(100, b))

    ok = True
    err = ""

    try:
        send_led_value("red", r)
        send_led_value("green", g)
        send_led_value("blue", b)
    except Exception as e:
        ok = False
        err = str(e)
        print("Serial error in api_set_rgb:", e)

    return jsonify({"ok": ok, "error": err, "r": r, "g": g, "b": b})


@app.route("/api/dht11", methods=["GET"])
def api_dht11():
    """
    AJAX에서 호출하는 DHT11 값 조회용 API.
    백그라운드 스레드가 저장해둔 최신 값(dht_last)을 반환.
    JSON: { ok: True/False, temp: ..., humi: ..., ts: unix time }
    """
    with dht_lock:
        if dht_last is None:
            return jsonify({"ok": False, "error": "no data yet"})

        ts, temp, humi = dht_last

    return jsonify({
        "ok": True,
        "temp": temp,
        "humi": humi,
        "ts": ts,
    })


if __name__ == "__main__":
    # 백그라운드 시리얼 리더 스레드 시작
    t = threading.Thread(target=serial_reader_loop, daemon=True)
    t.start()

    app.run(debug=False, host="0.0.0.0", port=5000)

