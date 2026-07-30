"""Yahoo chart API 采集:GC=F(国际金价)/ COPX / GLD / ^IXIC。

策略:文件不存在时 range=max 全量回填;已存在时 range=1y 增量,按 date 合并、
新值覆盖旧值(接住 Yahoo 事后修正的 bar)。XAUUSD=X 已验证不可用,金价口径为 GC=F。
"""
import datetime as dt
import os
import time
import urllib.parse

from . import common

SYMBOLS = [
    ("GC=F", "gc_daily.csv"),
    ("COPX", "copx_daily.csv"),
    ("GLD", "gld_daily.csv"),
    ("^IXIC", "ixic_daily.csv"),
]

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
HEADERS = {"Accept": "application/json"}
MIN_NEW_ROWS = 5  # 增量响应解析出低于此行数视为失败


def collect(status):
    for symbol, filename in SYMBOLS:
        sid = f"yahoo:{symbol}"
        path = os.path.join(common.DATA, "market", filename)
        try:
            rng = "1y" if os.path.exists(path) else "max"
            url = URL.format(urllib.parse.quote(symbol))
            r = common.fetch(url, headers=HEADERS,
                             params={"range": rng, "interval": "1d"})
            new_rows = _parse(r.json())
            if len(new_rows) < MIN_NEW_ROWS:
                raise ValueError(f"only {len(new_rows)} rows parsed from range={rng}")
            merged = _merge(path, new_rows)
            common.write_csv_guarded(
                path, ["date", "open", "high", "low", "close", "volume"], merged)
            status.record(sid, True, rows=len(merged), latest_date=merged[-1][0],
                          freq="daily")
        except Exception as e:  # noqa: BLE001
            status.record(sid, False, error=e, freq="daily")
        time.sleep(1)


def _parse(doc):
    result = doc.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"chart error: {doc.get('chart', {}).get('error')}")
    res = result[0]
    gmtoffset = res["meta"].get("gmtoffset", 0)
    ts = res.get("timestamp") or []
    quote = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = (quote[k][i] for k in ("open", "high", "low", "close"))
        v = quote["volume"][i]
        if c is None or o is None:
            continue  # 停牌/坏点整行丢弃
        date = dt.datetime.fromtimestamp(t + gmtoffset, dt.timezone.utc).strftime("%Y-%m-%d")
        rows.append([date, common.fmt_num(o), common.fmt_num(h), common.fmt_num(l),
                     common.fmt_num(c), common.fmt_num(v or 0)])
    return rows


def _merge(path, new_rows):
    by_date = {}
    for r in common.read_csv_dicts(path):
        by_date[r["date"]] = [r["date"], r["open"], r["high"], r["low"],
                              r["close"], r["volume"]]
    for row in new_rows:
        by_date[row[0]] = row  # 新值覆盖
    return [by_date[d] for d in sorted(by_date)]
