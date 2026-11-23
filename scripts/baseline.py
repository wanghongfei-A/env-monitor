"""打印当前数据库基线（7 天运行的起点/终点快照）。

用法（项目根目录）：
    .\.venv\Scripts\python.exe scripts\baseline.py

作用：记下"启动这一刻"库里有多少条，7 天后减去这个数，
     就是这 7 天真实采集的条数（避免把压测/试运行的数据算进去）。
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from storage import connect  # noqa: E402

TZ = timezone(timedelta(hours=8))


def main():
    conn = connect()
    now = datetime.now(TZ)

    total = conn.execute("SELECT COUNT(*) FROM reading").fetchone()[0]
    node = conn.execute("SELECT COUNT(*) FROM reading WHERE node_id='node01'").fetchone()[0]
    alerts = conn.execute("SELECT COUNT(*) FROM alert").fetchone()[0]
    latest = conn.execute(
        "SELECT ts FROM reading WHERE node_id='node01' ORDER BY ts DESC LIMIT 1"
    ).fetchone()

    print("=" * 46)
    print(f"时间        : {now.isoformat(timespec='seconds')}")
    print(f"总条数      : {total}")
    print(f"node01 条数 : {node}    ← 7 天后用这个数做差")
    print(f"告警条数    : {alerts}")
    print(f"最新一条 ts : {latest[0] if latest else '(无)'}")
    print("=" * 46)
    print("把这四行抄进 docs/运维日志.md 的对应行")


if __name__ == "__main__":
    main()
