#include <WiFi.h>
#include <time.h>
#include <MQTT.h>
#include <Wire.h>
#include <BH1750.h>
#include "DHT.h"
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "secrets.h"

#define DHTPIN      4
#define DHTTYPE     DHT22
#define REPORT_MS   10000
#define BUF_SIZE    200

#define LED_G       26
#define LED_R       27
#define BUZZER      25
#define TEMP_ALARM  32.0      // R1 过热阈值，与需求说明一致

DHT dht(DHTPIN, DHTTYPE);
BH1750 lightMeter;
Adafruit_SSD1306 display(128, 64, &Wire, -1);
bool oledOk = false;

WiFiClient net;
MQTTClient client(512);
String topic;

unsigned long lastReport  = 0;
unsigned long lastTry     = 0;
unsigned long lastWifiTry = 0;
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

// ---------- OLED ----------
void drawScreen(float t, float h, float lux) {
  if (!oledOk) return;

  char l1[24], l2[24], l3[24];
  snprintf(l1, sizeof(l1), "T %.1fC   H %.1f%%", t, h);
  snprintf(l2, sizeof(l2), "Lux %.0f", lux);
  snprintf(l3, sizeof(l3), "buf %d/%d", bufCount, BUF_SIZE);

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.print("node01 ");
  display.print(WiFi.status() == WL_CONNECTED ? "WiFi OK" : "WiFi --");

  display.setCursor(0, 16);
  display.print(l1);

  display.setCursor(0, 28);
  display.print(l2);

  display.setCursor(0, 40);
  display.print(client.connected() ? "MQTT OK" : "MQTT --");

  display.setCursor(0, 52);
  display.print(l3);

  display.display();
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

// ---------- 连接维护 ----------
void ensureConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    // WiFi.reconnect() 在 ESP32 上不可靠：热点短暂消失后可能永远连不回来。
    // 改用 disconnect + begin 重新发起，并限流到每 10 秒一次。
    if (millis() - lastWifiTry > 10000) {
      lastWifiTry = millis();
      Serial.println("[WiFi] reconnect (disconnect+begin)");
      WiFi.disconnect();
      delay(100);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
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
  Serial.println("=== firmware: sensors + buffer + LED + buzzer + OLED ===");

  pinMode(LED_G, OUTPUT);
  pinMode(LED_R, OUTPUT);
  pinMode(BUZZER, OUTPUT);
  digitalWrite(LED_R, LOW);
  digitalWrite(BUZZER, LOW);
  digitalWrite(LED_G, HIGH);

  Wire.begin(21, 22);

  oledOk = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (oledOk) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("env-monitor booting...");
    display.display();
    Serial.println("OLED ok (0x3C)");
  } else {
    Serial.println("OLED init FAILED (try 0x3D)");
  }

  dht.begin();
  lightMeter.begin();

  connectWiFi();
  syncTime();

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

  bool hot = (t > TEMP_ALARM);
  digitalWrite(LED_R, hot ? HIGH : LOW);
  digitalWrite(LED_G, hot ? LOW  : HIGH);
  digitalWrite(BUZZER, hot ? HIGH : LOW);

  if (hot != lastHot) {
    lastHot = hot;
    if (hot) Serial.printf("[ALARM] ON   t=%.1f > %.1f\n", t, TEMP_ALARM);
    else     Serial.println("[ALARM] OFF");
  }

  drawScreen(t, h, lux);

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