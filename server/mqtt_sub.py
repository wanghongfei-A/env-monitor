"""MQTT 订阅 → SQLite 入库。

三个关键点：
1. 固定 client_id + clean_session=False —— broker 会在后端离线期间替我保留 QoS1 消息
2. on_connect 里订阅 —— 断线重连后必须重新订阅，否则连上了也收不到
3. on_message 里 try/except —— 一条坏消息不能把整个订阅搞崩
"""

import json

import paho.mqtt.client as mqtt

from storage import connect, init_db, insert_reading

BROKER = "127.0.0.1"
PORT = 1883
TOPIC = "iot/+/data"
CLIENT_ID = "server-sub"          # 固定！随机 ID 会让 broker 认不出是同一个人

conn = connect()
init_db(conn)


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[connect] rc={reason_code}")
    client.subscribe(TOPIC, qos=1)
    print(f"[subscribe] {TOPIC} qos=1")


def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode("utf-8"))
        node = msg.topic.split("/")[1]            # iot/node01/data -> node01
        ok = insert_reading(conn, d["id"], node, d["ts"],
                            d.get("t"), d.get("h"), d.get("lux"))
        print(f"[{'NEW' if ok else 'DUP'}] {node} {d['id'][:8]} "
              f"t={d.get('t')} h={d.get('h')} lux={d.get('lux')}")
    except Exception as e:
        print(f"[error] {e} | payload={msg.payload[:120]}")


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    print(f"[disconnect] rc={reason_code}")


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=CLIENT_ID,
    clean_session=False,          # 关掉"断线即清会话"
)
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect
client.connect(BROKER, PORT, keepalive=60)

try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n[exit]")
    client.disconnect()