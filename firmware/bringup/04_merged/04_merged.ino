// 阶段 1.5：三个测量值合并到一个程序
// 输出格式刻意做成 JSON —— 这就是后面要 publish 到 MQTT 的 payload 形状，
// 先在串口里把数据格式调对，再上网络；出问题时能分清"格式问题"还是"网络问题"。
//
// 注意：DHT22 一颗芯片同时给温度和湿度（一次读两个值），BH1750 单独走 I2C。
// 所以"三个数据"其实是两次读。

#include <Wire.h>
#include <BH1750.h>
#include "DHT.h"

#define DHTPIN  4
#define DHTTYPE DHT22

DHT dht(DHTPIN, DHTTYPE);
BH1750 lightMeter;

void setup() {
  Serial.begin(115200);
  dht.begin();
  Wire.begin(21, 22);
  lightMeter.begin();
  delay(500);
  Serial.println();
  Serial.println("=== node01 : 3 sensors ===");
}

void loop() {
  delay(2000);                       // 验证阶段 2 秒；固件阶段改 10 秒

  float t   = dht.readTemperature();
  float h   = dht.readHumidity();
  float lux = lightMeter.readLightLevel();

  if (isnan(t) || isnan(h)) {
    Serial.println("{\"error\":\"dht read failed\"}");
    return;
  }

  Serial.print("{\"t\":");   Serial.print(t, 1);
  Serial.print(",\"h\":");   Serial.print(h, 1);
  Serial.print(",\"lux\":"); Serial.print(lux, 1);
  Serial.println("}");
}
