"""告警引擎：规则判定 + 状态机 + 分级抑制 + 持续提醒。

四个核心设计（面试会问，答案已定）：

1. "连续 N 条"的计数存在哪？
   内存 dict，key=(node_id, rule_id)。告警是流式实时判定，每条读数都要读写计数，
   落库会拉高延迟；代价是进程重启丢状态（可做定时快照兜底，本版没做，写进"后续可做"）。

2. 告警状态怎么存？
   {"count": int, "status": "normal"|"firing", "last_notify": datetime|None}

3. 时段判断用 ts 还是 recv_ts？
   用设备自带的 ts。网络抖动、排队延迟会让 recv_ts 失真；告警窗口描述的是
   "设备采集那一刻，房间在不在使用时段"，不是"服务收到包的时刻"。

4. 恢复判定：不满足 1 次就恢复，还是连续 N 次？
   一次不满足就恢复。触发要防抖（连续 N 条命中），恢复不防抖——
   宁可早恢复，也不要让告警一直挂着。

另外两条：
5. 分级抑制：同一指标上，红级 firing 时不推该指标的黄级提示。
6. 抑制只影响"推送"，不影响"判定"——黄级状态机照常流转，消息被过滤而已。
"""

from datetime import datetime
from typing import List, Dict, Any

RULES = [
    dict(id="R1", name="过热",  metric="t",  op=">", th=32.0, need=18, window="always", level="红"),
    dict(id="R2", name="过冷",  metric="t",  op="<", th=20.0, need=30, window="night",  level="红"),
    dict(id="R3", name="潮湿",  metric="h",  op=">", th=85.0, need=30, window="always", level="红"),
    dict(id="R4", name="忘关灯", metric="lux", op=">", th=100.0, need=60, window="night", level="红"),
    dict(id="R5", name="舒适度", metric="t",  op=">", th=28.0, need=60, window="day",    level="黄"),
]

# 输出里只有 rule id，需要反查指标（分级抑制用）
RULE_METRIC = {r["id"]: r["metric"] for r in RULES}

# 持续告警的重复提醒间隔（分钟）：红 60，黄 120
REMIND_MIN = {"红": 60, "黄": 120}

# 状态容器：key=(node_id, rule_id)
_state: Dict[tuple, Dict[str, Any]] = {}


def reset_state():
    """清空所有状态。测试用（否则用例之间会互相污染）。"""
    _state.clear()


def in_window(window: str, ts: str) -> bool:
    """window: "always" / "night"(22:30-07:00) / "day"(07:00-22:30)"""
    if window == "always":
        return True

    dt = datetime.fromisoformat(ts)
    total_min = dt.hour * 60 + dt.minute

    night_start = 22 * 60 + 30      # 22:30
    night_end = 7 * 60              # 07:00

    if window == "night":
        return total_min >= night_start or total_min < night_end
    if window == "day":
        return night_end <= total_min < night_start
    return False


def _op_check(op: str, val: float, th: float) -> bool:
    if op == ">":
        return val > th
    if op == "<":
        return val < th
    if op == ">=":
        return val >= th
    if op == "<=":
        return val <= th
    return False


def check_alerts(db, reading: dict) -> List[dict]:
    """检查一条 reading，返回需要推送的告警列表。

    返回项格式：
        触发：{"rule": "R1", "level": "红",   "msg": "..."}
        提醒：{"rule": "R1", "level": "红",   "msg": "过热持续告警：已持续 65 分钟..."}
        恢复：{"rule": "R1", "level": "恢复", "msg": "..."}
    """
    node_id = reading["node_id"]
    ts = reading["ts"]
    now = datetime.fromisoformat(ts)
    out = []

    for rule in RULES:
        rid = rule["id"]
        metric = rule["metric"]
        need = rule["need"]
        level = rule["level"]
        name = rule["name"]

        # ---- 条件判定：指标缺失 / 窗口外 都等价于"不满足" ----
        val = reading.get(metric)
        if val is None:
            hit = False
        elif not in_window(rule["window"], ts):
            hit = False
        else:
            hit = _op_check(rule["op"], val, rule["th"])

        # ---- 状态机 ----
        state_key = (node_id, rid)
        if state_key not in _state:
            _state[state_key] = {"count": 0, "status": "normal", "last_notify": None}
        st = _state[state_key]
        firing = st["status"] == "firing"

        if hit:
            st["count"] += 1

            if not firing and st["count"] >= need:
                # 首次触发：normal -> firing 的跃迁
                st["status"] = "firing"
                st["last_notify"] = now
                out.append({
                    "rule": rid,
                    "level": level,
                    "msg": f"{name}：{metric}={val}，阈值 {rule['th']}，连续 {st['count']} 次",
                })

            elif firing:
                # 已告警中：只在超过提醒间隔时再推一次
                last = st.get("last_notify")
                if last is not None:
                    elapsed_min = int((now - last).total_seconds() // 60)
                    if elapsed_min >= REMIND_MIN[level]:
                        st["last_notify"] = now
                        out.append({
                            "rule": rid,
                            "level": level,
                            "msg": f"{name}持续告警：已持续 {elapsed_min} 分钟，"
                                   f"当前 {metric}={val}（阈值 {rule['th']}）",
                        })
        else:
            if firing:
                out.append({
                    "rule": rid,
                    "level": "恢复",
                    "msg": f"{name}已恢复，当前 {metric}={val}",
                })
                st["status"] = "normal"
                st["last_notify"] = None
            st["count"] = 0

    # ---- 分级抑制：同一指标上，红级 firing 时不推黄级 ----
    red_metrics = {
        rule["metric"]
        for rule in RULES
        if rule["level"] == "红"
        and _state.get((node_id, rule["id"]), {}).get("status") == "firing"
    }

    return [a for a in out
            if not (a["level"] == "黄" and RULE_METRIC[a["rule"]] in red_metrics)]