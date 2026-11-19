// 阶段 1.4：BH1750 光照（含 I2C 扫描）
// 接线：VCC→3V3  GND→GND  SDA→D21(左排14)  SCL→D22(左排17)  ADDR→悬空
// 结论：2026-11-19 扫描到 0x23，读数正常
//       白天朝窗 41 662.9 lux，手掌遮住 1.7 lux（相差 2 万倍）
//
// 排障顺序：先跑 I2C 扫描确认设备在总线上，再谈读数。扫不到就是接线/焊接问题，改代码没用。

#include <Wire.h>
#include <BH1750.h>

BH1750 lightMeter;

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);

  // --- 先扫描总线，确认 0x23 在 ---
  Serial.println();
  Serial.println("=== I2C scan ===");
  int n = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print("found 0x");
      if (addr < 16) Serial.print("0");
      Serial.println(addr, HEX);
      n++;
    }
  }
  Serial.print("devices: ");
  Serial.println(n);

  lightMeter.begin();
  delay(200);
}

void loop() {
  float lux = lightMeter.readLightLevel();
  Serial.print("lux = ");
  Serial.println(lux, 1);
  delay(1000);
}
