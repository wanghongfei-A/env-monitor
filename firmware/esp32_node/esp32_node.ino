#include <WiFi.h>
#include <time.h>
#include <MQTT.h>
#include <Wire.h>
#include <BH1750.h>
#include "DHT.h"
#include "secrets.h"

#define DHTPIN     4
#define DHTTYPE    DHT22
#define REPORT_MS  10000        // 10 秒一采一报

DHT dht(DHTPIN, DHTTYPE);
BH1750 lightMeter;

WiFiClient net;
MQTTClient client(512);
String topic;
unsigned long lastReport = 0;

// ---------- WiFi ----------
bool connectWiFi() {
  Serial.print("WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int n = 0;
  while (WiFi.status() != WL_CONNECTED && n < 40) {
    delay(500); Serial.print("."); n++;
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("  IP="); Serial.println(WiFi.localIP());
    return true;
  }
  Serial.println("  WiFi FAILED");
  return false;
}

// ---------- NTP ----------
bool syncTime() {
  configTime(8 * 3600, 0, "ntp.aliyun.com", "cn.pool.ntp.org");
  Serial.print("NTP");
  time_t now = 0; int n = 0;
  while ((now = time(nullptr)) < 1700000000 && n < 40) {
    delay(500); Serial.print("."); n++;
  }
  Serial.println();
  return now >= 1700000000;
}

String isoNow() {
  struct tm t;
  if (!getLocalTime(&t, 1000)) return String("(no time)");
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &t);
  return String(buf) + "+08:00";
}

// ---------- msg_id：uuid v4 ----------
// 用硬件随机数生成，重启也不重复。服务端靠它做幂等去重。
String uuid4() {
  uint8_t b[16];
  for (int i = 0; i < 16; i += 4) {
    uint32_t r = esp_random();
    memcpy(b + i, &r, 4);
  }
  b[6] = (b[6] & 0x0F) | 0x40;      // version 4
  b[8] = (b[8] & 0x3F) | 0x80;      // variant
  char s[37];
  snprintf(s, sizeof(s),
           "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           b[0], b[1], b[2],  b[3],  b[4],  b[5],  b[6],  b[7],
           b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
  return String(s);
}

// ---------- MQTT ----------
void connectMQTT() {
  Serial.print("MQTT");
  while (!client.connect(NODE_ID)) {
    Serial.print(".");
    delay(1000);
  }
  Serial.println("  connected");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("=== 3.4 report ===");

  if (!connectWiFi()) return;
  if (!syncTime())   return;

  dht.begin();
  Wire.begin(21, 22);
  lightMeter.begin();

  topic = String("iot/") + NODE_ID + "/data";
  client.begin(MQTT_HOST, MQTT_PORT, net);
  client.setKeepAlive(60);
  connectMQTT();
}

void loop() {
  client.loop();

  if (!client.connected()) {
    Serial.println("MQTT lost, reconnecting...");
    connectMQTT();
  }

  if (millis() - lastReport < REPORT_MS) {
    delay(50);
    return;
  }
  lastReport = millis();

  float t   = dht.readTemperature();
  float h   = dht.readHumidity();
  float lux = lightMeter.readLightLevel();

  if (isnan(t) || isnan(h)) {
    Serial.println("dht read failed, skip this round");
    return;
  }

  String payload = String("{\"id\":\"") + uuid4()
                 + "\",\"ts\":\"" + isoNow()
                 + "\",\"t\":" + String(t, 1)
                 + ",\"h\":" + String(h, 1)
                 + ",\"lux\":" + String(lux, 1) + "}";

  bool ok = client.publish(topic, payload, false, 1);   // QoS 1
  Serial.print(ok ? "PUB OK   " : "PUB FAIL ");
  Serial.println(payload);
}