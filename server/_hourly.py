"""按小时统计当天数据量，用来看有没有断档（临时自查脚本）。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "iot.db"
conn = sqlite3.connect(DB)

print("DB:", DB)
print("总计:", conn.execute("SELECT COUNT(*) FROM reading").fetchone()[0])
print()
print("今日按小时：")
print(f"{'小时':<6}{'条数':>6}   最早                      最晚")
for hh, n, tmin, tmax in conn.execute(
    "SELECT substr(ts, 12, 2) AS hh, COUNT(*) AS n, MIN(ts), MAX(ts) "
    "FROM reading WHERE substr(ts, 1, 10) = '2026-11-20' "
    "GROUP BY hh ORDER BY hh"
):
    print(f"{hh:<8}{n:>4}   {tmin}  {tmax}")

print()
print("近 24 小时每 10 分钟一条的期望值：360 条/小时")
