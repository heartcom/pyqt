# ledSensorServerRun01.py
# 센서 값 수신 + 그래프 표시 + 기존 3색 LED 제어 송신 (CRC16 프레임)
# 클라이언트에서 오는 값은 모두 소수점 1자리로 표시

import sys
from collections import deque
from PyQt5 import QtWidgets, QtNetwork

import pyqtgraph as pg

from ledSensorServerGui01 import Ui_Dialog  # UI from Qt Designer


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


class SensorServer(QtWidgets.QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # pyqtgraph 설정
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        # 그래프 데이터 버퍼
        self.max_points = 200
        self.temp_data = deque(maxlen=self.max_points)
        self.humi_data = deque(maxlen=self.max_points)
        self.nh3_data = deque(maxlen=self.max_points)
        self.h2s_data = deque(maxlen=self.max_points)

        # Plot curves
        self.temp_curve = self.graphTemp.plot(pen="r")
        self.humi_curve = self.graphHumi.plot(pen="b")
        self.nh3_curve = self.graphNH3.plot(pen="g")
        self.h2s_curve = self.graphH2S.plot(pen="m")

        # LED 버튼 상태
        self.led_states = {
            LED_RED: False,
            LED_GREEN: False,
            LED_BLUE: False,
        }
        self.update_button_styles()

        # 버튼 클릭 → LED 제어 프레임 송신
        self.btnRed.clicked.connect(lambda: self.toggle_led(LED_RED))
        self.btnGreen.clicked.connect(lambda: self.toggle_led(LED_GREEN))
        self.btnBlue.clicked.connect(lambda: self.toggle_led(LED_BLUE))

        # TCP 서버
        self.server = QtNetwork.QTcpServer(self)
        self.server.newConnection.connect(self.on_new_connection)

        if not self.server.listen(QtNetwork.QHostAddress.LocalHost, 60010):
            QtWidgets.QMessageBox.critical(
                self,
                "Server Error",
                f"Listen 실패: {self.server.errorString()}",
            )
        else:
            print("Server listening on 127.0.0.1:60010")

        self.client_socket = None

    # ---------- 네트워크 ----------

    def on_new_connection(self):
        if self.client_socket is not None:
            self.client_socket.disconnectFromHost()
            self.client_socket.deleteLater()

        self.client_socket = self.server.nextPendingConnection()
        self.client_socket.readyRead.connect(self.on_ready_read)
        self.client_socket.disconnected.connect(self.on_client_disconnected)

        print(
            "클라이언트 접속:",
            self.client_socket.peerAddress().toString(),
            self.client_socket.peerPort(),
        )

    def on_client_disconnected(self):
        print("클라이언트 연결 해제")
        self.client_socket.deleteLater()
        self.client_socket = None

    def on_ready_read(self):
        if self.client_socket is None:
            return

        # 클라이언트 → 서버 : 센서 CSV 한 줄씩
        while self.client_socket.canReadLine():
            line_bytes = self.client_socket.readLine()
            try:
                line = bytes(line_bytes).decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not line:
                continue
            print("RX sensor:", line)
            self.process_sensor_line(line)

    # ---------- 센서 처리 ----------

    def process_sensor_line(self, line: str):
        parts = line.split(",")
        if len(parts) != 4:
            print("잘못된 데이터 형식:", line)
            return
        try:
            temp = float(parts[0])
            humi = float(parts[1])
            nh3 = float(parts[2])
            h2s = float(parts[3])
        except ValueError:
            print("숫자 변환 실패:", line)
            return

        # Edit 박스에 표시 (소수점 1자리)
        self.valueTemp.setText(f"{temp:.1f}")
        self.valueHumi.setText(f"{humi:.1f}")
        self.valueNH3.setText(f"{nh3:.1f}")
        self.valueH2S.setText(f"{h2s:.1f}")

        # 데이터 버퍼에 추가
        self.temp_data.append(temp)
        self.humi_data.append(humi)
        self.nh3_data.append(nh3)
        self.h2s_data.append(h2s)

        self.update_plots()

    def update_plots(self):
        x_temp = list(range(len(self.temp_data)))
        x_humi = list(range(len(self.humi_data)))
        x_nh3 = list(range(len(self.nh3_data)))
        x_h2s = list(range(len(self.h2s_data)))

        self.temp_curve.setData(x_temp, list(self.temp_data))
        self.humi_curve.setData(x_humi, list(self.humi_data))
        self.nh3_curve.setData(x_nh3, list(self.nh3_data))
        self.h2s_curve.setData(x_h2s, list(self.h2s_data))

    # ---------- LED 제어 (서버 → 클라이언트) ----------

    def toggle_led(self, led_no: int):
        self.led_states[led_no] = not self.led_states[led_no]
        on = self.led_states[led_no]
        value = 0x64 if on else 0x00

        self.update_button_styles()
        self.send_led_command(led_no, value)

    def send_led_command(self, led_no: int, value: int):
        if self.client_socket is None:
            print("클라이언트가 연결되지 않았습니다.")
            return
        frame = build_frame(led_no, value)
        self.client_socket.write(frame)
        self.client_socket.flush()
        print("TX LED:", frame.hex(" "))

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
                }}
            """
        else:
            style = """
                QPushButton {
                    background-color: rgb(177, 177, 177);
                    color: black;
                    font-weight: bold;
                }
            """
        btn.setStyleSheet(style)

    # ---------- 기타 ----------

    def closeEvent(self, event):
        if self.client_socket is not None:
            self.client_socket.disconnectFromHost()
        self.server.close()
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    dlg = SensorServer()
    dlg.setWindowTitle("LED Sensor Server")
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
