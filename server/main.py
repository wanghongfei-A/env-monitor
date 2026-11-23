# FastAPI：查询接口 + 生命周期里挂 MQTT 订阅
#
# 启动（项目根目录）：
#   .\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --host 127.0.0.1 --port 8000
#
# 两个要点：
# 1. FastAPI 0.163 已弃用 @app.on_event，改用 lifespan
# 2. SQLite 连接不能跨线程：MQTT 回调用 thread_db()，HTTP 用 Depends(get_db)

import json
import threading
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
from fastapi import Depends, FastAPI, HTTPException, Query

from storage import connect, init_db, insert_reading, latest, query_series, stats
from alerts import check_alerts
from notifier import send_alert
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
            ok = insert_reading(thread_db(), d["id"], node, d["ts"],
                                d.get("t"), d.get("h"), d.get("lux"))
            print(f"[{'NEW' if ok else 'DUP'}] {node} "
                  f"t={d.get('t')} h={d.get('h')} lux={d.get('lux')}")
            import time
            for a in check_alerts(thread_db(), {
                "msg_id": d["id"], "node_id": node, "ts": d["ts"],
                "t": d.get("t"), "h": d.get("h"), "lux": d.get("lux"),
            }):
                t0 = time.time()
                sent = send_alert(a["level"], a["msg"])
                cost = (time.time() - t0) * 1000
                print(f"[ALERT] {a['level']} {a['rule']} sent={sent} "
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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)