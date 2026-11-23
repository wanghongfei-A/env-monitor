r"""环境监测看板（Streamlit）。

启动（项目根目录）：
    .\.venv\Scripts\python.exe -m streamlit run dashboard\app.py

依赖后端：http://127.0.0.1:8000（先起 main.py）
"""

from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API = "http://127.0.0.1:8000"
NODE = "node01"

st.set_page_config(page_title="环境监测看板", page_icon="🌡", layout="wide")


@st.cache_data(ttl=5)
def api_get(path: str, params: dict | None = None):
    """带 5 秒缓存：避免每次交互都打后端"""
    try:
        r = requests.get(f"{API}{path}", params=params or {}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"接口调用失败：{path} → {e}")
        return None


def to_local(s: str) -> datetime:
    return pd.to_datetime(s).tz_convert("Asia/Shanghai")


# ---------------- 侧边栏 ----------------
with st.sidebar:
    st.header("控制")
    hours = st.slider("曲线时间范围（小时）", 1, 72, 24)
    only_alerts = st.checkbox("告警只看未处理", value=False)
    if st.button("🔄 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"数据源：{API}　节点：{NODE}")

st.title("🌡 环境监测看板")
st.caption("实验室 / 自习室 · 10 秒一采 · 越限自动告警")

# ---------------- ① 最新值卡片 ----------------
latest = api_get("/api/latest", {"node": NODE})

if not latest:
    st.warning("暂无数据。检查：EMQX 是否启动 / 固件是否上电 / main.py 是否在跑")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("温度", f"{latest['t']:.1f} ℃")
c2.metric("湿度", f"{latest['h']:.1f} %")
c3.metric("光照", f"{latest['lux']:.0f} lx")
c4.metric("最后更新", to_local(latest["ts"]).strftime("%H:%M:%S"))

st.divider()

# ---------------- ② 24h 曲线 ----------------
start = (datetime.now().astimezone() - timedelta(hours=hours)).isoformat(timespec="seconds")
series = api_get("/api/series", {"node": NODE, "start": start, "limit": 5000})

st.subheader(f"最近 {hours} 小时曲线")

if series and series["items"]:
    df = pd.DataFrame(series["items"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert("Asia/Shanghai")
    df = df.sort_values("ts")

    # 温湿度双轴
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["ts"], y=df["t"], name="温度 ℃",
                             line=dict(color="#e74c3c", width=2)))
    fig.add_trace(go.Scatter(x=df["ts"], y=df["h"], name="湿度 %",
                             yaxis="y2", line=dict(color="#3498db", width=2)))
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="温度 ℃"),
        yaxis2=dict(title="湿度 %", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.1),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # 光照单独一条（量级差太大，不能和温湿度同轴）
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=df["ts"], y=df["lux"], name="光照 lx",
                              fill="tozeroy", line=dict(color="#f39c12")))
    fig2.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10),
                       yaxis=dict(title="lux"))
    st.plotly_chart(fig2, use_container_width=True)

    st.caption(f"共 {len(df)} 个数据点")
else:
    st.info("这个时间范围内没有数据")

st.divider()

# ---------------- ③ 告警列表 ----------------
st.subheader("告警记录")
alerts = api_get("/api/alerts", {"limit": 200})

if alerts and alerts["items"]:
    adf = pd.DataFrame(alerts["items"])
    if only_alerts:
        adf = adf[adf["ack"] == 0]

    adf = adf[["ts", "level", "rule_id", "kind", "msg", "ack"]].copy()
    adf["ts"] = pd.to_datetime(adf["ts"]).dt.tz_convert("Asia/Shanghai").dt.strftime("%m-%d %H:%M:%S")
    adf["ack"] = adf["ack"].map({0: "未处理", 1: "已处理"})
    adf.columns = ["时间", "级别", "规则", "类型", "内容", "状态"]

    st.dataframe(adf, use_container_width=True, hide_index=True, height=320)

    counts = pd.DataFrame(alerts["items"])["level"].value_counts()
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("🔴 红级", int(counts.get("红", 0)))
    cc2.metric("🟡 黄级", int(counts.get("黄", 0)))
    cc3.metric("🟢 恢复", int(counts.get("恢复", 0)))
else:
    st.info("还没有告警记录")