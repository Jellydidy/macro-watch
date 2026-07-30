"""FRED 采集:免 key 的 fredgraph.csv 端点,单序列逐个请求,全量覆盖。

注意:多序列合并请求会返回 zip,严禁 id=A,B 的写法。
"""
import os
import time

from . import common

# (序列ID, 频率) —— 频率用于前端新鲜度判定
SERIES = [
    ("T10YIE", "daily"),                 # 10Y 盈亏平衡通胀预期
    ("DFII10", "daily"),                 # 10Y TIPS 实际利率
    ("PCETRIM12M159SFRBDAL", "monthly_fred"),  # 达拉斯联储 Trimmed Mean PCE(12个月)
    ("DGS2", "daily"),
    ("DGS10", "daily"),
    ("DGS30", "daily"),
    ("T10Y2Y", "daily"),                 # 10Y-2Y 期限利差
    ("UNRATE", "monthly_fred"),          # 失业率
    ("FEDFUNDS", "monthly_fred"),        # 有效联邦基金利率
    ("BAMLH0A0HYM2", "daily"),           # 高收益债 OAS 利差
    ("DCOILWTICO", "daily"),             # WTI 油价(地缘代理)
    ("NASDAQCOM", "daily"),              # 纳斯达克综合指数(Yahoo 拦数据中心 IP,用 FRED 版)
]

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def collect(status):
    for series_id, freq in SERIES:
        sid = f"fred:{series_id}"
        try:
            r = common.fetch(URL, params={"id": series_id})
            rows = _parse(r.text, series_id)
            if len(rows) < 10:
                raise ValueError(f"only {len(rows)} rows parsed, response suspicious")
            path = os.path.join(common.DATA, "fred", f"{series_id}.csv")
            common.write_csv_guarded(path, ["date", "value"], rows)
            status.record(sid, True, rows=len(rows), latest_date=rows[-1][0], freq=freq)
        except Exception as e:  # noqa: BLE001
            status.record(sid, False, error=e, freq=freq)
        time.sleep(1)  # 礼貌限速


def _parse(text, series_id):
    lines = text.strip().splitlines()
    if not lines:
        raise ValueError("empty response")
    header = lines[0].lower()
    if "date" not in header or series_id.lower() not in header:
        raise ValueError(f"unexpected header: {lines[0][:80]}")
    rows = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        date, value = parts[0].strip(), parts[1].strip()
        if value in (".", ""):
            continue  # FRED 缺失值
        float(value)  # 非数值直接抛错,让整源失败而不是落脏数据
        rows.append([date, value])
    rows.sort(key=lambda x: x[0])
    return rows
