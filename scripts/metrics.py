"""从数据库算压测指标：条数 / 丢包 / 重复 / P95 延迟（含时钟偏移校正）。

用法（项目根目录）：
    .\.venv\Scripts\python.exe scripts\metrics.py --since 2026-11-23T15:30:00+08:00 --expect 900
"""

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from storage import connect  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO8601 起点，如 2026-11-23T15:30:00+08:00")
    ap.add_argument("--expect", type=int, default=0, help="应发条数（用于算丢包率）")
    ap.add_argument("--prefix", default="sim", help="节点名前缀")
    args = ap.parse_args()

    conn = connect()
    rows = conn.execute(
        "SELECT msg_id, node_id, ts, recv_ts, "
        "(julianday(recv_ts) - julianday(ts)) * 86400 AS delay_s "
        "FROM reading WHERE ts >= ? AND node_id LIKE ?",
        (args.since, args.prefix + "%"),
    ).fetchall()

    total = len(rows)
    uniq = len({r["msg_id"] for r in rows})
    delays = sorted(r["delay_s"] for r in rows)

    print(f"节点前缀 : {args.prefix}*")
    print(f"起点     : {args.since}")
    print(f"入库条数 : {total}（唯一 {uniq}）")
    print(f"重复率   : {1 - uniq / total if total else 0:.4f}")

    if args.expect:
        lost = args.expect - total
        print(f"应发条数 : {args.expect}")
        print(f"丢包     : {lost}  → 丢失率 {lost / args.expect * 100:.3f}%")

    if delays:
        raw_p95 = delays[int(len(delays) * 0.95)]
        offset = statistics.median(delays)          # 中位数当作时钟偏移
        fixed = sorted(d - offset for d in delays)
        p95 = fixed[int(len(fixed) * 0.95)]
        print(f"延迟原始 : 中位 {offset:+.3f}s   P95 {raw_p95:+.3f}s")
        print(f"时钟偏移 : {offset:+.3f}s（取中位数）")
        print(f"延迟校正 : P50 {fixed[len(fixed) // 2]:.3f}s   P95 {p95:.3f}s   "
              f"max {fixed[-1]:.3f}s")


if __name__ == "__main__":
    main()
