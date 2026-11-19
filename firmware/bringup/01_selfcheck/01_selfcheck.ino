// 阶段 1.1 / 1.2：最小自检 —— 串口能打印、GPIO 能输出
// 结论：烧录链路、USB 串口、GPIO 全部正常（2026-11-18 验证通过）

#define LED 2   // 板载灯接 GPIO2（不用 LED_BUILTIN：ESP32 核心 3.x 未给通用板型定义该宏）

void setup() {
  Serial.begin(115200);
  pinMode(LED, OUTPUT);
  delay(500);
  Serial.println();
  Serial.println("=== boot ===");
  Serial.println("serial ok @ 115200");
}

void loop() {
  digitalWrite(LED, HIGH);
  Serial.println("tick: LED on");
  delay(500);
  digitalWrite(LED, LOW);
  Serial.println("tick: LED off");
  delay(500);
}
