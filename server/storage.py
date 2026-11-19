"""SQLite 存储层：建表 + 幂等写入。

设计要点：
1. msg_id 做主键 —— 数据库层面保证"同一条消息只存一次"
2. INSERT OR IGNORE —— 重复时静默跳过，不抛异常、不覆盖原值
3. 双时间戳：ts 是设备时间（业务用），recv_ts 是服务端接收时间（排障用）
4. 暂不建 (node_id, ts) 索引 —— 留给验收第 8 项做"加索引前后"对比
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "iot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reading (
    msg_id  TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    ts      TEXT NOT NULL,
    recv_ts TEXT NOT NULL,
    t       REAL,
    h       REAL,
    lux     REAL
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def insert_reading(conn, msg_id, node_id, ts, t=None, h=None, lux=None) -> bool:
    """返回 True = 新插入；False = 重复，被忽略"""
    recv_ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    cur = conn.execute(
        "INSERT OR IGNORE INTO reading (msg_id, node_id, ts, recv_ts, t, h, lux) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (msg_id, node_id, ts, recv_ts, t, h, lux),
    )
    conn.commit()
    return cur.rowcount == 1


if __name__ == "__main__":
    conn = connect()
    init_db(conn)
    conn.execute("DELETE FROM reading")      # 每次自测前清空，保证结果可重复
    conn.commit()

    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print("第 1 条:", insert_reading(conn, "u-001", "node01", ts, 23.5, 55.0, 320))
    print("第 2 条:", insert_reading(conn, "u-002", "node01", ts, 23.6, 55.2, 310))
    print("重复条:", insert_reading(conn, "u-001", "node01", ts, 99.9, 99.9, 999))

    total = conn.execute("SELECT COUNT(*) FROM reading").fetchone()[0]
    uniq = conn.execute("SELECT COUNT(DISTINCT msg_id) FROM reading").fetchone()[0]
    print(f"total={total}  unique={uniq}  dup_ratio={1 - uniq / total:.4f}")

    kept = conn.execute("SELECT t FROM reading WHERE msg_id='u-001'").fetchone()[0]
    print("重复的 99.9 没有覆盖原来的 23.5？", kept == 23.5, "（实际 t =", kept, "）")