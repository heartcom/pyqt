# ledDht11Run.py
#  - ledDht11.py (Ui_Dialog) 사용
#  - R/G/B 슬라이더 값 SEND → ESP32 전송
#  - ESP32에서 오는 LED 상태 / DHT11 값을 파싱해서 GUI에 표시

import sys
import serial
from PyQt5 import QtWidgets, QtCore
from ledDht11 import Ui_Dialog

SOF = 0xAA
# PC → ESP32 LED 제어는 LEN = 0x02 (LED No, Value)

LED_RED   = 0x01
LED_GREEN = 0x02
LED_BLUE  = 0x03


def crc16_ibm(data: bytes) -> int:
    """CRC16-IBM (poly 0xA001, init 0xFFFF)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class LedDhtDialog(QtWidgets.QDialog):
    def __init__(self, port="COM3", baudrate=115200, parent=None):
        super().__init__(parent)

        # ----- UI -----
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)

        # 온도/습도는 모니터링용이므로 편집 못 하게 막음(원하면 해제)
        self.ui.lineTemp.setReadOnly(True)
        self.ui.lineHumi.setReadOnly(True)

        # ----- Serial -----
        try:
            self.ser = serial.Serial(port, baudrate, timeout=0)
        except serial.SerialException as e:
            QtWidgets.QMessageBox.critical(
                self, "Serial Error", f"시리얼 포트를 열 수 없습니다.\n{e}"
            )
            self.ser = None

        # ----- SEND 버튼 연결 -----
        self.ui.btnAllon.clicked.connect(self.on_send_clicked)

        # ----- 수신 파서 상태 -----
        self.rx_state = "WAIT_SOF"
        self.rx_len = 0
        self.rx_buf = bytearray()
        self.rx_idx = 0
        self.rx_crc = 0

        # ----- 주기적으로 시리얼 폴링 -----
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll_serial)
        self.timer.start(30)  # 30ms마다 체크

    # ================== 송신 쪽 ==================

    def send_led_value(self, led_no: int, value: int):
        """LED No, Value 를 기존 프로토콜에 맞게 전송."""
        if self.ser is None or not self.ser.is_open:
            return

        if value < 0:
            value = 0
        if value > 100:
            value = 100

        frame_no_crc = bytes([SOF, 0x02, led_no & 0xFF, value & 0xFF])
        crc = crc16_ibm(frame_no_crc)
        frame = frame_no_crc + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

        self.ser.write(frame)
        # 디버그용:
        # print("TX:", frame.hex(" "))

    def on_send_clicked(self):
        """SEND 버튼 눌렀을 때 슬라이더 값 전송."""
        r = self.ui.sliderRed.value()
        g = self.ui.sliderGreen.value()
        b = self.ui.sliderBlue.value()

        self.send_led_value(LED_RED, r)
        self.send_led_value(LED_GREEN, g)
        self.send_led_value(LED_BLUE, b)

    # ================== 수신 쪽 ==================

    def poll_serial(self):
        """주기적으로 시리얼을 읽어서 바이트 단위로 파싱."""
        if self.ser is None or not self.ser.is_open:
            return

        while True:
            if self.ser.in_waiting <= 0:
                break
            b = self.ser.read(1)
            if not b:
                break
            self.process_byte(b[0])

    def process_byte(self, b: int):
        """ESP32 쪽과 같은 상태 머신으로 프레임 파싱."""
        if self.rx_state == "WAIT_SOF":
            if b == SOF:
                self.rx_buf = bytearray([b])  # SOF 저장
                self.rx_state = "WAIT_LEN"

        elif self.rx_state == "WAIT_LEN":
            self.rx_len = b
            self.rx_buf.append(b)        # LEN 저장
            self.rx_idx = 0
            # payload 길이 간단 체크
            if self.rx_len > 32:         # 너무 길면 버리기
                self.reset_rx()
            else:
                self.rx_state = "WAIT_PAYLOAD"

        elif self.rx_state == "WAIT_PAYLOAD":
            self.rx_buf.append(b)
            self.rx_idx += 1
            if self.rx_idx >= self.rx_len:
                self.rx_state = "WAIT_CRC_L"

        elif self.rx_state == "WAIT_CRC_L":
            self.rx_crc = b              # LSB
            self.rx_state = "WAIT_CRC_H"

        elif self.rx_state == "WAIT_CRC_H":
            self.rx_crc |= (b << 8)      # MSB
            # CRC 체크 (SOF..payload)
            calc = crc16_ibm(self.rx_buf)
            if calc == self.rx_crc:
                # payload는 SOF,LEN 뒤의 부분
                payload = self.rx_buf[2:]
                self.handle_frame(bytes(payload))
            # 다음 프레임 준비
            self.reset_rx()

    def reset_rx(self):
        self.rx_state = "WAIT_SOF"
        self.rx_len = 0
        self.rx_idx = 0
        self.rx_crc = 0
        self.rx_buf = bytearray()

    def handle_frame(self, payload: bytes):
        """
        LEN에 따라 프레임 종류 구분:
        - LEN = 3 (payload 길이 3) → LED 상태 (R,G,B)
        - LEN = 2 (payload 길이 2) → DHT11 (TEMP,HUMI)
        """
        plen = len(payload)

        if plen == 3:
            # LED 상태 프레임: [R,G,B] (0~100)
            r, g, b = payload[0], payload[1], payload[2]
            # 슬라이더 값 동기화 (값이 들어온 범위만큼 클램프)
            self.ui.sliderRed.setValue(min(max(r, 0), 100))
            self.ui.sliderGreen.setValue(min(max(g, 0), 100))
            self.ui.sliderBlue.setValue(min(max(b, 0), 100))
            # sliderRed/Green/Blue → lblRed/Green/Blue는 이미 디자이너에서 연결됨

        elif plen == 2:
            # DHT11 프레임: [TEMP, HUMI]
            temp = payload[0]
            humi = payload[1]

            if temp == 0xFF and humi == 0xFF:
                # 센서 읽기 실패 표시
                self.ui.lineTemp.setText("ERR")
                self.ui.lineHumi.setText("ERR")
            else:
                self.ui.lineTemp.setText(f"{temp}")
                self.ui.lineHumi.setText(f"{humi}")

        # 그 외 길이는 무시

    # ================== 기타 ==================

    def closeEvent(self, event):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        super().closeEvent(event)


def main():
    # 사용법: python ledDht11Run.py COM5  처럼 포트명을 인자로 줄 수 있음
    port = "COM3"
    if len(sys.argv) >= 2:
        port = sys.argv[1]

    app = QtWidgets.QApplication(sys.argv)
    dlg = LedDhtDialog(port=port)
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
