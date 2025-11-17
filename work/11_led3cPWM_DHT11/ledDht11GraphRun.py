# -*- coding: utf-8 -*-
"""
LED 제어 + 온습도 그래프 표시 통합 프로그램
- UI: ledDht11Graph.py (질문에서 제공한 파일) import
- 시리얼 프로토콜 (바이너리):
  TX(LED 설정): | AA | LEN=02 | LED(01/02/03/0F) | VAL(00~64) | CRC_L | CRC_H |
  RX(상태):     | AA | 03     | R(0~100) | G | B | CRC_L | CRC_H |
  RX(센서1):    | AA | 02     | T(uint8°C) | H(uint8%) | CRC_L | CRC_H |
  RX(센서2):    | AA | 05     | 0x54('T') | tLo tHi | hLo hHi | CRC_L | CRC_H |  # (0.1 단위)
  RX(센서3):    | AA | 04     | tLo tHi | hLo hHi | CRC_L | CRC_H |             # (0.1 단위, 태그 없음)
"""
import sys
from collections import deque
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal, QThread
import serial, serial.tools.list_ports
import pyqtgraph as pg

# 질문에서 주신 UI 파일(동일 폴더)에 있어야 합니다.
import ledDht11Graph as ui_module

SOF = 0xAA

# ---------------- CRC16-IBM (Modbus) ----------------
def crc16_ibm(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def build_led_frame(led_no: int, value_percent: int) -> bytes:
    """LED 설정 프레임 생성 (0~100 -> 0x00~0x64)"""
    if value_percent < 0: value_percent = 0
    if value_percent > 100: value_percent = 100
    payload = bytes([led_no & 0xFF, value_percent & 0xFF])
    head = bytes([SOF, len(payload)])  # SOF, LEN
    crc = crc16_ibm(head + payload)    # SOF~payload
    return head + payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

# ---------------- Serial Worker ----------------
class SerialThread(QThread):
    sig_status = pyqtSignal(int, int, int)     # r,g,b (0~100)
    sig_sensor = pyqtSignal(float, float)      # temp, humi
    sig_log    = pyqtSignal(str)
    sig_opened = pyqtSignal(bool)

    def __init__(self, port=None, baud=115200, parent=None):
        super().__init__(parent)
        self._port = port
        self._baud = baud
        self._ser = None
        self._rxbuf = bytearray()
        self._running = True

    def stop(self):
        self._running = False
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except:
            pass

    def open_port_auto(self):
        # 1) 지정 포트 우선
        if self._port:
            try:
                self._ser = serial.Serial(self._port, self._baud, timeout=0.1)
                self.sig_log.emit(f"[INFO] Open {self._port}")
                return True
            except Exception as e:
                self.sig_log.emit(f"[ERR] open {self._port}: {e}")

        # 2) CP210x(10C4:EA60) 우선 탐색
        for p in serial.tools.list_ports.comports():
            if (p.vid, p.pid) == (0x10C4, 0xEA60):
                try:
                    self._ser = serial.Serial(p.device, self._baud, timeout=0.1)
                    self.sig_log.emit(f"[INFO] Auto-open CP210x {p.device}")
                    return True
                except Exception as e:
                    self.sig_log.emit(f"[ERR] open {p.device}: {e}")

        # 3) 그 외 첫 번째 포트
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            try:
                self._ser = serial.Serial(ports[0], self._baud, timeout=0.1)
                self.sig_log.emit(f"[INFO] Auto-open {ports[0]}")
                return True
            except Exception as e:
                self.sig_log.emit(f"[ERR] open {ports[0]}: {e}")

        return False

    @QtCore.pyqtSlot(bytes)
    def tx_write(self, data: bytes):
        if self._ser and self._ser.is_open:
            try:
                self._ser.write(data)
            except Exception as e:
                self.sig_log.emit(f"[TX ERR] {e}")

    def parse_frames(self):
        """SOF 기반 고정형 프레이밍 파서: SOF, LEN, payload, CRC2"""
        buf = self._rxbuf
        while True:
            sof_idx = buf.find(bytes([SOF]))
            if sof_idx < 0:
                buf.clear()
                return
            if sof_idx > 0:
                del buf[:sof_idx]
            if len(buf) < 2:
                return

            length = buf[1]
            need = 2 + length + 2
            if len(buf) < need:
                return

            frame = bytes(buf[:need])
            del buf[:need]

            payload = frame[2:-2]
            recv_crc = frame[-2] | (frame[-1] << 8)
            calc_crc = crc16_ibm(frame[:-2])
            if recv_crc != calc_crc:
                self.sig_log.emit("[WARN] CRC mismatch - drop frame")
                continue

            # ---- 타입 분기 ----
            if length == 3:
                # 상태: R,G,B (0~100)
                r, g, b = payload[0], payload[1], payload[2]
                self.sig_status.emit(r, g, b)

            elif length == 2:
                # 센서 단순형: T(uint8 °C), H(uint8 %)
                t, h = payload[0], payload[1]
                # 값 범위가 일반적이면 센서로 간주
                if -40 <= t <= 125 and 0 <= h <= 100:
                    self.sig_sensor.emit(float(t), float(h))
                else:
                    self.sig_log.emit(f"[INFO] Unhandled 2B payload: {payload.hex(' ')}")

            elif length == 5 and payload[0] == 0x54:
                # 센서 태그형: 'T', int16_le * 2 (0.1 단위)
                t10 = payload[1] | (payload[2] << 8)
                h10 = payload[3] | (payload[4] << 8)
                if t10 >= 0x8000: t10 -= 0x10000
                if h10 >= 0x8000: h10 -= 0x10000
                self.sig_sensor.emit(t10/10.0, h10/10.0)

            elif length == 4:
                # 센서 정밀형(태그 없음): int16_le * 2 (0.1 단위)
                t10 = payload[0] | (payload[1] << 8)
                h10 = payload[2] | (payload[3] << 8)
                if t10 >= 0x8000: t10 -= 0x10000
                if h10 >= 0x8000: h10 -= 0x10000
                self.sig_sensor.emit(t10/10.0, h10/10.0)

            else:
                self.sig_log.emit(f"[INFO] Unknown payload len={length} : {payload.hex(' ')}")

    def run(self):
        if not self.open_port_auto():
            self.sig_opened.emit(False)
            self.sig_log.emit("[ERR] No serial port available.")
            return

        self.sig_opened.emit(True)
        try:
            while self._running:
                try:
                    data = self._ser.read(128)
                    if data:
                        self._rxbuf += data
                        self.parse_frames()
                except serial.SerialException as e:
                    self.sig_log.emit(f"[SER] {e}")
                    break
                except Exception as e:
                    self.sig_log.emit(f"[RX ERR] {e}")
        finally:
            try:
                if self._ser: self._ser.close()
            except:
                pass
            self.sig_opened.emit(False)

# ---------------- Main Dialog ----------------
class MainDialog(QtWidgets.QDialog, ui_module.Ui_Dialog):
    sig_tx = pyqtSignal(bytes)  # QThread로 보낼 송신 시그널

    def __init__(self, serial_port=None, baud=115200, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 그래프 설정
        self._setup_plot()

        # 데이터 버퍼
        self.max_pts = 300
        self.x_idx = 0
        self.xdata = deque(maxlen=self.max_pts)
        self.tdata = deque(maxlen=self.max_pts)
        self.hdata = deque(maxlen=self.max_pts)

        # 시리얼 스레드
        self.th = SerialThread(port=serial_port, baud=baud)
        self.sig_tx.connect(self.th.tx_write)
        self.th.sig_opened.connect(self.on_serial_opened)
        self.th.sig_status.connect(self.on_status)
        self.th.sig_sensor.connect(self.on_sensor)
        self.th.sig_log.connect(self.append_log)
        self.th.start()

        # UI 이벤트 → 전송
        self.sliderRed.valueChanged.connect(lambda v: self.send_led(0x01, v))
        self.sliderGreen.valueChanged.connect(lambda v: self.send_led(0x02, v))
        self.sliderBlue.valueChanged.connect(lambda v: self.send_led(0x03, v))
        self.btnAllon.clicked.connect(self.send_all_current)

    def _setup_plot(self):
        pg.setConfigOptions(antialias=True)
        self.graphicsView.showGrid(x=True, y=True, alpha=0.3)
        self.graphicsView.addLegend()
        self.graphicsView.setLabel('left', 'Value')
        self.graphicsView.setLabel('bottom', 'Samples')
        self.curve_t = self.graphicsView.plot([], [], pen=None, name="Temp(°C)")
        self.curve_h = self.graphicsView.plot([], [], pen=None, name="Humi(%)")
        # 기본 펜(색상 자동) + 굵기만 지정
        self.curve_t.setPen(pg.mkPen(width=2))
        self.curve_h.setPen(pg.mkPen(width=2))

    # ---------- Serial handlers ----------
    def on_serial_opened(self, ok: bool):
        self.append_log("[INFO] Serial opened" if ok else "[INFO] Serial closed")

    def on_status(self, r, g, b):
        # 슬라이더 ↔ 전송 루프 방지 위해 블록
        self.sliderRed.blockSignals(True)
        self.sliderGreen.blockSignals(True)
        self.sliderBlue.blockSignals(True)
        self.sliderRed.setValue(r)
        self.sliderGreen.setValue(g)
        self.sliderBlue.setValue(b)
        self.sliderRed.blockSignals(False)
        self.sliderGreen.blockSignals(False)
        self.sliderBlue.blockSignals(False)

    def on_sensor(self, temp: float, humi: float):
        # 라벨/라인에 표시
        self.lineTemp.setText(f"{temp:.1f}")
        self.lineHumi.setText(f"{humi:.1f}")
        # 그래프 업데이트
        self.x_idx += 1
        self.xdata.append(self.x_idx)
        self.tdata.append(temp)
        self.hdata.append(humi)
        self.curve_t.setData(list(self.xdata), list(self.tdata))
        self.curve_h.setData(list(self.xdata), list(self.hdata))

    def append_log(self, msg: str):
        # 별도의 로그 위젯이 없으므로 콘솔로 출력
        print(msg)

    # ---------- TX helpers ----------
    def send_led(self, led_no: int, value: int):
        frame = build_led_frame(led_no, value)
        self.sig_tx.emit(frame)

    def send_all_current(self):
        self.send_led(0x01, self.sliderRed.value())
        self.send_led(0x02, self.sliderGreen.value())
        self.send_led(0x03, self.sliderBlue.value())

    # 종료 처리
    def closeEvent(self, e):
        try:
            self.th.stop()
            self.th.wait(1000)
        except:
            pass
        return super().closeEvent(e)

# ---------------- Entrypoint ----------------
def main():
    # 커맨드라인에서 포트를 지정하고 싶으면: python main_led_graph.py COM7
    port = sys.argv[1] if len(sys.argv) > 1 else None
    app = QtWidgets.QApplication(sys.argv)
    dlg = MainDialog(serial_port=port, baud=115200)
    dlg.setWindowTitle("LED + Temp/Humi Monitor")
    dlg.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
