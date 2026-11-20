"""临时自查脚本：只读，不写库。看完可以删。"""
from storage import connect, init_db, query_series, latest, stats

conn = connect()
init_db(conn)

print("== stats 全表 ==")
print(stats(conn))

print("== stats node01 ==")
print(stats(conn, node_id="node01"))

print("== latest ==")
print(latest(conn, "node01"))

print("== 最近 3 条 ==")
for r in query_series(conn, "node01", limit=3):
    print(r["ts"], r["t"], r["h"], r["lux"])