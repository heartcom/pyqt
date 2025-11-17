# ledDht11Run.py
# 환경 제어 프로그램 : RGB PWM + DHT11(온도/습도)
# - RGB LED : GPIO13(RED), GPIO12(GREEN), GPIO18(BLUE)
# - DHT11   : GPIO4 (board.D4)

import sys
import time
from PyQt5 import QtWidgets, QtCore
from ledDht11 import Ui_Dialog   # <- 방금 만들어둔 UI 파일

# -------------------- RPi.GPIO (RGB PWM) -------------------- #
try:
    import RPi.GPIO as GPIO
    RPI_AVAILABLE = True
except ImportError:
    GPIO = None
    RPI_AVAILABLE = False
    print("[INFO] RPi.GPIO 모듈이 없어 RGB 제어는 시뮬레이션 모드로 동작합니다.")


class LedPwmController:
    RED_PIN = 13    # BCM
    GREEN_PIN = 12
    BLUE_PIN = 18

    def __init__(self, freq: int = 1000):
        self.red_val = 0
        self.green_val = 0
        self.blue_val = 0

        self.simulation = not RPI_AVAILABLE
        if self.simulation:
            print("[INFO] GPIO 제어 없이 값만 기록합니다.")
            return

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

    def set_rgb(self, r: int, g: int, b: int):
        """0~100 값으로 RGB PWM 설정"""
        self.red_val = max(0, min(100, r))
        self.green_val = max(0, min(100, g))
        self.blue_val = max(0, min(100, b))

        if self.simulation:
            print(f"[SIM] set_rgb -> R={self.red_val}, G={self.green_val}, B={self.blue_val}")
            return

        self.red_pwm.ChangeDutyCycle(self.red_val)
        self.green_pwm.ChangeDutyCycle(self.green_val)
        self.blue_pwm.ChangeDutyCycle(self.blue_val)

    def cleanup(self):
        if self.simulation:
            return
        self.red_pwm.stop()
        self.green_pwm.stop()
        self.blue_pwm.stop()
        GPIO.cleanup()


# -------------------- DHT11 읽기용 QThread -------------------- #
class DhtThread(QtCore.QThread):
    # temp(C), humi(%) 를 메인 스레드로 보내는 시그널
    newData = QtCore.pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def run(self):
        # 여기서 센서 초기화 (쓰레드 안에서 실행)
        try:
            import board
            import adafruit_dht
            sensor = adafruit_dht.DHT11(board.D4, use_pulseio=False)
            hw_ok = True
            print("[INFO] DHT11 센서 초기화 성공 (GPIO4)")
        except Exception as e:
            print("[WARN] DHT11 초기화 실패, 모의 데이터로 동작합니다:", e)
            sensor = None
            hw_ok = False

        while self._running:
            if hw_ok:
                try:
                    temperature_c = sensor.temperature
                    humidity = sensor.humidity
                    if (temperature_c is not None) and (humidity is not None):
                        self.newData.emit(float(temperature_c), float(humidity))
                except RuntimeError as e:
                    # DHT 특성상 가끔 에러가 나므로 너무 시끄럽지 않게 출력
                    print("[DHT] RuntimeError:", e)
                except Exception as e:
                    print("[DHT] 기타 오류:", e)
            else:
                # 센서가 없을 때 테스트용 가짜 값
                self.newData.emit(25.0, 40.0)

            # 약 3초 간격
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(0.1)

    def stop(self):
        self._running = False


# -------------------- 메인 다이얼로그 -------------------- #
class MainDialog(QtWidgets.QDialog, Ui_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 텍스트 입력 막기 (표시용)
        self.lineTemp.setReadOnly(True)
        self.lineHumi.setReadOnly(True)

        # RGB PWM 컨트롤러
        self.led = LedPwmController()

        # SEND 버튼 → 현재 슬라이더 값으로 RGB 세팅
        self.btnAllon.clicked.connect(self.on_send_clicked)

        # DHT11 쓰레드 시작
        self.dht_thread = DhtThread()
        self.dht_thread.newData.connect(self.update_dht_display)
        self.dht_thread.start()

    # SEND 버튼 핸들러 (RGB PWM 제어)
    def on_send_clicked(self):
        r = self.sliderRed.value()
        g = self.sliderGreen.value()
        b = self.sliderBlue.value()
        self.led.set_rgb(r, g, b)
        print(f"[LED] R={r}%, G={g}%, B={b}%")

    # DHT11 데이터 수신 시 UI 업데이트
    @QtCore.pyqtSlot(float, float)
    def update_dht_display(self, temp_c: float, humi: float):
        self.lineTemp.setText(f"{temp_c:0.1f}")
        self.lineHumi.setText(f"{humi:0.1f}")

    # 창 닫을 때 정리
    def closeEvent(self, event):
        # DHT 쓰레드 종료
        self.dht_thread.stop()
        self.dht_thread.wait(2000)

        # GPIO 정리
        self.led.cleanup()
        event.accept()


# -------------------- main -------------------- #
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    dlg = MainDialog()
    dlg.show()
    sys.exit(app.exec_())
