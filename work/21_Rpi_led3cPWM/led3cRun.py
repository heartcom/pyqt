# led3cRun.py
# PyQt5 + RPi.GPIO 를 이용한 RGB LED 제어 (토글 + 버튼 색 변경)

import sys
from PyQt5 import QtWidgets
from led3cGUI import Ui_Dialog

try:
    import RPi.GPIO as GPIO
except ImportError:
    raise RuntimeError("RPi.GPIO 모듈이 필요합니다. 라즈베리파이에서 실행해주세요.")


# -------------------- CRC16 (IBM / Modbus) -------------------- #
def crc16_ibm(data: bytes, poly: int = 0xA001, init: int = 0xFFFF) -> int:
    """
    CRC16-IBM (Modbus) 계산
    - poly : 0xA001
    - init : 0xFFFF
    - little-endian 반환
    """
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_tx_frame(led_no: int, value: int) -> bytes:
    """
    SOF(0xAA) | LEN | LED No | Value | CRC(L) | CRC(H)
    LEN = LED No + Value 의 길이 (2)
    CRC 는 SOF ~ Value 전체에 대해 계산 (CRC 미포함)
    """
    sof = 0xAA
    value = max(0, min(0x64, value))  # 0~0x64
    payload = bytes([led_no, value])
    length = len(payload)  # 2
    frame_wo_crc = bytes([sof, length]) + payload
    crc = crc16_ibm(frame_wo_crc)
    crc_l = crc & 0xFF
    crc_h = (crc >> 8) & 0xFF
    return frame_wo_crc + bytes([crc_l, crc_h])


def build_status_frame(r: int, g: int, b: int) -> bytes:
    """
    응답 프레임 예시
    SOF(0xAA) | LEN(3) | R | G | B | CRC(L) | CRC(H)
    """
    sof = 0xAA
    r = max(0, min(0x64, r))
    g = max(0, min(0x64, g))
    b = max(0, min(0x64, b))
    payload = bytes([r, g, b])
    length = len(payload)  # 3
    frame_wo_crc = bytes([sof, length]) + payload
    crc = crc16_ibm(frame_wo_crc)
    crc_l = crc & 0xFF
    crc_h = (crc >> 8) & 0xFF
    return frame_wo_crc + bytes([crc_l, crc_h])


def frame_to_hex_str(frame: bytes) -> str:
    return " ".join(f"{b:02X}" for b in frame)


# -------------------- GPIO / PWM 제어 -------------------- #
class LedController:
    # BCM 기준 핀 번호
    RED_PIN = 13
    GREEN_PIN = 12
    BLUE_PIN = 18

    def __init__(self, freq: int = 1000):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for pin in (self.RED_PIN, self.GREEN_PIN, self.BLUE_PIN):
            GPIO.setup(pin, GPIO.OUT)

        self.red_pwm = GPIO.PWM(self.RED_PIN, freq)
        self.green_pwm = GPIO.PWM(self.GREEN_PIN, freq)
        self.blue_pwm = GPIO.PWM(self.BLUE_PIN, freq)

        self.red_pwm.start(0)
        self.green_pwm.start(0)
        self.blue_pwm.start(0)

        self.red_val = 0
        self.green_val = 0
        self.blue_val = 0

    def set_red(self, value: int):
        self.red_val = max(0, min(100, value))
        self.red_pwm.ChangeDutyCycle(self.red_val)

    def set_green(self, value: int):
        self.green_val = max(0, min(100, value))
        self.green_pwm.ChangeDutyCycle(self.green_val)

    def set_blue(self, value: int):
        self.blue_val = max(0, min(100, value))
        self.blue_pwm.ChangeDutyCycle(self.blue_val)

    # 프로토콜 명령 적용
    def apply_command(self, led_no: int, value: int):
        value = max(0, min(0x64, value))
        if led_no == 0x01:        # Red
            self.set_red(value)
        elif led_no == 0x02:      # Green
            self.set_green(value)
        elif led_no == 0x03:      # Blue
            self.set_blue(value)
        elif led_no == 0x0F:      # All
            self.set_red(value)
            self.set_green(value)
            self.set_blue(value)

    def cleanup(self):
        self.red_pwm.stop()
        self.green_pwm.stop()
        self.blue_pwm.stop()
        GPIO.cleanup()


# -------------------- PyQt Dialog -------------------- #
class LedDialog(QtWidgets.QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.led = LedController()

        # 버튼 시그널 연결
        self.btnRed.clicked.connect(self.click_red)
        self.btnGreen.clicked.connect(self.click_green)
        self.btnBlue.clicked.connect(self.click_blue)
        self.btnAllon.clicked.connect(self.click_all_on)
        self.btnAlloff.clicked.connect(self.click_all_off)

        # 처음에는 모두 OFF 상태
        self.update_button_styles()

    # 버튼 색 스타일 업데이트
    # 버튼 색/테두리 스타일 업데이트
    def update_button_styles(self):
        # 공통 스타일 템플릿
        def on_style(bg):
            return f"""
            QPushButton {{
                background-color: {bg};
                color: black;             /* 글자는 항상 검정 */
                border: 2px solid black;  /* 굵은 검정 테두리 */
                border-radius: 4px;
                font-weight: bold;
            }}
            """

        off_style = """
        QPushButton {
            background-color: lightgray;  /* OFF = 회색 */
            color: black;                 /* 검정 글자 */
            border: 2px solid black;      /* 테두리 확실하게 */
            border-radius: 4px;
        }
        """

        # RED 버튼
        if self.led.red_val > 0:
            self.btnRed.setStyleSheet(on_style("red"))
        else:
            self.btnRed.setStyleSheet(off_style)

        # GREEN 버튼
        if self.led.green_val > 0:
            self.btnGreen.setStyleSheet(on_style("limegreen"))
        else:
            self.btnGreen.setStyleSheet(off_style)

        # BLUE 버튼
        if self.led.blue_val > 0:
            self.btnBlue.setStyleSheet(on_style("deepskyblue"))
        else:
            self.btnBlue.setStyleSheet(off_style)


    # 공통: 프레임 생성 → 적용 → 상태프레임 출력
    def send_and_apply(self, led_no: int, value: int, desc: str = ""):
        tx = build_tx_frame(led_no, value)
        print(f"[TX] {desc}: {frame_to_hex_str(tx)}")

        self.led.apply_command(led_no, value)
        self.update_button_styles()

        rx = build_status_frame(self.led.red_val,
                                self.led.green_val,
                                self.led.blue_val)
        print(f"[RX] STATUS : {frame_to_hex_str(rx)}")
        print("-" * 40)

    # --------- 버튼 핸들러 (토글) --------- #
    def click_red(self):
        # 현재 값이 0이면 100%, 아니면 0 으로 토글
        new_val = 0x64 if self.led.red_val == 0 else 0x00
        self.send_and_apply(0x01, new_val, "RED TOGGLE")

    def click_green(self):
        new_val = 0x64 if self.led.green_val == 0 else 0x00
        self.send_and_apply(0x02, new_val, "GREEN TOGGLE")

    def click_blue(self):
        new_val = 0x64 if self.led.blue_val == 0 else 0x00
        self.send_and_apply(0x03, new_val, "BLUE TOGGLE")

    def click_all_on(self):
        # 전체 100%
        self.send_and_apply(0x0F, 0x64, "ALL ON")

    def click_all_off(self):
        # 전체 0%
        self.send_and_apply(0x0F, 0x00, "ALL OFF")

    # 창 닫을 때 GPIO 정리
    def closeEvent(self, event):
        self.led.cleanup()
        event.accept()


# -------------------- main -------------------- #
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    dlg = LedDialog()
    dlg.show()
    sys.exit(app.exec_())

