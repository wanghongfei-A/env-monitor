# FastAPI：查询接口 + 生命周期里挂 MQTT 订阅
#
# 启动（项目根目录）：
#   .\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --host 127.0.0.1 --port 8000
#
# 三个要点：
# 1. FastAPI 0.163 已弃用 @app.on_event，改用 lifespan
# 2. SQLite 连接不能跨线程：MQTT 回调用 thread_db()，HTTP 用 Depends(get_db)
# 3. 告警落库（alert 表）后再推钉钉，推送失败不影响入库

import json
import threading
import time
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
from fastapi import Depends, FastAPI, HTTPException, Query

from alerts import check_alerts
from notifier import send_alert
from storage import (connect, init_db, insert_reading, insert_alert,
                     latest, query_series, query_alerts, stats)

BROKER = "127.0.0.1"
PORT = 1883
TOPIC = "iot/+/data"
CLIENT_ID = "server-sub"
NODE = "node01"

_local = threading.local()


def thread_db():
    # 线程本地连接：paho 的回调线程与主线程不同，不能共用连接
    c = getattr(_local, "conn", None)
    if c is None:
        c = connect()
        _local.conn = c
    return c


def get_db():
    # 请求级连接：用完即关
    c = connect()
    try:
        yield c
    finally:
        c.close()


def start_mqtt():
    def on_message(client, userdata, msg):
        try:
            d = json.loads(msg.payload.decode("utf-8"))
            node = msg.topic.split("/")[1]
            db = thread_db()

            ok = insert_reading(db, d["id"], node, d["ts"],
                                d.get("t"), d.get("h"), d.get("lux"))
            print(f"[{'NEW' if ok else 'DUP'}] {node} "
                  f"t={d.get('t')} h={d.get('h')} lux={d.get('lux')}")

            for a in check_alerts(db, {
                "msg_id": d["id"], "node_id": node, "ts": d["ts"],
                "t": d.get("t"), "h": d.get("h"), "lux": d.get("lux"),
            }):
                # 先落库：推送失败也不丢告警记录
                insert_alert(db, a["rule"], a["level"], a["kind"], a["msg"],
                             d["ts"], d.get("t"), d.get("h"), d.get("lux"))

                t0 = time.time()
                sent = send_alert(a["level"], a["msg"])
                cost = (time.time() - t0) * 1000
                print(f"[ALERT] {a['level']} {a['rule']} {a['kind']} sent={sent} "
                      f"cost={cost:.0f}ms | {a['msg']}")

        except Exception as e:
            print(f"[error] {e} | {msg.payload[:120]}")

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=CLIENT_ID, clean_session=False)
    c.on_message = on_message
    c.connect(BROKER, PORT, keepalive=60)
    c.subscribe(TOPIC, qos=1)
    c.loop_start()
    print("[mqtt] subscribed", TOPIC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(connect())
    threading.Thread(target=start_mqtt, daemon=True).start()
    print("[startup] mqtt thread started")
    yield
    print("[shutdown] bye")


app = FastAPI(title="环境监测 API", version="0.1", lifespan=lifespan)


@app.get("/api/health")
def health(db=Depends(get_db)):
    return {"ok": True, "rows": stats(db)["total"]}


@app.get("/api/latest")
def api_latest(node: str = Query(NODE), db=Depends(get_db)):
    row = latest(db, node)
    if not row:
        raise HTTPException(status_code=404, detail="no data")
    return row


@app.get("/api/series")
def api_series(
    node: str = Query(NODE),
    start: str | None = Query(None, description="ISO8601，如 2026-11-20T00:00:00+08:00"),
    end: str | None = Query(None),
    limit: int = Query(500, le=5000),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    rows = query_series(db, node, start, end, limit, offset)
    return {"count": len(rows), "items": rows}


@app.get("/api/stats")
def api_stats(node: str | None = None, day: str | None = None, db=Depends(get_db)):
    return stats(db, node, day)


@app.get("/api/alerts")
def api_alerts(
    limit: int = Query(100, le=1000),
    level: str | None = None,
    since: str | None = None,
    db=Depends(get_db),
):
    return {"items": query_alerts(db, limit, level, since)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)