// ESP32 RGB LED Binary Protocol Controller (Arduino core 3.x)
// Frame (TX->ESP32): | SOF(0xAA) | LEN | LED No. | Value | CRC16(LSB) | CRC16(MSB) |
// Frame (ESP32->RX): | 0xAA | 0x03 | R | G | B | CRC16(LSB) | CRC16(MSB) |
// CRC16-IBM (poly 0xA001, init 0xFFFF), computed over SOF..payload (CRC 제외)

#include <Arduino.h>
#include <esp32-hal-ledc.h>   // core 3.x: ledcAttach(pin,freq,res), ledcWrite(pin,duty)

/// ====== 핀/LEDC 설정 ======
static const int PIN_R = 23;
static const int PIN_G = 22;
static const int PIN_B = 21;

static const uint32_t LEDC_FREQ = 5000;   // 5 kHz
static const uint8_t  LEDC_RES  = 8;      // 8-bit (0~255)

// 공통 애노드 LED면 true로 (듀티 반전)
static const bool COMMON_ANODE = false;

// 내부 상태(0~100 %)
static uint8_t valR = 0, valG = 0, valB = 0;

/// ====== CRC16-IBM (Modbus) ======
static uint16_t crc16_ibm(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (int j = 0; j < 8; ++j) {
      if (crc & 0x0001) crc = (crc >> 1) ^ 0xA001;
      else              crc >>= 1;
    }
  }
  return crc;
}

// 0~100% → 0~255 듀티(반올림, 공통애노드 반전)
static inline uint8_t percentToDuty(uint8_t p) {
  if (p > 100) p = 100;
  uint16_t duty = (uint16_t)p * 255 + 50; // rounding
  duty /= 100;
  if (COMMON_ANODE) duty = 255 - duty;
  return (uint8_t)duty;
}

static void applyChannels() {
  ledcWrite(PIN_R, percentToDuty(valR));
  ledcWrite(PIN_G, percentToDuty(valG));
  ledcWrite(PIN_B, percentToDuty(valB));
}

// 상태 응답: | AA | 03 | R | G | B | CRC(LSB) | CRC(MSB) |
static void sendStatus() {
  uint8_t frame[2 + 3]; // SOF + LEN + payload(3)
  frame[0] = 0xAA;
  frame[1] = 0x03;
  frame[2] = valR;
  frame[3] = valG;
  frame[4] = valB;

  uint16_t crc = crc16_ibm(frame, sizeof(frame));
  Serial.write(frame, sizeof(frame));
  Serial.write((uint8_t)(crc & 0xFF));         // LSB
  Serial.write((uint8_t)((crc >> 8) & 0xFF));  // MSB
}

/// ====== 수신 파서 ======
enum RxState { WAIT_SOF, WAIT_LEN, WAIT_PAYLOAD, WAIT_CRC_L, WAIT_CRC_H };
static RxState rxState = WAIT_SOF;

static uint8_t  rxLen   = 0;
static uint8_t  rxBuf[32];
static uint8_t  rxIdx   = 0;
static uint16_t rxCrc   = 0;

static void resetRx() {
  rxState = WAIT_SOF;
  rxLen   = 0;
  rxIdx   = 0;
  rxCrc   = 0;
}

static void handleFrame(const uint8_t* payload, uint8_t len) {
  if (len < 2) {          // payload = [LED No.][Value]
    sendStatus();
    return;
  }
  uint8_t ledNo = payload[0];
  uint8_t value = payload[1];
  if (value > 0x64) value = 0x64; // 100% clamp

  switch (ledNo) {
    case 0x01: valR = value; break;
    case 0x02: valG = value; break;
    case 0x03: valB = value; break;
    case 0x0F: valR = valG = valB = value; break;
    default: /* 알 수 없는 채널: 무시 */ break;
  }
  applyChannels();
  sendStatus();
}

static void processSerial() {
  while (Serial.available() > 0) {
    uint8_t b = (uint8_t)Serial.read();

    switch (rxState) {
      case WAIT_SOF:
        if (b == 0xAA) {
          rxBuf[0] = b;
          rxState  = WAIT_LEN;
        }
        break;

      case WAIT_LEN:
        rxLen     = b;     // payload 길이
        rxBuf[1]  = b;     // LEN 저장
        rxIdx     = 0;     // payload 채우기 시작
        if (rxLen > sizeof(rxBuf) - 2) {
          resetRx();       // 과도한 길이 → 폐기
        } else {
          rxState = WAIT_PAYLOAD;
        }
        break;

      case WAIT_PAYLOAD:
        rxBuf[2 + rxIdx] = b;
        rxIdx++;
        if (rxIdx >= rxLen) {
          rxState = WAIT_CRC_L;
        }
        break;

      case WAIT_CRC_L:
        rxCrc = b;                 // LSB
        rxState = WAIT_CRC_H;
        break;

      case WAIT_CRC_H: {
        rxCrc |= (uint16_t)b << 8; // MSB
        // CRC 검증 (SOF..payload)
        uint16_t calc = crc16_ibm(rxBuf, 2 + rxLen);
        if (calc == rxCrc) {
          handleFrame(&rxBuf[2], rxLen);
        }
        resetRx();
        break;
      }
    }
  }
}

void setup() {
  Serial.begin(115200);

  // core 3.x: 핀 단위 LEDC 초기화 (채널 개념 없이 자동 할당)
  ledcAttach(PIN_R, LEDC_FREQ, LEDC_RES);
  ledcAttach(PIN_G, LEDC_FREQ, LEDC_RES);
  ledcAttach(PIN_B, LEDC_FREQ, LEDC_RES);

  // 공통 애노드면 역상
  if (COMMON_ANODE) {
    ledcOutputInvert(PIN_R, true);
    ledcOutputInvert(PIN_G, true);
    ledcOutputInvert(PIN_B, true);
  }

  applyChannels();
  sendStatus(); // 부팅 알림(옵션)
}

void loop() {
  processSerial();
}

    
