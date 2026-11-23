"""索引前后查询耗时对比（验收第 8 项）。

用法（项目根目录）：
    .\.venv\Scripts\python.exe scripts\index_bench.py --rows 100000

关键设计：
1. 用**独立的 data/bench.db**，不污染 iot.db（否则"日均采集量"统计会被 10 万条基准数据搞乱）
2. 测**两种查询**，因为它们对索引的反应完全相反：
   A. 窄时间窗（1 小时）—— 索引的主场，行数从 10 万降到 360
   B. 全区间聚合（10 万行 COUNT+AVG）—— 索引反而更慢：范围没缩小，还要回表取 t
3. 建索引时 SQLite 要排序，默认用临时文件；本机 %TEMP% 不可写 → PRAGMA temp_store=MEMORY
"""

import argparse
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from storage import connect, init_db  # noqa: E402

TZ = timezone(timedelta(hours=8))
BENCH_DB = Path(__file__).resolve().parent.parent / "data" / "bench.db"
INDEX = "idx_reading_node_ts"


def gen(conn, n):
    have = conn.execute("SELECT COUNT(*) FROM reading WHERE node_id='bench'").fetchone()[0]
    if have >= n:
        print(f"[bench] 已有 {have} 条，跳过生成")
        return

    base = datetime.now(TZ) - timedelta(days=3)
    rows = []
    for i in range(n):
        ts = (base + timedelta(seconds=10 * i)).isoformat(timespec="milliseconds")
        rows.append((
            str(uuid.uuid4()), "bench", ts, ts,
            round(random.uniform(16, 20), 1),
            round(random.uniform(45, 60), 1),
            round(random.uniform(10, 900), 1),
        ))
    print(f"[bench] 插入 {n} 条...")
    conn.executemany(
        "INSERT OR IGNORE INTO reading (msg_id,node_id,ts,recv_ts,t,h,lux) "
        "VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    print("[bench] 完成")


def timeit(conn, label, sql, args, times=5):
    plan = conn.execute("EXPLAIN QUERY PLAN " + sql, args).fetchall()
    plan_txt = plan[0][3] if plan else "?"
    print(f"    [{label}] 计划: {plan_txt}")

    costs = []
    for _ in range(times):
        t0 = time.perf_counter()
        conn.execute(sql, args).fetchall()
        costs.append((time.perf_counter() - t0) * 1000)
    costs.sort()
    med = costs[len(costs) // 2]
    print(f"    [{label}] 5 次(ms): " + ", ".join(f"{c:.1f}" for c in costs) + f"  中位 {med:.1f}")
    return med


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100000)
    args = ap.parse_args()

    print(f"[bench] DB = {BENCH_DB}")
    conn = connect(BENCH_DB)
    # 建索引要排序，默认写临时文件；本机 %TEMP% 不可写 → 报 "unable to open database file"
    conn.execute("PRAGMA temp_store = MEMORY")
    init_db(conn)
    gen(conn, args.rows)

    total = conn.execute("SELECT COUNT(*) FROM reading WHERE node_id='bench'").fetchone()[0]
    tmin, tmax = conn.execute(
        "SELECT MIN(ts), MAX(ts) FROM reading WHERE node_id='bench'").fetchone()
    # 取一个 1 小时窗口（360 行）
    start = datetime.fromisoformat(tmin)
    w0 = start.isoformat(timespec="milliseconds")
    w1 = (start + timedelta(hours=1)).isoformat(timespec="milliseconds")

    print(f"[bench] 基准数据 {total} 条，时间跨度 {tmin[:19]} ~ {tmax[:19]}")
    print(f"[bench] 窄窗口：{w0} ~ {w1}")

    # 确保从"无索引"状态开始
    conn.execute(f"DROP INDEX IF EXISTS {INDEX}")
    conn.commit()

    print("\n===== 场景 A：窄时间窗查询（360 行）=====")
    sql_a = ("SELECT * FROM reading WHERE node_id='bench' AND ts >= ? AND ts <= ? "
             "ORDER BY ts DESC LIMIT 500")
    a_before = timeit(conn, "无索引", sql_a, (w0, w1))

    print("\n===== 场景 B：全区间聚合（10 万行）=====")
    sql_b = "SELECT COUNT(*), AVG(t) FROM reading WHERE node_id='bench'"
    b_before = timeit(conn, "无索引", sql_b, ())

    print(f"\n[bench] 创建索引 {INDEX} (node_id, ts) ...")
    t0 = time.perf_counter()
    conn.execute(f"CREATE INDEX {INDEX} ON reading(node_id, ts)")
    conn.commit()
    print(f"[bench] 建索引耗时 {(time.perf_counter() - t0) * 1000:.0f} ms")

    print("\n===== 场景 A（加索引后）=====")
    a_after = timeit(conn, "有索引", sql_a, (w0, w1))

    print("\n===== 场景 B（加索引后）=====")
    b_after = timeit(conn, "有索引", sql_b, ())

    print("\n=== 结论 ===")
    print(f"A 窄窗口 : {a_before:8.1f} ms  →  {a_after:8.1f} ms   加速 {a_before / a_after:.1f} 倍")
    print(f"B 全聚合 : {b_before:8.1f} ms  →  {b_after:8.1f} ms   变化 {b_before / b_after:.2f} 倍")
    print("\n解读：索引只对「能缩小扫描范围」的查询有用（A）；")
    print("      对「范围覆盖全表 + 需要索引里没有的列」的聚合（B），回表开销反而让它变慢。")


if __name__ == "__main__":
    main()
