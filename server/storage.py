"""SQLite 存储层：建表 + 幂等写入 + 查询。

设计要点：
1. msg_id 做主键 —— 数据库层面保证"同一条消息只存一次"
2. INSERT OR IGNORE —— 重复时静默跳过，不抛异常、不覆盖原值
3. 双时间戳：ts 是设备时间（业务用），recv_ts 是服务端接收时间（排障用）
4. dup_ratio = 1 - 唯一数/总数，0 表示零重复
5. 暂不建 (node_id, ts) 索引 —— 留给验收第 8 项做"加索引前后"对比
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


def query_series(conn, node_id, start_ts=None, end_ts=None, limit=500, offset=0):
    """按时间段查历史数据，按 ts 倒序。返回 list[dict]。"""
    sql = "SELECT msg_id, node_id, ts, recv_ts, t, h, lux FROM reading WHERE node_id = ?"
    args = [node_id]

    if start_ts:
        sql += " AND ts >= ?"
        args.append(start_ts)
    if end_ts:
        sql += " AND ts <= ?"
        args.append(end_ts)

    sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])

    return [dict(r) for r in conn.execute(sql, args)]


def latest(conn, node_id):
    """最新一条"""
    row = conn.execute(
        "SELECT msg_id, node_id, ts, recv_ts, t, h, lux FROM reading "
        "WHERE node_id = ? ORDER BY ts DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    return dict(row) if row else None


def stats(conn, node_id=None, day=None):
    """条数 / 唯一条数 / 重复率 / 平均延迟（秒）"""
    where, args = [], []
    if node_id:
        where.append("node_id = ?")
        args.append(node_id)
    if day:
        where.append("substr(ts, 1, 10) = ?")
        args.append(day)

    w = ("WHERE " + " AND ".join(where)) if where else ""

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT msg_id) AS uniq,
               ROUND(1.0 - 1.0 * COUNT(DISTINCT msg_id) / COUNT(*), 4) AS dup_ratio,
               ROUND(AVG((julianday(recv_ts) - julianday(ts)) * 86400), 3) AS avg_delay_s
        FROM reading {w}
        """,
        args,
    ).fetchone()

    return dict(row)


if __name__ == "__main__":
    # 自测用内存库：不读也不改 data/iot.db
    conn = connect(Path(":memory:"))
    init_db(conn)

    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print("第 1 条:", insert_reading(conn, "u-001", "node01", ts, 23.5, 55.0, 320))
    print("第 2 条:", insert_reading(conn, "u-002", "node01", ts, 23.6, 55.2, 310))
    print("重复条:", insert_reading(conn, "u-001", "node01", ts, 99.9, 99.9, 999))

    print("stats :", stats(conn))
    print("latest:", latest(conn, "node01"))
    print("最近 2 条:", query_series(conn, "node01", limit=2))