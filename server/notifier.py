r"""钉钉群机器人推送。

用法：
    from notifier import send_alert
    send_alert("红",   "过热：温度 33.2℃，超过阈值 32℃，连续 18 次")
    send_alert("恢复",  "过热已恢复，当前温度 30.1℃")
    send_alert("黄",   "舒适度：温度 29.0℃，建议调空调")

配置：把 webhook 和加签密钥写进 server/local_config.py（在 .gitignore 里，不进仓库）
    WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=xxx"
    SECRET  = "SECxxxxxxxx"
    AT_MOBILES = ["13800000000"]   # 告警要 @ 的人；留空则只发不 @

自测（会真的发一条到群里）：
    .\.venv\Scripts\python.exe server\notifier.py
"""

import base64
import hashlib
import hmac
import time
import urllib.parse

import requests

try:
    import local_config as cfg
    WEBHOOK = getattr(cfg, "WEBHOOK", "")
    SECRET = getattr(cfg, "SECRET", "")
    AT_MOBILES = getattr(cfg, "AT_MOBILES", [])
except ImportError:
    WEBHOOK, SECRET, AT_MOBILES = "", "", []

# 级别 -> emoji 前缀，让人一眼看出轻重
LEVEL_ICON = {"红": "🔴", "黄": "🟡", "恢复": "🟢"}


def _signed_url() -> str:
    """加签：把 timestamp + 签名拼到 webhook 上"""
    if not SECRET:
        return WEBHOOK

    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{SECRET}"
    hmac_code = hmac.new(
        SECRET.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{WEBHOOK}&timestamp={ts}&sign={sign}"


def send_alert(level: str, msg: str) -> bool:
    """发一条钉钉消息。返回 True=成功。发不出去也绝不让主流程崩。"""
    if not WEBHOOK:
        print("[notifier] 未配置 WEBHOOK，跳过推送：", msg)
        return False

    # 只有红级 @人；黄级和恢复不 @（避免打扰）
    at = AT_MOBILES if level == "红" else []

    payload = {
        "msgtype": "text",
        "text": {"content": f"{LEVEL_ICON.get(level, '')} [{level}] {msg}"},
        "at": {"atMobiles": at, "isAtAll": False},
    }

    try:
        r = requests.post(_signed_url(), json=payload, timeout=5)
        ok = r.status_code == 200 and r.json().get("errcode") == 0
        if not ok:
            print("[notifier] 发送失败：", r.status_code, r.text[:200])
        return ok
    except Exception as e:
        print("[notifier] 异常：", e)
        return False


if __name__ == "__main__":
    print("webhook 已配置:", bool(WEBHOOK), "| secret 已配置:", bool(SECRET))
    ok = send_alert("红", "测试消息：如果你在群里看到这条，说明告警通道通了")
    print("发送结果:", "成功 ✅" if ok else "失败 ❌（看上面的错误）")
