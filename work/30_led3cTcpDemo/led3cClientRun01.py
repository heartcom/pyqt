# led3cClientRun01.py
# LED 원 3개를 가진 클라이언트 (TCP 클라이언트)

import sys
from PyQt5 import QtWidgets, QtCore, QtNetwork

from led3cClientGui01 import Ui_Dialog  # 디자인 파일 import


SOF = 0xAA
LED_RED = 0x01
LED_GREEN = 0x02
LED_BLUE = 0x03
LED_ALL = 0x0F


def crc16_ibm(data: bytes, poly: int = 0xA001, init: int = 0xFFFF) -> int:
    """CRC16-IBM(Modbus) 계산 (poly 0xA001, init 0xFFFF, little-endian)."""
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc & 0xFFFF


class ClientDialog(QtWidgets.QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # TCP 클라이언트 소켓
        self.socket = QtNetwork.QTcpSocket(self)
        self.socket.connected.connect(self.on_connected)
        self.socket.disconnected.connect(self.on_disconnected)
        self.socket.readyRead.connect(self.on_ready_read)
        self.socket.errorOccurred.connect(self.on_error)

        # 수신 버퍼
        self.rx_buffer = bytearray()

        # LED 상태 (True = ON, False = OFF)
        self.led_states = {
            LED_RED: False,
            LED_GREEN: False,
            LED_BLUE: False,
        }

        # 초기 LED 스타일 (OFF = 회색)
        self.update_all_leds()

        # 프로그램 시작 시 서버 접속 시도
        QtCore.QTimer.singleShot(0, self.connect_to_server)

    # --- 네트워크 관련 ---

    def connect_to_server(self):
        print("서버 접속 시도: 127.0.0.1:50000")
        self.socket.connectToHost(QtNetwork.QHostAddress.LocalHost, 50000)

    def on_connected(self):
        print("서버에 연결되었습니다.")

    def on_disconnected(self):
        print("서버와 연결이 끊어졌습니다.")

    def on_error(self, socket_error):
        print("소켓 에러:", self.socket.errorString())

    def on_ready_read(self):
        data = self.socket.readAll()
        data_bytes = bytes(data)
        print("RX:", data_bytes.hex(" "))
        self.rx_buffer.extend(data_bytes)
        self.process_rx_buffer()

    def process_rx_buffer(self):
        """수신 버퍼에서 프레임을 파싱."""
        while True:
            if len(self.rx_buffer) < 4:
                # 최소 SOF(1) + LEN(1) + CRC(2) 는 있어야 함
                return

            # SOF(0xAA) 찾기
            try:
                sof_index = self.rx_buffer.index(SOF)
            except ValueError:
                # SOF 없음 → 버퍼 삭제
                self.rx_buffer.clear()
                return

            # SOF 앞부분은 버림
            if sof_index > 0:
                del self.rx_buffer[:sof_index]

            if len(self.rx_buffer) < 4:
                return

            length = self.rx_buffer[1]
            total_len = 1 + 1 + length + 2  # SOF + LEN + payload + CRC(2)

            if len(self.rx_buffer) < total_len:
                # 아직 프레임이 다 안 들어옴
                return

            frame = self.rx_buffer[:total_len]
            del self.rx_buffer[:total_len]

            # CRC 체크
            data_without_crc = frame[:-2]
            recv_crc = frame[-2] | (frame[-1] << 8)
            calc_crc = crc16_ibm(data_without_crc)

            if recv_crc != calc_crc:
                print("CRC 에러, 프레임 무시:", frame.hex(" "))
                continue

            # payload 파싱
            payload = frame[2:2 + length]
            if len(payload) < 2:
                print("payload 길이 오류:", payload.hex(" "))
                continue

            led_no = payload[0]
            value = payload[1]
            self.apply_led_command(led_no, value)

    # --- LED 제어 ---

    def apply_led_command(self, led_no: int, value: int):
        """수신한 명령에 따라 LED on/off."""
        on = value != 0

        if led_no == LED_ALL:
            self.led_states[LED_RED] = on
            self.led_states[LED_GREEN] = on
            self.led_states[LED_BLUE] = on
        else:
            if led_no in self.led_states:
                self.led_states[led_no] = on
            else:
                print(f"알 수 없는 LED No: {led_no}")
                return

        self.update_all_leds()

    def update_all_leds(self):
        # 여기만 objectName 변경에 맞게 수정
        self.set_led_style(self.ledRed, self.led_states[LED_RED], "red")       # 빨강
        self.set_led_style(self.ledGreen, self.led_states[LED_GREEN], "green") # 초록
        self.set_led_style(self.ledBlue, self.led_states[LED_BLUE], "blue")    # 파랑

    @staticmethod
    def set_led_style(widget: QtWidgets.QFrame, on: bool, color_name: str):
        if on:
            bg = color_name
        else:
            bg = "#555555"  # OFF = 진한 회색

        style = f"""
            background-color: {bg};
            border-radius: 20px;
            border: 2px solid #333333;
        """
        widget.setStyleSheet(style)


def main():
    app = QtWidgets.QApplication(sys.argv)
    dlg = ClientDialog()
    dlg.setWindowTitle("LED 3-Color Client")
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
