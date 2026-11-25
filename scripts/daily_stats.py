r"""按天生成运维统计（7 天运行收尾时一次性用，中间不用每天打卡）。

用法（项目根目录）：
    .\.venv\Scripts\python.exe scripts\daily_stats.py
    .\.venv\Scripts\python.exe scripts\daily_stats.py --since 2026-11-24

输出：每天一行（日期 / 条数 / 首末时刻 / 覆盖时长 / 断档次数 / 最长断档），
     并自动判断「正常 / 可能中断」，直接可抄进 docs/运维日志.md。

断档判定：相邻两条 ts 间隔 > GAP_SECONDS（默认 60 秒）记为一次断档。
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from storage import connect  # noqa: E402

TZ = timezone(timedelta(hours=8))
GAP_SECONDS = 60
EXPECTED_INTERVAL = 10.085          # 第 1 天实测值


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-24", help="从哪天开始统计（默认 7 天运行起点）")
    ap.add_argument("--node", default="node01")
    args = ap.parse_args()

    conn = connect()
    rows = conn.execute(
        "SELECT ts FROM reading WHERE node_id = ? AND ts >= ? ORDER BY ts",
        (args.node, args.since),
    ).fetchall()

    if not rows:
        print("没有数据")
        return

    by_day = defaultdict(list)
    for r in rows:
        dt = datetime.fromisoformat(r["ts"])
        by_day[dt.date()].append(dt)

    print(f"节点 {args.node} · 起点 {args.since}")
    print("=" * 96)
    print(f"{'日期':<12}{'条数':>7}{'首条':>10}{'末条':>10}{'跨度h':>8}"
          f"{'断档次':>7}{'最长断档':>11}  判定")
    print("-" * 96)

    total = 0
    for day in sorted(by_day):
        dts = by_day[day]
        total += len(dts)

        gaps = []
        for a, b in zip(dts, dts[1:]):
            delta = (b - a).total_seconds()
            if delta > GAP_SECONDS:
                gaps.append(delta)

        span_h = (dts[-1] - dts[0]).total_seconds() / 3600
        longest = max(gaps) / 60 if gaps else 0

        # 覆盖率：实际条数 / 该时段应有条数
        expect = (dts[-1] - dts[0]).total_seconds() / EXPECTED_INTERVAL + 1
        ratio = len(dts) / expect if expect else 0

        verdict = "正常" if ratio > 0.97 and not gaps else (
            f"缺 {100 * (1 - ratio):.1f}%" if ratio <= 0.97 else "有短暂断档")

        print(f"{str(day):<12}{len(dts):>7}  {dts[0]:%H:%M:%S}  {dts[-1]:%H:%M:%S}"
              f"{span_h:>8.2f}{len(gaps):>8}{longest:>10.1f}m  {verdict}")

    print("-" * 96)
    print(f"合计 {total} 条，覆盖 {len(by_day)} 天")
    print()
    print("把上面每一行抄进 docs/运维日志.md 的对应日期即可。")
    print("（断档次/最长断档 用于填「断线次数」列与「异常」列）")


if __name__ == "__main__":
    main()
