"""SPDR GLD 官方持仓吨位采集(尝试 + 三重校验)。

该端点 2026-07 实测已改为返回 PDF,故本采集器预期常态失败(status 灰/红),
信号层会自动降级到 manual/gold_etf_flows.json 的人工月度数据。
保留本采集器是为了端点一旦恢复即可自动接管(恢复后数据更细:日频吨位)。
三重校验:content-type 含 csv/text、前 512 字节不含 %PDF、能解析出 >100 行。
"""
import csv
import io
import os

from . import common

URL = "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv"


def collect(status):
    sid = "auto:gld_holdings"
    try:
        r = common.fetch(URL, retries=1)  # 常态失败,不值得重试三次
        ctype = r.headers.get("Content-Type", "")
        if "csv" not in ctype and "text/plain" not in ctype:
            raise ValueError(f"content-type {ctype!r}, expected csv")
        head = r.content[:512]
        if b"%PDF" in head:
            raise ValueError("response is PDF, endpoint still broken")
        rows = _parse(r.text)
        if len(rows) < 100:
            raise ValueError(f"only {len(rows)} rows parsed")
        path = os.path.join(common.DATA, "auto", "gld_holdings.csv")
        common.write_csv_guarded(path, ["date", "tonnes"], rows)
        status.record(sid, True, rows=len(rows), latest_date=rows[-1][0],
                      freq="daily")
    except Exception as e:  # noqa: BLE001
        status.record(sid, False, error=e, freq="daily")


def _parse(text):
    """历史格式含前言行,定位含 Tonnes 的表头行后按列名取值。"""
    reader = csv.reader(io.StringIO(text))
    header, tonnes_idx, date_idx = None, None, None
    rows = []
    for line in reader:
        if header is None:
            for i, cell in enumerate(line):
                if "tonne" in cell.lower():
                    header, tonnes_idx = line, i
                    for j, c2 in enumerate(line):
                        if "date" in c2.lower():
                            date_idx = j
                            break
                    if date_idx is None:
                        date_idx = 0
                    break
            continue
        if len(line) <= max(tonnes_idx, date_idx):
            continue
        try:
            tonnes = float(line[tonnes_idx].replace(",", ""))
            date = _norm_date(line[date_idx])
        except ValueError:
            continue
        if tonnes > 0 and date:
            rows.append([date, common.fmt_num(tonnes)])
    rows.sort(key=lambda x: x[0])
    return rows


def _norm_date(s):
    import datetime as dt
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
