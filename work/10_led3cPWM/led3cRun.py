# led3cRun.py
# ESP32 RGB LED 컨트롤용 PyQt GUI 실행 스크립트
#  - led3cGUI.py 의 Ui_Dialog 사용
#  - 버튼 클릭 시 버튼 배경색을 RED/GREEN/BLUE 로 토글
#  - ON 상태일 때 ESP32로 Value = 0x64 전송
#  - OFF 상태일 때 Value = 0x00 전송

import sys
import serial
from PyQt5 import QtWidgets
from led3cGUI import Ui_Dialog

SOF = 0xAA
LEN = 0x02  # LED No + Value

LED_RED = 0x01
LED_GREEN = 0x02
LED_BLUE = 0x03

def crc16_ibm(buf: bytes) -> int:
    """CRC16-IBM (poly 0xA001, init 0xFFFF)"""
    crc = 0xFFFF
    for b in buf:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class LedDialog(QtWidgets.QDialog):
    def __init__(self, port="COM3", baudrate=115200, parent=None):
        super().__init__(parent)

        # ----- UI 세팅 -----
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)

        # 버튼 상태 (True=ON, False=OFF)
        self.red_on = False
        self.green_on = False
        self.blue_on = False

        # ----- 시리얼 포트 열기 -----
        try:
            self.ser = serial.Serial(port, baudrate, timeout=0.1)
        except serial.SerialException as e:
            QtWidgets.QMessageBox.critical(
                self, "Serial Error", f"포트를 열 수 없습니다.\n{e}"
            )
            self.ser = None

        # ----- 시그널 연결 -----
        self.ui.btnRed.clicked.connect(self.toggle_red)      # RED
        self.ui.btnGreen.clicked.connect(self.toggle_green)  # GREEN
        self.ui.btnBlue.clicked.connect(self.toggle_blue)   # BLUE
        self.ui.btnAllon.clicked.connect(self.all_on)        # All ON
        self.ui.btnAlloff.clicked.connect(self.all_off)       # All OFF

    # ---------- 시리얼 송신 관련 ----------

    def send_led_value(self, led_no: int, value: int):
        """프로토콜에 맞게 한 프레임 전송"""
        if self.ser is None or not self.ser.is_open:
            return

        header_and_payload = bytes([SOF, LEN, led_no & 0xFF, value & 0xFF])
        crc = crc16_ibm(header_and_payload)
        frame = header_and_payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

        self.ser.write(frame)

    # ---------- 버튼 색상/상태 업데이트 ----------

    def set_button_style(self, button, color_name: str, on: bool):
        """버튼 ON/OFF에 따라 배경색 변경"""
        if on:
            # 클릭 시 버튼 배경을 해당 색으로
            button.setStyleSheet(
                f"background-color: {color_name}; color: white; font-weight: bold;"
            )
        else:
            # 원래 스타일로 복원
            button.setStyleSheet("")

    # ---------- 개별 버튼 클릭 핸들러 ----------
    def toggle_red(self):
        self.red_on = not self.red_on
        value = 0x64 if self.red_on else 0x00
        self.set_button_style(self.ui.btnRed, "red", self.red_on)
        self.send_led_value(LED_RED, value)

    def toggle_green(self):
        self.green_on = not self.green_on
        value = 0x64 if self.green_on else 0x00
        self.set_button_style(self.ui.btnGreen, "green", self.green_on)
        self.send_led_value(LED_GREEN, value)

    def toggle_blue(self):
        self.blue_on = not self.blue_on
        value = 0x64 if self.blue_on else 0x00
        self.set_button_style(self.ui.btnBlue, "blue", self.blue_on)
        self.send_led_value(LED_BLUE, value)

    # ---------- ALL ON / ALL OFF ----------

    def all_on(self):
        self.red_on = self.green_on = self.blue_on = True

        self.set_button_style(self.ui.btnRed, "red", True)
        self.set_button_style(self.ui.btnGreen, "green", True)
        self.set_button_style(self.ui.btnBlue, "blue", True)

        self.send_led_value(LED_RED, 0x64)
        self.send_led_value(LED_GREEN, 0x64)
        self.send_led_value(LED_BLUE, 0x64)

    def all_off(self):
        self.red_on = self.green_on = self.blue_on = False

        self.set_button_style(self.ui.btnRed, "red", False)
        self.set_button_style(self.ui.btnGreen, "green", False)
        self.set_button_style(self.ui.btnBlue, "blue", False)

        self.send_led_value(LED_RED, 0x00)
        self.send_led_value(LED_GREEN, 0x00)
        self.send_led_value(LED_BLUE, 0x00)

    # ---------- 창 닫힐 때 시리얼 정리 ----------
    def closeEvent(self, event):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        super().closeEvent(event)

def main():
    port = "COM3"
    if len(sys.argv) >= 2:
        port = sys.argv[1]

    app = QtWidgets.QApplication(sys.argv)
    dlg = LedDialog(port=port)
    dlg.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
