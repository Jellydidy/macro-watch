"""新浪期货采集:沪铜主力(CU0)日 K 全历史 + 实时快照。

- 日K:JSONP 端点返回 2005 至今全历史,全量覆盖(自愈:任何历史修正下次自动带回)。
- 实时价:仅写入 status 的 extra 字段供前端展示,绝不写入日K文件(防盘中价污染日线信号)。
"""
import json
import os

from . import common

REFERER = {"Referer": "https://finance.sina.com.cn"}
KLINE_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
             "var%20_=/InnerFuturesNewService.getDailyKLine?symbol=CU0")
REALTIME_URL = "https://hq.sinajs.cn/list=nf_CU0"


def collect(status):
    _collect_kline(status)
    _collect_realtime(status)


def _collect_kline(status):
    sid = "sina:CU0_daily"
    try:
        r = common.fetch(KLINE_URL, headers=REFERER)
        rows = _parse_kline(r.text)
        if len(rows) < 100:
            raise ValueError(f"only {len(rows)} rows, response suspicious")
        path = os.path.join(common.DATA, "market", "cu0_daily.csv")
        common.write_csv_guarded(
            path, ["date", "open", "high", "low", "close", "volume", "oi"], rows)
        status.record(sid, True, rows=len(rows), latest_date=rows[-1][0], freq="daily")
    except Exception as e:  # noqa: BLE001
        status.record(sid, False, error=e, freq="daily")


def _parse_kline(text):
    # JSONP 剥壳:取第一个 '[' 到最后一个 ']'(比正则稳)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON array in response: {text[:80]!r}")
    data = json.loads(text[start:end + 1])
    rows = []
    for item in data:
        rows.append([
            item["d"],
            common.fmt_num(float(item["o"])),
            common.fmt_num(float(item["h"])),
            common.fmt_num(float(item["l"])),
            common.fmt_num(float(item["c"])),
            common.fmt_num(float(item["v"])),
            common.fmt_num(float(item.get("p", 0) or 0)),  # p = 持仓量
        ])
    rows.sort(key=lambda x: x[0])
    return rows


def _collect_realtime(status):
    sid = "sina:CU0_realtime"
    try:
        r = common.fetch(REALTIME_URL, headers=REFERER)
        text = r.content.decode("gbk", errors="replace")
        payload = text.split('="', 1)[1].rsplit('"', 1)[0]
        f = payload.split(",")
        snap = {
            "price": float(f[8]),
            "date": f[17],
            "time": f[1],
            "fetched_at": common.now_utc(),
        }
        if snap["price"] <= 0:
            raise ValueError("zero/negative realtime price")
        status.set_extra("cu0_realtime", snap)
        status.record(sid, True, rows=1, latest_date=snap["date"], freq="daily")
    except Exception as e:  # noqa: BLE001
        status.record(sid, False, error=e, freq="daily")
