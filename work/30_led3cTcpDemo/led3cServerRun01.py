# led3cServerRun01.py
# 버튼 프로그램 (TCP 서버)

import sys
from PyQt5 import QtWidgets, QtCore, QtNetwork

from led3cServerGui01 import Ui_Dialog  # 디자인 파일 import


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


def build_frame(led_no: int, value: int) -> bytes:
    """SOF/LEN/LED No./Value/CRC16(LSB,MSB) 프레임 생성."""
    payload = bytes([led_no & 0xFF, value & 0xFF])
    length = len(payload)  # CMD+PAYLOAD 길이 (CRC 제외)
    header = bytes([SOF, length]) + payload
    crc = crc16_ibm(header)
    crc_bytes = bytes([crc & 0xFF, (crc >> 8) & 0xFF])  # little-endian
    return header + crc_bytes


class ServerDialog(QtWidgets.QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 버튼 상태 (True = ON, False = OFF)
        self.led_states = {
            LED_RED: False,
            LED_GREEN: False,
            LED_BLUE: False,
        }

        # 버튼 클릭 시그널 연결
        self.btnRed.clicked.connect(lambda: self.toggle_led(LED_RED))
        self.btnGreen.clicked.connect(lambda: self.toggle_led(LED_GREEN))
        self.btnBlue.clicked.connect(lambda: self.toggle_led(LED_BLUE))

        # TCP 서버 준비
        self.server = QtNetwork.QTcpServer(self)
        self.server.newConnection.connect(self.on_new_connection)

        if not self.server.listen(QtNetwork.QHostAddress.LocalHost, 50000):
            QtWidgets.QMessageBox.critical(
                self,
                "Server Error",
                f"Listen 실패: {self.server.errorString()}",
            )
        else:
            print("Server listening on 127.0.0.1:50000")

        self.client_socket = None

        # 초기 버튼 스타일 갱신
        self.update_button_styles()

    # --- 네트워크 관련 ---

    def on_new_connection(self):
        if self.client_socket is not None:
            # 기존 연결은 닫고 새로 연결
            self.client_socket.disconnectFromHost()
            self.client_socket.deleteLater()

        self.client_socket = self.server.nextPendingConnection()
        self.client_socket.disconnected.connect(self.on_client_disconnected)
        self.client_socket.readyRead.connect(self.on_ready_read)

        print("클라이언트 접속:", self.client_socket.peerAddress().toString())

    def on_client_disconnected(self):
        print("클라이언트 연결 해제")
        self.client_socket.deleteLater()
        self.client_socket = None

    def on_ready_read(self):
        # 지금은 클라이언트 응답은 사용하지 않고 로그만 출력
        if self.client_socket is None:
            return
        data = self.client_socket.readAll()
        print("RX from client:", bytes(data).hex(" "))

    def send_led_command(self, led_no: int, value: int):
        if self.client_socket is None:
            print("클라이언트가 연결되지 않았습니다.")
            return

        frame = build_frame(led_no, value)
        self.client_socket.write(frame)
        self.client_socket.flush()
        print("TX:", frame.hex(" "))

    # --- LED/버튼 제어 ---

    def toggle_led(self, led_no: int):
        # 상태 토글
        self.led_states[led_no] = not self.led_states[led_no]
        on = self.led_states[led_no]
        value = 0x64 if on else 0x00

        # 버튼 색 갱신
        self.update_button_styles()

        # 클라이언트로 명령 전송
        self.send_led_command(led_no, value)

    def update_button_styles(self):
        self.set_button_style(self.btnRed, self.led_states[LED_RED], "red")
        self.set_button_style(self.btnGreen, self.led_states[LED_GREEN], "green")
        self.set_button_style(self.btnBlue, self.led_states[LED_BLUE], "blue")

    @staticmethod
    def set_button_style(btn: QtWidgets.QPushButton, on: bool, color_name: str):
        if on:
            style = f"""
                QPushButton {{
                    background-color: {color_name};
                    color: white;
                    font-weight: bold;
                    border-radius: 8px;
                    padding: 6px 12px;
                }}
            """
        else:
            style = """
                QPushButton {
                    background-color: #555555;
                    color: white;
                    font-weight: bold;
                    border-radius: 8px;
                    padding: 6px 12px;
                }
            """
        btn.setStyleSheet(style)


def main():
    app = QtWidgets.QApplication(sys.argv)
    dlg = ServerDialog()
    dlg.setWindowTitle("LED 3-Color Server")
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
