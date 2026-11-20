#include <WiFi.h>
#include <time.h>
#include <MQTT.h>
#include <Wire.h>
#include <BH1750.h>
#include "DHT.h"
#include "secrets.h"

#define DHTPIN      4
#define DHTTYPE     DHT22
#define REPORT_MS   10000
#define BUF_SIZE    200

#define LED_G       26
#define LED_R       27
#define BUZZER      25
#define TEMP_ALARM  32.0      // 测试用！验证完改成 32.0（与需求说明 R1 一致）

DHT dht(DHTPIN, DHTTYPE);
BH1750 lightMeter;

WiFiClient net;
MQTTClient client(512);
String topic;

unsigned long lastReport = 0;
unsigned long lastTry    = 0;
bool lastHot = false;

// ---------- 环形缓冲 ----------
String buf[BUF_SIZE];
int    bufHead  = 0;
int    bufCount = 0;

void bufPush(const String &s) {
  buf[bufHead] = s;
  bufHead = (bufHead + 1) % BUF_SIZE;
  if (bufCount < BUF_SIZE) bufCount++;
  Serial.printf("[BUF] %d/%d\n", bufCount, BUF_SIZE);
}

int bufOldest() {
  return (bufHead - bufCount + BUF_SIZE) % BUF_SIZE;
}

void flushBuffer() {
  if (bufCount == 0) return;
  Serial.printf("[FLUSH] 开始补发 %d 条\n", bufCount);
  while (bufCount > 0 && client.connected()) {
    int i = bufOldest();
    if (!client.publish(topic, buf[i], false, 1)) break;
    bufCount--;
    delay(20);
  }
  Serial.printf("[FLUSH] 结束，剩余 %d 条\n", bufCount);
}

// ---------- WiFi / NTP ----------
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
  char b[32];
  strftime(b, sizeof(b), "%Y-%m-%dT%H:%M:%S", &t);
  return String(b) + "+08:00";
}

String uuid4() {
  uint8_t b[16];
  for (int i = 0; i < 16; i += 4) {
    uint32_t r = esp_random();
    memcpy(b + i, &r, 4);
  }
  b[6] = (b[6] & 0x0F) | 0x40;
  b[8] = (b[8] & 0x3F) | 0x80;
  char s[37];
  snprintf(s, sizeof(s),
           "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           b[0], b[1], b[2],  b[3],  b[4],  b[5],  b[6],  b[7],
           b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
  return String(s);
}

// ---------- 非阻塞重连 ----------
void ensureConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] lost, reconnect");
    WiFi.reconnect();
    delay(1000);
    return;
  }
  if (client.connected()) return;
  if (millis() - lastTry < 5000) return;
  lastTry = millis();

  Serial.print("[MQTT] reconnect...");
  if (client.connect(NODE_ID)) {
    Serial.println(" ok");
    flushBuffer();
  } else {
    Serial.println(" fail");
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("=== 3.6 firmware (buffer + LED + buzzer) ===");

  pinMode(LED_G, OUTPUT);
  pinMode(LED_R, OUTPUT);
  pinMode(BUZZER, OUTPUT);
  digitalWrite(LED_R, LOW);
  digitalWrite(BUZZER, LOW);
  digitalWrite(LED_G, HIGH);          // 上电即绿灯 = 正常运行

  connectWiFi();
  syncTime();

  dht.begin();
  Wire.begin(21, 22);
  lightMeter.begin();

  topic = String("iot/") + NODE_ID + "/data";
  client.begin(MQTT_HOST, MQTT_PORT, net);
  client.setKeepAlive(60);

  if (client.connect(NODE_ID)) {
    Serial.println("MQTT connected");
    flushBuffer();
  } else {
    Serial.println("MQTT not connected, will retry in loop");
  }
}

void loop() {
  client.loop();
  ensureConnected();

  if (millis() - lastReport < REPORT_MS) {
    delay(50);
    return;
  }
  lastReport = millis();

  float t   = dht.readTemperature();
  float h   = dht.readHumidity();
  float lux = lightMeter.readLightLevel();

  if (isnan(t) || isnan(h)) {
    Serial.println("dht read failed, skip");
    return;
  }

  // ---- 本地告警：断网时云端判不了，蜂鸣器是唯一还能报警的通道 ----
  bool hot = (t > TEMP_ALARM);
  digitalWrite(LED_R, hot ? HIGH : LOW);
  digitalWrite(LED_G, hot ? LOW  : HIGH);
  digitalWrite(BUZZER, hot ? HIGH : LOW);

  if (hot != lastHot) {
    lastHot = hot;
    if (hot) Serial.printf("[ALARM] ON   t=%.1f > %.1f\n", t, TEMP_ALARM);
    else     Serial.println("[ALARM] OFF");
  }

  String payload = String("{\"id\":\"") + uuid4()
                 + "\",\"ts\":\"" + isoNow()
                 + "\",\"t\":" + String(t, 1)
                 + ",\"h\":" + String(h, 1)
                 + ",\"lux\":" + String(lux, 1) + "}";

  if (client.connected() && client.publish(topic, payload, false, 1)) {
    Serial.print("PUB OK  ");
    Serial.println(payload);
  } else {
    Serial.print("PUB FAIL -> buffer  ");
    Serial.println(payload.substring(0, 60));
    bufPush(payload);
  }
}