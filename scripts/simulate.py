"""模拟 5 个节点并发上报，用于压测（不碰真机）。

用法（项目根目录）：
    .\.venv\Scripts\python.exe scripts\simulate.py --minutes 2      # 先短跑验证
    .\.venv\Scripts\python.exe scripts\simulate.py --minutes 30     # 正式压测

设计说明（面试会问）：
1. 单线程循环，每 interval 秒一次性发 5 条（每节点一条）——发送数可控，便于核对丢包
2. ts = 当前时间 - 50~300ms 随机延迟，人为制造延迟分布。
   ⚠️ 必须用 milliseconds 精度：用 seconds 会把毫秒抹掉，P95 会被量化成 1 秒的桶。
3. 每 40 轮插一个 33℃ 尖峰，顺带验证高并发下告警引擎不会崩
4. 跑满指定分钟数自动退出；Ctrl+C 也能中断（会打印已发条数）

默认连 127.0.0.1（模拟器就跑在本机），需要时可 --host 指定。
"""

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

TZ = timezone(timedelta(hours=8))
NODES = [f"sim0{i}" for i in range(1, 6)]


def now_ts(offset_ms: int) -> str:
    """设备时间 = 当前 - 人为延迟（毫秒）。必须是毫秒精度。"""
    return (datetime.now(TZ) - timedelta(milliseconds=offset_ms)).isoformat(timespec="milliseconds")


def make_payload(seq: int) -> dict:
    spike = (seq % 40 == 0)                      # 每 40 轮一个尖峰
    t = 33.0 if spike else round(random.uniform(16.0, 19.0), 1)
    return {
        "id": str(uuid.uuid4()),
        "ts": now_ts(random.randint(50, 300)),
        "t": t,
        "h": round(random.uniform(48.0, 56.0), 1),
        "lux": round(random.uniform(20.0, 900.0), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="simulator", clean_session=True)
    print(f"[sim] connecting {args.host}:{args.port} ...")
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()

    rounds = int(args.minutes * 60 / args.interval)
    print(f"[sim] nodes={len(NODES)} interval={args.interval}s "
          f"rounds={rounds} expect={rounds * len(NODES)} 条")

    sent = 0
    t_start = time.time()

    try:
        for rnd in range(rounds):
            target = t_start + rnd * args.interval

            for node in NODES:
                payload = json.dumps(make_payload(rnd), ensure_ascii=False)
                client.publish(f"iot/{node}/data", payload, qos=1)
                sent += 1

            if (rnd + 1) % 6 == 0:
                print(f"[sim] {time.time() - t_start:6.1f}s  sent={sent}")

            sleep = target + args.interval - time.time()
            if sleep > 0:
                time.sleep(sleep)
    except KeyboardInterrupt:
        print("\n[sim] interrupted")

    client.loop_stop()
    client.disconnect()

    dur = time.time() - t_start
    print(f"\n[sim] done: sent={sent}  duration={dur:.1f}s  rate={sent / dur:.2f} msg/s")
    print("[sim] 核对用的起止时间：")
    print(f"      since ≈ {(datetime.now(TZ) - timedelta(seconds=dur)).isoformat(timespec='seconds')}")
    print(f"      until ≈ {datetime.now(TZ).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
