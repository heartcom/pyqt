import time
import board
import adafruit_dht

sensor = adafruit_dht.DHT11(board.D4, use_pulseio=False)

while True:
    try:
        t = sensor.temperature
        h = sensor.humidity
        print("Temp: {:.1f} C, Humi: {:.1f} %".format(t, h))
    except RuntimeError as e:
        print("RuntimeError:", e)
    except Exception as e:
        print("Exception:", e)
        sensor.exit()
        raise
    time.sleep(3)
