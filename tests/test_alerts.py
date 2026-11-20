r"""告警引擎验收用例。

跑法（项目根目录）：
    .\.venv\Scripts\python.exe tests\test_alerts.py

第一轮：R1 状态机（用例 1、2、6、7）
第二轮：5 条规则 + 时段窗口（用例 3、4、5、9）
第三轮：分级抑制（用例 8，目前只打印现状）

注意：33℃ 同时满足 R5（>28℃）的条件，所以按 rule 过滤，避免互相污染。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from alerts import check_alerts, reset_state   # noqa: E402

DAY_START = "2026-11-20T14:00:00+08:00"
NIGHT_START = "2026-11-20T23:00:00+08:00"
_seq = 0


def reading(ts, t=20.0, h=50.0, lux=200.0):
    global _seq
    _seq += 1
    return {"msg_id": f"test-{_seq}", "node_id": "node01",
            "ts": ts, "t": t, "h": h, "lux": lux}


def seq_ts(start, n, step=10):
    t0 = datetime.fromisoformat(start)
    for i in range(n):
        yield (t0 + timedelta(seconds=step * i)).isoformat()


def feed(n, t=20.0, start=DAY_START, h=50.0, lux=200.0):
    out = []
    for ts in seq_ts(start, n):
        out += check_alerts(None, reading(ts, t=t, h=h, lux=lux))
    return out


def only(alerts, rule):
    return [a for a in alerts if a.get("rule") == rule]


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   -> {detail}"))
    return cond


def main():
    ok = True

    # ================= 第一轮：R1 状态机 =================
    reset_state()
    a = only(feed(18, 33.0), "R1")
    ok &= check("用例1  33℃ 连续 18 条 -> 触发 1 次", len(a) == 1, f"实际 {len(a)}: {a}")
    if a:
        ok &= check("用例1  内容是 R1 / 级别红",
                    a[0].get("rule") == "R1" and a[0].get("level") == "红", str(a[0]))

    reset_state()
    a = only(feed(17, 33.0), "R1")
    ok &= check("用例2  33℃ 连续 17 条 -> 不触发", len(a) == 0, f"实际 {len(a)}")

    reset_state()
    feed(18, 33.0)
    a = only(feed(42, 33.0, start="2026-11-20T14:03:10+08:00"), "R1")
    ok &= check("用例6  已触发后继续 42 条 -> 不重复推", len(a) == 0, f"实际 {len(a)}: {a}")

    reset_state()
    feed(18, 33.0)
    a = [x for x in feed(6, 30.0, start="2026-11-20T14:03:10+08:00")
         if x.get("rule") == "R1" and x.get("level") == "恢复"]
    ok &= check("用例7  回落到 30℃ -> 推 1 条恢复", len(a) == 1, f"实际 {len(a)}")

    # ================= 第二轮：时段窗口 =================
    reset_state()
    a = only(feed(30, 19.0), "R2")                     # 白天 14:00 起
    ok &= check("用例3  19℃ 30 条（白天）-> 不触发 R2", len(a) == 0, f"实际 {len(a)}: {a}")

    reset_state()
    a = only(feed(30, 19.0, start=NIGHT_START), "R2")   # 夜间 23:00 起
    ok &= check("用例4  19℃ 30 条（夜间）-> 触发 R2", len(a) == 1, f"实际 {len(a)}: {a}")

    reset_state()
    a = feed(60, 29.0)
    r5, r1 = only(a, "R5"), only(a, "R1")
    ok &= check("用例5  29℃ 60 条（白天）-> 触发 R5 且不触发 R1",
                len(r5) == 1 and len(r1) == 0, f"R5={len(r5)} R1={len(r1)}")

    # 用例9：夜间触发 R2，白天的读数进来 -> 应推恢复（窗口外 = 条件不成立）
    reset_state()
    feed(30, 19.0, start=NIGHT_START)                  # 23:00 触发
    a = [x for x in only(feed(1, 19.0, start="2026-11-21T08:00:00+08:00"), "R2")
         if x.get("level") == "恢复"]
    ok &= check("用例9  夜间触发后进入白天 -> 推 1 条恢复", len(a) == 1, f"实际 {len(a)}: {a}")

    # ================= 第三轮：分级抑制 =================
    reset_state()
    a = feed(60, 33.0)
    r1, r5 = only(a, "R1"), only(a, "R5")
    ok &= check("用例8  33℃ 60 条 -> 推 R1(红) 且抑制 R5(黄)",
                len(r1) == 1 and len(r5) == 0, f"R1={len(r1)} R5={len(r5)}")

    # 用例8b：没有红级成立时，黄级提示照常（29℃ 不触发 R1）
    reset_state()
    a = feed(60, 29.0)
    ok &= check("用例8b 29℃ 60 条 -> R5 照常推（无红级可抑制）",
                len(only(a, "R5")) == 1, f"R5={len(only(a, 'R5'))}")

    # ================= 第四轮：60 分钟重复提醒 =================
    # 14:00 起连续 66 分钟的 33℃：应推 2 次（触发 1 次 + 满 60 分钟提醒 1 次）
    reset_state()
    a = only(feed(18, 33.0), "R1")
    a += only(feed(400, 33.0, start="2026-11-20T14:03:00+08:00"), "R1")
    ok &= check("用例10 持续越限 66 分钟 -> 共推 2 次（触发 + 1 提醒）",
                len(a) == 2, f"实际 {len(a)} 次")

    # 50 分钟内不应有提醒
    reset_state()
    a = only(feed(18, 33.0), "R1")
    a += only(feed(280, 33.0, start="2026-11-20T14:03:00+08:00"), "R1")   # 到 14:49
    ok &= check("用例10b 持续 49 分钟 -> 只推 1 次（未到提醒间隔）",
                len(a) == 1, f"实际 {len(a)} 次")

    print()
    print("全部通过 🎉" if ok else "还有用例没通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
