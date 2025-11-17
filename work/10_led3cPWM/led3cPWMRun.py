# led3cPWMRun.py
#  - led3cPWMGUI.py 의 Ui_Dialog 사용
#  - R/G/B 슬라이더 값(0~100)을 SEND 버튼 클릭 시
#    ESP32로 각각 한 프레임씩 전송

import sys
import serial
from PyQt5 import QtWidgets
from led3cPWMGUI import Ui_Dialog

SOF = 0xAA
LEN = 0x02  # LED No + Value 두 바이트

# ESP32 펌웨어에서 사용하는 LED 번호 (led3cPWM.ino 기준)
LED_RED   = 0x01
LED_GREEN = 0x02
LED_BLUE  = 0x03


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


class LedPwmDialog(QtWidgets.QDialog):
    def __init__(self, port="COM3", baudrate=115200, parent=None):
        super().__init__(parent)

        # ----- UI 세팅 -----
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)

        # ----- 시리얼 포트 열기 -----
        try:
            self.ser = serial.Serial(port, baudrate, timeout=0.1)
        except serial.SerialException as e:
            QtWidgets.QMessageBox.critical(
                self, "Serial Error", f"시리얼 포트를 열 수 없습니다.\n{e}"
            )
            self.ser = None

        # ----- SEND 버튼 시그널 연결 -----
        self.ui.btnAllon.clicked.connect(self.on_send_clicked)

    # ---------- 시리얼 프레임 전송 ----------

    def send_led_value(self, led_no: int, value: int):
        """프로토콜에 맞게 한 프레임 전송"""
        if self.ser is None or not self.ser.is_open:
            return

        value &= 0xFF
        led_no &= 0xFF

        header_and_payload = bytes([SOF, LEN, led_no, value])
        crc = crc16_ibm(header_and_payload)
        frame = header_and_payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

        self.ser.write(frame)
        # 디버깅용으로 보고 싶으면 아래 주석 해제
        # print("TX:", frame.hex(" "))

    # ---------- SEND 버튼 핸들러 ----------

    def on_send_clicked(self):
        # 슬라이더 값 읽기 (0~100)
        r_val = self.ui.sliderRed.value()
        g_val = self.ui.sliderGreen.value()
        b_val = self.ui.sliderBlue.value()

        # 각각 RED / GREEN / BLUE 로 전송
        self.send_led_value(LED_RED,   r_val)
        self.send_led_value(LED_GREEN, g_val)
        self.send_led_value(LED_BLUE,  b_val)

    # ---------- 창 닫힐 때 시리얼 닫기 ----------

    def closeEvent(self, event):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        super().closeEvent(event)


def main():
    # 사용법: python led3cPWMRun.py COM5  처럼 포트명을 첫 인자로 줄 수 있음
    port = "COM3"
    if len(sys.argv) >= 2:
        port = sys.argv[1]

    app = QtWidgets.QApplication(sys.argv)
    dlg = LedPwmDialog(port=port)
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
