// 阶段 1.3：DHT22 单点读数（温湿度）
// 接线：VCC→3V3(右排19)  NC→空  DAT→D4(左排7)  GND→GND(右排6)
// 结论：2026-11-18 读通 T=19.40C / H=45.50%，数值稳定不跳
//
// 踩过的坑：模块丝印是 GND / NC / DAT / VCC，与"常见模块 VCC 在前"相反，
// 第一次按经验接，串口全是 read failed。

#include "DHT.h"

#define DHTPIN  4
#define DHTTYPE DHT22

DHT dht(DHTPIN, DHTTYPE);

void setup() {
  Serial.begin(115200);
  dht.begin();
  delay(500);
  Serial.println();
  Serial.println("=== DHT22 test ===");
}

void loop() {
  delay(2000);                    // DHT22 最快 2 秒一次，读太快返回 nan

  float h = dht.readHumidity();
  float t = dht.readTemperature();

  if (isnan(h) || isnan(t)) {
    Serial.println("read failed: check VCC(3V3) / DATA(D4) / GND / pull-up");
    return;
  }

  Serial.print("T="); Serial.print(t);
  Serial.print(" C   H="); Serial.print(h);
  Serial.println(" %");
}
