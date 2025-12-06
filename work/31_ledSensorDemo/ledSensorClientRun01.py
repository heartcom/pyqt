# ledSensorClientRun01.py
# 센서 값 랜덤 전송 + 기존 3색 LED 제어 수신 (CRC16 프레임)
# START: 1초마다 Min~Max 범위에서 랜덤값 (소수점 1자리)
# SEND : Alarm 값이 있으면 그 값, 없으면 해당 항목만 랜덤값 전송 (즉시 1회)

import sys
import random
from PyQt5 import QtWidgets, QtCore, QtNetwork

from ledSensorClientGui01 import Ui_Dialog  # UI from Qt Designer


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


class SensorClient(QtWidgets.QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # TCP 소켓
        self.socket = QtNetwork.QTcpSocket(self)
        self.socket.connected.connect(self.on_connected)
        self.socket.disconnected.connect(self.on_disconnected)
        self.socket.readyRead.connect(self.on_ready_read)
        self.socket.errorOccurred.connect(self.on_error)

        # LED 수신용 버퍼
        self.rx_buffer = bytearray()

        # LED 상태 (True = ON, False = OFF)
        self.led_states = {
            LED_RED: False,
            LED_GREEN: False,
            LED_BLUE: False,
        }
        self.update_all_leds()  # 초기 OFF

        # 센서 전송 타이머 (1초 주기)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.send_random_values)

        # 버튼 연결
        self.btnStart.clicked.connect(self.on_start)
        self.btnStop.clicked.connect(self.on_stop)
        self.btnSend.clicked.connect(self.on_send_alarm)  # ← SEND는 Alarm 값 기준 전송

        # START 버튼 기본 스타일
        self.start_default_style = self.btnStart.styleSheet()

        # 처음에 서버 접속 시도
        QtCore.QTimer.singleShot(0, self.connect_to_server)

    # ---------- 네트워크 ----------

    def connect_to_server(self):
        if self.socket.state() == QtNetwork.QAbstractSocket.ConnectedState:
            return
        print("서버 접속 시도: 127.0.0.1:60010")
        self.socket.connectToHost(QtNetwork.QHostAddress.LocalHost, 60010)

    def on_connected(self):
        print("서버에 연결되었습니다.")

    def on_disconnected(self):
        print("서버와의 연결이 끊어졌습니다.")

    def on_error(self, err):
        print("소켓 에러:", self.socket.errorString())

    def ensure_connected(self):
        if self.socket.state() != QtNetwork.QAbstractSocket.ConnectedState:
            self.connect_to_server()
            return False
        return True

    def on_ready_read(self):
        # 서버 → 클라이언트 : LED 제어 프레임 수신
        data = self.socket.readAll()
        data_bytes = bytes(data)
        self.rx_buffer.extend(data_bytes)
        self.process_rx_buffer()

    def process_rx_buffer(self):
        """LED 제어 프레임 파싱 (SOF/LEN/LED No./Value/CRC16)."""
        while True:
            if len(self.rx_buffer) < 4:
                return

            # SOF(0xAA) 찾기
            try:
                sof_index = self.rx_buffer.index(SOF)
            except ValueError:
                self.rx_buffer.clear()
                return

            if sof_index > 0:
                del self.rx_buffer[:sof_index]

            if len(self.rx_buffer) < 4:
                return

            length = self.rx_buffer[1]
            total_len = 1 + 1 + length + 2  # SOF + LEN + payload + CRC(2)

            if len(self.rx_buffer) < total_len:
                return

            frame = self.rx_buffer[:total_len]
            del self.rx_buffer[:total_len]

            data_without_crc = frame[:-2]
            recv_crc = frame[-2] | (frame[-1] << 8)
            calc_crc = crc16_ibm(data_without_crc)

            if recv_crc != calc_crc:
                print("CRC 에러, 프레임 무시:", frame.hex(" "))
                continue

            payload = frame[2:2 + length]
            if len(payload) < 2:
                print("payload 길이 에러:", payload.hex(" "))
                continue

            led_no = payload[0]
            value = payload[1]
            self.apply_led_command(led_no, value)

    # ---------- LED 표시 ----------

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
        self.set_led_style(self.ledRed, self.led_states[LED_RED], "red")
        self.set_led_style(self.ledGreen, self.led_states[LED_GREEN], "green")
        self.set_led_style(self.ledBlue, self.led_states[LED_BLUE], "blue")

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

    # ---------- Min/Max & Alarm 읽기 ----------

    def set_start_button_running(self, running: bool):
        if running:
            self.btnStart.setStyleSheet(
                "background-color: red; color: white; font-weight: bold;"
            )
        else:
            self.btnStart.setStyleSheet(self.start_default_style)

    def read_ranges(self):
        """각 항목의 (min, max)를 읽어와서 dict로 반환."""
        try:
            temp_min = float(self.tempMin.text())
            temp_max = float(self.tempMax.text())
            humi_min = float(self.humiMin.text())
            humi_max = float(self.humiMax.text())
            nh3_min = float(self.nh3Min.text())
            nh3_max = float(self.nh3Max.text())
            h2s_min = float(self.h2sMin.text())
            h2s_max = float(self.h2sMax.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self, "입력 오류", "Min/Max 칸에 숫자를 입력해 주세요."
            )
            return False, None

        for name, vmin, vmax in [
            ("온도", temp_min, temp_max),
            ("습도", humi_min, humi_max),
            ("NH3", nh3_min, nh3_max),
            ("H2S", h2s_min, h2s_max),
        ]:
            if vmax < vmin:
                QtWidgets.QMessageBox.warning(
                    self, "입력 오류", f"{name}의 Max는 Min보다 크거나 같아야 합니다."
                )
                return False, None

        ranges = {
            "temp": (temp_min, temp_max),
            "humi": (humi_min, humi_max),
            "nh3": (nh3_min, nh3_max),
            "h2s": (h2s_min, h2s_max),
        }
        return True, ranges

    # ---------- START / STOP / SEND ----------

    def on_start(self):
        ok, ranges = self.read_ranges()
        if not ok:
            return

        if not self.ensure_connected():
            QtWidgets.QMessageBox.warning(
                self, "연결 실패", "서버에 아직 연결되지 않았습니다.\n잠시 후 다시 시도하세요."
            )
            return

        self.ranges = ranges
        self.timer.start()
        self.set_start_button_running(True)
        print("랜덤 전송 시작")

    def on_stop(self):
        self.timer.stop()
        self.set_start_button_running(False)
        print("랜덤 전송 정지")

    def on_send_alarm(self):
        """SEND 버튼: Alarm 값이 있으면 그 값, 없으면 랜덤값으로 즉시 1회 전송."""
        ok, ranges = self.read_ranges()
        if not ok:
            return
        self.ranges = ranges
        self.send_alarm_values()

    # ---------- 값 전송 ----------

    def send_random_values(self):
        """1초 주기로 Min~Max 범위 내 랜덤값 전송 (소수점 1자리)."""
        if not hasattr(self, "ranges"):
            ok, ranges = self.read_ranges()
            if not ok:
                return
            self.ranges = ranges

        if not self.ensure_connected():
            return

        temp = random.uniform(*self.ranges["temp"])
        humi = random.uniform(*self.ranges["humi"])
        nh3 = random.uniform(*self.ranges["nh3"])
        h2s = random.uniform(*self.ranges["h2s"])

        line = f"{temp:.1f},{humi:.1f},{nh3:.1f},{h2s:.1f}\n"
        self.socket.write(line.encode("utf-8"))
        self.socket.flush()
        print("TX sensor(random):", line.strip())

    def _value_from_alarm_or_random(self, name: str,
                                    alarm_edit: QtWidgets.QLineEdit,
                                    key: str):
        """Alarm 칸 값이 있으면 그 값을, 없으면 Min~Max 사이 랜덤값 반환."""
        txt = alarm_edit.text().strip()
        if txt == "":
            # Alarm 값이 비어 있으면 범위 내 랜덤
            return random.uniform(*self.ranges[key])
        try:
            return float(txt)
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self, "입력 오류", f"{name} Alarm 값이 숫자가 아닙니다."
            )
            return None

    def send_alarm_values(self):
        """SEND 버튼에서 호출: 각 Alarm/랜덤 값으로 즉시 1회 전송."""
        if not self.ensure_connected():
            return

        temp = self._value_from_alarm_or_random("온도", self.tempAlarm, "temp")
        if temp is None:
            return
        humi = self._value_from_alarm_or_random("습도", self.humiAlarm, "humi")
        if humi is None:
            return
        nh3 = self._value_from_alarm_or_random("NH3", self.nh3Alarm, "nh3")
        if nh3 is None:
            return
        h2s = self._value_from_alarm_or_random("H2S", self.h2sAlarm, "h2s")
        if h2s is None:
            return

        line = f"{temp:.1f},{humi:.1f},{nh3:.1f},{h2s:.1f}\n"
        self.socket.write(line.encode("utf-8"))
        self.socket.flush()
        print("TX sensor(ALARM/SEND):", line.strip())

    # ---------- 기타 ----------

    def closeEvent(self, event):
        self.timer.stop()
        if self.socket.isOpen():
            self.socket.close()
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    dlg = SensorClient()
    dlg.setWindowTitle("LED Sensor Client")
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
