"""告警引擎：规则判定 + 状态机 + 分级抑制 + 持续提醒。

四个核心设计：
1. 连续 N 条的计数存在内存 dict，key=(node_id, rule_id)；进程重启会丢（可做快照兜底，本版没做）
2. 状态：{"count": int, "status": "normal"|"firing", "last_notify": datetime|None}
3. 时段判断用设备自带的 ts（网络抖动会让 recv_ts 失真；窗口描述的是采集那一刻）
4. 恢复不防抖：一次不满足就恢复。触发要连续 N 条，恢复要快

另外两条：
5. 分级抑制：同一指标上红级 firing 时不推黄级
6. 抑制只影响推送，不影响判定

返回项都带 kind：trigger / remind / recover（看板要按它区分）。
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

RULE_METRIC = {r["id"]: r["metric"] for r in RULES}
REMIND_MIN = {"红": 60, "黄": 120}

_state: Dict[tuple, Dict[str, Any]] = {}


def reset_state():
    _state.clear()


def in_window(window: str, ts: str) -> bool:
    if window == "always":
        return True

    dt = datetime.fromisoformat(ts)
    total_min = dt.hour * 60 + dt.minute
    night_start = 22 * 60 + 30
    night_end = 7 * 60

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

        val = reading.get(metric)
        if val is None:
            hit = False
        elif not in_window(rule["window"], ts):
            hit = False
        else:
            hit = _op_check(rule["op"], val, rule["th"])

        state_key = (node_id, rid)
        if state_key not in _state:
            _state[state_key] = {"count": 0, "status": "normal", "last_notify": None}
        st = _state[state_key]
        firing = st["status"] == "firing"

        if hit:
            st["count"] += 1

            if not firing and st["count"] >= need:
                st["status"] = "firing"
                st["last_notify"] = now
                out.append({
                    "rule": rid,
                    "level": level,
                    "kind": "trigger",
                    "msg": f"{name}：{metric}={val}，阈值 {rule['th']}，连续 {st['count']} 次",
                })

            elif firing:
                last = st.get("last_notify")
                if last is not None:
                    elapsed_min = int((now - last).total_seconds() // 60)
                    if elapsed_min >= REMIND_MIN[level]:
                        st["last_notify"] = now
                        out.append({
                            "rule": rid,
                            "level": level,
                            "kind": "remind",
                            "msg": f"{name}持续告警：已持续 {elapsed_min} 分钟，"
                                   f"当前 {metric}={val}（阈值 {rule['th']}）",
                        })
        else:
            if firing:
                out.append({
                    "rule": rid,
                    "level": "恢复",
                    "kind": "recover",
                    "msg": f"{name}已恢复，当前 {metric}={val}",
                })
                st["status"] = "normal"
                st["last_notify"] = None
            st["count"] = 0

    red_metrics = {
        rule["metric"]
        for rule in RULES
        if rule["level"] == "红"
        and _state.get((node_id, rule["id"]), {}).get("status") == "firing"
    }

    return [a for a in out
            if not (a["level"] == "黄" and RULE_METRIC[a["rule"]] in red_metrics)]