// 用法：把本文件复制一份，改名 secrets.h，填入你自己的真实值。
// secrets.h 已在 .gitignore 中（和钉钉 Webhook 一样属于凭据），不会进仓库。
//
// Windows 复制命令（在 firmware/esp32_node 目录下）：
//   Copy-Item secrets.example.h secrets.h

#pragma once

// ---- 手机热点（必须 2.4GHz；ESP32 不支持 5GHz）----
#define WIFI_SSID  "your-hotspot-ssid"
#define WIFI_PASS  "your-hotspot-password"

// ---- 电脑在热点网段的 IP（在电脑上 ipconfig 查"无线局域网适配器 WLAN"的 IPv4）----
// 注意：不是 127.0.0.1——板子是另一台设备，必须用局域网地址
#define MQTT_HOST  "192.168.x.x"
#define MQTT_PORT  1883

// ---- 节点编号（写进主题 iot/<NODE_ID>/data 和数据库 node_id）----
#define NODE_ID    "node01"
